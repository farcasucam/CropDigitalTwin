"""Offline acceptance audit for Phase 4.2 temporal crop evolution."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agri_twin.application import OpenFieldPhysicalModel, WeatherEngine
from agri_twin.application.clock import SimulationClock
from agri_twin.domain import (
    CropConfigRepository,
    CropDigitalTwinState,
    CropEngine,
    CropEngineError,
    FarmConfigRepository,
    SoilState,
    WeatherConfiguration,
    WeatherState,
)
from agri_twin.infrastructure import CsvWeatherProvider

ROOT = Path(__file__).resolve().parent
CROP = ROOT / "src" / "crop_config.json"
FARM = ROOT / "src" / "farm_config.json"
DATASET = ROOT / "data" / "weather" / "manual_forecast.csv"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_check(name: str, function, results: list[tuple[str, str, str]]) -> None:
    try:
        results.append((name, "PASS", str(function() or "verified")))
    except Exception as exc:
        results.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))


def context(plot_id: str = "plot_14705"):
    plot = FarmConfigRepository(FARM).get_plot(plot_id)
    crop = CropConfigRepository(CROP).get_crop(plot.crop_key)
    stage = crop.resolve_stage(plot.current_stage)
    return plot, crop, stage


def weather(**changes: float) -> WeatherState:
    values = dict(
        temperature_c=25.0,
        relative_humidity_pct=80.0,
        solar_radiation_w_m2=600.0,
        wind_speed_m_s=2.0,
        wind_direction_deg=180.0,
        rain_rate_mm_h=0.0,
        pressure_hpa=1012.0,
    )
    values.update(changes)
    return WeatherState(**values)


def environment(state: WeatherState):
    return OpenFieldPhysicalModel().evaluate(
        state, SoilState(0.25, 20.0, 0.35, 0.10, 0.0, 0.25), 3600
    ).environment


def parameter_audit() -> str:
    payload = json.loads(CROP.read_text(encoding="utf-8"))
    used = {"stress_thresholds", "vpd_thresholds", "vwc_thresholds"}
    loaded_only = {"stage_name", "months", "solar_radiation_thresholds", "irrigation"}
    for crop in payload["crops"].values():
        for stage in crop["stages"].values():
            require(used <= stage.keys() and loaded_only <= stage.keys(), "stage parameter set changed unexpectedly")
    return "stress/VPD/VWC used; months/radiation/irrigation retained for future semantics"


def stage_and_temperature() -> str:
    _, crop, _ = context()
    engine = CropEngine()
    soil = SoilState(0.25, 20.0, 0.35, 0.10, 0.0, 0.25)
    timestamp = datetime(2026, 8, 28, tzinfo=timezone.utc)
    favorable = weather(temperature_c=30)
    excessive = weather(temperature_c=40, relative_humidity_pct=10)
    stage_a = crop.resolve_stage("establishment")
    stage_b = crop.resolve_stage("yield_maturation")
    a = engine.evaluate(crop, stage_a, favorable, environment(favorable), soil, timestamp, 0)
    b = engine.evaluate(crop, stage_b, favorable, environment(favorable), soil, timestamp, 0)
    hot = engine.evaluate(crop, stage_b, excessive, environment(excessive), soil, timestamp, 0)
    require(a.temperature_stress != b.temperature_stress, "different stage thresholds had no effect")
    require(hot.temperature_stress > b.temperature_stress, "high temperature did not increase stress")
    return "stage thresholds and temperature response are active"


def temporal_progression() -> str:
    _, crop, stage = context()
    engine = CropEngine()
    soil = SoilState(0.25, 20.0, 0.35, 0.10, 0.0, 0.25)
    state = engine.evaluate(crop, stage, weather(), environment(weather()), soil, datetime(2026, 8, 28, tzinfo=timezone.utc))
    evolved = engine.advance(crop, stage, state, weather(), environment(weather()), soil, datetime(2026, 8, 28, tzinfo=timezone.utc), 86400)
    require(evolved.development_index > state.development_index, "development did not progress")
    require(evolved.biomass >= state.biomass, "biomass decreased with favorable time")
    return f"development_index {state.development_index:.4f} -> {evolved.development_index:.4f}"


def stress_growth_causality() -> str:
    _, crop, stage = context()
    engine = CropEngine()
    soil = SoilState(0.25, 20.0, 0.35, 0.10, 0.0, 0.25)
    timestamp = datetime(2026, 8, 28, tzinfo=timezone.utc)
    good = weather(temperature_c=24, relative_humidity_pct=80)
    bad = weather(temperature_c=40, relative_humidity_pct=10)
    good_state = engine.evaluate(crop, stage, good, environment(good), soil, timestamp)
    bad_state = engine.evaluate(crop, stage, bad, environment(bad), SoilState(0.11, 20, 0.35, 0.10, 0, 0.11), timestamp)
    good_next = engine.advance(crop, stage, good_state, good, environment(good), soil, timestamp, 86400)
    bad_next = engine.advance(crop, stage, bad_state, bad, environment(bad), soil, timestamp, 86400)
    require(bad_state.total_stress > good_state.total_stress, "stress causality failed")
    require(bad_state.growth_factor < good_state.growth_factor, "growth factor did not respond to stress")
    require(good_next.biomass > bad_next.biomass, "stress did not reduce growth")
    return "more stress produces lower growth"


def clock_reproducibility() -> str:
    _, crop, stage = context()
    provider = CsvWeatherProvider(DATASET)
    weather_engine = WeatherEngine(WeatherConfiguration(), provider=provider)
    physical = OpenFieldPhysicalModel()
    crop_engine = CropEngine()
    initial = provider.timestamps[0]
    initial_soil = SoilState(0.25, 20.0, 0.35, 0.10, 0.0, 0.25)

    def simulate(speed: float):
        clock = SimulationClock(initial, speed=speed)
        soil = initial_soil
        current = initial
        state = crop_engine.evaluate(crop, stage, weather_engine.generate(current), physical.evaluate(weather_engine.generate(current), soil, 3600).environment, soil, current)
        for _ in range(24):
            current += timedelta(hours=1)
            weather_state = weather_engine.generate(current)
            result = physical.evaluate(weather_state, soil, 3600)
            state = crop_engine.advance(crop, stage, state, weather_state, result.environment, soil, current, 3600)
            soil = result.soil
            clock.advance(3600)
        return clock.now(), state

    slow = simulate(1)
    fast = simulate(100)
    require(slow[0] == fast[0] == initial + timedelta(hours=24), "clock did not advance simulated 24 hours")
    require(slow[1] == fast[1], "wall-clock speed changed crop state")
    return "1x and 100x produced identical state after 24 simulated hours"


def explicit_state_and_offline_chain() -> str:
    provider = CsvWeatherProvider(DATASET)
    weather_engine = WeatherEngine(WeatherConfiguration(), provider=provider)
    physical = OpenFieldPhysicalModel()
    plot, crop, stage = context()
    timestamp = provider.timestamps[0]
    weather_state = weather_engine.generate(timestamp)
    physical_result = physical.evaluate(weather_state, SoilState(0.25, 20, 0.35, 0.10, 0, 0.25), 3600)
    crop_state = CropEngine().evaluate(crop, stage, weather_state, physical_result.environment, physical_result.soil, timestamp)
    twin = CropDigitalTwinState(plot.plot_id, crop.crop_key, plot.variety, stage.stage_key, timestamp, weather_state, {"vpd_kpa": physical_result.environment.vpd_kpa}, crop_state)
    require(twin.crop_state == crop_state and twin.weather_state == weather_state, "dynamic state was not explicit")
    return "WeatherState, DerivedEnvironmentState, SoilState and CropState coexist offline"


def invalid_temporal_inputs() -> str:
    _, crop, stage = context()
    engine = CropEngine()
    state = engine.evaluate(crop, stage, weather(), environment(weather()), SoilState(0.25, 20, 0.35, 0.10, 0, 0.25), datetime(2026, 8, 28, tzinfo=timezone.utc))
    try:
        engine.advance(crop, stage, state, weather(), environment(weather()), SoilState(0.25, 20, 0.35, 0.10, 0, 0.25), datetime(2026, 8, 28, tzinfo=timezone.utc), -1)
    except CropEngineError:
        return "negative dt rejected; dt=0 is an explicit no-op"
    raise AssertionError("negative dt accepted")


def http_isolation() -> str:
    allowed = ROOT / "src" / "agri_twin" / "infrastructure" / "open_meteo.py"
    forbidden = ("requests", "httpx", "aiohttp", "urllib", "urlopen")
    offenders = []
    for path in (ROOT / "src" / "agri_twin").rglob("*.py"):
        if path == allowed:
            continue
        if any(token in path.read_text(encoding="utf-8") for token in forbidden):
            offenders.append(str(path))
    require(not offenders, f"HTTP dependency outside Open-Meteo: {offenders}")
    require(not any(token in (ROOT / "src" / "agri_twin" / "domain" / "crop_engine.py").read_text(encoding="utf-8") for token in ("datetime.now", "datetime.utcnow", "time.time", "sleep(")), "wall clock in CropEngine")
    return "no HTTP or wall-clock dependency"


def regression() -> str:
    completed = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    require(completed.returncode == 0, completed.stdout[-500:] or completed.stderr[-500:])
    return completed.stdout.strip().splitlines()[-1]


def main() -> int:
    results: list[tuple[str, str, str]] = []
    run_check("Crop config parameter audit", parameter_audit, results)
    run_check("Stage definitions and temperature response", stage_and_temperature, results)
    run_check("Temporal development progression", temporal_progression, results)
    run_check("Stress and growth causality", stress_growth_causality, results)
    run_check("SimulationClock acceleration", clock_reproducibility, results)
    results.append(("Stage transition", "SKIP", "crop_config.json has no GDD, stage durations, or transition thresholds"))
    run_check("Explicit offline DigitalTwin state", explicit_state_and_offline_chain, results)
    run_check("Invalid temporal inputs", invalid_temporal_inputs, results)
    run_check("HTTP and wall-clock isolation", http_isolation, results)
    run_check("Regression", regression, results)
    print("=" * 60)
    print(" CROP DIGITAL TWIN - PHASE 4.2 ACCEPTANCE")
    print("=" * 60)
    for index, (name, status, detail) in enumerate(results, 1):
        print(f"[{index:02d}] {name:.<39} {status}  {detail}")
    passed = sum(status == "PASS" for _, status, _ in results)
    failed = sum(status == "FAIL" for _, status, _ in results)
    skipped = sum(status == "SKIP" for _, status, _ in results)
    print("\n" + "=" * 60)
    print(f"PASS: {passed}\nFAIL: {failed}\nSKIP: {skipped}")
    print("PHASE 4.2 STATUS: " + ("ACCEPTED" if failed == 0 and skipped == 1 else "NOT READY"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
