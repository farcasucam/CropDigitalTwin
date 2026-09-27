"""Environment- and hemisphere-independent dormancy / chilling experiments (Phase 5.33).

Drives the existing ``PhenologyEngine`` (whose dormancy branch is the
``DormancyChillingController``: start policy + chilling model + requirement) with
one ``SimulationClock``/``SimulationScheduler`` and the existing ``WeatherEngine``.
Synthetic locations carry latitude/longitude/elevation as metadata; the hemisphere
is derived from latitude and used only to generate the synthetic climate calendar
and to label results. Physiology never reads latitude, hemisphere or calendar
months. Explicit calendar instants appear only as labelled experiment
configurations (FIXED_DATE protocols, analysis windows), never as biology.

Results are SOFTWARE_RESULT; literature rows from ``src/crop_phenology.csv`` are
reported separately as SCIENTIFIC_EVIDENCE. Nothing here is calibration or
biological validation.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import math
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Mapping, Sequence

from agri_twin.application.clock import SimulationClock
from agri_twin.application.integrated_synthetic_validation import static_audit
from agri_twin.application.scenarios import Scenario, ScenarioEvent, ScenarioKind, ScenarioRunner
from agri_twin.application.scheduler import SimulationScheduler
from agri_twin.application.seasonal_synthetic_campaign import BASE_PROFILE, SeasonalSyntheticCampaignSuite, climate_profile, seasonal_weather_factory, weather_configuration
from agri_twin.application.weather import WeatherEngine
from agri_twin.domain.calibration import ParameterSet
from agri_twin.domain.models import CropGrowthState, SoilState, WeatherState
from agri_twin.domain.parameter_audit import ParameterRegistry
from agri_twin.domain.phenology import (
    APPROXIMATE_PROFILES,
    ChillingModel,
    ChillingModelType,
    ChillingStartPolicy,
    ChillingStartPolicyType,
    DormancyChillingController,
    PhenologyEngine,
    PhenologyError,
)

UTC = timezone.utc
VERSION = "5.33.1"
DEFAULT_SEED = 533
DT = 3600.0
SPECIES = ("peach", "apple", "plum")
SPECIES_VARIETY = {"peach": "UNSPECIFIED", "apple": "UNSPECIFIED", "plum": "Suplum 26"}
CONTEXT_LEAD_HOURS = 24.0  # engineering rule: record must show >= 24 h without effective chill before the first one


class DormancyOutcome(StrEnum):
    RELEASED = "RELEASED"
    RELEASED_INCOMPLETE_CONTEXT = "RELEASED_INCOMPLETE_CONTEXT"
    NO_CHILL = "NO_CHILL"
    INSUFFICIENT_TEMPORAL_CONTEXT = "INSUFFICIENT_TEMPORAL_CONTEXT"
    DORMANCY_NOT_RELEASED = "DORMANCY_NOT_RELEASED"
    MODEL_NOT_SUPPORTED = "MODEL_NOT_SUPPORTED"


def hemisphere(latitude: float) -> str:
    """Geographic label only; never an input of the chilling computation."""
    if latitude > 0:
        return "NORTHERN"
    if latitude < 0:
        return "SOUTHERN"
    return "EQUATORIAL"


@dataclass(frozen=True, slots=True)
class SyntheticLocation:
    """Synthetic software location (not real climatology, not an agronomic zone)."""

    location_id: str
    latitude: float
    longitude: float
    elevation_m: float
    temperature_min_c: float
    temperature_max_c: float
    seasonal_amplitude_c: float
    warmest_day_of_year: float
    daily_temperature_c: float = 2.0

    @property
    def hemisphere(self) -> str:
        return hemisphere(self.latitude)

    def profile(self, *, temperature_offset_c: float = 0.0, daily_temperature_c: float | None = None) -> dict[str, float]:
        profile = dict(BASE_PROFILE)
        profile.update({
            "temperature_min_c": self.temperature_min_c + temperature_offset_c,
            "temperature_max_c": self.temperature_max_c + temperature_offset_c,
            "seasonal_temperature_amplitude_c": self.seasonal_amplitude_c,
            "warmest_day_of_year": self.warmest_day_of_year,
            "daily_temperature_c": self.daily_temperature_c if daily_temperature_c is None else daily_temperature_c,
        })
        return profile

    def analysis_start(self, season_year: int) -> datetime:
        """Analysis window start: the synthetic climate's warmest day of the preceding
        summer (derived from the climate profile, not a physiological start)."""
        year = season_year - 1 if self.hemisphere == "NORTHERN" else season_year
        return datetime(year, 1, 1, tzinfo=UTC) + timedelta(days=round(self.warmest_day_of_year) - 1)


LOCATIONS: tuple[SyntheticLocation, ...] = (
    SyntheticLocation("NH_20N_WARM_WINTER", 20.0, -100.0, 1500.0, 16.0, 29.0, 4.0, 150.0, 1.5),
    SyntheticLocation("NH_38N_MEDITERRANEAN", 38.0, -1.1, 300.0, 11.5, 24.0, 8.5, 200.0),
    SyntheticLocation("NH_50N_CONTINENTAL", 50.0, 10.0, 200.0, 5.0, 15.0, 11.0, 200.0),
    SyntheticLocation("SH_20S_WARM_WINTER", -20.0, -48.0, 800.0, 16.0, 29.0, 4.0, 17.0, 1.5),
    SyntheticLocation("SH_35S_TEMPERATE", -35.0, -71.0, 300.0, 11.5, 24.0, 8.5, 17.0),
    SyntheticLocation("SH_50S_COLD", -50.0, -70.0, 100.0, 5.0, 15.0, 9.0, 17.0),
)
SEASON_YEAR = 2026
# Explicit experimental protocol instants (literature conventions, e.g. 1 May counting
# in South Africa); configurations to compare, never physiological defaults.
PROTOCOL_START = {"NORTHERN": datetime(2025, 11, 1, tzinfo=UTC), "SOUTHERN": datetime(2026, 5, 1, tzinfo=UTC)}
SHIFTED_START = {"NORTHERN": datetime(2025, 12, 1, tzinfo=UTC), "SOUTHERN": datetime(2026, 6, 1, tzinfo=UTC)}


def _hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def initial_dormant_state(crop: str, start: datetime) -> CropGrowthState:
    return CropGrowthState(start, crop, SPECIES_VARIETY.get(crop, "UNSPECIFIED"), "establishment", biomass_total=45.0, biomass_leaf=5.0, biomass_stem=20.0, biomass_root=20.0, leaf_area_index=0.1, root_depth_m=0.6, soil_water_vwc=0.3, dormancy_released=False, phenology_model="SYNTHETIC_INITIAL_STATE")


# ---------------------------------------------------------------------------
# Season driver (single SimulationClock / SimulationScheduler)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DormancySeasonResult:
    crop: str
    location_id: str | None
    hemisphere: str | None
    latitude: float | None
    longitude: float | None
    policy: str
    model: str
    record_start: datetime
    record_days: int
    counting_start: datetime | None
    first_effective_chill: datetime | None
    chill_total: float
    chill_at_release: float | None
    chill_excluded_by_policy_hours: float
    dormancy_release: datetime | None
    forcing_start: datetime | None
    budburst: datetime | None
    outcome: DormancyOutcome
    trajectory_hash: str
    finite: bool
    final_state: CropGrowthState | None = field(default=None, compare=False)
    elapsed_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        iso = lambda value: value.isoformat() if value is not None else None
        return {
            "crop": self.crop, "location_id": self.location_id, "hemisphere": self.hemisphere, "latitude": self.latitude, "longitude": self.longitude,
            "policy": self.policy, "model": self.model, "record_start": iso(self.record_start), "record_days": self.record_days,
            "counting_start": iso(self.counting_start), "first_effective_chill": iso(self.first_effective_chill),
            "chill_total_h": self.chill_total, "chill_at_release_h": self.chill_at_release, "chill_excluded_by_policy_h": self.chill_excluded_by_policy_hours,
            "dormancy_release": iso(self.dormancy_release), "forcing_start": iso(self.forcing_start), "budburst": iso(self.budburst),
            "days_to_release": (self.dormancy_release - self.record_start).total_seconds() / 86400.0 if self.dormancy_release else None,
            "outcome": self.outcome.value, "trajectory_hash": self.trajectory_hash, "elapsed_hash": self.elapsed_hash, "finite": self.finite,
            "result_type": "SOFTWARE_RESULT",
        }


WeatherSource = Callable[[datetime], WeatherState]


def run_dormancy_season(crop: str, weather: WeatherSource, start: datetime, days: int, *, policy: ChillingStartPolicy | None = None, model: ChillingModel | None = None, location: SyntheticLocation | None = None, initial: CropGrowthState | None = None) -> DormancySeasonResult:
    """Advance the existing PhenologyEngine hourly from ``start`` for ``days`` days."""
    policy = policy or ChillingStartPolicy()
    model = model or ChillingModel()
    engine = PhenologyEngine(dormancy=DormancyChillingController(policy, model))
    profile = engine.profile_for(crop)
    base = dict(crop=crop, location_id=location.location_id if location else None, hemisphere=location.hemisphere if location else None,
                latitude=location.latitude if location else None, longitude=location.longitude if location else None,
                policy=policy.policy_type.value, model=model.model_type.value, record_start=start, record_days=days)
    if not policy.implemented or not model.implemented:
        return DormancySeasonResult(**base, counting_start=None, first_effective_chill=None, chill_total=0.0, chill_at_release=None, chill_excluded_by_policy_hours=0.0,
                                    dormancy_release=None, forcing_start=None, budburst=None, outcome=DormancyOutcome.MODEL_NOT_SUPPORTED, trajectory_hash=_hash([]), finite=True)
    clock = SimulationClock(start)
    scheduler = SimulationScheduler(clock, DT)
    record: dict[str, Any] = {"state": initial or initial_dormant_state(crop, start), "first_effective": None, "counting_start": None, "excluded": 0.0,
                              "release": None, "forcing": None, "budburst": None, "chill_at_release": None, "finite": True, "digest": hashlib.sha256(), "elapsed": hashlib.sha256()}

    def tick(timestamp: datetime) -> None:
        state = record["state"]
        forcing = weather(timestamp)
        was_dormant = not state.dormancy_released
        effective = profile.chilling_min_temperature_c <= forcing.temperature_c <= profile.chilling_max_temperature_c
        if was_dormant:
            if policy.counting(timestamp):
                record["counting_start"] = record["counting_start"] or timestamp
            elif effective:
                record["excluded"] += DT / 3600.0
        new = engine.advance(state, forcing, timestamp, DT)
        if was_dormant and new.chilling_hours > state.chilling_hours and record["first_effective"] is None:
            record["first_effective"] = timestamp
        if was_dormant and new.dormancy_released:
            record["release"], record["chill_at_release"] = timestamp, new.chilling_hours
        if not was_dormant and record["forcing"] is None and new.gdd_accumulated > state.gdd_accumulated:
            record["forcing"] = timestamp
        if record["budburst"] is None and new.current_stage == "vegetative_growth":
            record["budburst"] = timestamp
        record["finite"] = record["finite"] and all(math.isfinite(v) for v in (new.chilling_hours, new.gdd_accumulated, new.maturity_index))
        record["digest"].update(repr((timestamp.isoformat(), new.chilling_hours, new.gdd_accumulated, new.current_stage, new.dormancy_released)).encode("ascii"))
        # Calendar-free fingerprint: the same trajectory as a function of elapsed hours.
        record["elapsed"].update(repr(((timestamp - start).total_seconds() / 3600.0, new.chilling_hours, new.gdd_accumulated, new.current_stage, new.dormancy_released)).encode("ascii"))
        record["state"] = new

    scheduler.register("dormancy-chilling", DT, tick)
    scheduler.advance(days * 86400.0)
    final = record["state"]
    released, first = record["release"] is not None, record["first_effective"]
    context_complete = first is not None and (first - start).total_seconds() / 3600.0 >= CONTEXT_LEAD_HOURS
    if released:
        outcome = DormancyOutcome.RELEASED if context_complete else DormancyOutcome.RELEASED_INCOMPLETE_CONTEXT
    elif final.chilling_hours == 0.0 and first is None:
        outcome = DormancyOutcome.NO_CHILL
    elif not context_complete:
        outcome = DormancyOutcome.INSUFFICIENT_TEMPORAL_CONTEXT
    else:
        outcome = DormancyOutcome.DORMANCY_NOT_RELEASED
    return DormancySeasonResult(**base, counting_start=record["counting_start"], first_effective_chill=first, chill_total=final.chilling_hours, chill_at_release=record["chill_at_release"],
                                chill_excluded_by_policy_hours=record["excluded"], dormancy_release=record["release"], forcing_start=record["forcing"], budburst=record["budburst"],
                                outcome=outcome, trajectory_hash=record["digest"].hexdigest(), finite=record["finite"], final_state=final, elapsed_hash=record["elapsed"].hexdigest())


def location_weather(location: SyntheticLocation, seed: int = DEFAULT_SEED, **profile_changes: float) -> WeatherSource:
    return WeatherEngine(weather_configuration(location.profile(**profile_changes), seed)).generate


class ReplayedWeather:
    """Replay a recorded hourly series by elapsed time from its own start (calendar-free)."""

    def __init__(self, series: Sequence[WeatherState], start: datetime) -> None:
        self.series, self.start = tuple(series), start

    def __call__(self, timestamp: datetime) -> WeatherState:
        return self.series[int((timestamp - self.start).total_seconds() // DT) - 1]


def record_series(weather: WeatherSource, start: datetime, days: int) -> list[WeatherState]:
    return [weather(start + timedelta(hours=h + 1)) for h in range(days * 24)]


def policies_for(location: SyntheticLocation) -> list[tuple[str, ChillingStartPolicy]]:
    return [
        ("DORMANCY_STATE", ChillingStartPolicy()),
        ("FIXED_DATE_PROTOCOL", ChillingStartPolicy(ChillingStartPolicyType.FIXED_DATE, PROTOCOL_START[location.hemisphere], "explicit experimental protocol instant")),
        ("FIXED_DATE_SHIFTED", ChillingStartPolicy(ChillingStartPolicyType.FIXED_DATE, SHIFTED_START[location.hemisphere], "explicit protocol instant shifted by one month")),
        ("EFFECTIVE_CHILL_ONSET", ChillingStartPolicy(ChillingStartPolicyType.EFFECTIVE_CHILL_ONSET, rationale="count from the first effective chill hour")),
        ("MODEL_DEFINED", ChillingStartPolicy(ChillingStartPolicyType.MODEL_DEFINED, rationale="onset defined inside a chilling model (Utah/Dynamic), not implemented")),
    ]


# ---------------------------------------------------------------------------
# Suite
# ---------------------------------------------------------------------------


class DormancyChillingFrameworkSuite:
    VERSION = VERSION

    def __init__(self, root: str | Path, *, registry: ParameterRegistry | None = None, seed: int = DEFAULT_SEED, species: Sequence[str] = SPECIES, include_twin: bool = True, locations: Sequence[str] | None = None) -> None:
        self.root = Path(root)
        self.registry = registry or ParameterRegistry.from_repository(self.root)
        self.seed = seed
        self.species = tuple(species)
        self.include_twin = include_twin
        self.locations = tuple(item for item in LOCATIONS if locations is None or item.location_id in locations)

    def location(self, location_id: str) -> SyntheticLocation:
        return next(item for item in LOCATIONS if item.location_id == location_id)

    # -- experiments -----------------------------------------------------------------

    def policy_matrix(self) -> list[dict[str, Any]]:
        rows = []
        for location in self.locations:
            start = location.analysis_start(SEASON_YEAR)
            weather = location_weather(location, self.seed)
            for crop in self.species:
                for label, policy in policies_for(location):
                    result = run_dormancy_season(crop, weather, start, 365, policy=policy, location=location)
                    rows.append({"experiment": label, "requirement_h": PhenologyEngine().profile_for(crop).chilling_requirement_hours, **result.to_dict()})
        return rows

    def hemisphere_inversion(self) -> dict[str, Any]:
        north, south = self.location("NH_38N_MEDITERRANEAN"), self.location("SH_35S_TEMPERATE")
        results = {}
        for location in (north, south):
            start = location.analysis_start(SEASON_YEAR)
            weather = location_weather(location, self.seed, daily_temperature_c=0.0)
            results[location.location_id] = {crop: run_dormancy_season(crop, weather, start, 365, location=location) for crop in self.species}

        def winter_months(location: SyntheticLocation, result: DormancySeasonResult) -> list[int]:
            return sorted({(result.first_effective_chill + timedelta(days=d)).month for d in range(0, 60, 10)}) if result.first_effective_chill else []

        rows = []
        for crop in self.species:
            n, s = results[north.location_id][crop], results[south.location_id][crop]
            elapsed = lambda r: (r.dormancy_release - r.record_start).total_seconds() / 3600.0 if r.dormancy_release else None
            difference = abs(elapsed(n) - elapsed(s)) if elapsed(n) is not None and elapsed(s) is not None else None
            rows.append({
                "crop": crop, "north": n.to_dict(), "south": s.to_dict(),
                "north_chill_months": winter_months(north, n), "south_chill_months": winter_months(south, s),
                "release_elapsed_difference_h": difference,
                "passed": difference is not None and difference <= 48.0 and n.dormancy_release.month in {12, 1, 2, 3, 4} and s.dormancy_release.month in {6, 7, 8, 9, 10},
            })
        control = self._northern_calendar_anchor_control(south)
        return {
            "status": "PASS" if all(row["passed"] for row in rows) and control["detected"] else "FAIL",
            "method": "thermally equivalent synthetic years (daily anomalies off, same profile, warmest day NH 200 / SH 17); release measured in elapsed hours from the analysis start",
            "tolerance_h": 48.0, "tolerance_kind": "ENGINEERING_TEST_THRESHOLD (calendar-year day-of-year vs 365.25-day cycle)",
            "rows": rows, "negative_control": control,
        }

    def _northern_calendar_anchor_control(self, south: SyntheticLocation) -> dict[str, Any]:
        """Deliberately wrong counter restricted to the northern October-May window:
        it must disagree with the calendar-free controller for a southern location."""
        start = south.analysis_start(SEASON_YEAR)
        weather = location_weather(south, self.seed, daily_temperature_c=0.0)
        profile = PhenologyEngine().profile_for("peach")
        anchored, correct = 0.0, 0.0
        for hour in range(365 * 24):
            timestamp = start + timedelta(hours=hour + 1)
            effective = profile.chilling_min_temperature_c <= weather(timestamp).temperature_c <= profile.chilling_max_temperature_c
            correct += effective
            anchored += effective and timestamp.month not in {6, 7, 8, 9}
        return {"description": "chill counted only outside June-September (a northern October-May anchor)", "anchored_chill_h": anchored, "calendar_free_chill_h": correct, "detected": anchored < 0.5 * correct}

    def calendar_independence(self) -> dict[str, Any]:
        location = self.location("NH_38N_MEDITERRANEAN")
        start = location.analysis_start(SEASON_YEAR)
        series = record_series(location_weather(location, self.seed), start, 365)
        # Explicit experimental instant inside the base record's chill season (not a rule).
        fixed_instant = start + timedelta(days=150)
        rows = []
        for shift_days in (0, 40, 91, 182):
            shifted = start + timedelta(days=shift_days)
            replay = ReplayedWeather(series, shifted)
            state = run_dormancy_season("peach", replay, shifted, 365)
            fixed = run_dormancy_season("peach", replay, shifted, 365, policy=ChillingStartPolicy(ChillingStartPolicyType.FIXED_DATE, fixed_instant))
            rows.append({"shift_days": shift_days, "record_start": shifted.isoformat(), "dormancy_state_elapsed_hash": state.elapsed_hash, "dormancy_state_chill_h": state.chill_total,
                         "dormancy_state_days_to_release": state.to_dict()["days_to_release"], "fixed_date_instant": fixed_instant.isoformat(),
                         "fixed_date_excluded_chill_h": fixed.chill_excluded_by_policy_hours, "fixed_date_days_to_release": fixed.to_dict()["days_to_release"]})
        independent = len({row["dormancy_state_elapsed_hash"] for row in rows}) == 1
        fixed_depends = len({row["fixed_date_days_to_release"] for row in rows}) > 1
        return {"status": "PASS" if independent and fixed_depends else "FAIL", "rows": rows,
                "dormancy_state_calendar_independent": independent, "fixed_date_depends_on_calendar": fixed_depends,
                "interpretation": "same thermal sequence at different calendar dates gives identical accumulation unless a policy explicitly uses the calendar (FIXED_DATE)"}

    def location_metadata_independence(self) -> dict[str, Any]:
        base = self.location("NH_38N_MEDITERRANEAN")
        start = base.analysis_start(SEASON_YEAR)
        series = record_series(location_weather(base, self.seed), start, 365)
        variants = [replace(base, location_id=f"META_{lat}_{lon}", latitude=lat, longitude=lon) for lat, lon in ((20.0, -1.1), (38.0, -1.1), (50.0, -1.1), (-35.0, -1.1), (38.0, 140.0), (38.0, -120.0))]
        hashes = {variant.location_id: run_dormancy_season("apple", ReplayedWeather(series, start), start, 365, location=variant).trajectory_hash for variant in variants}
        tree = ast.parse((self.root / "src" / "agri_twin" / "domain" / "phenology.py").read_text(encoding="utf-8"))
        tokens = _identifier_tokens(tree, ("latitude", "longitude", "hemisphere", "elevation"))
        passed = len(set(hashes.values())) == 1 and not tokens
        return {"status": "PASS" if passed else "FAIL", "trajectory_hashes": hashes, "physiology_location_tokens": tokens,
                "interpretation": "latitude/longitude are environmental metadata; with the weather series held constant they do not change chilling, and the physiology has no location input"}

    def climate_comparison(self) -> dict[str, Any]:
        location = self.location("NH_38N_MEDITERRANEAN")
        start = location.analysis_start(SEASON_YEAR)
        winters = {"warm": {"temperature_offset_c": 4.0}, "moderate": {}, "cold": {"temperature_offset_c": -4.0}, "high_variability": {"daily_temperature_c": 6.0}}
        rows = []
        for crop in self.species:
            results = {name: run_dormancy_season(crop, location_weather(location, self.seed, **changes), start, 365, location=location) for name, changes in winters.items()}
            rows.append({"crop": crop, **{name: result.to_dict() for name, result in results.items()},
                         "warm_not_more_chill_than_moderate": results["warm"].chill_total <= results["moderate"].chill_total,
                         "all_finite": all(result.finite for result in results.values())})
        return {"status": "PASS" if all(row["warm_not_more_chill_than_moderate"] and row["all_finite"] for row in rows) else "FAIL", "winters": winters, "rows": rows,
                "note": "only the warm-vs-moderate ordering is asserted (fewer hours reach 0-7.2 C); cold and high-variability winters are reported, since colder air can also fall below 0 C"}

    def phase532_reproduction(self) -> dict[str, Any]:
        weather = WeatherEngine(weather_configuration(climate_profile("BASE_SEASON"), 532)).generate
        starts = {"01-Oct": datetime(2025, 10, 1, tzinfo=UTC), "01-Nov": datetime(2025, 11, 1, tzinfo=UTC), "01-Dec": datetime(2025, 12, 1, tzinfo=UTC), "01-Jan": datetime(2026, 1, 1, tzinfo=UTC), "01-Feb": datetime(2026, 2, 1, tzinfo=UTC)}
        end = datetime(2026, 7, 1, tzinfo=UTC)
        rows = []
        for crop in self.species:
            for label, start in starts.items():
                result = run_dormancy_season(crop, weather, start, (end - start).days)
                rows.append({"campaign_start": label, "experimental_date": True, **result.to_dict()})
        expected = {"01-Oct": "RELEASED", "01-Nov": "RELEASED", "01-Jan": "INSUFFICIENT_TEMPORAL_CONTEXT", "01-Feb": "INSUFFICIENT_TEMPORAL_CONTEXT"}
        peach_apple = [row for row in rows if row["crop"] in {"peach", "apple"} and row["campaign_start"] in expected]
        diagnosed = all(row["outcome"] == expected[row["campaign_start"]] for row in peach_apple)
        return {
            "status": "PASS" if diagnosed else "FAIL",
            "climate": "Phase 5.32 BASE_SEASON synthetic climate, seed 532",
            "rows": rows,
            "diagnosis": "WINDOW (insufficient temporal context): effective chill starts in mid-November; campaigns starting on 1 January or 1 February miss it. The 600 h requirement is reachable when the record starts before chill onset; requirement, forcing and transitions are not the cause.",
            "note": "the start dates are experiments, not candidate rules",
        }

    def twin_integration(self) -> dict[str, Any]:
        """Full twin (ScenarioRunner + orchestrator) for peach from an explicit 1-Nov record start."""
        start, end = datetime(2025, 11, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)
        initial = initial_dormant_state("peach", start)
        soil = SoilState(0.35, 15.0, 0.35, 0.10, 0.0, 150.0)
        scenario = Scenario("p533_peach_twin", "p533_peach_twin", "peach full twin from an explicit record start", "peach", "UNSPECIFIED", start, end, 3600, ScenarioKind.SYNTHETIC,
                            initial, soil, WeatherState(20.0, 60.0, 0.0, 2.0, 180.0, 0.0, 1013.0), "outdoor",
                            (ScenarioEvent("irrigation", "irrigation", start, end, 0.4, {"amount_mm": 0.4}),), labels=("climate=BASE_SEASON", "weather_seed=532"), seed=532)
        runner = ScenarioRunner(seasonal_weather_factory)
        first, second = runner.run(scenario), runner.run(scenario)
        snaps = first.snapshots
        release = next((s.simulation_time for s in snaps if s.crop.dormancy_released), None)
        before = [s for s in snaps if not s.crop.dormancy_released]
        grew_before = any(s.actual_growth_g_m2 > 0 for s in before)
        grew_after = any(s.actual_growth_g_m2 > 0 for s in snaps if s.crop.dormancy_released)
        suite = SeasonalSyntheticCampaignSuite(self.root, registry=self.registry, crops=("peach",), include_multi=False)
        restart = suite.restart(SimpleNamespace(run_id=scenario.scenario_id, scenario=scenario), first)
        from agri_twin.application.integrated_synthetic_validation import trajectory_hash

        deterministic = trajectory_hash(first.snapshots) == trajectory_hash(second.snapshots)
        passed = release is not None and not grew_before and grew_after and restart["status"] == "PASS" and deterministic
        return {"status": "PASS" if passed else "FAIL", "dormancy_release": release.isoformat() if release else None, "growth_before_release": grew_before, "growth_after_release": grew_after,
                "final_biomass_g_m2": snaps[-1].crop.biomass_total, "final_maturity": snaps[-1].crop.maturity_index, "restart": restart, "deterministic_replay": deterministic,
                "chain": "Phenology / dormancy -> growth-stage eligibility -> growth engines (orchestrator)"}

    def multi_plot(self) -> dict[str, Any]:
        """Several plots on one SimulationClock/SimulationScheduler; combined equals isolated."""
        plots = (("peach", self.location("NH_38N_MEDITERRANEAN")), ("apple", self.location("SH_35S_TEMPERATE")), ("plum", self.location("NH_50N_CONTINENTAL")))
        start = datetime(2025, 7, 19, tzinfo=UTC)
        days = 400
        clock = SimulationClock(start)
        scheduler = SimulationScheduler(clock, DT)
        engines = {crop: PhenologyEngine() for crop, _ in plots}
        weathers = {crop: location_weather(location, self.seed) for crop, location in plots}
        states = {crop: initial_dormant_state(crop, start) for crop, _ in plots}

        def make_tick(crop: str):
            def tick(timestamp: datetime) -> None:
                states[crop] = engines[crop].advance(states[crop], weathers[crop](timestamp), timestamp, DT)
            return tick

        for crop, _ in plots:
            scheduler.register(f"plot-{crop}", DT, make_tick(crop))
        scheduler.advance(days * 86400.0)
        isolated = {crop: run_dormancy_season(crop, location_weather(location, self.seed), start, days, location=location).final_state for crop, location in plots}
        equal = all(states[crop] == isolated[crop] for crop, _ in plots)
        return {"status": "PASS" if equal and clock.now() == start + timedelta(days=days) else "FAIL", "plots": [f"{crop}@{location.location_id}" for crop, location in plots],
                "single_clock_final_time": clock.now().isoformat(), "combined_equals_isolated": equal,
                "released": {crop: state.dormancy_released for crop, state in states.items()}}

    def multi_cycle(self) -> dict[str, Any]:
        location = self.location("NH_38N_MEDITERRANEAN")
        weather = location_weather(location, self.seed)
        first_start = location.analysis_start(SEASON_YEAR)
        second_start = location.analysis_start(SEASON_YEAR + 1)
        first = run_dormancy_season("plum", weather, first_start, (second_start - first_start).days, location=location)
        second = run_dormancy_season("plum", weather, second_start, 365, location=location)
        inherited = run_dormancy_season("plum", weather, second_start, 365, location=location, initial=replace(first.final_state, simulation_time=second_start)) if first.final_state else None
        fresh = second.final_state is not None and second.dormancy_release is not None and second.first_effective_chill is not None and second.first_effective_chill > second_start
        not_inherited = inherited is not None and inherited.trajectory_hash != second.trajectory_hash and inherited.dormancy_release is None
        return {"status": "PASS" if fresh and not_inherited else "FAIL", "first_season": first.to_dict(), "second_season": second.to_dict(),
                "second_season_starts_fresh": fresh, "carrying_released_state_would_skip_chilling": not_inherited,
                "capability": "OPEN_MODEL_CAPABILITY: PhenologyEngine has no dormancy induction (post-harvest -> dormancy); each dormancy season starts from an explicit dormant state"}

    # -- audit, integrity -------------------------------------------------------------

    def physiology_static_audit(self) -> dict[str, Any]:
        path = self.root / "src" / "agri_twin" / "domain" / "phenology.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        months = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")
        month_tokens = sorted({month for month in months for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str) and month in node.value.lower()})
        calendar_calls = [f"line {node.lineno}" for node in ast.walk(tree) if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) in {"datetime", "date"}]
        month_attributes = [f"line {node.lineno}" for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr in {"month", "tm_yday", "timetuple"}]
        location_tokens = _identifier_tokens(tree, ("latitude", "longitude", "hemisphere", "elevation"))
        source_root = self.root / "src" / "agri_twin"
        chilling_classes = sorted(f"{p.relative_to(source_root.parent).as_posix()}:{node.name}" for p in source_root.rglob("*.py") for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))) if isinstance(node, ast.ClassDef) and ("Phenology" in node.name and node.name.endswith("Engine") or "Chilling" in node.name and ("Engine" in node.name or "Controller" in node.name)))
        project = static_audit(self.root)
        passed = not month_tokens and not calendar_calls and not month_attributes and not location_tokens and chilling_classes == ["agri_twin/domain/phenology.py:DormancyChillingController", "agri_twin/domain/phenology.py:PhenologyEngine"] and project["status"] == "PASS"
        return {"status": "PASS" if passed else "FAIL", "physiology_file": "src/agri_twin/domain/phenology.py", "hardcoded_month_names": month_tokens, "calendar_constructors": calendar_calls,
                "calendar_attributes": month_attributes, "location_tokens": location_tokens, "phenology_and_chilling_engines": chilling_classes,
                "project_static_audit": {key: project[key] for key in ("status", "violations", "duplicate_core_classes", "missing_core_classes")}}

    def _fingerprint(self) -> dict[str, str]:
        return {
            "parameter_registry": _hash([record.to_dict() for record in self.registry.records]),
            "parameter_sets": _hash({crop: ParameterSet.from_registry(self.registry, crop=crop).value_map() for crop in self.species}),
            "phenology_profiles": _hash({crop: asdict(profile) for crop, profile in APPROXIMATE_PROFILES.items()}),
            "weather_profiles": _hash({location.location_id: location.profile() for location in LOCATIONS}),
            "default_controller": _hash({"policy": ChillingStartPolicy().policy_type.value, "model": ChillingModel().model_type.value}),
        }

    def scientific_evidence(self) -> list[dict[str, Any]]:
        rows = []
        with (self.root / "src" / "crop_phenology.csv").open(encoding="utf-8-sig") as stream:
            for row in csv.DictReader(stream):
                if row["crop"] in self.species and row["stage"] == "endodormancy_release":
                    rows.append({key: row[key] for key in ("id", "crop", "parameter", "minimum", "maximum", "value", "unit", "biofix", "reference_cultivar", "reference_region", "authors", "year", "doi", "notes", "activation_status")} | {"result_type": "SCIENTIFIC_EVIDENCE"})
        return rows

    # -- report -------------------------------------------------------------------------

    def build_report(self) -> "ChillingFrameworkReport":
        before = self._fingerprint()
        sections: dict[str, Any] = {}
        matrix = self.policy_matrix()
        sections["policy_matrix"] = {"status": "PASS" if all(row["finite"] for row in matrix) else "FAIL", "rows": matrix}
        sections["hemisphere_inversion"] = self.hemisphere_inversion()
        sections["calendar_independence"] = self.calendar_independence()
        sections["location_metadata_independence"] = self.location_metadata_independence()
        sections["climate_comparison"] = self.climate_comparison()
        sections["phase532_reproduction"] = self.phase532_reproduction()
        sections["multi_plot"] = self.multi_plot()
        sections["multi_cycle"] = self.multi_cycle()
        if self.include_twin:
            sections["twin_integration"] = self.twin_integration()
        replay = self.policy_matrix()
        mismatches = [f"{a['crop']}/{a['location_id']}/{a['experiment']}" for a, b in zip(matrix, replay) if a != b]
        sections["determinism"] = {"status": "PASS" if not mismatches else "FAIL", "replayed_runs": len(replay), "mismatches": mismatches}
        sections["static_audit"] = self.physiology_static_audit()
        after = self._fingerprint()
        sections["parameter_integrity"] = {"status": "PASS" if before == after else "FAIL", "before": before, "after": after}
        return ChillingFrameworkReport(VERSION, self.seed, self.species, sections, self.scientific_evidence())

    def write_report(self, report: "ChillingFrameworkReport", directory: str | Path | None = None) -> tuple[Path, Path]:
        output = Path(directory) if directory is not None else self.root / "data" / "phenology"
        output.mkdir(parents=True, exist_ok=True)
        report_path, readme_path = output / "chilling_framework_report.json", output / "chilling_framework_README.md"
        payload = report.to_dict()
        report_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        readme_path.write_text("\n".join([
            "# Dormancy / chilling framework (Phase 5.33)",
            "",
            "Synthetic software experiments of the environment- and hemisphere-independent dormancy/chilling layer. SOFTWARE_RESULT entries are",
            "model outputs; SCIENTIFIC_EVIDENCE entries are literature rows from src/crop_phenology.csv. Nothing here is calibration or biological validation.",
            "",
            f"- status: `{payload['status']}`; decision: `{payload['scientific_decision']['outcome']}`",
            f"- report hash: `{payload['report_hash']}`",
            "",
            "## Sections",
            "",
            *[f"- {name}: `{value['status']}`" for name, value in report.sections.items()],
            "",
            "## Open scientific decisions",
            "",
            *[f"- `{item['decision']}` ({item['classification']}): {item['detail']}" for item in payload["open_scientific_decisions"]],
            "",
        ]), encoding="utf-8")
        return report_path, readme_path


def _identifier_tokens(tree: ast.AST, tokens: Sequence[str]) -> list[str]:
    """Location tokens used as code identifiers (names, attributes, arguments), not prose."""
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)} | {node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)}
    return sorted({token for token in tokens for name in names if token in name.lower()})


OPEN_DECISIONS = (
    {"decision": "CHILLING_START_POLICY", "classification": "POLICY_UNCERTAINTY", "detail": "several defensible policies exist (dormancy state, explicit protocol date, effective onset, model-defined onset); literature start dates are protocol conventions that differ by region and hemisphere; the policy stays configurable and no universal calendar date is adopted"},
    {"decision": "CHILLING_MODEL_SELECTION", "classification": "OPEN_SCIENTIFIC_DECISION", "detail": "only Chilling Hours is implemented; the project evidence for apple is in chill portions (Dynamic Model), and Murcia studies use the Dynamic Model; implementing Utah/Dynamic requires model parameters and cultivar requirements in the same unit"},
    {"decision": "DORMANCY_INDUCTION", "classification": "OPEN_MODEL_CAPABILITY", "detail": "no transition from post-harvest into endodormancy exists; every dormancy season starts from an explicitly configured dormant state"},
    {"decision": "CULTIVAR_REQUIREMENTS", "classification": "OPEN_SCIENTIFIC_DECISION", "detail": "runtime requirements are species-level engineering defaults; literature rows exist but are NOT_ACTIVATED and require cultivar selection and unit consistency before use"},
)


@dataclass(frozen=True, slots=True)
class ChillingFrameworkReport:
    version: str
    seed: int
    species: tuple[str, ...]
    sections: Mapping[str, Any]
    evidence: Sequence[Mapping[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        statuses = {name: value["status"] for name, value in self.sections.items()}
        software_ok = all(status == "PASS" for status in statuses.values())
        payload = {
            "phase": "5.33",
            "version": self.version,
            "status": "PASS" if software_ok else "FAIL",
            "species": list(self.species),
            "matrix_locations": sorted({row["location_id"] for row in self.sections["policy_matrix"]["rows"]}),
            "varieties": {crop: SPECIES_VARIETY[crop] for crop in self.species},
            "hemispheres": sorted({location.hemisphere for location in LOCATIONS}),
            "latitudes": {location.location_id: location.latitude for location in LOCATIONS},
            "climate_scenarios": {location.location_id: location.profile() | {"hemisphere": location.hemisphere, "longitude": location.longitude, "elevation_m": location.elevation_m} for location in LOCATIONS},
            "chilling_models": [{"model_type": model.value, "implemented": ChillingModel(model).implemented} for model in ChillingModelType],
            "start_policies": [{"policy_type": policy.value, "implemented": policy in {ChillingStartPolicyType.DORMANCY_STATE, ChillingStartPolicyType.FIXED_DATE, ChillingStartPolicyType.EFFECTIVE_CHILL_ONSET}} for policy in ChillingStartPolicyType],
            "experiments": {name: value for name, value in self.sections.items() if name not in {"determinism", "static_audit", "parameter_integrity"}},
            "determinism": self.sections["determinism"],
            "parameter_integrity": self.sections["parameter_integrity"],
            "static_audit": self.sections["static_audit"],
            "section_status": statuses,
            "scientific_evidence": [dict(row) for row in self.evidence],
            "scientific_decision": {
                "outcome": "POLICY_UNCERTAINTY",
                "universal_start_date": "NOT_JUSTIFIED",
                "statement": "ChillingStartPolicy is environment-dependent. No universal calendar date is scientifically justified. The framework supports explicit policy selection. Peach, apple and plum are compatible test cases. Northern and Southern Hemisphere use the same physiological abstraction. Real cultivar-specific calibration remains pending.",
                "default_policy": "DORMANCY_STATE (engineering default; count whenever endodormant from the start of the record)",
            },
            "open_scientific_decisions": [dict(item) for item in OPEN_DECISIONS],
            "limitations": [
                "Synthetic locations and climates are software experiments, not climatologies or agronomic zones.",
                "Only the Chilling Hours model is implemented; results in chill hours are not comparable to chill portions.",
                "Dormancy induction is not modelled; budburst is represented by the first GDD stage transition (establishment -> vegetative_growth).",
                "Requirements are species-level engineering defaults; no cultivar calibration.",
                "The temporal-context rule (24 h without effective chill before the first one) is an engineering classification rule.",
            ],
            "real_agricultural_data_verified": False,
            "calibration_performed": False,
            "experimental_validation_performed": False,
            "biological_validity_claimed": False,
        }
        payload["report_hash"] = _hash(payload)
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, default=str)


__all__ = [
    "ChillingFrameworkReport",
    "DormancyChillingFrameworkSuite",
    "DormancyOutcome",
    "DormancySeasonResult",
    "LOCATIONS",
    "ReplayedWeather",
    "SyntheticLocation",
    "hemisphere",
    "initial_dormant_state",
    "location_weather",
    "record_series",
    "run_dormancy_season",
]
