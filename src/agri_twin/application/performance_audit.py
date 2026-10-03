"""Performance, latency and scalability audit of the existing twin stack (Phase 5.36).

PERFORMANCE_INSTRUMENTATION only. This module measures the existing components
(configuration loaders, ParameterRegistry, WeatherEngine, PhenologyEngine,
GreenhouseMicroclimateEngine, the orchestrator, ScenarioRunner, the dormancy season
driver, validators and report builders); it does not reimplement any model logic
and adds no timing call to the scientific code.

``time.perf_counter`` and ``cProfile`` are used here as instrumentation (the only
other ``perf_counter`` uses are the pre-existing execution-metadata timers of the
sensitivity, integrated and seasonal validation suites; no domain module and no
simulation step uses a clock other than SimulationClock). Wall-clock
values are PERFORMANCE_MEASUREMENT: they never enter configuration hashes, workload
hashes or the report's ``deterministic_hash``. What is deterministic and hashed:
workload descriptions, step counts, simulation output hashes (trajectory hashes),
profiler call counts and the optimization equivalence checks.

Every workload is run sequentially on one thread; there is no concurrency.
"""

from __future__ import annotations

import cProfile
import hashlib
import io
import json
import math
import platform
import pstats
import statistics
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from agri_twin.application.chilling_models_framework import CONFIGURATIONS as CHILLING_CONFIGURATIONS
from agri_twin.application.clock import SimulationClock
from agri_twin.application.dormancy_chilling_framework import LOCATIONS, SEASON_YEAR, DormancyChillingFrameworkSuite, location_weather, policies_for, run_dormancy_season
from agri_twin.application.integrated_synthetic_validation import checkpoint_payload, restore_checkpoint, resumed_scenario, snapshot_numbers, trajectory_hash, twin_state_from_snapshot
from agri_twin.application.orchestrator import CropDigitalTwinOrchestrator
from agri_twin.application.scenarios import Scenario, ScenarioRunner, _ScenarioWeatherProvider
from agri_twin.application.scheduler import SimulationScheduler
from agri_twin.application.seasonal_synthetic_campaign import (
    KNOWN_CROPS,
    SeasonalSyntheticCampaignSuite,
    _max_abs_difference,
    build_campaign,
    climate_profile,
    seasonal_weather_factory,
    weather_configuration,
)
from agri_twin.application.twin_state import InMemoryTwinStateRepository, TwinSnapshot
from agri_twin.application.weather import WeatherEngine
from agri_twin.domain import (
    ClimateStressEngine,
    CropGrowthEngine,
    GreenhouseMicroclimateEngine,
    NutrientBalanceEngine,
    PhenologyEngine,
    RadiationGrowthEngine,
    WaterBalanceEngine,
)
from agri_twin.domain.calibration import ParameterSet
from agri_twin.domain.crop import CropConfigRepository
from agri_twin.domain.farm import FarmConfigRepository
from agri_twin.domain.growth_configuration import GrowthModelConfigurationRepository
from agri_twin.domain.parameter_audit import ParameterRegistry
from agri_twin.domain.phenology import APPROXIMATE_PROFILES, DormancyChillingController, canonicalize_dormancy_configuration
from agri_twin.domain.water_balance import IrrigationRequest
from agri_twin.domain.weather import WeatherConfiguration

UTC = timezone.utc
VERSION = "5.36.0"
SEED = 532
DT = 3600.0
SCENARIO_MATRIX = ("BASE_SEASON", "HOT_SEASON", "COLD_SEASON", "DRY_SEASON", "HUMID_SEASON", "HEAT_WAVE", "COLD_WAVE", "HEAT_WAVE_WITH_DRYNESS")
GREENHOUSE_CROPS = ("tomato", "lettuce", "pepper")
CHILLING_WORKLOADS = ("CHILLING_HOURS+DEFAULT", "FIXED_DATE+UTAH+SOFTWARE_TEST_ONLY", "DYNAMIC+STRICT+SOFTWARE_TEST_ONLY")
MULTI_PLOT_START = datetime(2026, 4, 1, tzinfo=UTC)
# Advisory, technology-neutral latency bands for one simulation request on the audit machine.
FRONTEND_BANDS = (("INTERACTIVE", 1.0), ("INTERACTIVE_WITH_PROGRESS", 10.0), ("BACKGROUND_TASK", 120.0), ("BATCH_ONLY", math.inf))
BOTTLENECK_CLASSES = ("MODEL_COMPUTATION", "STATE_MANAGEMENT", "SERIALIZATION", "PERSISTENCE", "VALIDATION", "DIAGNOSTICS", "REPORTING", "CONFIGURATION",
                      "DUPLICATED_WORK", "ALLOCATION", "PYTHON_OVERHEAD", "I/O", "OTHER")


OPTIMIZATIONS: tuple[Mapping[str, Any], ...] = (
    {"id": "O1_RESTART_SNAPSHOT_FLATTENING", "scope": "VALIDATION (Phase 5.32 SeasonalSyntheticCampaignSuite.restart)", "classification": "DUPLICATED_WORK",
     "evidence": "validation profile: _numeric_fields/fields/isinstance/getattr ~70 % of evaluate+restart; snapshot_numbers(b) was rebuilt once per key (~80 keys) for every compared snapshot",
     "change": "flatten each compared snapshot once (_max_abs_difference); same keys, same order, same subtraction and max",
     "scientific_risk": "NONE (validation comparison only; no model, state or trajectory touched)", "equivalence": "restart rows byte-identical to the pre-5.36 expression (oracle) - see optimization_equivalence"},
    {"id": "O2_POLICY_MATRIX_WEATHER_REPLAY", "scope": "VALIDATION (Phase 5.33 DormancyChillingFrameworkSuite.policy_matrix)", "classification": "DUPLICATED_WORK",
     "evidence": "profile: WeatherEngine.generate 52 % of policy_matrix; 12 executed seasons per location regenerate the identical hourly series",
     "change": "generate each location's series once per policy_matrix call (record_series) and replay it (ReplayedWeather), as Phase 5.34 already does",
     "scientific_risk": "NONE (identical forcing values; weather engine, equations and trajectories unchanged)",
     "equivalence": "all policy-matrix rows byte-identical to the live-weather loop and to the committed Phase 5.33 artifact - see optimization_equivalence"},
    {"id": "O3_READINESS_TEST_SHARED_EVALUATION", "scope": "TEST_INFRASTRUCTURE (tests/test_scientific_readiness.py)", "classification": "DUPLICATED_WORK",
     "evidence": "baseline regression --durations: 13 tests x 13-28 s each re-ran the same deterministic evaluate_scientific_readiness(ROOT)",
     "change": "module-scoped read-only fixtures; determinism tests still compare against an independent fresh evaluation; the mutation test evaluates on its own; no assertion changed",
     "scientific_risk": "NONE (tests only)", "equivalence": "same 14 assertions pass"},
)

DUPLICATED_WORK_AUDIT: tuple[Mapping[str, str], ...] = (
    {"item": "parameter lookups / registry construction", "finding": "ParameterRegistry.from_repository ~13 ms; built per suite and per test, not per step", "decision": "NECESSARY"},
    {"item": "configuration canonicalization", "finding": "DormancyConfiguration canonicalized once per controller (~22 us); not per step", "decision": "NECESSARY"},
    {"item": "repeated hashing", "finding": "trajectory_hash ~94 us/snapshot; used by validators and determinism replays, never by the simulation step", "decision": "SHOULD_REMAIN_EXPLICIT"},
    {"item": "repeated JSON serialization / to_dict", "finding": "checkpoint_payload ~79 us, crop.to_dict ~26 us; only in checkpoint/persistence validation", "decision": "NECESSARY"},
    {"item": "state copies (dataclasses.replace)", "finding": "7 CropGrowthState replacements per step, each re-running __post_init__ (~34 % of simulation time)", "decision": "SHOULD_REMAIN_EXPLICIT (invariant contract; OPEN_PERFORMANCE_ARCHITECTURE)"},
    {"item": "filesystem writes", "finding": "artifact writing ~2 ms per report; no writes inside simulation", "decision": "NECESSARY"},
    {"item": "report generation", "finding": "Phase 5.33 build_report replays its whole policy matrix for determinism", "decision": "NECESSARY (determinism evidence)"},
    {"item": "weather for identical inputs", "finding": "Phase 5.33 policy matrix regenerated identical series 12x per location", "decision": "REDUNDANT -> fixed (O2)"},
    {"item": "phenology / greenhouse calculations", "finding": "one call per step per engine; no recomputation for identical inputs found", "decision": "NECESSARY"},
    {"item": "invariant calculations", "finding": "snapshot_numbers rebuilt per key in Phase 5.32 restart", "decision": "REDUNDANT -> fixed (O1)"},
    {"item": "validation of immutable configuration", "finding": "Scenario/WeatherConfiguration validated at construction only", "decision": "NECESSARY"},
    {"item": "test re-evaluation of identical deterministic reports", "finding": "readiness tests re-evaluated per test (fixed, O3); other suites already share module fixtures or test different inputs", "decision": "REDUNDANT -> fixed in readiness tests (O3)"},
)

OPEN_PERFORMANCE_ARCHITECTURE: tuple[Mapping[str, str], ...] = (
    {"item": "IMMUTABLE_STATE_REVALIDATION", "evidence": "simulation profile: dataclasses._replace + CropGrowthState.__post_init__ + getattr ~40 % of a campaign",
     "note": "each orchestrator step creates ~7 validated CropGrowthState copies; removing or batching validation would change the invariant contract - not done in this phase"},
    {"item": "VALIDATION_DOMINATES_SUITE_TIME", "evidence": "same campaign: simulation ~1.3 s, Phase 5.32 restart validation ~14.7 s before O1; phase manuals 116-386 s vs 0.5-3.3 s per simulated season",
     "note": "phase reports re-run simulations for determinism/restart evidence; the interactive frontend should call the simulation, not the qualification suites"},
    {"item": "CROSS_ARTIFACT_FILESYSTEM_DEPENDENCY", "evidence": "Phase 5.34/5.35 reports read the committed Phase 5.33/5.34 artifacts (baseline_report_hash, regression rows); rerunning an earlier manual changes later artifacts",
     "note": "hidden ordering dependency between artifacts; documented, not redesigned"},
)


def _hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _clock() -> float:
    return time.perf_counter()  # PERFORMANCE_INSTRUMENTATION only


def timed(function: Callable[[], Any], repeats: int = 1) -> tuple[Any, list[float]]:
    """Run ``function`` ``repeats`` times sequentially; return the last result and every duration."""
    durations, result = [], None
    for _ in range(max(1, repeats)):
        start = _clock()
        result = function()
        durations.append(_clock() - start)
    return result, durations


def _stats(durations: Sequence[float]) -> dict[str, float]:
    return {"min_seconds": min(durations), "median_seconds": statistics.median(durations), "max_seconds": max(durations), "repeats": len(durations)}


# ---------------------------------------------------------------------------
# Workloads
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Workload:
    """Deterministic description of one benchmark (no timing inside)."""

    workload_id: str
    category: str  # SIMULATION | VALIDATION | REPORTING | INITIALIZATION | COMPONENT
    scenario: str
    crop: str
    environment: str
    days: float
    plots: int = 1
    cycles: int = 1
    scenarios: int = 1
    model_configuration_hash: str = ""

    @property
    def simulation_steps(self) -> int:
        return int(round(self.days * 86400.0 / DT)) * self.plots * self.cycles * self.scenarios

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "simulation_steps": self.simulation_steps}


def truncated(scenario: Scenario, days: float) -> Scenario:
    """The same scenario over its first ``days`` days (events clipped, nothing else changed)."""
    end = scenario.start + timedelta(days=days)
    if end >= scenario.end:
        return scenario
    events = tuple(replace(event, end=min(event.end, end)) for event in scenario.events if event.start < end)
    return replace(scenario, end=end, events=events)


def campaign_scenario(crop: str, environment: str, scenario_id: str, days: float | None = None) -> Scenario:
    scenario = build_campaign(crop, environment, scenario_id, seed=SEED).scenario
    return truncated(scenario, days) if days is not None else scenario


def _days(scenario: Scenario) -> float:
    return (scenario.end - scenario.start).total_seconds() / 86400.0


def _campaign_workload(workload_id: str, scenario: Scenario, environment: str, scenario_id: str, *, cycles: int = 1) -> Workload:
    return Workload(workload_id, "SIMULATION", scenario_id, scenario.crop, environment, _days(scenario), cycles=cycles, model_configuration_hash=scenario.config_hash())


@dataclass(frozen=True, slots=True)
class Measurement:
    workload: Workload
    durations: tuple[float, ...]
    steps_executed: int
    output_hash: str
    breakdown: Mapping[str, float] = field(default_factory=dict)

    @property
    def elapsed_seconds(self) -> float:
        return min(self.durations)

    def deterministic(self) -> dict[str, Any]:
        return {"workload": self.workload.to_dict(), "steps_executed": self.steps_executed, "output_hash": self.output_hash}

    def to_dict(self) -> dict[str, Any]:
        elapsed = self.elapsed_seconds
        days = self.workload.days * self.workload.plots * self.workload.cycles * self.workload.scenarios
        return {
            **self.deterministic(),
            "performance_measurement": {
                **_stats(self.durations), "elapsed_seconds": elapsed,
                "seconds_per_simulated_day": elapsed / days if days else None,
                "milliseconds_per_step": 1000.0 * elapsed / self.steps_executed if self.steps_executed else None,
                "breakdown_seconds": dict(self.breakdown),
            },
        }


def run_campaign(scenario: Scenario) -> tuple[int, str]:
    result = ScenarioRunner(seasonal_weather_factory).run(scenario)
    if result.status != "SUCCESS":
        raise RuntimeError(f"benchmark campaign failed: {scenario.scenario_id}: {result.warnings}")
    return len(result.snapshots), trajectory_hash(result.snapshots)


def run_multi_plot(crops: Sequence[str], days: float) -> tuple[int, str]:
    """``len(crops)`` outdoor plots ticked by one SimulationClock/SimulationScheduler."""
    clock = SimulationClock(MULTI_PLOT_START)
    scheduler = SimulationScheduler(clock, DT)
    snapshots: dict[str, list[Any]] = {}
    for index, crop in enumerate(crops):
        spec = build_campaign(crop, "outdoor", "BASE_SEASON", seed=SEED)
        weather = WeatherEngine(weather_configuration(climate_profile("BASE_SEASON"), SEED + index))
        orchestrator = CropDigitalTwinOrchestrator(SimulationClock(MULTI_PLOT_START), weather, replace(spec.scenario.initial_crop, simulation_time=MULTI_PLOT_START), spec.scenario.initial_soil, "outdoor")
        plot = f"plot_{index:02d}_{crop}"
        snapshots[plot] = []
        irrigation = IrrigationRequest("scheduled", 0.4, irrigation_type="drip")

        def tick(timestamp: datetime, orchestrator: CropDigitalTwinOrchestrator = orchestrator, target: list[Any] = snapshots[plot], irrigation: IrrigationRequest = irrigation) -> None:
            target.append(orchestrator.step_at(timestamp, DT, None, irrigation))

        scheduler.register(plot, DT, tick)
    scheduler.advance(days * 86400.0)
    steps = sum(len(items) for items in snapshots.values())
    return steps, _hash({plot: trajectory_hash(items) for plot, items in sorted(snapshots.items())})


def run_cycles(crop: str, cycles: int, days: float | None = None) -> tuple[int, str]:
    hashes, steps = [], 0
    scenario = campaign_scenario(crop, "outdoor", "BASE_SEASON", days)
    for _ in range(cycles):
        count, digest = run_campaign(scenario)
        steps, hashes = steps + count, [*hashes, digest]
    return steps, _hash(hashes)


def run_chilling(label: str) -> tuple[int, str]:
    location = next(item for item in LOCATIONS if item.location_id == "NH_38N_MEDITERRANEAN")
    start = location.analysis_start(SEASON_YEAR)
    result = run_dormancy_season("peach", location_weather(location, 533), start, 365, location=location, configuration=dict(CHILLING_CONFIGURATIONS)[label])
    return 365 * 24, result.trajectory_hash


# ---------------------------------------------------------------------------
# Suite
# ---------------------------------------------------------------------------


class PerformanceAuditSuite:
    """Canonical deterministic benchmark matrix, profiling, scaling and frontend estimates."""

    VERSION = VERSION

    def __init__(self, root: str | Path, *, repeats: int = 2, quick: bool = False, profile_top: int = 25) -> None:
        self.root = Path(root)
        self.repeats = repeats
        self.quick = quick  # reduced matrix for tests (same code paths, shorter horizons)
        self.profile_top = profile_top

    # -- matrix --------------------------------------------------------------------------

    def _full_days(self, days: float | None) -> float | None:
        return 7.0 if self.quick and days is None else (min(days, 7.0) if self.quick and days is not None else days)

    def benchmark_matrix(self) -> list[tuple[Workload, Callable[[], tuple[int, str]]]]:
        matrix: list[tuple[Workload, Callable[[], tuple[int, str]]]] = []

        def campaign(workload_id: str, crop: str, environment: str, scenario_id: str, days: float | None = None) -> None:
            scenario = campaign_scenario(crop, environment, scenario_id, self._full_days(days))
            matrix.append((_campaign_workload(workload_id, scenario, environment, scenario_id), lambda scenario=scenario: run_campaign(scenario)))

        campaign("small_tomato_outdoor_7d", "tomato", "outdoor", "BASE_SEASON", 7.0)
        campaign("medium_tomato_outdoor_full_season", "tomato", "outdoor", "BASE_SEASON")
        for scenario_id in SCENARIO_MATRIX[1:]:
            campaign(f"scenario_tomato_outdoor_{scenario_id.lower()}", "tomato", "outdoor", scenario_id)
        for crop in KNOWN_CROPS:
            if crop != "tomato":
                campaign(f"crop_{crop}_outdoor_full_season", crop, "outdoor", "BASE_SEASON")
        for crop in GREENHOUSE_CROPS:
            campaign(f"greenhouse_{crop}_full_season", crop, "greenhouse", "BASE_SEASON")
        plot_days = 7.0 if self.quick else 30.0
        crops = tuple(KNOWN_CROPS)
        matrix.append((Workload("multi_plot_7_crops_outdoor", "SIMULATION", "BASE_SEASON", "+".join(crops), "outdoor", plot_days, plots=len(crops),
                                model_configuration_hash=_hash([build_campaign(crop, "outdoor", "BASE_SEASON", seed=SEED).scenario.config_hash() for crop in crops])),
                       lambda: run_multi_plot(crops, plot_days)))
        cycle_scenario = campaign_scenario("lettuce", "outdoor", "BASE_SEASON", self._full_days(None))
        matrix.append((_campaign_workload("multi_cycle_lettuce_outdoor_x3", cycle_scenario, "outdoor", "BASE_SEASON", cycles=3), lambda: run_cycles("lettuce", 3, self._full_days(None))))
        if not self.quick:
            for label in CHILLING_WORKLOADS:
                config = canonicalize_dormancy_configuration(dict(CHILLING_CONFIGURATIONS)[label])
                matrix.append((Workload(f"chilling_{label.split('+')[0].lower()}_{label.split('+')[1].lower()}_peach_365d", "SIMULATION", "NH_38N_MEDITERRANEAN", "peach", "outdoor", 365.0,
                                        model_configuration_hash=config.configuration_hash), lambda label=label: run_chilling(label)))
        return matrix

    def run_matrix(self) -> list[Measurement]:
        rows = []
        for workload, function in self.benchmark_matrix():
            (steps, digest), durations = timed(function, self.repeats)
            rows.append(Measurement(workload, tuple(durations), steps, digest))
        return rows

    # -- initialization and per-step components ---------------------------------------------

    def initialization(self) -> list[dict[str, Any]]:
        root, repeats = self.root, 3 if self.quick else 10
        src = root / "src"
        spec = build_campaign("tomato", "greenhouse", "BASE_SEASON", seed=SEED)
        cases: list[tuple[str, str, Callable[[], Any]]] = [
            ("configuration.crop_config", "CONFIGURATION", lambda: CropConfigRepository(src / "crop_config.json")),
            ("configuration.farm_config", "CONFIGURATION", lambda: FarmConfigRepository(src / "farm_config.json")),
            ("configuration.growth_model_config", "CONFIGURATION", lambda: GrowthModelConfigurationRepository(src / "growth_model_config.json", src / "crop_config.json", src / "farm_config.json")),
            ("parameter_registry.from_repository", "CONFIGURATION", lambda: ParameterRegistry.from_repository(root)),
            ("weather.engine", "MODEL_SETUP", lambda: WeatherEngine(weather_configuration(climate_profile("BASE_SEASON"), SEED))),
            ("phenology.engine_default", "MODEL_SETUP", lambda: PhenologyEngine()),
            ("phenology.controller_canonical_configuration", "MODEL_SETUP", lambda: DormancyChillingController(configuration=dict(CHILLING_CONFIGURATIONS)["DYNAMIC+STRICT+SOFTWARE_TEST_ONLY"])),
            ("greenhouse.engine", "MODEL_SETUP", lambda: GreenhouseMicroclimateEngine()),
            ("scenario.build_campaign", "SCENARIO_SETUP", lambda: build_campaign("tomato", "greenhouse", "BASE_SEASON", seed=SEED)),
            ("scenario.config_hash", "SCENARIO_SETUP", lambda: spec.scenario.config_hash()),
            ("orchestrator.construct", "MODEL_SETUP", lambda: CropDigitalTwinOrchestrator(SimulationClock(spec.scenario.start), WeatherEngine(weather_configuration(climate_profile("BASE_SEASON"), SEED)), spec.scenario.initial_crop, spec.scenario.initial_soil, "passive_greenhouse")),
            ("twin_state.repository", "PERSISTENCE", lambda: InMemoryTwinStateRepository()),
        ]
        rows = []
        for name, kind, function in cases:
            _, durations = timed(function, repeats)
            rows.append({"component": name, "kind": kind, **_stats(durations)})
        return rows

    def step_components(self) -> dict[str, Any]:
        """Per-call cost of each existing engine on one representative mid-season state."""
        spec = build_campaign("tomato", "greenhouse", "BASE_SEASON", seed=SEED)
        scenario = truncated(spec.scenario, 60.0)
        result = ScenarioRunner(seasonal_weather_factory).run(scenario)
        snapshot = result.snapshots[len(result.snapshots) // 2]
        previous = result.snapshots[len(result.snapshots) // 2 - 1]
        t = snapshot.simulation_time
        crop, soil, micro = previous.crop, previous.soil, previous.microclimate.indoor_state
        base = seasonal_weather_factory(scenario)
        scenario_provider = _ScenarioWeatherProvider(scenario, base)
        weather_engine = WeatherEngine(WeatherConfiguration(simulation=WeatherConfiguration().simulation), provider=scenario_provider)
        outdoor = snapshot.outdoor_weather
        greenhouse, phenology, radiation, water, nutrients, climate = GreenhouseMicroclimateEngine(), PhenologyEngine(), RadiationGrowthEngine(), WaterBalanceEngine(), NutrientBalanceEngine(), ClimateStressEngine()
        indoor = snapshot.weather
        irrigation = IrrigationRequest("scheduled", 0.4, irrigation_type="drip")
        phenological = replace(phenology.advance(crop, indoor, t, DT), soil_water_vwc=soil.vwc_m3_m3)
        potential = radiation.advance(phenological, indoor, DT)
        water_result = water.advance(soil, indoor, DT, phenological, irrigation)
        nutrient_result = nutrients.advance(phenological, potential.biomass_total - phenological.biomass_total, DT, None)
        repository = InMemoryTwinStateRepository()
        cases: list[tuple[str, str, Callable[[], Any]]] = [
            ("weather.base_seasonal_engine", "MODEL_COMPUTATION", lambda: base.get(t)),
            ("weather.scenario_event_overlay", "MODEL_COMPUTATION", lambda: scenario_provider.get(t)),
            ("weather.engine_generate_total", "MODEL_COMPUTATION", lambda: weather_engine.generate(t)),
            ("greenhouse.advance", "MODEL_COMPUTATION", lambda: greenhouse.advance(outdoor, crop, DT, "passive_greenhouse", None, prior=micro)),
            ("phenology.advance", "MODEL_COMPUTATION", lambda: phenology.advance(crop, indoor, t, DT)),
            ("radiation_growth.advance", "MODEL_COMPUTATION", lambda: radiation.advance(phenological, indoor, DT)),
            ("water_balance.advance", "MODEL_COMPUTATION", lambda: water.advance(soil, indoor, DT, phenological, irrigation)),
            ("nutrient_balance.advance", "MODEL_COMPUTATION", lambda: nutrients.advance(phenological, potential.biomass_total - phenological.biomass_total, DT, None)),
            ("climate_stress.advance", "MODEL_COMPUTATION", lambda: climate.advance(nutrient_result.state, indoor, DT, snapshot.environment, water_result.water_stress, nutrient_result.nutrient_factor)),
            ("co2_response", "MODEL_COMPUTATION", lambda: CropGrowthEngine.co2_response(micro.co2_ppm)),
            ("state.replace_crop_growth_state", "STATE_MANAGEMENT", lambda: replace(crop, soil_water_vwc=soil.vwc_m3_m3)),
            ("persistence.twin_state_from_snapshot", "PERSISTENCE", lambda: twin_state_from_snapshot(snapshot, spec)),
            ("serialization.crop_to_dict", "SERIALIZATION", lambda: snapshot.crop.to_dict()),
            ("serialization.checkpoint_payload", "SERIALIZATION", lambda: checkpoint_payload(snapshot)),
            ("serialization.snapshot_numbers", "VALIDATION", lambda: snapshot_numbers(snapshot)),
            ("hashing.trajectory_hash_one_snapshot", "SERIALIZATION", lambda: trajectory_hash((snapshot,))),
        ]
        calls = 50 if self.quick else 400
        rows = []
        for name, kind, function in cases:
            _, durations = timed(lambda function=function: [function() for _ in range(calls)], 3)
            rows.append({"component": name, "kind": kind, **_stats([d / calls for d in durations]), "calls_per_sample": calls})
        stored = result.snapshots[:calls]

        def save_all() -> None:
            repository = InMemoryTwinStateRepository()
            for item in stored:
                repository.save_snapshot(TwinSnapshot(item.simulation_time, (twin_state_from_snapshot(item, spec),)))

        _, durations = timed(save_all, 3)
        rows.append({"component": "persistence.repository_save_snapshot", "kind": "PERSISTENCE", **_stats([d / len(stored) for d in durations]), "calls_per_sample": len(stored)})
        cost = {row["component"]: row["min_seconds"] for row in rows}
        model_ids = ("greenhouse.advance", "phenology.advance", "radiation_growth.advance", "radiation_growth.advance", "water_balance.advance", "nutrient_balance.advance", "climate_stress.advance", "co2_response")
        estimate = cost["weather.engine_generate_total"] + sum(cost[name] for name in model_ids) + cost["state.replace_crop_growth_state"] * 2
        return {"state": {"crop": "tomato", "environment": "passive_greenhouse", "simulation_time": t.isoformat(), "stage": crop.current_stage},
                "rows": rows, "per_step_components_seconds_estimate": estimate,
                "note": "isolated calls with fixed inputs; radiation_growth.advance runs twice per orchestrator step (potential and actual growth); the estimate sums weather, every engine call and the two explicit state replacements of one step"}

    # -- simulation vs validation vs reporting ----------------------------------------------

    def cost_separation(self) -> dict[str, Any]:
        days = 7.0 if self.quick else None
        spec = build_campaign("tomato", "outdoor", "BASE_SEASON", seed=SEED)
        if days is not None:
            spec = replace(spec, scenario=truncated(spec.scenario, days), window=None)
        suite = SeasonalSyntheticCampaignSuite(self.root, crops=("tomato",), scenarios=("BASE_SEASON",), supplementary=False, include_multi=False)
        result, simulation = timed(lambda: suite.run(spec), self.repeats)
        evaluation, evaluation_time = timed(lambda: suite.evaluate(spec, result), 1)
        _, hashing = timed(lambda: trajectory_hash(result.snapshots), self.repeats)
        _, restart = timed(lambda: suite.restart(spec, result), 1)
        _, persistence = timed(lambda: suite.persistence(spec, result), 1)
        _, replay = timed(lambda: suite.run(spec), 1)
        sim = min(simulation)
        parts = {"simulation_seconds": sim, "validation_seconds": evaluation_time[0], "serialization_hashing_seconds": min(hashing),
                 "checkpoint_restart_validation_seconds": restart[0], "persistence_validation_seconds": persistence[0], "determinism_replay_seconds": replay[0]}
        infrastructure = sum(value for key, value in parts.items() if key != "simulation_seconds")
        return {"workload": {"crop": "tomato", "environment": "outdoor", "scenario": "BASE_SEASON", "days": _days(spec.scenario), "steps": len(result.snapshots),
                             "trajectory_hash": evaluation.trajectory_hash},
                "seconds": parts, "infrastructure_to_simulation_ratio": infrastructure / sim if sim else None,
                "answer": {"twin_simulation_seconds": sim, "validation_and_reporting_infrastructure_seconds": infrastructure}}

    def reporting(self) -> dict[str, Any]:
        suite = SeasonalSyntheticCampaignSuite(self.root, crops=("lettuce",), scenarios=("BASE_SEASON",), supplementary=False, include_multi=False)
        report, build = timed(suite.build_report, 1)
        payload, to_dict = timed(report.to_dict, self.repeats)
        text, dumps = timed(lambda: json.dumps(payload, indent=2, sort_keys=True, default=str), self.repeats)
        _, digest = timed(lambda: hashlib.sha256(text.encode("utf-8")).hexdigest(), self.repeats)
        with tempfile.TemporaryDirectory() as scratch:
            _, write = timed(lambda: suite.write_report(report, scratch), self.repeats)
        campaign_seconds = report.execution_metadata.get("campaign_seconds")
        simulation = sum(campaign_seconds.values()) if isinstance(campaign_seconds, Mapping) else None
        return {"report": "SeasonalSyntheticCampaignSuite(lettuce, BASE_SEASON) Phase 5.32 builder", "bytes": len(text.encode("utf-8")),
                "seconds": {"report_construction_total": build[0], "of_which_campaign_simulation": simulation, "to_dict": min(to_dict), "json_serialization": min(dumps),
                            "sha256": min(digest), "artifact_writing_including_serialization": min(write)},
                "note": "report construction includes the builder's own validation (climate profile checks over a synthetic year, determinism replay, restarts, persistence, static audit)"}

    # -- profiling ----------------------------------------------------------------------------

    def _profile(self, label: str, function: Callable[[], Any]) -> dict[str, Any]:
        profiler = cProfile.Profile()
        profiler.enable()
        function()
        profiler.disable()
        stats = pstats.Stats(profiler, stream=io.StringIO())
        total = stats.total_tt
        entries = []
        for (filename, line, name), (primitive, calls, tottime, cumtime, _) in stats.stats.items():
            entries.append({"function": f"{_short(filename)}:{line}({name})", "module": _short(filename), "name": name, "calls": calls, "primitive_calls": primitive,
                            "tottime_seconds": tottime, "cumtime_seconds": cumtime})
        by_tottime = sorted(entries, key=lambda item: (-item["tottime_seconds"], item["function"]))[: self.profile_top]
        by_cumtime = sorted(entries, key=lambda item: (-item["cumtime_seconds"], item["function"]))[: self.profile_top]
        for item in by_tottime + by_cumtime:
            item["seconds_per_call"] = item["tottime_seconds"] / item["calls"] if item["calls"] else None
            item["percentage_of_workload"] = 100.0 * item["tottime_seconds"] / total if total else None
            item["classification"] = classify(item["module"], item["name"])
        by_class: dict[str, float] = {}
        for item in entries:
            key = classify(item["module"], item["name"])
            by_class[key] = by_class.get(key, 0.0) + item["tottime_seconds"]
        return {"workload": label, "profiled_seconds": total, "function_count": len(entries), "total_calls": sum(item["calls"] for item in entries),
                "top_by_tottime": by_tottime, "top_by_cumtime": by_cumtime,
                "time_by_classification": {key: {"seconds": value, "percentage": 100.0 * value / total if total else None} for key, value in sorted(by_class.items(), key=lambda kv: -kv[1])},
                "deterministic_call_counts": {item["function"]: item["calls"] for item in sorted(entries, key=lambda item: item["function"]) if item["module"].startswith("agri_twin")}}

    def profiling(self) -> dict[str, Any]:
        days = 7.0 if self.quick else None
        spec = build_campaign("tomato", "greenhouse", "BASE_SEASON", seed=SEED)
        if days is not None:
            spec = replace(spec, scenario=truncated(spec.scenario, days), window=None)
        suite = SeasonalSyntheticCampaignSuite(self.root, crops=("tomato",), scenarios=("BASE_SEASON",), supplementary=False, include_multi=False)
        result = suite.run(spec)
        return {
            "simulation": self._profile("simulation: tomato passive greenhouse BASE_SEASON campaign (ScenarioRunner)", lambda: suite.run(spec)),
            "validation": self._profile("validation: Phase 5.32 evaluate + checkpoint/restart of the same campaign", lambda: (suite.evaluate(spec, result), suite.restart(spec, result))),
            "note": "cProfile overhead inflates absolute times; use percentages and call counts",
        }

    # -- scaling ------------------------------------------------------------------------------

    def scaling(self) -> dict[str, Any]:
        base_days = 4.0 if self.quick else 15.0
        axes: dict[str, list[tuple[float, Callable[[], tuple[int, str]]]]] = {
            "simulation_days": [(d, lambda d=d: run_campaign(campaign_scenario("tomato", "outdoor", "BASE_SEASON", d))) for d in ((2.0, 4.0, 8.0) if self.quick else (15.0, 30.0, 60.0, 120.0))],
            "number_of_plots": [(p, lambda p=p: run_multi_plot(tuple(KNOWN_CROPS)[:1] * p, base_days)) for p in ((1, 2, 4) if self.quick else (1, 2, 4, 7))],
            "number_of_crops": [(c, lambda c=c: run_multi_plot(tuple(KNOWN_CROPS)[:c], base_days)) for c in ((1, 3) if self.quick else (1, 3, 5, 7))],
            "number_of_scenarios": [(s, lambda s=s: _run_scenarios(SCENARIO_MATRIX[:s], base_days)) for s in ((1, 2, 4) if self.quick else (1, 2, 4, 8))],
            "number_of_cycles": [(c, lambda c=c: run_cycles("lettuce", c, base_days)) for c in ((1, 2, 3) if self.quick else (1, 2, 3, 4))],
        }
        result = {}
        for axis, points in axes.items():
            rows = []
            for size, function in points:
                (steps, digest), durations = timed(function, self.repeats)
                rows.append({"size": size, "steps": steps, "output_hash": digest, "seconds": min(durations)})
            result[axis] = {"rows": rows, **fit_linear([row["size"] for row in rows], [row["seconds"] for row in rows])}
        grid = []
        for days in (base_days, 2 * base_days):
            for plots in (1, 4):
                (steps, digest), durations = timed(lambda days=days, plots=plots: run_multi_plot(tuple(KNOWN_CROPS)[:1] * plots, days), self.repeats)
                grid.append({"days": days, "plots": plots, "steps": steps, "output_hash": digest, "seconds": min(durations), "seconds_per_plot_day": min(durations) / (days * plots)})
        per_unit = [row["seconds_per_plot_day"] for row in grid]
        result["time_x_plots_grid"] = {"rows": grid, "seconds_per_plot_day_cv": statistics.pstdev(per_unit) / statistics.mean(per_unit),
                                      "consistent_with_O_T_x_P": statistics.pstdev(per_unit) / statistics.mean(per_unit) < 0.25}
        result["theoretical_structure"] = {
            "simulation_days": "O(T): one orchestrator step per hourly timestep, constant work per step",
            "number_of_plots": "O(P): one independent orchestrator per plot on a shared scheduler",
            "number_of_crops": "O(P): crops differ only in parameters/state, same step structure",
            "number_of_scenarios": "O(S): each scenario is an independent campaign",
            "number_of_cycles": "O(C): consecutive independent campaigns",
            "combined": "O(S x C x T x P)",
        }
        return result

    # -- frontend ------------------------------------------------------------------------------

    def frontend(self, matrix: Sequence[Measurement], scaling: Mapping[str, Any]) -> dict[str, Any]:
        by_id = {row.workload.workload_id: row for row in matrix}
        per_plot_day = statistics.median(row["seconds_per_plot_day"] for row in scaling["time_x_plots_grid"]["rows"])
        full_days = by_id["medium_tomato_outdoor_full_season"].workload.days
        cases = {
            "interactive_short_one_crop_one_plot": by_id["small_tomato_outdoor_7d"].elapsed_seconds,
            "interactive_full_season_one_crop_one_plot": by_id["medium_tomato_outdoor_full_season"].elapsed_seconds,
            "multi_plot_7_plots_full_season_estimate": per_plot_day * full_days * 7,
            "multi_plot_50_plots_full_season_estimate": per_plot_day * full_days * 50,
            **{f"greenhouse_{crop}_full_season": by_id[f"greenhouse_{crop}_full_season"].elapsed_seconds for crop in GREENHOUSE_CROPS},
        }
        return {"cases": {name: {"seconds": seconds, "classification": band(seconds) if seconds is not None else None} for name, seconds in cases.items() if seconds is not None},
                "bands_seconds": {name: limit for name, limit in FRONTEND_BANDS if math.isfinite(limit)},
                "basis": "simulation only (ScenarioRunner/orchestrator); validation, reporting and artifact writing excluded; single thread on the audit machine; advisory, technology-neutral"}

    # -- optimization equivalence ------------------------------------------------------------

    def restart_equivalence(self) -> dict[str, Any]:
        """O1: Phase 5.32 restart() flattens each snapshot once instead of once per key.

        Oracle: the pre-5.36 expression (``_reference_restart_difference``) applied to the
        same resumed/continuous pairs. Rows, differences and checkpoint hashes must be
        identical; both comparison passes are timed on identical inputs."""
        spec = build_campaign("tomato", "outdoor", "BASE_SEASON", seed=SEED)
        if self.quick:
            spec = replace(spec, scenario=truncated(spec.scenario, 7.0), window=None)
        suite = SeasonalSyntheticCampaignSuite(self.root, crops=("tomato",), scenarios=("BASE_SEASON",), supplementary=False, include_multi=False)
        continuous = suite.run(spec)
        optimized, optimized_seconds = timed(lambda: suite.restart(spec, continuous), 1)
        reference_rows, pairs = [], []
        steps = len(continuous.snapshots)
        for fraction in (0.25, 0.5, 0.75):
            index = int(steps * fraction)
            index = max(0, min(steps - 2, index - (index + 1 - 12) % 24))
            payload = checkpoint_payload(continuous.snapshots[index])
            restart_time, crop, soil, micro = restore_checkpoint(payload)
            resumed = suite.runner.run(resumed_scenario(spec.scenario, restart_time, crop, soil, micro))
            tail = continuous.snapshots[index + 1:]
            pairs.append((resumed.snapshots, tail))
            aligned = len(resumed.snapshots) == len(tail) and all(a.simulation_time == b.simulation_time for a, b in zip(resumed.snapshots, tail))
            difference = _reference_restart_difference(resumed.snapshots, tail)
            reference_rows.append({"checkpoint": restart_time.isoformat(), "fraction": fraction, "checkpoint_hash": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                                   "aligned": aligned, "max_difference": difference, "equivalent": aligned and difference <= 1e-9})
        reference = {"run_id": spec.run_id, "status": "PASS" if all(row["equivalent"] for row in reference_rows) else "FAIL", "checkpoints": reference_rows}
        _, reference_compare = timed(lambda: [_reference_restart_difference(a, b) for a, b in pairs], 1)
        _, optimized_compare = timed(lambda: [max((_hoisted_difference(x, y) for x, y in zip(a, b)), default=math.inf) for a, b in pairs], 1)
        identical = json.dumps(optimized, sort_keys=True, default=str) == json.dumps(reference, sort_keys=True, default=str)
        return {"optimization": "O1_RESTART_SNAPSHOT_FLATTENING", "status": "PASS" if identical else "FAIL", "rows_byte_identical": identical,
                "compared_pairs": sum(len(b) for _, b in pairs), "evidence_rows": optimized,
                "seconds": {"restart_total_optimized": optimized_seconds[0], "comparison_reference_expression": reference_compare[0], "comparison_optimized_expression": optimized_compare[0],
                            "comparison_speedup": reference_compare[0] / optimized_compare[0] if optimized_compare[0] else None}}

    def policy_matrix_equivalence(self) -> dict[str, Any]:
        """O2: Phase 5.33 policy_matrix generates each location's hourly weather once per call
        and replays it. Oracle 1: the pre-5.36 loop with live WeatherEngine weather. Oracle 2:
        the committed Phase 5.33 artifact rows (generated with live weather)."""
        location_ids = ("SH_35S_TEMPERATE",) if self.quick else tuple(item.location_id for item in LOCATIONS)
        suite = DormancyChillingFrameworkSuite(self.root, locations=location_ids, include_twin=False)
        optimized, optimized_seconds = timed(suite.policy_matrix, 1)
        reference_location = location_ids[0]
        location = next(item for item in LOCATIONS if item.location_id == reference_location)

        def reference_loop() -> list[dict[str, Any]]:  # pre-5.36 loop, verbatim, one location
            rows, start, weather = [], location.analysis_start(SEASON_YEAR), location_weather(location, suite.seed)
            for crop in suite.species:
                for label, policy in policies_for(location):
                    result = run_dormancy_season(crop, weather, start, 365, policy=policy, location=location)
                    rows.append({"experiment": label, "requirement_h": PhenologyEngine().profile_for(crop).chilling_requirement_hours, **result.to_dict()})
            return rows

        reference, reference_seconds = timed(reference_loop, 1)
        optimized_location = [row for row in optimized if row["location_id"] == reference_location]
        _, location_seconds = timed(lambda: DormancyChillingFrameworkSuite(self.root, locations=(reference_location,), include_twin=False).policy_matrix(), 1)
        identical_to_reference = _canonical(optimized_location) == _canonical(reference)
        artifact = self.root / "data" / "phenology" / "chilling_framework_report.json"
        committed = json.loads(artifact.read_text(encoding="utf-8"))["experiments"]["policy_matrix"]["rows"] if artifact.exists() else []
        committed_subset = [row for row in committed if row["location_id"] in location_ids]
        identical_to_artifact = bool(committed_subset) and _canonical(optimized) == _canonical(committed_subset)
        return {"optimization": "O2_POLICY_MATRIX_WEATHER_REPLAY", "status": "PASS" if identical_to_reference and identical_to_artifact else "FAIL",
                "rows_byte_identical": identical_to_reference and identical_to_artifact, "rows_identical_to_live_weather_loop": identical_to_reference,
                "rows_identical_to_committed_phase533_artifact": identical_to_artifact, "compared_pairs": len(optimized),
                "evidence_rows": {"locations": list(location_ids), "row_hash": _hash(_canonical(optimized))},
                "seconds": {"policy_matrix_optimized_all_locations": optimized_seconds[0], "one_location_reference_live_weather": reference_seconds[0],
                            "one_location_optimized": location_seconds[0], "one_location_speedup": reference_seconds[0] / location_seconds[0] if location_seconds[0] else None}}

    # -- report --------------------------------------------------------------------------------

    def environment(self) -> dict[str, Any]:
        return {"python": sys.version.split()[0], "implementation": platform.python_implementation(), "platform": platform.platform(), "processor": platform.processor(),
                "executable_is_venv": ".venv" in sys.executable, "dont_write_bytecode": sys.dont_write_bytecode, "concurrency": "none (sequential, single thread)"}

    def build_report(self, *, baseline: Mapping[str, Any] | None = None, optimizations: Sequence[Mapping[str, Any]] = ()) -> "PerformanceAuditReport":
        before = _fingerprint(self.root)
        sections: dict[str, Any] = {"environment": self.environment(), "initialization": self.initialization(), "step_components": self.step_components()}
        matrix = self.run_matrix()
        sections["benchmark_matrix"] = [row.to_dict() for row in matrix]
        sections["cost_separation"] = self.cost_separation()
        sections["reporting"] = self.reporting()
        sections["profiling"] = self.profiling()
        sections["scaling"] = self.scaling()
        sections["frontend"] = self.frontend(matrix, sections["scaling"])
        sections["bottlenecks"] = bottlenecks(sections["profiling"])
        replay = {row.workload.workload_id: row.output_hash for row in self.run_matrix_outputs()}
        sections["determinism_checks"] = {"status": "PASS" if replay == {row.workload.workload_id: row.output_hash for row in matrix} else "FAIL",
                                          "replayed_workloads": len(replay), "method": "every benchmark workload re-executed; output (trajectory) hashes compared"}
        after = _fingerprint(self.root)
        sections["mutation_checks"] = {"status": "PASS" if before == after else "FAIL", "before": before, "after": after}
        sections["optimizations"] = [dict(item) for item in (optimizations or OPTIMIZATIONS)]
        sections["optimization_equivalence"] = [self.restart_equivalence(), self.policy_matrix_equivalence()]
        sections["before_after"] = compare_with_baseline(baseline, matrix) if baseline is not None else None
        if sections["before_after"] is not None:
            sections["before_after"]["cost_separation"] = compare_cost_separation(baseline, sections["cost_separation"])
            sections["before_after"]["all_outputs_identical"] = sections["before_after"]["all_outputs_identical"] and sections["before_after"]["cost_separation"]["same_workload_and_trajectory"]
        return PerformanceAuditReport(VERSION, self.quick, sections)

    def run_matrix_outputs(self) -> list[Measurement]:
        return [Measurement(workload, (0.0,), *function()) for workload, function in self.benchmark_matrix()]


def _reference_restart_difference(resumed: Sequence[Any], tail: Sequence[Any]) -> float:
    """Verification oracle: the pre-Phase-5.36 restart() expression, verbatim (one
    snapshot_numbers(b) per key). Used only to prove O1 equivalent; never in production."""
    return max((max(abs(v - snapshot_numbers(b)[k]) for k, v in snapshot_numbers(a).items()) for a, b in zip(resumed, tail)), default=math.inf)


def _canonical(rows: Any) -> str:
    return json.dumps(json.loads(json.dumps(rows, default=str)), sort_keys=True, separators=(",", ":"))


def _hoisted_difference(a: Any, b: Any) -> float:
    return _max_abs_difference(snapshot_numbers(a), snapshot_numbers(b))


def _run_scenarios(scenario_ids: Sequence[str], days: float) -> tuple[int, str]:
    steps, hashes = 0, []
    for scenario_id in scenario_ids:
        count, digest = run_campaign(campaign_scenario("tomato", "outdoor", scenario_id, days))
        steps, hashes = steps + count, [*hashes, digest]
    return steps, _hash(hashes)


def _short(filename: str) -> str:
    path = filename.replace("\\", "/")
    if "/agri_twin/" in path:
        return "agri_twin/" + path.split("/agri_twin/", 1)[1]
    if path.startswith("~") or path.startswith("<"):
        return path
    return path.rsplit("/", 1)[-1]


_MODEL_MODULES = ("radiation_growth", "water_balance", "phenology", "greenhouse", "climate_stress", "nutrient", "chilling_models", "crop_growth", "application/weather.py", "domain/weather.py", "providers.py")


def classify(module: str, name: str) -> str:
    """Bottleneck class of one profiled function (rules documented in the report)."""
    if module == "~" or module.startswith("<built-in"):  # C built-ins: classify by what they do
        lowered = name.lower()
        if "math." in lowered or "blake2b" in lowered:
            return "MODEL_COMPUTATION"  # numeric kernels and the seeded weather anchors
        if any(token in lowered for token in ("sha256", "hexdigest", "_json", "isoformat", "encode", "dumps")):
            return "SERIALIZATION"
        if any(token in lowered for token in ("open", "write", "read", "stat", "listdir", "scandir")):
            return "I/O"
        return "PYTHON_OVERHEAD"
    if name in {"__post_init__", "_in_range"}:
        return "VALIDATION"
    if module.startswith("<string>") and name == "__init__":
        return "ALLOCATION"  # dataclass-generated constructors
    if name in {"replace", "_replace"} and module.startswith("dataclasses"):
        return "STATE_MANAGEMENT"
    if module in {"dataclasses.py"} and name in {"asdict", "_asdict_inner", "fields", "astuple", "_astuple_inner"}:
        return "SERIALIZATION"
    if name in {"to_dict", "from_dict", "checkpoint_payload", "dumps", "encode", "iterencode", "default", "isoformat", "fromisoformat"} or module.startswith(("json", "encoder")):
        return "SERIALIZATION"
    if name in {"sha256", "hexdigest", "update", "blake2b", "digest"} and "weather" not in module:
        return "SERIALIZATION"
    if module.startswith("agri_twin/") and any(token in module for token in ("validation", "invariant", "seasonal_synthetic_campaign", "integrated_synthetic")):
        if name in {"snapshot_numbers", "_numeric_fields"}:
            return "DIAGNOSTICS"
        return "VALIDATION"
    if module.startswith("agri_twin/") and any(token in module for token in _MODEL_MODULES):
        return "MODEL_COMPUTATION"
    if module.startswith("agri_twin/application/twin_state") or module.startswith("agri_twin/application/history"):
        return "PERSISTENCE"
    if module.startswith("agri_twin/application/orchestrator") or module.startswith("agri_twin/application/scenarios") or module.startswith("agri_twin/application/clock") or module.startswith("agri_twin/application/scheduler"):
        return "STATE_MANAGEMENT"
    if module.startswith("agri_twin/"):
        return "OTHER"
    if module.startswith("{") or module.startswith("~") or module.startswith("<built-in") or module in {"~"}:
        return "PYTHON_OVERHEAD"
    if module in {"enum.py", "abc.py", "typing.py", "copy.py", "functools.py", "threading.py"}:
        return "PYTHON_OVERHEAD"
    if module in {"datetime.py", "_strptime.py"}:
        return "PYTHON_OVERHEAD"
    if module in {"pathlib.py", "_pathlib.py", "ntpath.py", "posixpath.py", "genericpath.py", "codecs.py", "io.py"} or name in {"open", "read", "write", "read_text", "write_text"}:
        return "I/O"
    return "OTHER"


def bottlenecks(profiling: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Functions with >= 3 % of a profiled workload's own time (tottime)."""
    rows = []
    for key in ("simulation", "validation"):
        section = profiling[key]
        for item in section["top_by_tottime"]:
            if (item["percentage_of_workload"] or 0.0) < 3.0:
                continue
            rows.append({"workload": key, "component": item["module"], "function": item["name"], "total_time_seconds": item["tottime_seconds"], "call_count": item["calls"],
                         "time_per_call_seconds": item["seconds_per_call"], "percentage_of_workload": item["percentage_of_workload"], "classification": item["classification"]})
    return rows


def fit_linear(sizes: Sequence[float], seconds: Sequence[float]) -> dict[str, Any]:
    n = len(sizes)
    mean_x, mean_y = sum(sizes) / n, sum(seconds) / n
    sxx = sum((x - mean_x) ** 2 for x in sizes)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(sizes, seconds)) / sxx if sxx else 0.0
    intercept = mean_y - slope * mean_x
    ss_tot = sum((y - mean_y) ** 2 for y in seconds)
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(sizes, seconds))
    r2 = 1.0 - ss_res / ss_tot if ss_tot else 1.0
    ratio = (seconds[-1] / seconds[0]) / (sizes[-1] / sizes[0]) if seconds[0] and sizes[0] else None
    measured = "LINEAR" if r2 >= 0.98 and ratio is not None and 0.75 <= ratio <= 1.25 else ("SUBLINEAR" if ratio is not None and ratio < 0.75 else ("SUPERLINEAR" if ratio is not None and ratio > 1.25 else "INCONCLUSIVE"))
    return {"slope_seconds_per_unit": slope, "intercept_seconds": intercept, "r_squared": r2, "end_to_end_cost_ratio": ratio, "measured_scaling": measured,
            "rule": "LINEAR if R^2 >= 0.98 and (t_max/t_min)/(n_max/n_min) in [0.75, 1.25]"}


def band(seconds: float) -> str:
    return next(name for name, limit in FRONTEND_BANDS if seconds <= limit)


def _fingerprint(root: Path) -> dict[str, str]:
    registry = ParameterRegistry.from_repository(root)
    spec = build_campaign("tomato", "outdoor", "BASE_SEASON", seed=SEED)
    return {
        "parameter_registry": _hash([record.to_dict() for record in registry.records]),
        "parameter_sets": _hash({crop: ParameterSet.from_registry(registry, crop=crop).value_map() for crop in KNOWN_CROPS}),
        "phenology_profiles": _hash({crop: asdict(profile) for crop, profile in APPROXIMATE_PROFILES.items()}),
        "initial_twin_state": _hash({"crop": spec.scenario.initial_crop.to_dict(), "soil": asdict(spec.scenario.initial_soil)}),
        "campaign_configuration": spec.scenario.config_hash(),
    }


def compare_with_baseline(baseline: Mapping[str, Any], matrix: Sequence[Measurement]) -> dict[str, Any]:
    reference = {row["workload"]["workload_id"]: row for row in baseline["performance_measurement"]["benchmark_matrix"]}
    rows = []
    for row in matrix:
        before = reference.get(row.workload.workload_id)
        if before is None:
            continue
        before_seconds = before["performance_measurement"]["elapsed_seconds"]
        rows.append({"workload_id": row.workload.workload_id, "output_hash_identical": before["output_hash"] == row.output_hash, "steps_identical": before["steps_executed"] == row.steps_executed,
                     "seconds_before": before_seconds, "seconds_after": row.elapsed_seconds, "ratio_after_over_before": row.elapsed_seconds / before_seconds if before_seconds else None})
    return {"baseline_source": baseline.get("source"), "rows": rows, "all_outputs_identical": bool(rows) and all(r["output_hash_identical"] and r["steps_identical"] for r in rows),
            "note": "timings are PERFORMANCE_MEASUREMENT (machine dependent); output hashes are deterministic"}


def compare_cost_separation(baseline: Mapping[str, Any] | None, current: Mapping[str, Any]) -> dict[str, Any] | None:
    if baseline is None:
        return None
    before = baseline["performance_measurement"]["cost_separation"]
    same_workload = before["workload"] == current["workload"]
    rows = {key: {"seconds_before": before["seconds"][key], "seconds_after": value, "ratio_after_over_before": value / before["seconds"][key] if before["seconds"][key] else None}
            for key, value in current["seconds"].items() if key in before["seconds"]}
    return {"same_workload_and_trajectory": same_workload, "rows": rows}


@dataclass(frozen=True, slots=True)
class PerformanceAuditReport:
    version: str
    quick: bool
    sections: Mapping[str, Any]

    def deterministic_view(self) -> dict[str, Any]:
        """Everything that must be identical across builds (no timings)."""
        sections = self.sections
        return {
            "version": self.version, "quick": self.quick,
            "benchmark_matrix": [{key: row[key] for key in ("workload", "steps_executed", "output_hash")} for row in sections["benchmark_matrix"]],
            "scaling_outputs": {axis: [{k: r[k] for k in ("steps", "output_hash") if k in r} | {"size": r.get("size", (r.get("days"), r.get("plots")))} for r in value["rows"]]
                                for axis, value in sections["scaling"].items() if isinstance(value, Mapping) and "rows" in value},
            "profiling_call_counts": {key: sections["profiling"][key]["deterministic_call_counts"] for key in ("simulation", "validation")},
            "cost_separation_workload": sections["cost_separation"]["workload"],
            "determinism": sections["determinism_checks"]["status"], "mutation": sections["mutation_checks"],
            "optimizations": [dict(item) for item in sections["optimizations"]],
            "optimization_equivalence": [{key: item[key] for key in ("optimization", "status", "rows_byte_identical", "compared_pairs", "evidence_rows")} for item in sections["optimization_equivalence"]],
        }

    def to_dict(self) -> dict[str, Any]:
        sections = self.sections
        deterministic = self.deterministic_view()
        software_ok = sections["determinism_checks"]["status"] == "PASS" and sections["mutation_checks"]["status"] == "PASS" \
            and (sections["before_after"] is None or sections["before_after"]["all_outputs_identical"]) \
            and all(item["status"] == "PASS" for item in sections["optimization_equivalence"])
        return {
            "phase": "5.36",
            "version": self.version,
            "status": "PASS" if software_ok else "FAIL",
            "software_result": {"determinism_checks": sections["determinism_checks"], "mutation_checks": sections["mutation_checks"],
                                "optimization_equivalence": [{key: item[key] for key in ("optimization", "status", "rows_byte_identical", "compared_pairs")} for item in sections["optimization_equivalence"]],
                                "before_after_output_equivalence": None if sections["before_after"] is None else sections["before_after"]["all_outputs_identical"]},
            "performance_measurement": {
                "baseline": "see 'before_after' and docs/phase5_36_performance_audit.md (regression and manual timings)",
                "environment": sections["environment"], "benchmark_matrix": sections["benchmark_matrix"], "initialization": sections["initialization"],
                "step_components": sections["step_components"], "cost_separation": sections["cost_separation"], "reporting": sections["reporting"],
                "profiling_summary": sections["profiling"], "bottlenecks": sections["bottlenecks"], "scaling": sections["scaling"], "frontend": sections["frontend"],
            },
            "optimization_result": {"optimizations": sections["optimizations"], "equivalence": sections["optimization_equivalence"], "before_after": sections["before_after"]},
            "duplicated_work_audit": [dict(item) for item in DUPLICATED_WORK_AUDIT],
            "open_performance_architecture": [dict(item) for item in OPEN_PERFORMANCE_ARCHITECTURE],
            "scientific_evidence": [],
            "deterministic_hash": _hash(deterministic),
            "limitations": [
                "Wall-clock timings depend on the machine, OS scheduling and background load; they are measurements, not contracts.",
                "Timings are minima over repeated sequential runs; cProfile adds overhead, so profiled seconds are larger than plain timings.",
                "Frontend classes are advisory latency bands for simulation only, measured on one machine; no frontend technology is assumed.",
                "No model equation, parameter or semantic was changed for speed.",
            ],
            "real_agricultural_data_verified": False, "calibration_performed": False, "experimental_validation_performed": False,
            "biological_validity_claimed": False, "field_accuracy_claimed": False, "data_assimilation_implemented": False,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, default=str)


def write_report(report: PerformanceAuditReport, directory: str | Path) -> tuple[Path, Path]:
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    payload = report.to_dict()
    report_path, readme_path = output / "performance_audit_report.json", output / "performance_audit_README.md"
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    perf = payload["performance_measurement"]
    lines = [
        "# Performance, latency and scalability audit (Phase 5.36)",
        "",
        "PERFORMANCE_MEASUREMENT values are wall-clock measurements on the audit machine (not deterministic, never hashed).",
        "SOFTWARE_RESULT: determinism, mutation and optimization-equivalence checks. SCIENTIFIC_EVIDENCE: none.",
        "",
        f"- status: `{payload['status']}`; deterministic hash: `{payload['deterministic_hash']}`",
        f"- environment: Python {perf['environment']['python']} on {perf['environment']['platform']}",
        "",
        "## Twin simulation vs validation/reporting",
        "",
        f"- twin simulation (tomato outdoor full season): {perf['cost_separation']['answer']['twin_simulation_seconds']:.3f} s",
        f"- validation/reporting infrastructure on the same campaign: {perf['cost_separation']['answer']['validation_and_reporting_infrastructure_seconds']:.3f} s",
        "",
        "## Benchmark matrix (simulation only)",
        "",
        "| Workload | Days | Plots x cycles | Steps | Seconds | ms/step | s/simulated day |",
        "|---|---|---|---|---|---|---|",
        *[f"| {row['workload']['workload_id']} | {row['workload']['days']:.0f} | {row['workload']['plots']}x{row['workload']['cycles']} | {row['steps_executed']} | "
          f"{row['performance_measurement']['elapsed_seconds']:.3f} | {row['performance_measurement']['milliseconds_per_step']:.3f} | {row['performance_measurement']['seconds_per_simulated_day']:.4f} |"
          for row in perf["benchmark_matrix"]],
        "",
        "## Frontend classification (advisory)",
        "",
        *[f"- {name}: {value['seconds']:.2f} s -> `{value['classification']}`" for name, value in perf["frontend"]["cases"].items()],
        "",
        "## Scaling",
        "",
        *[f"- {axis}: {value['measured_scaling']} (R^2 {value['r_squared']:.4f}, slope {value['slope_seconds_per_unit']:.4f} s/unit)" for axis, value in perf["scaling"].items() if isinstance(value, Mapping) and "measured_scaling" in value],
        "",
    ]
    readme_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path, readme_path


__all__ = [
    "BOTTLENECK_CLASSES",
    "Measurement",
    "PerformanceAuditReport",
    "PerformanceAuditSuite",
    "Workload",
    "band",
    "bottlenecks",
    "campaign_scenario",
    "classify",
    "fit_linear",
    "run_campaign",
    "run_multi_plot",
    "timed",
    "truncated",
    "write_report",
]
