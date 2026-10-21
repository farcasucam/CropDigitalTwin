"""EnergyPlus as a greenhouse backend through a per-run timeline.

Before a run, EnergyPlus is executed once as an external process over the whole campaign prefix up to the run end,
driven by the same weather and commanded actuators the other backend would see. The orchestrator then reads the hourly
result step by step. Deterministic and independent of the Python version; EnergyPlus cannot restart from a checkpoint,
so every run (prefix, baseline, intervention) simulates from the campaign start and branches stay consistent.

Limits (also reported to the user): the crop does not feed back into EnergyPlus (no transpiration, no CO2 uptake);
CO2 is not modelled; hygrothermal values come from placeholder envelope properties; nothing is validated.
"""

from __future__ import annotations

import glob
import hashlib
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence

from agri_twin.domain.greenhouse import (
    GreenhouseMicroclimateResult,
    GreenhouseMicroclimateState,
    GreenhouseModelError,
    MicroclimateState,
    derived_environment,
    vapour_pressure_deficit_kpa,
)
from agri_twin.domain.greenhouse_typology import GreenhouseGeometrySpec, floor_area_m2
from agri_twin.domain.models import WeatherState
from agri_twin.infrastructure.epw_weather import EpwLocation, HourConvention, write_epw_from_states
from agri_twin.infrastructure.greenhouse_idf import EnvelopeSpec, RunSpec, ThermalSpec, build_greenhouse_idf

REQUIRED_VERSION_PREFIX = "26.1"  # the generated IDF is written for this EnergyPlus version
TIMEOUT_SECONDS = 900
CACHE_SIZE = 6
OUTDOOR_CO2_PPM = 420.0


class EnergyPlusTimelineError(RuntimeError):
    """Raised when EnergyPlus is unavailable, incompatible or fails."""


@dataclass(frozen=True, slots=True)
class EnergyPlusInstall:
    executable: Path
    version: str
    source: str  # how it was found (environment variable, PATH, standard location)


def find_energyplus() -> EnergyPlusInstall | None:
    """Locate an EnergyPlus executable without a Python API: ENERGYPLUS_EXECUTABLE, PATH, then standard install folders."""
    candidates: list[tuple[Path, str]] = []
    configured = os.environ.get("ENERGYPLUS_EXECUTABLE")
    if configured:
        candidates.append((Path(configured), "ENERGYPLUS_EXECUTABLE"))
    for name in ("energyplus", "EnergyPlus"):
        found = shutil.which(name)
        if found:
            candidates.append((Path(found), "PATH"))
    for pattern in (r"C:\EnergyPlus*\energyplus.exe", "/usr/local/EnergyPlus*/energyplus", "/Applications/EnergyPlus*/energyplus", "/opt/EnergyPlus*/energyplus"):
        candidates.extend((Path(path), "standard install folder") for path in sorted(glob.glob(pattern), reverse=True))
    for path, source in candidates:
        version = _version(path)
        if version is not None:
            return EnergyPlusInstall(path, version, source)
    return None


def _version(executable: Path) -> str | None:
    if not executable.is_file():
        return None
    try:
        done = subprocess.run((str(executable), "--version"), capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"Version\s+([0-9]+\.[0-9]+\.[0-9]+)", done.stdout or done.stderr)
    return match.group(1) if match else None


def require_energyplus() -> EnergyPlusInstall:
    install = find_energyplus()
    if install is None:
        raise EnergyPlusTimelineError("EnergyPlus was not found: set ENERGYPLUS_EXECUTABLE or install EnergyPlus 26.1 in a standard folder")
    if not install.version.startswith(REQUIRED_VERSION_PREFIX):
        raise EnergyPlusTimelineError(f"EnergyPlus {install.version} found at {install.executable}; the generated IDF targets {REQUIRED_VERSION_PREFIX}.x")
    return install


@dataclass(frozen=True, slots=True)
class TimelineValue:
    air_temperature_c: float
    relative_humidity_pct: float
    radiation_w_m2: float  # transmitted solar power per floor area
    ventilation_fraction: float  # ventilation air change rate over the design maximum
    heating_kw: float
    cooling_kw: float


@dataclass(frozen=True, slots=True)
class EnergyPlusTimeline:
    values: Mapping[datetime, TimelineValue]
    provenance: Mapping[str, str]

    @property
    def timeline_hash(self) -> str:
        return self.provenance["timeline_hash"]


@dataclass(frozen=True, slots=True)
class TimelineInputs:
    location: EpwLocation
    series: tuple[tuple[datetime, WeatherState], ...]  # hourly, UTC, each label is the end of its hour
    forced_ventilation: tuple[float, ...]  # fraction 0..1 per row (commanded vent opening)
    shading: tuple[float, ...]  # fraction 0..1 per row (external screen approximation: scales the solar input)
    geometry: GreenhouseGeometrySpec
    envelope: EnvelopeSpec = field(default_factory=EnvelopeSpec)
    thermal: ThermalSpec = field(default_factory=ThermalSpec)


def _epw_day(label: datetime) -> tuple[int, int, int]:
    day = label - timedelta(seconds=1)
    return day.year, day.month, day.day


def _hour_of_year(label: datetime) -> int:
    day = label - timedelta(seconds=1)
    if day.month == 2 and day.day == 29:
        raise EnergyPlusTimelineError("29 February is not supported by the 8760-hour schedule file")
    ordinal = (datetime(2001, day.month, day.day) - datetime(2001, 1, 1)).days
    return ordinal * 24 + (24 if label.hour == 0 else label.hour) - 1


_CACHE: "OrderedDict[str, EnergyPlusTimeline]" = OrderedDict()
_LOCK = threading.Lock()


def run_timeline(inputs: TimelineInputs, install: EnergyPlusInstall | None = None) -> EnergyPlusTimeline:
    install = install or require_energyplus()
    series = inputs.series
    labels = [stamp.astimezone(timezone.utc) for stamp, _ in series]
    if not labels or labels[0].minute or labels[0].second or labels[0].microsecond:
        raise EnergyPlusTimelineError("the weather series must be hourly and aligned to the hour")
    first, last = _epw_day(labels[0]), _epw_day(labels[-1])
    if (first[1], first[2]) > (last[1], last[2]) or first[0] != last[0]:
        raise EnergyPlusTimelineError("runs that cross a calendar year are not supported")
    if len({_epw_day(label) for label in labels}) * 24 != len(labels):
        raise EnergyPlusTimelineError("the weather series must cover whole EPW days (each ending at 00:00)")

    forced = [0.0] * 8760
    for label, value in zip(labels, inputs.forced_ventilation):
        forced[_hour_of_year(label)] = min(1.0, max(0.0, float(value)))
    idf = build_greenhouse_idf(
        inputs.geometry, inputs.envelope, inputs.thermal,
        RunSpec(first[1], first[2], last[1], last[2], timesteps_per_hour=4, forced_ventilation_file="forced_ventilation.csv"),
    )
    schedule_text = "\n".join(f"{value:.4f}" for value in forced) + "\n"
    with tempfile.TemporaryDirectory(prefix="agri_twin_ep_") as folder:
        work = Path(folder)
        epw_report = write_epw_from_states(series, work / "weather.epw", inputs.location, HourConvention.END_OF_HOUR, solar_factors=[1.0 - min(1.0, max(0.0, f)) for f in inputs.shading])
        epw_text = (work / "weather.epw").read_text(encoding="utf-8")
        digest = hashlib.sha256("\n".join((idf.idf_hash, epw_report.sha256, hashlib.sha256(schedule_text.encode()).hexdigest(), install.version)).encode()).hexdigest()
        with _LOCK:
            cached = _CACHE.get(digest)
            if cached is not None:
                _CACHE.move_to_end(digest)
                return cached
        (work / "forced_ventilation.csv").write_text(schedule_text, encoding="utf-8")
        (work / "greenhouse.idf").write_text(idf.text, encoding="utf-8")
        try:
            done = subprocess.run((str(install.executable), "-w", "weather.epw", "-d", "out", "greenhouse.idf"), cwd=work, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise EnergyPlusTimelineError(f"EnergyPlus could not be executed: {exc}") from exc
        error_file = work / "out" / "eplusout.err"
        error_text = error_file.read_text(encoding="utf-8", errors="replace") if error_file.exists() else done.stderr
        if done.returncode != 0 or "** Severe" in error_text or "**  Fatal" in error_text:
            severe = [line.strip() for line in error_text.splitlines() if "** Severe" in line or "**  Fatal" in line][:3]
            raise EnergyPlusTimelineError(f"EnergyPlus failed (exit {done.returncode}): {'; '.join(severe) or error_text[-300:]}")
        values = _read_results(work / "out" / "eplusout.sql", labels, floor_area_m2(inputs.geometry), inputs.thermal.max_ventilation_ach.value)
    provenance = {
        "backend": "ENERGYPLUS", "energyplus_version": install.version, "executable_source": install.source,
        "idf_hash": idf.idf_hash, "epw_sha256": epw_report.sha256, "timeline_hash": digest,
        "classification": "SOFTWARE_QUALIFICATION_ONLY (placeholder envelope properties; not validated against a real greenhouse)",
        "feedback": "no crop feedback into EnergyPlus (no transpiration, no CO2 uptake)", "co2": "not modelled",
    }
    timeline = EnergyPlusTimeline(values, provenance)
    with _LOCK:
        _CACHE[digest] = timeline
        while len(_CACHE) > CACHE_SIZE:
            _CACHE.popitem(last=False)
    return timeline


_VARIABLES = {
    "air": ("GREENHOUSE ZONE", "Zone Mean Air Temperature"),
    "rh": ("GREENHOUSE ZONE", "Zone Air Relative Humidity"),
    "solar": ("GREENHOUSE ZONE", "Enclosure Windows Total Transmitted Solar Radiation Rate"),
    "vent": ("GREENHOUSE ZONE", "Zone Ventilation Standard Density Air Change Rate"),
    "heat": ("HEATER", "Zone Ideal Loads Zone Total Heating Rate"),
    "cool": ("HEATER", "Zone Ideal Loads Zone Total Cooling Rate"),
}


def _read_results(database: Path, labels: Sequence[datetime], floor_area: float, max_ach: float) -> dict[datetime, TimelineValue]:
    connection = sqlite3.connect(database)
    try:
        found: dict[str, dict[tuple[int, int, int], float]] = {}
        for name, (key, variable) in _VARIABLES.items():
            rows = connection.execute(
                "select t.Month, t.Day, t.Hour, v.Value from ReportData v join ReportDataDictionary d using(ReportDataDictionaryIndex) join Time t using(TimeIndex) "
                "where upper(d.KeyValue)=? and d.Name=? and t.Minute=0 and (t.WarmupFlag is null or t.WarmupFlag=0)", (key, variable)).fetchall()
            found[name] = {(month, day, hour): value for month, day, hour, value in rows}
    finally:
        connection.close()
    values: dict[datetime, TimelineValue] = {}
    for label in labels:
        _, month, day = _epw_day(label)
        index = (month, day, 24 if label.hour == 0 else label.hour)
        try:
            raw = {name: found[name][index] for name in _VARIABLES}
        except KeyError:
            raise EnergyPlusTimelineError(f"EnergyPlus produced no result for {label.isoformat()}") from None
        values[label] = TimelineValue(
            air_temperature_c=raw["air"], relative_humidity_pct=min(100.0, max(0.0, raw["rh"])), radiation_w_m2=max(0.0, raw["solar"]) / floor_area,
            ventilation_fraction=min(1.0, max(0.0, raw["vent"] / max_ach)), heating_kw=max(0.0, raw["heat"]) / 1000.0, cooling_kw=max(0.0, raw["cool"]) / 1000.0)
    return values


class EnergyPlusMicroclimateEngine:
    """Orchestrator-facing engine: serves the precomputed EnergyPlus timeline step by step."""

    requires_simulation_time = True

    def __init__(self, timeline: EnergyPlusTimeline) -> None:
        self.timeline = timeline

    def advance(self, weather: WeatherState, crop, dt_seconds: float, mode: str = "passive_greenhouse", actuators=None, prior=None, simulation_time: datetime | None = None) -> GreenhouseMicroclimateResult:
        if simulation_time is None:
            raise GreenhouseModelError("the EnergyPlus backend needs the simulation time of the step")
        label = simulation_time.astimezone(timezone.utc)
        try:
            value = self.timeline.values[label]
        except KeyError:
            raise GreenhouseModelError(f"EnergyPlus timeline has no value at {label.isoformat()}") from None
        state = MicroclimateState(
            air_temperature_c=value.air_temperature_c, relative_humidity_pct=value.relative_humidity_pct,
            vpd_kpa=vapour_pressure_deficit_kpa(value.air_temperature_c, value.relative_humidity_pct), pressure_hpa=weather.pressure_hpa,
            solar_radiation_w_m2=value.radiation_w_m2, par_umol_m2_s=value.radiation_w_m2 * 2.04, co2_ppm=OUTDOOR_CO2_PPM,
            wind_speed_m_s=weather.wind_speed_m_s, ventilation_fraction=value.ventilation_fraction, heating_kw=value.heating_kw, cooling_kw=value.cooling_kw,
            shading_fraction=self._commanded_shading(actuators), temperature_c=value.air_temperature_c)
        return GreenhouseMicroclimateResult(derived_environment(state), GreenhouseMicroclimateState(**state.to_dict()), 0.0, 0.0)

    @staticmethod
    def _commanded_shading(actuators) -> float:
        control = (actuators or {}).get("shade") or (actuators or {}).get("shading")
        return float(control.actual) if control is not None else 0.0
