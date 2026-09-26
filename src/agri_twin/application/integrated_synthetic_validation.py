"""Integrated synthetic validation of the digital twin (Phase 5.29).

This module is an orchestration and evaluation layer. It composes the existing
SimulationClock, ScenarioRunner, CropDigitalTwinOrchestrator, MultiPlotSimulation,
TwinStateRepository, CropGreenhouseFeedbackLoop, SimplifiedGreenhouseModel,
ParameterRegistry and the Phase 5.22/5.28 robustness and transferability suites.
It contains no growth, photosynthesis, water-balance, temperature, VPD, CO2 or
phenology equations of its own.

Scientific stance:
    - validation kind is ``SYNTHETIC_INTEGRATED_VALIDATION``: it qualifies software
      and mechanistic consistency under controlled synthetic scenarios only;
    - model outputs are never converted into observations (no circular validation);
    - no calibration, optimisation or parameter change is performed;
    - ``PASS`` means the defined synthetic checks passed, never that a crop is
      scientifically, biologically or field validated.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from agri_twin.application.clock import SimulationClock
from agri_twin.application.multi_plot import MultiPlotSimulation
from agri_twin.application.orchestrator import CropDigitalTwinOrchestrator, CropSimulationSnapshot
from agri_twin.application.providers import SyntheticWeatherProvider
from agri_twin.application.scenarios import Scenario, ScenarioError, ScenarioEvent, ScenarioKind, ScenarioResult, ScenarioRunner
from agri_twin.application.scientific_benchmark import KNOWN_CROPS, KNOWN_VARIETIES, PERENNIAL_CROPS
from agri_twin.application.synthetic_dataset import SyntheticCropCycle, SyntheticPlot, SyntheticReferenceDatasetGenerator
from agri_twin.application.twin_state import InMemoryTwinStateRepository, TwinSnapshot, TwinState, TwinStateConflict
from agri_twin.application.weather import WeatherEngine
from agri_twin.domain.calibration import ParameterSet
from agri_twin.domain.climate_stress import ClimateStressEngine
from agri_twin.domain.crop_greenhouse_feedback import CropGreenhouseFeedbackLoop
from agri_twin.domain.crop_growth import CropGrowthEngine
from agri_twin.domain.greenhouse import (
    AIR_DENSITY_KG_M3,
    AIR_SPECIFIC_HEAT_J_KG_K,
    CropMicroclimateFeedback,
    GreenhouseActuatorState,
    GreenhouseConfiguration,
    GreenhouseMicroclimateState,
    SimplifiedGreenhouseModel,
)
from agri_twin.domain.models import CropGrowthState, SoilState, WeatherState
from agri_twin.domain.parameter_audit import ParameterRegistry
from agri_twin.domain.phenology import STAGES, PhenologyEngine
from agri_twin.domain.radiation_growth import RadiationGrowthEngine
from agri_twin.domain.water_balance import IrrigationRequest
from agri_twin.domain.weather import (
    HumidityConfiguration,
    RadiationConfiguration,
    TemperatureConfiguration,
    WeatherConfiguration,
    WeatherSimulationConfiguration,
)

UTC = timezone.utc
VERSION = "5.29.2"
VALIDATION_KIND = "SYNTHETIC_INTEGRATED_VALIDATION"
SOURCE_TYPE = "SYNTHETIC"
WEATHER_GENERATOR = "agri_twin.application.weather.WeatherEngine (seeded, timestamp-pure) + ScenarioEvent overlays"
ENGINEERING_TEST_THRESHOLD = "ENGINEERING_TEST_THRESHOLD"
ANNUAL_CROPS = tuple(crop for crop in KNOWN_CROPS if crop not in PERENNIAL_CROPS)
DAY = timedelta(days=1)
FLOAT_TOLERANCE = 1e-9
DEFAULT_SEED = 529
BASELINE_IRRIGATION_MM_H = 0.4
DORMANCY_CHILLING_TEMPERATURE_C = 4.0
DORMANCY_DAYS = 35


class SyntheticValidationStatus(StrEnum):
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    FAIL = "FAIL"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    INCOMPLETE_SCENARIO = "INCOMPLETE_SCENARIO"
    NON_DETERMINISTIC = "NON_DETERMINISTIC"
    INVARIANT_VIOLATION = "INVARIANT_VIOLATION"
    NUMERICAL_FAILURE = "NUMERICAL_FAILURE"
    CONVERGENCE_FAILURE = "CONVERGENCE_FAILURE"
    DATA_INSUFFICIENT = "DATA_INSUFFICIENT"
    NOT_APPLICABLE = "NOT_APPLICABLE"


PASSING_STATUSES = frozenset({SyntheticValidationStatus.PASS, SyntheticValidationStatus.PASS_WITH_WARNINGS})


class ValidationCategory(StrEnum):
    SOFTWARE_CONSISTENCY = "SOFTWARE_CONSISTENCY"
    MECHANISTIC_CONSISTENCY = "MECHANISTIC_CONSISTENCY"


class SyntheticScenarioKind(StrEnum):
    NORMAL_SEASON = "NORMAL_SEASON"
    WATER_STRESS_RECOVERY = "WATER_STRESS_RECOVERY"
    HEAT_WAVE_RECOVERY = "HEAT_WAVE_RECOVERY"
    LOW_RADIATION = "LOW_RADIATION"
    HIGH_RADIATION = "HIGH_RADIATION"
    GREENHOUSE_VENTILATION = "GREENHOUSE_VENTILATION"
    GREENHOUSE_SHADING = "GREENHOUSE_SHADING"
    GREENHOUSE_CO2 = "GREENHOUSE_CO2"
    COMBINED_STRESS = "COMBINED_STRESS"


class VarietyParameterResolution(StrEnum):
    VARIETY_SPECIFIC = "VARIETY_SPECIFIC"
    SPECIES_FALLBACK = "SPECIES_FALLBACK"


# Synthetic climate forcing profiles. These are scenario inputs (plausible
# weather for the season of each synthetic cycle), not crop parameters.
CLIMATE_PROFILES: Mapping[str, Mapping[str, float]] = {
    "warm_season": {"temperature_min_c": 12.0, "temperature_max_c": 30.0, "radiation_max_w_m2": 900.0, "humidity_min_pct": 35.0, "humidity_max_pct": 90.0},
    "cool_season": {"temperature_min_c": 7.0, "temperature_max_c": 21.0, "radiation_max_w_m2": 650.0, "humidity_min_pct": 45.0, "humidity_max_pct": 95.0},
}
CROP_CLIMATE = {"tomato": "warm_season", "pepper": "warm_season", "lettuce": "cool_season", "grape": "warm_season", "peach": "warm_season", "plum": "warm_season", "apple": "warm_season"}
SEASON_START = {"tomato": datetime(2026, 3, 1, tzinfo=UTC), "pepper": datetime(2026, 3, 1, tzinfo=UTC), "lettuce": datetime(2026, 1, 10, tzinfo=UTC)}
PERENNIAL_SEASON_START = datetime(2026, 1, 1, tzinfo=UTC)
SEASON_DAYS = {"tomato": 130, "pepper": 130, "lettuce": 110}
PERENNIAL_SEASON_DAYS = 170
# Offsets (days after the start of active growth) of the controlled event windows.
STRESS_WINDOW = {"lettuce": (25, 37)}
DEFAULT_STRESS_WINDOW = (35, 50)
TOMATO_EXTENDED_KINDS = (
    (SyntheticScenarioKind.LOW_RADIATION, "outdoor"),
    (SyntheticScenarioKind.HIGH_RADIATION, "outdoor"),
    (SyntheticScenarioKind.GREENHOUSE_VENTILATION, "greenhouse"),
    (SyntheticScenarioKind.GREENHOUSE_SHADING, "greenhouse"),
    (SyntheticScenarioKind.GREENHOUSE_CO2, "greenhouse"),
    (SyntheticScenarioKind.COMBINED_STRESS, "greenhouse"),
)


def _hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _plot_for(crop: str) -> SyntheticPlot:
    return next(plot for plot in SyntheticReferenceDatasetGenerator.DEFAULT_PLOTS if plot.crop == crop)


def _variety_for(crop: str) -> str:
    return KNOWN_VARIETIES.get(crop, "UNSPECIFIED")


def weather_configuration(profile: str, seed: int) -> WeatherConfiguration:
    values = CLIMATE_PROFILES[profile]
    return WeatherConfiguration(
        temperature=TemperatureConfiguration(minimum_c=values["temperature_min_c"], maximum_c=values["temperature_max_c"]),
        radiation=RadiationConfiguration(maximum_w_m2=values["radiation_max_w_m2"]),
        humidity=HumidityConfiguration(minimum_pct=values["humidity_min_pct"], maximum_pct=values["humidity_max_pct"]),
        simulation=WeatherSimulationConfiguration(seed=seed),
    )


def _label(scenario: Scenario, key: str) -> str:
    prefix = f"{key}="
    return next(label[len(prefix):] for label in scenario.labels if label.startswith(prefix))


def synthetic_weather_factory(scenario: Scenario) -> SyntheticWeatherProvider:
    """Seeded, timestamp-pure base weather selected by the scenario labels."""
    return SyntheticWeatherProvider(WeatherEngine(weather_configuration(_label(scenario, "climate"), int(_label(scenario, "weather_seed")))))


# ---------------------------------------------------------------------------
# Result structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SyntheticValidationMetric:
    name: str
    value: float | int | bool | None
    unit: str
    category: ValidationCategory
    passed: bool | None = None
    threshold: float | None = None
    threshold_kind: str | None = None
    definition: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "category": self.category.value,
            "passed": self.passed,
            "threshold": self.threshold,
            "threshold_kind": self.threshold_kind,
            "definition": self.definition,
        }


@dataclass(frozen=True, slots=True)
class SyntheticValidationIssue:
    code: str
    severity: str
    message: str
    simulation_time: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "severity": self.severity, "message": self.message, "simulation_time": self.simulation_time.isoformat() if self.simulation_time else None}


@dataclass(frozen=True, slots=True)
class SyntheticValidationScenario:
    """Declarative synthetic scenario; ``to_scenario`` builds the project Scenario."""

    scenario_id: str
    kind: SyntheticScenarioKind
    crop: str
    variety: str
    plot_id: str
    cycle_id: str
    environment: str
    start: datetime
    end: datetime
    timestep_seconds: int
    climate_profile: str
    weather_seed: int
    growth_start: datetime
    window: tuple[datetime, datetime] | None
    events: tuple[ScenarioEvent, ...]
    initial_crop: CropGrowthState
    initial_soil: SoilState

    @property
    def perennial(self) -> bool:
        return self.crop in PERENNIAL_CROPS

    @property
    def greenhouse_mode(self) -> str:
        return "passive_greenhouse" if self.environment == "greenhouse" else "outdoor"

    def to_scenario(self) -> Scenario:
        return Scenario(
            self.scenario_id,
            self.scenario_id,
            f"Phase 5.29 synthetic {self.kind.value} scenario",
            self.crop,
            self.variety,
            self.start,
            self.end,
            self.timestep_seconds,
            ScenarioKind.STRESS_TEST if self.kind is not SyntheticScenarioKind.NORMAL_SEASON else ScenarioKind.SYNTHETIC,
            self.initial_crop,
            self.initial_soil,
            WeatherState(20.0, 60.0, 0.0, 2.0, 180.0, 0.0, 1013.0),
            self.greenhouse_mode,
            self.events,
            labels=(f"climate={self.climate_profile}", f"weather_seed={self.weather_seed}", f"kind={self.kind.value}"),
            seed=self.weather_seed,
        )

    def definition_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "kind": self.kind.value,
            "crop": self.crop,
            "variety": self.variety,
            "plot_id": self.plot_id,
            "cycle_id": self.cycle_id,
            "environment": self.environment,
            "greenhouse_mode": self.greenhouse_mode,
            "start_time": self.start.isoformat(),
            "end_time": self.end.isoformat(),
            "timestep_seconds": self.timestep_seconds,
            "climate_profile": self.climate_profile,
            "climate_forcing": dict(CLIMATE_PROFILES[self.climate_profile]),
            "weather_seed": self.weather_seed,
            "growth_start": self.growth_start.isoformat(),
            "event_window": [self.window[0].isoformat(), self.window[1].isoformat()] if self.window else None,
            "events": [asdict(event) | {"start": event.start.isoformat(), "end": event.end.isoformat(), "parameters": dict(event.parameters)} for event in self.events],
            "initial_crop": self.initial_crop.to_dict(),
            "initial_soil": asdict(self.initial_soil),
            "project_scenario_config_hash": self.to_scenario().config_hash(),
        }

    def configuration_hash(self) -> str:
        return _hash(self.definition_dict())


@dataclass(frozen=True, slots=True)
class SyntheticValidationCase:
    case_id: str
    scenario: SyntheticValidationScenario
    expected_invariants: tuple[str, ...]
    expected_behaviours: tuple[str, ...]
    control_case_id: str | None = None


@dataclass(frozen=True, slots=True)
class SyntheticValidationResult:
    case_id: str
    scenario: SyntheticValidationScenario
    expected_invariants: tuple[str, ...]
    expected_behaviours: tuple[str, ...]
    observed_outputs: Mapping[str, Any]
    metrics: tuple[SyntheticValidationMetric, ...]
    status: SyntheticValidationStatus
    warnings: tuple[SyntheticValidationIssue, ...]
    failures: tuple[SyntheticValidationIssue, ...]
    provenance: Mapping[str, Any]
    configuration_hash: str
    trajectory_hash: str

    def to_dict(self) -> dict[str, Any]:
        scenario = self.scenario
        return {
            "case_id": self.case_id,
            "crop": scenario.crop,
            "variety": scenario.variety,
            "plot_id": scenario.plot_id,
            "cycle_id": scenario.cycle_id,
            "environment": scenario.environment,
            "scenario": scenario.kind.value,
            "scenario_id": scenario.scenario_id,
            "start_time": scenario.start.isoformat(),
            "end_time": scenario.end.isoformat(),
            "timestep_seconds": scenario.timestep_seconds,
            "expected_invariants": list(self.expected_invariants),
            "expected_behaviours": list(self.expected_behaviours),
            "observed_outputs": dict(self.observed_outputs),
            "metrics": [metric.to_dict() for metric in self.metrics],
            "status": self.status.value,
            "warnings": [issue.to_dict() for issue in self.warnings],
            "failures": [issue.to_dict() for issue in self.failures],
            "provenance": dict(self.provenance),
            "configuration_hash": self.configuration_hash,
            "trajectory_hash": self.trajectory_hash,
        }


@dataclass(frozen=True, slots=True)
class IntegratedValidationSummary:
    total_cases: int
    status_counts: Mapping[str, int]
    crops: tuple[str, ...]
    varieties: tuple[str, ...]
    environments: tuple[str, ...]
    scenario_kinds: tuple[str, ...]
    section_status: Mapping[str, str]
    qualification: Mapping[str, str]
    scientific_status: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_cases": self.total_cases,
            "status_counts": dict(self.status_counts),
            "crops": list(self.crops),
            "varieties": list(self.varieties),
            "environments": list(self.environments),
            "scenario_kinds": list(self.scenario_kinds),
            "section_status": dict(self.section_status),
            "qualification": dict(self.qualification),
            "scientific_status": dict(self.scientific_status),
        }


@dataclass(frozen=True, slots=True)
class SyntheticValidationReport:
    version: str
    configuration: Mapping[str, Any]
    cases: tuple[SyntheticValidationResult, ...]
    sections: Mapping[str, Any]
    coverage_matrix: tuple[Mapping[str, Any], ...]
    findings: tuple[Mapping[str, Any], ...]
    summary: IntegratedValidationSummary
    configuration_hash: str
    execution_metadata: Mapping[str, Any] = field(default_factory=dict, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """Deterministic content only; execution metadata (timings) is excluded."""
        payload = {
            "metadata": {
                "phase": "5.29",
                "version": self.version,
                "validation_kind": VALIDATION_KIND,
                "source_type": SOURCE_TYPE,
                "meaning_of_pass": "the software/model behaviour passed the defined synthetic checks; it is not scientific, biological or field validation",
                "real_agronomic_data_used": False,
            },
            "configuration": dict(self.configuration),
            "cases": [case.to_dict() for case in self.cases],
            **{name: value for name, value in self.sections.items()},
            "coverage_matrix": [dict(row) for row in self.coverage_matrix],
            "findings": [dict(finding) for finding in self.findings],
            "summary": self.summary.to_dict(),
            "configuration_hash": self.configuration_hash,
        }
        payload["report_hash"] = _hash(payload)
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# Reusable invariant validators
# ---------------------------------------------------------------------------


def _numeric_fields(prefix: str, value: Any, target: dict[str, float]) -> None:
    for item in fields(value):
        number = getattr(value, item.name)
        if isinstance(number, (int, float)) and not isinstance(number, bool):
            target[f"{prefix}.{item.name}"] = float(number)


def snapshot_numbers(snapshot: CropSimulationSnapshot) -> dict[str, float]:
    """Flatten every numeric state value of one orchestrator snapshot."""
    values: dict[str, float] = {}
    _numeric_fields("crop", snapshot.crop, values)
    _numeric_fields("soil", snapshot.soil, values)
    _numeric_fields("weather", snapshot.weather, values)
    _numeric_fields("environment", snapshot.environment, values)
    for key, number in snapshot.microclimate.indoor_state.to_dict().items():
        values[f"microclimate.{key}"] = float(number)
    values["potential_growth_g_m2"] = snapshot.potential_growth_g_m2
    values["actual_growth_g_m2"] = snapshot.actual_growth_g_m2
    values["growth_factor"] = snapshot.growth_factor
    return values


def trajectory_hash(snapshots: Sequence[CropSimulationSnapshot]) -> str:
    digest = hashlib.sha256()
    for snapshot in snapshots:
        digest.update(snapshot.simulation_time.isoformat().encode("ascii"))
        # Field order is fixed by the dataclass contracts; repr() of floats is exact.
        digest.update(repr(tuple(snapshot_numbers(snapshot).items())).encode("ascii"))
        digest.update(snapshot.crop.current_stage.encode("ascii"))
    return digest.hexdigest()


INVARIANT_DEFINITIONS: Mapping[str, str] = {
    "finite_state": "every numeric crop, soil, weather, microclimate and environment value is finite",
    "time_continuity": "snapshot i is at start + (i + 1) * dt: no reset, gap or double advance",
    "lai_contract_bounds": "0 <= LAI <= RadiationGrowthProfile.maximum_lai of the crop",
    "biomass_non_decreasing": "total biomass never decreases (the model has no explicit biomass loss term; senescence moves leaf to stem)",
    "maturity_bounds_monotonic": "maturity_index stays in [0, 1] and never decreases",
    "stage_monotonic": "phenological stage index never decreases and a finished cycle is never reactivated",
    "harvest_ready_persistent": "harvest_ready never returns to False once True",
    "thermal_time_monotonic": "GDD and chilling hours never decrease",
    "soil_water_contract": "wilting_point <= VWC <= field_capacity and root-zone water >= 0",
    "normalized_factors": "growth factor in [0, 1] and actual growth <= potential growth",
    "post_harvest_no_growth": "no biomass gain and no LAI gain during post_harvest_dormancy",
    "dormancy_gates_thermal_time": "perennials accumulate no GDD before dormancy release",
    "microclimate_contract": "0 <= RH <= 100, CO2 >= 0, radiation >= 0 in the microclimate state",
}


def validate_trajectory(scenario: SyntheticValidationScenario, snapshots: Sequence[CropSimulationSnapshot]) -> tuple[tuple[SyntheticValidationMetric, ...], tuple[SyntheticValidationIssue, ...]]:
    """Check the model-contract invariants over a full trajectory."""
    maximum_lai = RadiationGrowthEngine().profile_for(scenario.crop).maximum_lai
    dt = timedelta(seconds=scenario.timestep_seconds)
    violations: dict[str, list[datetime]] = {name: [] for name in INVARIANT_DEFINITIONS}
    previous: CropSimulationSnapshot | None = None
    for index, snapshot in enumerate(snapshots):
        crop, soil, micro = snapshot.crop, snapshot.soil, snapshot.microclimate.indoor_state
        instant = snapshot.simulation_time
        if not all(math.isfinite(value) for value in snapshot_numbers(snapshot).values()):
            violations["finite_state"].append(instant)
        if instant != scenario.start + dt * (index + 1) or crop.simulation_time != instant:
            violations["time_continuity"].append(instant)
        if not 0.0 <= crop.leaf_area_index <= maximum_lai + FLOAT_TOLERANCE:
            violations["lai_contract_bounds"].append(instant)
        if not 0.0 <= crop.maturity_index <= 1.0:
            violations["maturity_bounds_monotonic"].append(instant)
        if not soil.wilting_point - FLOAT_TOLERANCE <= soil.vwc_m3_m3 <= soil.field_capacity + FLOAT_TOLERANCE or soil.root_zone_water < 0:
            violations["soil_water_contract"].append(instant)
        if not 0.0 <= snapshot.growth_factor <= 1.0 or snapshot.actual_growth_g_m2 > snapshot.potential_growth_g_m2 + FLOAT_TOLERANCE or snapshot.actual_growth_g_m2 < -FLOAT_TOLERANCE:
            violations["normalized_factors"].append(instant)
        if not 0.0 <= micro.relative_humidity_pct <= 100.0 or micro.co2_ppm < 0 or micro.solar_radiation_w_m2 < 0:
            violations["microclimate_contract"].append(instant)
        before = previous.crop if previous is not None else scenario.initial_crop
        if crop.biomass_total < before.biomass_total - FLOAT_TOLERANCE:
            violations["biomass_non_decreasing"].append(instant)
        if crop.maturity_index < before.maturity_index - FLOAT_TOLERANCE:
            violations["maturity_bounds_monotonic"].append(instant)
        if STAGES.index(crop.current_stage) < STAGES.index(before.current_stage):
            violations["stage_monotonic"].append(instant)
        if previous is not None and previous.crop.harvest_ready and not crop.harvest_ready:
            violations["harvest_ready_persistent"].append(instant)
        if crop.gdd_accumulated < before.gdd_accumulated - FLOAT_TOLERANCE or crop.chilling_hours < before.chilling_hours - FLOAT_TOLERANCE:
            violations["thermal_time_monotonic"].append(instant)
        if before.current_stage == "post_harvest_dormancy" and (crop.biomass_total > before.biomass_total + FLOAT_TOLERANCE or crop.leaf_area_index > before.leaf_area_index + FLOAT_TOLERANCE):
            violations["post_harvest_no_growth"].append(instant)
        if scenario.perennial and not crop.dormancy_released and crop.gdd_accumulated > FLOAT_TOLERANCE:
            violations["dormancy_gates_thermal_time"].append(instant)
        previous = snapshot
    metrics = []
    issues = []
    for name, times in violations.items():
        category = ValidationCategory.SOFTWARE_CONSISTENCY if name in {"finite_state", "time_continuity", "microclimate_contract"} else ValidationCategory.MECHANISTIC_CONSISTENCY
        metrics.append(SyntheticValidationMetric(f"invariant.{name}.violations", len(times), "steps", category, not times, 0, None, INVARIANT_DEFINITIONS[name]))
        if times:
            code = "NUMERICAL_FAILURE" if name == "finite_state" else "INVARIANT_VIOLATION"
            issues.append(SyntheticValidationIssue(code, "FAILURE", f"{name}: {len(times)} violating steps; {INVARIANT_DEFINITIONS[name]}", times[0]))
    return tuple(metrics), tuple(issues)


# ---------------------------------------------------------------------------
# Scenario catalogue
# ---------------------------------------------------------------------------


def _initial_state(crop: str, variety: str, start: datetime) -> tuple[CropGrowthState, SoilState]:
    perennial = crop in PERENNIAL_CROPS
    woody = 20.0 if perennial else 2.5
    state = CropGrowthState(
        start, crop, variety, "establishment",
        biomass_total=5.0 + 2 * woody, biomass_leaf=5.0, biomass_stem=woody, biomass_root=woody,
        leaf_area_index=0.1, root_depth_m=0.6, soil_water_vwc=0.35,
        dormancy_released=not perennial, phenology_model="SYNTHETIC_INITIAL_STATE",
    )
    return state, SoilState(0.35, 15.0, 0.35, 0.10, 0.0, 150.0)


def _irrigation(event_id: str, start: datetime, end: datetime) -> ScenarioEvent:
    return ScenarioEvent(event_id, "irrigation", start, end, BASELINE_IRRIGATION_MM_H, {"amount_mm": BASELINE_IRRIGATION_MM_H})


def build_scenario(crop: str, environment: str, kind: SyntheticScenarioKind, *, seed: int = DEFAULT_SEED, timestep_seconds: int = 3600) -> SyntheticValidationScenario:
    if crop not in KNOWN_CROPS:
        raise ScenarioError(f"unknown crop for synthetic validation: {crop}")
    if environment not in {"outdoor", "greenhouse"}:
        raise ScenarioError(f"unknown environment: {environment}")
    if environment == "greenhouse" and crop in PERENNIAL_CROPS:
        raise ScenarioError(f"greenhouse is not configured for perennial crop {crop}")
    greenhouse_only = {SyntheticScenarioKind.GREENHOUSE_VENTILATION, SyntheticScenarioKind.GREENHOUSE_SHADING, SyntheticScenarioKind.GREENHOUSE_CO2, SyntheticScenarioKind.COMBINED_STRESS}
    if kind in greenhouse_only and environment != "greenhouse":
        raise ScenarioError(f"{kind.value} requires the greenhouse environment")
    perennial = crop in PERENNIAL_CROPS
    start = PERENNIAL_SEASON_START if perennial else SEASON_START[crop]
    end = start + DAY * (PERENNIAL_SEASON_DAYS if perennial else SEASON_DAYS[crop])
    growth_start = start + DAY * DORMANCY_DAYS if perennial else start
    offset = STRESS_WINDOW.get(crop, DEFAULT_STRESS_WINDOW)
    window_start = growth_start + DAY * offset[0]
    window_end = growth_start + DAY * offset[1]
    events: list[ScenarioEvent] = []
    if perennial:
        events.append(ScenarioEvent("dormancy_chilling", "cold", start, growth_start, DORMANCY_CHILLING_TEMPERATURE_C, {"temperature_c": DORMANCY_CHILLING_TEMPERATURE_C}))
    window: tuple[datetime, datetime] | None = None
    if kind is SyntheticScenarioKind.NORMAL_SEASON:
        events.append(_irrigation("irrigation_season", start, end))
    elif kind is SyntheticScenarioKind.WATER_STRESS_RECOVERY:
        window = (window_start, window_end)
        events += [_irrigation("irrigation_before_deficit", start, window_start), _irrigation("irrigation_recovery", window_end, end)]
    elif kind is SyntheticScenarioKind.COMBINED_STRESS:
        window = (window_start, window_start + DAY * 7)
        events += [
            _irrigation("irrigation_before_deficit", start, window[0]),
            _irrigation("irrigation_recovery", window[1], end),
            ScenarioEvent("combined_heat", "heat", window[0], window[1], 8.0, {"temperature_offset_c": 8.0}),
            ScenarioEvent("combined_radiation", "high_radiation", window[0], window[1], 1.3, {"radiation_multiplier": 1.3}),
            ScenarioEvent("combined_ventilation", "ventilation", window[0], window[1], 3.0, {"value": 3.0, "maximum": 3.0}),
        ]
    else:
        events.append(_irrigation("irrigation_season", start, end))
        duration = 5 if kind is SyntheticScenarioKind.HEAT_WAVE_RECOVERY else 10
        window = (window_start, window_start + DAY * duration)
        event = {
            SyntheticScenarioKind.HEAT_WAVE_RECOVERY: ("heat_wave", "heat", 10.0, {"temperature_offset_c": 10.0}),
            SyntheticScenarioKind.LOW_RADIATION: ("low_radiation", "low_radiation", 0.3, {"radiation_multiplier": 0.3}),
            SyntheticScenarioKind.HIGH_RADIATION: ("high_radiation", "high_radiation", 1.4, {"radiation_multiplier": 1.4}),
            SyntheticScenarioKind.GREENHOUSE_VENTILATION: ("ventilation_open", "ventilation", 3.0, {"value": 3.0, "maximum": 3.0}),
            SyntheticScenarioKind.GREENHOUSE_SHADING: ("shading_screen", "shade", 0.5, {"value": 0.5, "maximum": 1.0}),
            SyntheticScenarioKind.GREENHOUSE_CO2: ("co2_enrichment", "co2", 400.0, {"value": 400.0, "maximum": 2000.0}),
        }[kind]
        events.append(ScenarioEvent(event[0], event[1], window[0], window[1], event[2], event[3]))
    variety = _variety_for(crop)
    initial_crop, initial_soil = _initial_state(crop, variety, start)
    plot = _plot_for(crop)
    scenario_id = f"p529_{crop}_{environment}_{kind.value.lower()}"
    return SyntheticValidationScenario(
        scenario_id, kind, crop, variety, plot.plot_id, f"{crop}_{plot.plot_id}_synthetic_2026", environment,
        start, end, timestep_seconds, CROP_CLIMATE[crop], seed, growth_start, window, tuple(events), initial_crop, initial_soil,
    )


def default_cases(crops: Sequence[str] = KNOWN_CROPS, *, seed: int = DEFAULT_SEED, include_extended: bool = True) -> tuple[SyntheticValidationCase, ...]:
    cases: list[SyntheticValidationCase] = []
    invariants = tuple(INVARIANT_DEFINITIONS)
    for crop in crops:
        environments = ("outdoor", "greenhouse") if crop in ANNUAL_CROPS else ("outdoor",)
        for environment in environments:
            normal = build_scenario(crop, environment, SyntheticScenarioKind.NORMAL_SEASON, seed=seed)
            cases.append(SyntheticValidationCase(normal.scenario_id, normal, invariants, BEHAVIOURS[SyntheticScenarioKind.NORMAL_SEASON]))
        for kind in (SyntheticScenarioKind.WATER_STRESS_RECOVERY, SyntheticScenarioKind.HEAT_WAVE_RECOVERY):
            scenario = build_scenario(crop, "outdoor", kind, seed=seed)
            cases.append(SyntheticValidationCase(scenario.scenario_id, scenario, invariants, BEHAVIOURS[kind], f"p529_{crop}_outdoor_normal_season"))
        if crop == "tomato" and include_extended:
            for kind, environment in TOMATO_EXTENDED_KINDS:
                scenario = build_scenario(crop, environment, kind, seed=seed)
                cases.append(SyntheticValidationCase(scenario.scenario_id, scenario, invariants, BEHAVIOURS[kind], f"p529_{crop}_{environment}_normal_season"))
    return tuple(cases)


# ---------------------------------------------------------------------------
# Controlled behaviour checks (relative to the paired control scenario)
# ---------------------------------------------------------------------------


def _window_indices(scenario: SyntheticValidationScenario, start: datetime, end: datetime) -> range:
    dt = scenario.timestep_seconds
    return range(int((start - scenario.start).total_seconds() // dt), int((end - scenario.start).total_seconds() // dt))


def _series(snapshots: Sequence[CropSimulationSnapshot], indices: Iterable[int], getter: Callable[[CropSimulationSnapshot], float]) -> list[float]:
    return [getter(snapshots[index]) for index in indices]


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


BehaviourCheck = Callable[[SyntheticValidationScenario, Sequence[CropSimulationSnapshot], Sequence[CropSimulationSnapshot] | None], list[tuple[SyntheticValidationMetric, SyntheticValidationIssue | None]]]


def _check(name: str, value: Any, passed: bool | None, definition: str, *, unit: str = "", severity: str = "FAILURE", code: str = "BEHAVIOUR_NOT_OBSERVED", threshold: float | None = None, threshold_kind: str | None = None) -> tuple[SyntheticValidationMetric, SyntheticValidationIssue | None]:
    metric = SyntheticValidationMetric(f"behaviour.{name}", value, unit, ValidationCategory.MECHANISTIC_CONSISTENCY, passed, threshold, threshold_kind, definition)
    issue = None if passed is not False else SyntheticValidationIssue(code, severity, f"{name}: {definition} (observed {value})")
    return metric, issue


def _normal_season(scenario: SyntheticValidationScenario, snapshots: Sequence[CropSimulationSnapshot], _control: Sequence[CropSimulationSnapshot] | None) -> list:
    stages: list[str] = []
    for snapshot in snapshots:
        if not stages or stages[-1] != snapshot.crop.current_stage:
            stages.append(snapshot.crop.current_stage)
    final = snapshots[-1].crop
    checks = [
        _check("full_stage_sequence", " -> ".join(stages), stages == list(STAGES), "the existing PhenologyEngine stage sequence is traversed completely and in order", code="INCOMPLETE_SCENARIO"),
        _check("maturity_reached", final.maturity_index, final.maturity_index >= 1.0, "maturity_index reaches 1 within the synthetic season", code="INCOMPLETE_SCENARIO"),
        _check("harvest_ready_at_end", final.harvest_ready, final.harvest_ready, "post-harvest state is represented (harvest_ready with post_harvest_dormancy)", code="INCOMPLETE_SCENARIO"),
        _check("biomass_growth", final.biomass_total - scenario.initial_crop.biomass_total, final.biomass_total > scenario.initial_crop.biomass_total, "the crop accumulates biomass over the season", unit="g_DM_m-2"),
    ]
    post = [snapshot.crop.leaf_area_index for snapshot in snapshots if snapshot.crop.current_stage == "post_harvest_dormancy"]
    if len(post) > 1:
        checks.append(_check("post_harvest_senescence", post[0] - post[-1], post[-1] < post[0], "LAI declines during post-harvest (RadiationGrowthEngine senescence)", unit="m2_m-2"))
    if scenario.perennial:
        released = [index for index, snapshot in enumerate(snapshots) if snapshot.crop.dormancy_released]
        release_index = released[0] if released else None
        checks.append(_check("dormancy_release", release_index is not None and release_index > 0, release_index is not None and release_index > 0, "chilling accumulation releases dormancy once, after a dormant period", code="INCOMPLETE_SCENARIO"))
        if release_index:
            dormant_growth = snapshots[release_index - 1].crop.biomass_total - scenario.initial_crop.biomass_total
            checks.append(_check(
                "growth_during_dormancy", dormant_growth, None if dormant_growth <= FLOAT_TOLERANCE else False,
                "biomass gain before dormancy release (the existing engines do not suppress growth during endodormancy)",
                unit="g_DM_m-2", severity="WARNING", code="DORMANCY_GROWTH_NOT_SUPPRESSED",
            ))
    return checks


def _water_stress(scenario, snapshots, control) -> list:
    assert scenario.window is not None and control is not None
    window = _window_indices(scenario, *scenario.window)
    stress = _series(snapshots, window, lambda s: s.crop.water_stress)
    control_stress = _series(control, window, lambda s: s.crop.water_stress)
    growth = sum(_series(snapshots, window, lambda s: s.actual_growth_g_m2))
    control_growth = sum(_series(control, window, lambda s: s.actual_growth_g_m2))
    peak = max(stress)
    resume = window.stop
    one_day = min(len(snapshots) - 1, resume + 86400 // scenario.timestep_seconds)
    final = snapshots[-1].crop
    return [
        _check("water_stress_increase", peak - max(control_stress), peak > max(control_stress), "peak water stress during the deficit exceeds the irrigated control", unit="fraction"),
        _check("growth_reduction", growth - control_growth, growth < control_growth, "actual growth during the deficit is lower than the irrigated control", unit="g_DM_m-2"),
        _check("recovery_after_irrigation", final.water_stress, final.water_stress < peak, "water stress decreases after irrigation resumes", unit="fraction"),
        _check("gradual_recovery", snapshots[one_day].crop.water_stress, snapshots[one_day].crop.water_stress >= 0.5 * peak, "one day after irrigation resumes stress remains >= 50% of peak (no instantaneous reset)", unit="fraction", threshold=0.5, threshold_kind=ENGINEERING_TEST_THRESHOLD),
        _check("persistent_biomass_deficit", final.biomass_total - control[-1].crop.biomass_total, final.biomass_total < control[-1].crop.biomass_total, "growth lost during the deficit is not restored by an artificial state reset", unit="g_DM_m-2"),
    ]


def _heat_wave(scenario, snapshots, control) -> list:
    assert scenario.window is not None and control is not None
    window = _window_indices(scenario, *scenario.window)
    profile = ClimateStressEngine().profile_for(scenario.crop)
    max_temperature = max(_series(snapshots, window, lambda s: s.weather.temperature_c))
    heat = max(_series(snapshots, window, lambda s: s.crop.heat_stress))
    factor = _mean(_series(snapshots, window, lambda s: s.growth_factor))
    control_factor = _mean(_series(control, window, lambda s: s.growth_factor))
    damage = [s.crop.heat_damage for s in snapshots]
    peak_damage = max(damage)
    exceeds = max_temperature > profile.max_temp_c
    return [
        _check("heat_stress_response", heat, heat > 0 if exceeds else None, f"heat stress > 0 when air temperature exceeds the existing ClimateStressProfile.max_temp_c ({profile.max_temp_c} C)", unit="fraction"),
        _check("growth_factor_reduction", factor - control_factor, factor < control_factor, "mean growth factor during the heat wave is below the control", unit="fraction"),
        _check("heat_damage_recovery", damage[-1], damage[-1] < peak_damage if peak_damage > 0 else None, "heat damage decays after the event with the existing recovery rate", unit="fraction"),
        _check("persistent_biomass_deficit", snapshots[-1].crop.biomass_total - control[-1].crop.biomass_total, snapshots[-1].crop.biomass_total < control[-1].crop.biomass_total, "lost growth is not restored by an artificial reset", unit="g_DM_m-2"),
    ]


def _radiation(direction: int) -> BehaviourCheck:
    def check(scenario, snapshots, control) -> list:
        assert scenario.window is not None and control is not None
        window = _window_indices(scenario, *scenario.window)
        potential = sum(_series(snapshots, window, lambda s: s.potential_growth_g_m2))
        control_potential = sum(_series(control, window, lambda s: s.potential_growth_g_m2))
        radiation = max(_series(snapshots, window, lambda s: s.weather.solar_radiation_w_m2))
        checks = [
            _check("potential_growth_response", potential - control_potential, potential < control_potential if direction < 0 else potential > control_potential, "PAR change produces a potential growth (APAR x RUE) change of the same sign", unit="g_DM_m-2"),
            _check("radiation_physically_bounded", radiation, radiation <= 1400.0, "incoming shortwave stays below 1400 W m-2", unit="W_m-2", threshold=1400.0, threshold_kind=ENGINEERING_TEST_THRESHOLD),
        ]
        if direction > 0:
            photo = max(_series(snapshots, window, lambda s: s.crop.radiation_stress))
            checks.append(_check("photoinhibition_observed", photo, None, "radiation stress from the existing photoinhibition ramp; actual growth is not required to increase", unit="fraction"))
        return checks
    return check


def _ventilation(scenario, snapshots, control) -> list:
    assert scenario.window is not None and control is not None
    window = _window_indices(scenario, *scenario.window)
    exchanged = _mean(_series(snapshots, window, lambda s: s.microclimate.indoor_state.ventilation_fraction))
    control_exchanged = _mean(_series(control, window, lambda s: s.microclimate.indoor_state.ventilation_fraction))
    gap = _mean(_series(snapshots, window, lambda s: abs(s.microclimate.indoor_state.temperature_c - s.outdoor_weather.temperature_c)))
    control_gap = _mean(_series(control, window, lambda s: abs(s.microclimate.indoor_state.temperature_c - s.outdoor_weather.temperature_c)))
    crop_temperature = all(s.weather.temperature_c == s.microclimate.indoor_state.temperature_c for s in snapshots)
    forcing_equal = all(snapshots[i].outdoor_weather == control[i].outdoor_weather for i in window)
    stress = _mean(_series(snapshots, window, lambda s: s.crop.vpd_stress))
    control_stress = _mean(_series(control, window, lambda s: s.crop.vpd_stress))
    return [
        _check("outdoor_forcing_unchanged", forcing_equal, forcing_equal, "the actuator does not modify outdoor weather forcing"),
        _check("air_exchange_response", exchanged - control_exchanged, exchanged > control_exchanged, "extra ACH raises the air fraction exchanged per step, 1 - exp(-ACH dt)", unit="fraction"),
        _check("indoor_temperature_toward_outdoor", gap - control_gap, gap < control_gap, "more air exchange brings indoor air temperature closer to outdoor", unit="C"),
        _check("crop_uses_indoor_temperature", crop_temperature, crop_temperature, "the crop environment temperature is the microclimate air temperature"),
        _check("crop_vpd_stress_observed", stress - control_stress, None, "crop VPD stress follows the resulting microclimate (sign not imposed)", unit="fraction"),
    ]


def _shading(scenario, snapshots, control) -> list:
    assert scenario.window is not None and control is not None
    window = _window_indices(scenario, *scenario.window)
    ratio = [snapshots[i].microclimate.indoor_state.solar_radiation_w_m2 / control[i].microclimate.indoor_state.solar_radiation_w_m2 for i in window if control[i].microclimate.indoor_state.solar_radiation_w_m2 > 0]
    potential = sum(_series(snapshots, window, lambda s: s.potential_growth_g_m2))
    control_potential = sum(_series(control, window, lambda s: s.potential_growth_g_m2))
    exact = bool(ratio) and all(abs(value - 0.5) <= 1e-9 for value in ratio)
    return [
        _check("indoor_radiation_transmission", _mean(ratio), exact, "indoor radiation equals (1 - shading_fraction) x unshaded indoor radiation", unit="ratio"),
        _check("potential_growth_reduction", potential - control_potential, potential < control_potential, "shading reduces potential growth through radiation only", unit="g_DM_m-2"),
    ]


def _co2(scenario, snapshots, control) -> list:
    assert scenario.window is not None and control is not None
    window = _window_indices(scenario, *scenario.window)
    co2 = _mean(_series(snapshots, window, lambda s: s.microclimate.indoor_state.co2_ppm))
    control_co2 = _mean(_series(control, window, lambda s: s.microclimate.indoor_state.co2_ppm))
    first_after = window.stop
    persisted = snapshots[first_after].microclimate.indoor_state.co2_ppm > control[first_after].microclimate.indoor_state.co2_ppm + FLOAT_TOLERANCE
    day_after = min(len(snapshots) - 1, window.stop + 24)
    decayed = abs(snapshots[day_after].microclimate.indoor_state.co2_ppm - control[day_after].microclimate.indoor_state.co2_ppm) <= 1.0
    single_path = all(s.co2_factor == CropGrowthEngine.co2_response(s.microclimate.indoor_state.co2_ppm) for s in snapshots)
    return [
        _check("indoor_co2_response", co2 - control_co2, co2 > control_co2, "CO2 supply raises indoor CO2", unit="ppm"),
        _check("co2_state_persists", persisted, persisted, "enriched CO2 is carried into the step after supply stops (persistent microclimate, no reset)"),
        _check("co2_decays_by_air_exchange", decayed, decayed, "within 24 h of supply stopping, indoor CO2 is back within 1 ppm of control through air exchange", threshold=1.0, threshold_kind=ENGINEERING_TEST_THRESHOLD),
        _check("co2_response_single_path", single_path, single_path, "every step applies CropGrowthEngine.co2_response(indoor CO2) exactly once"),
    ]


def _combined(scenario, snapshots, control) -> list:
    assert scenario.window is not None and control is not None
    window = _window_indices(scenario, *scenario.window)
    growth = sum(_series(snapshots, window, lambda s: s.actual_growth_g_m2))
    control_growth = sum(_series(control, window, lambda s: s.actual_growth_g_m2))
    return [_check("combined_growth_reduction", growth - control_growth, growth < control_growth, "combined heat, deficit, high radiation and ventilation reduce growth relative to control", unit="g_DM_m-2")]


BEHAVIOUR_CHECKS: Mapping[SyntheticScenarioKind, BehaviourCheck] = {
    SyntheticScenarioKind.NORMAL_SEASON: _normal_season,
    SyntheticScenarioKind.WATER_STRESS_RECOVERY: _water_stress,
    SyntheticScenarioKind.HEAT_WAVE_RECOVERY: _heat_wave,
    SyntheticScenarioKind.LOW_RADIATION: _radiation(-1),
    SyntheticScenarioKind.HIGH_RADIATION: _radiation(1),
    SyntheticScenarioKind.GREENHOUSE_VENTILATION: _ventilation,
    SyntheticScenarioKind.GREENHOUSE_SHADING: _shading,
    SyntheticScenarioKind.GREENHOUSE_CO2: _co2,
    SyntheticScenarioKind.COMBINED_STRESS: _combined,
}
BEHAVIOURS: Mapping[SyntheticScenarioKind, tuple[str, ...]] = {
    SyntheticScenarioKind.NORMAL_SEASON: ("full_stage_sequence", "maturity_reached", "harvest_ready_at_end", "biomass_growth", "post_harvest_senescence"),
    SyntheticScenarioKind.WATER_STRESS_RECOVERY: ("water_stress_increase", "growth_reduction", "recovery_after_irrigation", "gradual_recovery", "persistent_biomass_deficit"),
    SyntheticScenarioKind.HEAT_WAVE_RECOVERY: ("heat_stress_response", "growth_factor_reduction", "heat_damage_recovery", "persistent_biomass_deficit"),
    SyntheticScenarioKind.LOW_RADIATION: ("potential_growth_response", "radiation_physically_bounded"),
    SyntheticScenarioKind.HIGH_RADIATION: ("potential_growth_response", "radiation_physically_bounded", "photoinhibition_observed"),
    SyntheticScenarioKind.GREENHOUSE_VENTILATION: ("outdoor_forcing_unchanged", "air_exchange_response", "indoor_temperature_toward_outdoor", "crop_uses_indoor_temperature", "crop_vpd_stress_observed"),
    SyntheticScenarioKind.GREENHOUSE_SHADING: ("indoor_radiation_transmission", "potential_growth_reduction"),
    SyntheticScenarioKind.GREENHOUSE_CO2: ("indoor_co2_response", "co2_state_persists", "co2_decays_by_air_exchange", "co2_response_single_path"),
    SyntheticScenarioKind.COMBINED_STRESS: ("combined_growth_reduction",),
}


def _status_from(issues_fail: Sequence[SyntheticValidationIssue], issues_warn: Sequence[SyntheticValidationIssue]) -> SyntheticValidationStatus:
    codes = {issue.code for issue in issues_fail}
    for code, status in (
        ("NUMERICAL_FAILURE", SyntheticValidationStatus.NUMERICAL_FAILURE),
        ("INCOMPLETE_SCENARIO", SyntheticValidationStatus.INCOMPLETE_SCENARIO),
        ("INVARIANT_VIOLATION", SyntheticValidationStatus.INVARIANT_VIOLATION),
        ("CONVERGENCE_FAILURE", SyntheticValidationStatus.CONVERGENCE_FAILURE),
        ("NON_DETERMINISTIC", SyntheticValidationStatus.NON_DETERMINISTIC),
    ):
        if code in codes:
            return status
    if issues_fail:
        return SyntheticValidationStatus.FAIL
    return SyntheticValidationStatus.PASS_WITH_WARNINGS if issues_warn else SyntheticValidationStatus.PASS


def _section_status(passed: bool, warnings: bool = False, failure: SyntheticValidationStatus = SyntheticValidationStatus.FAIL) -> str:
    if not passed:
        return failure.value
    return (SyntheticValidationStatus.PASS_WITH_WARNINGS if warnings else SyntheticValidationStatus.PASS).value


# ---------------------------------------------------------------------------
# Checkpoints (full CropGrowthState/SoilState serialisation)
# ---------------------------------------------------------------------------


def checkpoint_payload(snapshot: CropSimulationSnapshot) -> str:
    """Full persistent orchestrator state: crop, soil and the greenhouse microclimate."""
    return json.dumps({
        "simulation_time": snapshot.simulation_time.isoformat(),
        "crop": snapshot.crop.to_dict(),
        "soil": asdict(snapshot.soil),
        "microclimate": snapshot.microclimate.indoor_state.to_dict(),
    }, sort_keys=True)


def restore_checkpoint(payload: str) -> tuple[datetime, CropGrowthState, SoilState, GreenhouseMicroclimateState]:
    data = json.loads(payload)
    crop_values = dict(data["crop"])
    crop_values["simulation_time"] = datetime.fromisoformat(crop_values["simulation_time"])
    return datetime.fromisoformat(data["simulation_time"]), CropGrowthState(**crop_values), SoilState(**data["soil"]), GreenhouseMicroclimateState(**data["microclimate"])


def resumed_scenario(scenario: Scenario, restart_time: datetime, crop: CropGrowthState, soil: SoilState, microclimate: GreenhouseMicroclimateState | None = None) -> Scenario:
    events = []
    for event in scenario.events:
        if event.end < restart_time:
            continue
        if event.end == restart_time:
            raise ScenarioError(f"checkpoint {restart_time.isoformat()} coincides with the end of event {event.event_id}")
        events.append(replace(event, start=max(event.start, restart_time)))
    return replace(scenario, start=restart_time, initial_crop=crop, initial_soil=soil, events=tuple(events), initial_microclimate=microclimate)


def twin_state_from_snapshot(snapshot: CropSimulationSnapshot, scenario: SyntheticValidationScenario) -> TwinState:
    """Observable persisted projection of an orchestrator snapshot (not a restart checkpoint)."""
    crop = snapshot.crop
    status = "HARVEST_READY" if crop.harvest_ready else ("DORMANCY" if not crop.dormancy_released else "ACTIVE")
    micro = snapshot.microclimate.indoor_state
    return TwinState(
        simulation_time=snapshot.simulation_time,
        plot_id=scenario.plot_id,
        cycle_id=scenario.cycle_id,
        crop=scenario.crop,
        variety=scenario.variety,
        cycle_status=status,
        phenological_stage=crop.current_stage,
        lai=crop.leaf_area_index,
        biomass_g_m2=crop.biomass_total,
        maturity=crop.maturity_index,
        stress=1.0 - snapshot.growth_factor,
        soil_water_m3_m3=snapshot.soil.vwc_m3_m3,
        temperature_c=micro.temperature_c,
        relative_humidity_pct=micro.relative_humidity_pct,
        vpd_kpa=snapshot.environment.vpd_kpa,
        radiation_w_m2=micro.solar_radiation_w_m2,
        co2_ppm=micro.co2_ppm,
        weather_source=SOURCE_TYPE,
        weather_timestamp=snapshot.simulation_time,
    )


# ---------------------------------------------------------------------------
# Static audit
# ---------------------------------------------------------------------------


FORBIDDEN_CALLS = {"datetime.now", "datetime.utcnow", "datetime.today", "date.today", "time.time", "time.sleep", "asyncio.sleep", "sleep"}
FORBIDDEN_IMPORTS = {"socket", "requests", "urllib", "http", "httpx", "aiohttp", "serial", "sklearn", "torch", "tensorflow", "keras", "xgboost", "scipy", "pyenergyplus", "eppy"}
OPTIMIZER_METHODS = {"calibrate", "software_fixture_calibration", "optimize", "minimize", "fit", "grid_search"}
SINGLETON_CLASSES = (
    "SimulationClock", "SimulationScheduler", "CropGrowthEngine", "PhenologyEngine", "WaterBalanceEngine",
    "ClimateStressEngine", "GreenhousePhysicalModel", "SimplifiedGreenhouseModel", "CropGreenhouseFeedbackLoop",
    "CropPhysicalExchangeModel", "ObservationDataset", "ParameterRegistry", "TwinStateRepository", "InMemoryTwinStateRepository",
)
ALLOWED_EXCEPTIONS = {
    "agri_twin/contracts.py": "datetime.now for the message-envelope emission timestamp (metadata, not simulation dynamics)",
    "agri_twin/infrastructure/open_meteo.py": "urllib network access and retrieved_at metadata for explicit, user-triggered weather downloads only",
    "agri_twin/infrastructure/energyplus_greenhouse.py": "optional EnergyPlus runtime loaded lazily via importlib",
    "agri_twin/infrastructure/eppy_greenhouse.py": "optional eppy IDF generation loaded lazily via importlib",
}


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def static_audit(root: str | Path) -> dict[str, Any]:
    """AST audit of simulation dynamics (domain and application layers)."""
    source_root = Path(root) / "src" / "agri_twin"
    scanned = sorted([*(source_root / "domain").glob("*.py"), *(source_root / "application").glob("*.py")])
    violations: list[dict[str, Any]] = []
    classes: dict[str, list[str]] = {name: [] for name in SINGLETON_CLASSES}
    for path in sorted(source_root.rglob("*.py")):
        relative = path.relative_to(source_root.parent).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in classes:
                classes[node.name].append(relative)
        if path not in scanned:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node.func) in FORBIDDEN_CALLS:
                violations.append({"file": relative, "line": node.lineno, "rule": "wall_clock_or_sleep", "detail": _call_name(node.func)})
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                for name in names:
                    if name.split(".")[0] in FORBIDDEN_IMPORTS:
                        violations.append({"file": relative, "line": node.lineno, "rule": "network_hardware_ml_or_mandatory_energyplus_import", "detail": name})
    duplicates = {name: files for name, files in classes.items() if len(files) > 1}
    missing = [name for name, files in classes.items() if not files]
    own = (source_root / "application" / "integrated_synthetic_validation.py").read_text(encoding="utf-8")
    own_tree = ast.parse(own)
    own_imports = {node.module for node in ast.walk(own_tree) if isinstance(node, ast.ImportFrom) and node.module}
    calibration_imports = sorted(name for name in own_imports if "calibration" in name and name != "agri_twin.domain.calibration")
    own_calls = {_call_name(node.func) for node in ast.walk(own_tree) if isinstance(node, ast.Call)}
    optimizer_calls = sorted(name for name in own_calls if name.rsplit(".", 1)[-1] in OPTIMIZER_METHODS)
    passed = not violations and not duplicates and not missing and not calibration_imports and not optimizer_calls
    return {
        "status": _section_status(passed),
        "scanned_files": len(scanned),
        "scope": "src/agri_twin/domain/*.py and src/agri_twin/application/*.py (AST: real calls/imports only, docs and strings ignored)",
        "violations": violations,
        "duplicate_core_classes": duplicates,
        "missing_core_classes": missing,
        "phase_module_calibration_imports": calibration_imports,
        "phase_module_optimizer_calls": optimizer_calls,
        "allowed_exceptions_outside_scope": dict(ALLOWED_EXCEPTIONS),
        "rules": {
            "forbidden_calls": sorted(FORBIDDEN_CALLS),
            "forbidden_imports": sorted(FORBIDDEN_IMPORTS),
            "singleton_classes": list(SINGLETON_CLASSES),
            "performance_timing": "time.perf_counter is used only for execution metadata excluded from hashes",
        },
    }


# ---------------------------------------------------------------------------
# Suite
# ---------------------------------------------------------------------------


class IntegratedSyntheticValidationSuite:
    """Run fixed-model synthetic scenarios and evaluate integrated consistency."""

    VERSION = VERSION

    def __init__(
        self,
        root: str | Path,
        *,
        registry: ParameterRegistry | None = None,
        crops: Sequence[str] = KNOWN_CROPS,
        seed: int = DEFAULT_SEED,
        include_extended: bool = True,
        include_integration_suites: bool = True,
    ) -> None:
        unknown = [crop for crop in crops if crop not in KNOWN_CROPS]
        if unknown:
            raise ScenarioError(f"unknown crops: {unknown}")
        self.root = Path(root)
        self.registry = registry or ParameterRegistry.from_repository(self.root)
        self.crops = tuple(crops)
        self.seed = seed
        self.include_extended = include_extended
        self.include_integration_suites = include_integration_suites
        self.runner = ScenarioRunner(synthetic_weather_factory)
        self._timings: dict[str, float] = {}

    # -- cases ---------------------------------------------------------------

    def cases(self) -> tuple[SyntheticValidationCase, ...]:
        return default_cases(self.crops, seed=self.seed, include_extended=self.include_extended)

    def run_scenario(self, scenario: SyntheticValidationScenario) -> ScenarioResult:
        return self.runner.run(scenario.to_scenario())

    def variety_resolution(self, crop: str, variety: str) -> dict[str, Any]:
        records = [record for record in self.registry.records if record.variety == variety]
        model_records = [record.parameter_id for record in records if record.subsystem != "farm_config"]
        phenology = PhenologyEngine().profile_for(crop)
        return {
            "variety": variety,
            "known_variety": variety in KNOWN_VARIETIES.values(),
            "resolution": (VarietyParameterResolution.VARIETY_SPECIFIC if model_records else VarietyParameterResolution.SPECIES_FALLBACK).value,
            "variety_registry_records": sorted(record.parameter_id for record in records),
            "variety_model_parameter_records": sorted(model_records),
            "runtime_profiles": {
                "phenology": f"APPROXIMATE_PROFILES[{crop}] ({phenology.evidence_level.value})",
                "radiation_growth": f"APPROXIMATE_RADIATION_PROFILES[{crop}] (crop-level engineering approximation)",
                "climate_stress": f"DEFAULT_PROFILES[{crop}] (engineering default)",
            },
            "parameter_status": "ENGINEERING_DEFAULT species profile; candidate for future calibration (FUTURE_CALIBRATABLE)",
        }

    def evaluate_case(self, case: SyntheticValidationCase, result: ScenarioResult, control: ScenarioResult | None) -> SyntheticValidationResult:
        scenario = case.scenario
        snapshots = result.snapshots
        expected_steps = int((scenario.end - scenario.start).total_seconds() // scenario.timestep_seconds)
        failures: list[SyntheticValidationIssue] = []
        warnings: list[SyntheticValidationIssue] = []
        metrics: list[SyntheticValidationMetric] = [
            SyntheticValidationMetric("software.steps_completed", len(snapshots), "steps", ValidationCategory.SOFTWARE_CONSISTENCY, len(snapshots) == expected_steps, expected_steps, None, "number of completed SimulationClock steps equals the scenario length"),
        ]
        if result.status != "SUCCESS":
            failures.append(SyntheticValidationIssue("NUMERICAL_FAILURE", "FAILURE", f"scenario runner failed: {'; '.join(result.warnings)}"))
        if len(snapshots) != expected_steps:
            failures.append(SyntheticValidationIssue("INCOMPLETE_SCENARIO", "FAILURE", f"{len(snapshots)} of {expected_steps} steps completed"))
        observed: dict[str, Any] = {}
        if snapshots:
            invariant_metrics, invariant_issues = validate_trajectory(scenario, snapshots)
            metrics += invariant_metrics
            failures += invariant_issues
            valid_steps = sum(1 for snapshot in snapshots if all(math.isfinite(value) for value in snapshot_numbers(snapshot).values()))
            metrics.append(SyntheticValidationMetric("software.valid_step_fraction", valid_steps / len(snapshots), "fraction", ValidationCategory.SOFTWARE_CONSISTENCY, valid_steps == len(snapshots), 1.0, None, "fraction of steps whose state is fully finite"))
            if len(snapshots) == expected_steps:
                check_control = control.snapshots if control is not None else None
                if case.control_case_id is not None and (check_control is None or len(check_control) != len(snapshots)):
                    failures.append(SyntheticValidationIssue("INVALID_CONFIGURATION", "FAILURE", f"paired control {case.control_case_id} is unavailable or misaligned"))
                else:
                    for metric, issue in BEHAVIOUR_CHECKS[scenario.kind](scenario, snapshots, check_control):
                        metrics.append(metric)
                        if issue is not None:
                            (warnings if issue.severity == "WARNING" else failures).append(issue)
            final = snapshots[-1]
            observed = {
                "final_simulation_time": final.simulation_time.isoformat(),
                "final_stage": final.crop.current_stage,
                "final_biomass_g_m2": final.crop.biomass_total,
                "final_biomass_fruit_g_m2": final.crop.biomass_fruit,
                "final_lai": final.crop.leaf_area_index,
                "final_maturity": final.crop.maturity_index,
                "harvest_ready": final.crop.harvest_ready,
                "final_gdd": final.crop.gdd_accumulated,
                "final_chilling_hours": final.crop.chilling_hours,
                "peak_water_stress": max(s.crop.water_stress for s in snapshots),
                "peak_heat_stress": max(s.crop.heat_stress for s in snapshots),
                "peak_heat_damage": max(s.crop.heat_damage for s in snapshots),
                "min_soil_vwc": min(s.soil.vwc_m3_m3 for s in snapshots),
                "peak_indoor_co2_ppm": max(s.microclimate.indoor_state.co2_ppm for s in snapshots),
                "stage_entry_times": _stage_entries(snapshots),
                "dormancy_release_time": next((s.simulation_time.isoformat() for s in snapshots if s.crop.dormancy_released), None) if scenario.perennial else None,
            }
        if any(issue.code == "INVALID_CONFIGURATION" for issue in failures):
            status = SyntheticValidationStatus.INVALID_CONFIGURATION
        else:
            status = _status_from(failures, warnings)
        provenance = {
            "source_type": SOURCE_TYPE,
            "validation_kind": VALIDATION_KIND,
            "generator": WEATHER_GENERATOR,
            "seed": scenario.weather_seed,
            "climate_profile": scenario.climate_profile,
            "scenario_id": scenario.scenario_id,
            "configuration_hash": scenario.configuration_hash(),
            "model_configuration": {
                "orchestrator": "CropDigitalTwinOrchestrator (PhenologyEngine, GreenhouseMicroclimateEngine, RadiationGrowthEngine, WaterBalanceEngine, NutrientBalanceEngine, ClimateStressEngine)",
                "greenhouse_mode": scenario.greenhouse_mode,
                "variety_parameters": self.variety_resolution(scenario.crop, scenario.variety),
            },
            "simulation_range": [scenario.start.isoformat(), scenario.end.isoformat()],
            "crop": scenario.crop,
            "variety": scenario.variety,
            "plot_id": scenario.plot_id,
            "environment": scenario.environment,
            "cycle_id": scenario.cycle_id,
            "observations_used": False,
            "calibration_performed": False,
        }
        return SyntheticValidationResult(
            case.case_id, scenario, case.expected_invariants, case.expected_behaviours, observed, tuple(metrics), status,
            tuple(warnings), tuple(failures), provenance, scenario.configuration_hash(), trajectory_hash(snapshots),
        )

    def run_cases(self, cases: Sequence[SyntheticValidationCase] | None = None) -> tuple[tuple[SyntheticValidationResult, ...], dict[str, ScenarioResult]]:
        cases = tuple(cases or self.cases())
        raw: dict[str, ScenarioResult] = {}
        started = time.perf_counter()
        for case in sorted(cases, key=lambda item: item.control_case_id is not None):
            raw[case.case_id] = self.run_scenario(case.scenario)
        self._timings["scenario_execution_seconds"] = time.perf_counter() - started
        results = tuple(self.evaluate_case(case, raw[case.case_id], raw.get(case.control_case_id) if case.control_case_id else None) for case in cases)
        return results, raw

    # -- determinism ----------------------------------------------------------

    def determinism(self, cases: Sequence[SyntheticValidationCase], first_hashes: Mapping[str, str]) -> dict[str, Any]:
        mismatches = []
        for case in cases:
            repeated = self.run_scenario(case.scenario)
            if trajectory_hash(repeated.snapshots) != first_hashes[case.case_id]:
                mismatches.append(case.case_id)
        return {
            "status": _section_status(not mismatches, failure=SyntheticValidationStatus.NON_DETERMINISTIC),
            "cases_rerun": len(cases),
            "identical_trajectory_hashes": len(cases) - len(mismatches),
            "mismatched_cases": mismatches,
            "method": "every case is executed twice with identical configuration and seeds; full trajectory hashes are compared",
        }

    # -- restart / checkpoint -------------------------------------------------

    def restart_equivalence(self, case: SyntheticValidationCase, continuous: ScenarioResult, fractions: Sequence[float] = (0.25, 0.5, 0.75)) -> dict[str, Any]:
        scenario = case.scenario
        steps = len(continuous.snapshots)
        checks = []
        for fraction in fractions:
            # Snapshot i is at start + (i + 1) h; checkpoint at 12:00 so no event boundary coincides.
            index = int(steps * fraction)
            index = max(0, min(steps - 2, index - (index + 1 - 12) % 24))
            restart = continuous.snapshots[index]
            payload = checkpoint_payload(restart)
            restart_time, crop, soil, microclimate = restore_checkpoint(payload)
            try:
                resumed = self.runner.run(resumed_scenario(scenario.to_scenario(), restart_time, crop, soil, microclimate))
            except ScenarioError as exc:
                checks.append({"checkpoint": restart_time.isoformat(), "status": SyntheticValidationStatus.INVALID_CONFIGURATION.value, "detail": str(exc)})
                continue
            tail = continuous.snapshots[index + 1:]
            aligned = len(resumed.snapshots) == len(tail) and all(a.simulation_time == b.simulation_time for a, b in zip(resumed.snapshots, tail))
            max_difference = max((_max_difference(snapshot_numbers(a), snapshot_numbers(b)) for a, b in zip(resumed.snapshots, tail)), default=math.inf)
            stage_equal = all(a.crop.current_stage == b.crop.current_stage and a.crop.harvest_ready == b.crop.harvest_ready for a, b in zip(resumed.snapshots, tail))
            restored_equal = crop == restart.crop and soil == restart.soil and microclimate.to_dict() == restart.microclimate.indoor_state.to_dict()
            passed = aligned and stage_equal and restored_equal and max_difference <= FLOAT_TOLERANCE
            checks.append({
                "checkpoint": restart_time.isoformat(),
                "checkpoint_fraction": fraction,
                "checkpoint_round_trip_exact": restored_equal,
                "time_axis_aligned": aligned,
                "stages_equal": stage_equal,
                "remaining_steps": len(tail),
                "max_abs_difference": max_difference,
                "tolerance": FLOAT_TOLERANCE,
                "tolerance_kind": ENGINEERING_TEST_THRESHOLD,
                "equivalent": passed,
                "status": _section_status(passed, failure=SyntheticValidationStatus.NON_DETERMINISTIC),
            })
        passed = all(check.get("equivalent") for check in checks)
        return {
            "case_id": case.case_id,
            "status": _section_status(passed, failure=SyntheticValidationStatus.NON_DETERMINISTIC),
            "method": "continuous run vs run restored at t1 from a JSON checkpoint of the full CropGrowthState, SoilState and greenhouse microclimate, compared at every later step (t1 -> t2 -> end)",
            "checkpoints": checks,
        }

    # -- persistence ------------------------------------------------------------

    def persistence(self, case: SyntheticValidationCase, result: ScenarioResult) -> dict[str, Any]:
        scenario = case.scenario
        repository = InMemoryTwinStateRepository()
        daily = [snapshot for index, snapshot in enumerate(result.snapshots) if (index + 1) % 24 == 0]
        mismatches = []
        for snapshot in daily:
            state = twin_state_from_snapshot(snapshot, scenario)
            repository.save_snapshot(TwinSnapshot(snapshot.simulation_time, (state,)))
            stored = repository.get_exact(scenario.plot_id, scenario.cycle_id, snapshot.simulation_time)
            round_trip = TwinState.from_dict(json.loads(json.dumps(stored.to_dict())))
            computed = (snapshot.crop.leaf_area_index, snapshot.crop.biomass_total, snapshot.crop.maturity_index, snapshot.soil.vwc_m3_m3, snapshot.microclimate.indoor_state.co2_ppm)
            persisted = (stored.lai, stored.biomass_g_m2, stored.maturity, stored.soil_water_m3_m3, stored.co2_ppm)
            if stored != state or round_trip != state or computed != persisted:
                mismatches.append(snapshot.simulation_time.isoformat())
        history = repository.history(scenario.plot_id, scenario.cycle_id)
        idempotent = repository.save(history[0]) == history[0]
        try:
            repository.save(replace(history[0], lai=(history[0].lai or 0.0) + 1.0))
            conflict_detected = False
        except TwinStateConflict:
            conflict_detected = True
        try:
            history[0].lai = 0.0  # type: ignore[misc]
            immutable = False
        except (AttributeError, TypeError):
            immutable = True
        ordered = [state.simulation_time for state in history] == sorted(state.simulation_time for state in history)
        passed = not mismatches and idempotent and conflict_detected and immutable and ordered and len(history) == len(daily)
        return {
            "case_id": case.case_id,
            "status": _section_status(passed, failure=SyntheticValidationStatus.INVARIANT_VIOLATION),
            "states_persisted": len(history),
            "snapshot_mismatches": mismatches,
            "json_round_trip_exact": not mismatches,
            "idempotent_resave": idempotent,
            "conflicting_write_rejected": conflict_detected,
            "twin_state_frozen": immutable,
            "history_ordered": ordered,
            "repository": "InMemoryTwinStateRepository (isolated instance, dedicated persistence check)",
            "limitation": "TwinState is the observable projection (LAI, biomass, maturity, stress, soil water, microclimate); it does not carry the full CropGrowthState, so restarts use the CropGrowthState/SoilState checkpoint",
        }

    # -- multi-plot -------------------------------------------------------------

    def _cycle_orchestrator(self, clock: SimulationClock, cycle: SyntheticCropCycle, environment: str, first_step: datetime, dt: float) -> CropDigitalTwinOrchestrator:
        crop, soil = _initial_state(cycle.crop, cycle.variety or "UNSPECIFIED", first_step - timedelta(seconds=dt))
        mode = "passive_greenhouse" if environment == "greenhouse" else "outdoor"
        return CropDigitalTwinOrchestrator(clock, WeatherEngine(weather_configuration("warm_season", self.seed)), replace(crop, dormancy_released=True), soil, mode)

    def _multi_plot_run(self, plots: Sequence[SyntheticPlot], cycles: Sequence[SyntheticCropCycle], start: datetime, days: int, *, dry_cycle: str | None = None) -> tuple[MultiPlotSimulation, dict[str, CropDigitalTwinOrchestrator], dict[str, list[CropSimulationSnapshot]]]:
        """One SimulationClock/Scheduler (MultiPlotSimulation) ticks one orchestrator per crop cycle."""
        clock = SimulationClock(start)
        environments = {plot.plot_id: plot.environment for plot in plots}
        orchestrators: dict[str, CropDigitalTwinOrchestrator] = {}
        steps: dict[str, list[CropSimulationSnapshot]] = {}

        def handler(result, dt: float) -> None:
            cycle = result.cycle
            orchestrator = orchestrators.get(cycle.crop_cycle_id)
            if orchestrator is None:
                orchestrator = self._cycle_orchestrator(clock, cycle, environments[cycle.plot_id], result.simulation_time, dt)
                orchestrators[cycle.crop_cycle_id] = orchestrator
            irrigation = None if cycle.crop_cycle_id == dry_cycle else IrrigationRequest("scheduled", BASELINE_IRRIGATION_MM_H)
            steps.setdefault(cycle.crop_cycle_id, []).append(orchestrator.step_at(result.simulation_time, dt, None, irrigation))

        engine = WeatherEngine(weather_configuration("warm_season", self.seed))

        simulation = MultiPlotSimulation(clock, plots, cycles, SyntheticWeatherProvider(engine), handler, 3600.0, InMemoryTwinStateRepository())
        simulation.advance(days * 86400.0)
        return simulation, orchestrators, steps

    def multi_plot(self) -> dict[str, Any]:
        crops = ("tomato", "pepper", "grape")
        plots = tuple(_plot_for(crop) for crop in crops)
        cycles = tuple(cycle for cycle in SyntheticReferenceDatasetGenerator._cycles(plots))
        start, days = datetime(2026, 4, 1, tzinfo=UTC), 30
        combined, orchestrators, _ = self._multi_plot_run(plots, cycles, start, days)
        final = {key: orchestrator.crop.to_dict() for key, orchestrator in orchestrators.items()}
        isolated = {}
        for plot in plots:
            _, alone, _ = self._multi_plot_run((plot,), tuple(cycle for cycle in cycles if cycle.plot_id == plot.plot_id), start, days)
            isolated.update({key: orchestrator.crop.to_dict() for key, orchestrator in alone.items()})
        dry_cycle = cycles[0].crop_cycle_id
        _, perturbed, _ = self._multi_plot_run(plots, cycles, start, days, dry_cycle=dry_cycle)
        perturbed_final = {key: orchestrator.crop.to_dict() for key, orchestrator in perturbed.items()}
        _, repeated, _ = self._multi_plot_run(plots, cycles, start, days)
        repeated_final = {key: orchestrator.crop.to_dict() for key, orchestrator in repeated.items()}
        snapshot = combined.latest_snapshot()
        histories = {plot.plot_id: combined.history(plot.plot_id) for plot in plots}
        history_isolated = all(all(state.plot_id == plot_id for state in states) for plot_id, states in histories.items())
        one_state_per_plot = snapshot is not None and sorted(state.plot_id for state in snapshot.states) == sorted(plot.plot_id for plot in plots)
        combined_equals_isolated = final == isolated
        perturbation_isolated = all(perturbed_final[key] == final[key] for key in final if key != dry_cycle) and perturbed_final[dry_cycle] != final[dry_cycle]
        deterministic = repeated_final == final
        passed = combined_equals_isolated and perturbation_isolated and deterministic and history_isolated and one_state_per_plot
        return {
            "status": _section_status(passed, failure=SyntheticValidationStatus.INVARIANT_VIOLATION),
            "plots": [plot.plot_id for plot in plots],
            "cycles": [cycle.crop_cycle_id for cycle in cycles],
            "simulated_days": days,
            "single_clock": "one SimulationClock and one SimulationScheduler (MultiPlotSimulation) drive every plot orchestrator",
            "combined_equals_isolated_runs": combined_equals_isolated,
            "perturbation_isolated": perturbation_isolated,
            "perturbed_cycle": dry_cycle,
            "deterministic": deterministic,
            "repository_histories_isolated": history_isolated,
            "one_state_per_plot_per_snapshot": one_state_per_plot,
            "final_biomass_g_m2": {key: value["biomass_total"] for key, value in sorted(final.items())},
        }

    # -- multi-cycle ------------------------------------------------------------

    def multi_cycle(self) -> dict[str, Any]:
        plots = (_plot_for("lettuce"), _plot_for("plum"))
        cycles = SyntheticReferenceDatasetGenerator._cycles(plots)
        start = datetime(2026, 1, 1, tzinfo=UTC)
        days = 258
        simulation, orchestrators, steps = self._multi_plot_run(plots, cycles, start, days)
        lettuce = [cycle for cycle in cycles if cycle.crop == "lettuce"]
        plum = next(cycle for cycle in cycles if cycle.crop == "plum")
        checks: dict[str, Any] = {}
        for cycle in lettuce:
            cycle_steps = [snapshot.simulation_time for snapshot in steps.get(cycle.crop_cycle_id, [])]
            last_allowed = datetime.combine(cycle.harvest_end + DAY, datetime.min.time(), tzinfo=UTC) if cycle.harvest_end else None
            first_allowed = datetime.combine(cycle.planting_date, datetime.min.time(), tzinfo=UTC) if cycle.planting_date else start
            statuses = _compress([state.cycle_status for state in simulation.history(cycle.plot_id, cycle.crop_cycle_id)])
            checks[cycle.crop_cycle_id] = {
                "steps": len(cycle_steps),
                "first_step": cycle_steps[0].isoformat() if cycle_steps else None,
                "last_step": cycle_steps[-1].isoformat() if cycle_steps else None,
                "stepped_only_within_cycle_dates": bool(cycle_steps) and cycle_steps[0] >= first_allowed and (last_allowed is None or cycle_steps[-1] <= last_allowed),
                "status_sequence": statuses,
                "not_reactivated": "ACTIVE" not in statuses[statuses.index("HARVEST_READY") + 1:] if "HARVEST_READY" in statuses else True,
                "final_biomass_g_m2": orchestrators[cycle.crop_cycle_id].crop.biomass_total if cycle.crop_cycle_id in orchestrators else None,
            }
        second = lettuce[1].crop_cycle_id
        first_second = steps[second][0]
        fresh = self._cycle_orchestrator(SimulationClock(start), lettuce[1], plots[0].environment, first_second.simulation_time, 3600.0)
        fresh_first = fresh.step_at(first_second.simulation_time, 3600.0, None, IrrigationRequest("scheduled", BASELINE_IRRIGATION_MM_H))
        second_starts_fresh = fresh_first.crop == first_second.crop
        histories_disjoint = not ({state.simulation_time for state in simulation.history(lettuce[0].plot_id, lettuce[0].crop_cycle_id)} & {state.simulation_time for state in simulation.history(lettuce[1].plot_id, second)})
        plum_statuses = _compress([state.cycle_status for state in simulation.history(plum.plot_id, plum.crop_cycle_id)])
        plum_expected = ["POST_HARVEST", "ACTIVE", "HARVEST_READY", "POST_HARVEST"]
        plum_ok = plum_statuses == plum_expected
        plum_crop = orchestrators[plum.crop_cycle_id].crop
        passed = all(item["stepped_only_within_cycle_dates"] and item["not_reactivated"] for item in checks.values()) and second_starts_fresh and histories_disjoint and plum_ok
        return {
            "status": _section_status(passed, warnings=True, failure=SyntheticValidationStatus.INVARIANT_VIOLATION),
            "lettuce_cycles": checks,
            "second_cycle_starts_from_fresh_state": second_starts_fresh,
            "cycle_histories_disjoint": histories_disjoint,
            "perennial_campaign": {
                "cycle_id": plum.crop_cycle_id,
                "status_sequence": plum_statuses,
                "expected_sequence": plum_expected,
                "status_sequence_valid": plum_ok,
                "final_stage": plum_crop.current_stage,
                "final_harvest_ready": plum_crop.harvest_ready,
                "next_campaign_transition": SyntheticValidationStatus.NOT_APPLICABLE.value,
                "next_campaign_note": "NOT_SUPPORTED by the existing engines: no transition from post_harvest_dormancy back to dormancy/establishment; recorded, not failed",
            },
            "source": "SyntheticReferenceDatasetGenerator cycles (lettuce_001, lettuce_002, plum_14705_2026)",
        }

    # -- greenhouse ---------------------------------------------------------------

    def actuator_causal_path(self) -> dict[str, Any]:
        """Shaded run vs unshaded run whose outdoor radiation equals the shaded transmission."""
        start = datetime(2026, 5, 1, tzinfo=UTC)
        crop, soil = _initial_state("tomato", "RAF", start)
        shade = 0.5

        def scenario(radiation: float, events: tuple[ScenarioEvent, ...]) -> Scenario:
            return Scenario(f"p529_causal_{radiation}", "causal", "actuator causal path", "tomato", "RAF", start, start + DAY, 3600, ScenarioKind.STRESS_TEST, crop, soil, WeatherState(26.0, 60.0, radiation, 2.0, 180.0, 0.0, 1013.0), "passive_greenhouse", events)

        shaded = ScenarioRunner().run(scenario(800.0, (ScenarioEvent("shade", "shade", start, start + DAY, shade, {"value": shade, "maximum": 1.0}),)))
        equivalent = ScenarioRunner().run(scenario(800.0 * (1 - shade), ()))
        actuator_fields = {"shading_fraction", "ventilation_fraction", "heating_kw", "cooling_kw"}

        def physical(snapshot: CropSimulationSnapshot) -> dict[str, float]:
            return {key: value for key, value in snapshot.microclimate.indoor_state.to_dict().items() if key not in actuator_fields}

        micro_equal = all(physical(a) == physical(b) and a.environment == b.environment for a, b in zip(shaded.snapshots, equivalent.snapshots))
        crop_equal = all(a.crop == b.crop for a, b in zip(shaded.snapshots, equivalent.snapshots))
        passed = micro_equal and crop_equal and len(shaded.snapshots) == 24
        return {
            "status": _section_status(passed),
            "chain": "actuator -> greenhouse radiation -> microclimate -> crop growth",
            "method": "a 50% shading screen under 800 W m-2 is compared with no screen under 400 W m-2; identical microclimate must give identical crop state",
            "microclimate_identical": micro_equal,
            "compared_microclimate_fields": "all physical MicroclimateState fields and DerivedEnvironmentState; actuator position fields excluded",
            "crop_state_identical": crop_equal,
            "interpretation": "the crop responds only to the resulting microclimate; the actuator has no direct path to biomass",
        }

    def feedback_loop(self, days: int = 7) -> dict[str, Any]:
        start = datetime(2026, 4, 1, tzinfo=UTC)
        engine = WeatherEngine(weather_configuration("warm_season", self.seed))
        # Air exchange is GreenhouseConfiguration.ventilation_ach (structure) plus
        # actuator ventilation; the runs vary the structural exchange only.
        configurations = {
            "ventilated_3ach": (GreenhouseConfiguration(ventilation_ach=3.0), lambda hour: GreenhouseActuatorState()),
            "low_infiltration_0_3ach_co2": (GreenhouseConfiguration(ventilation_ach=0.3), lambda hour: GreenhouseActuatorState(co2_supply_ppm=50.0 if 24 <= hour < 72 else 0.0)),
            "closed_0ach": (GreenhouseConfiguration(ventilation_ach=0.0), lambda hour: GreenhouseActuatorState()),
        }
        runs = {}
        for name, (greenhouse_configuration, actuators) in configurations.items():
            loop = CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel())
            crop = CropGrowthState(start, "tomato", "RAF", "vegetative_growth", biomass_total=100.0, biomass_leaf=60.0, biomass_stem=20.0, biomass_root=20.0, leaf_area_index=1.2, root_depth_m=0.6, soil_water_vwc=0.3, phenology_model="SYNTHETIC_INITIAL_STATE")
            soil = SoilState(0.30, 18.0, 0.35, 0.10, 0.0, 120.0)
            iterations, errors, co2, delta_t, converged, finite = [], [], [], [], 0, True
            latent_at_saturation, reversals, previous_delta = 0, 0, None
            for hour in range(days * 24):
                now = start + timedelta(hours=hour + 1)
                weather = engine.generate(now)
                result = loop.step(crop, weather, greenhouse_configuration, actuators(hour), 3600.0, soil, simulation_time=now)
                micro = result.microclimate
                values = [*micro.to_dict().values(), result.convergence.final_error, *result.crop.to_dict().values()]
                finite = finite and all(math.isfinite(v) for v in values if isinstance(v, float))
                iterations.append(result.convergence.iterations)
                errors.append(result.convergence.final_error)
                converged += int(result.convergence.converged)
                co2.append(micro.co2_ppm)
                delta = micro.temperature_c - weather.temperature_c
                delta_t.append(delta)
                if previous_delta is not None and abs(delta - previous_delta) > 1.0 and len(delta_t) > 2 and (delta - previous_delta) * (delta_t[-2] - delta_t[-3]) < 0:
                    reversals += 1
                previous_delta = delta
                if micro.vpd_kpa <= 1e-9 and result.exchange.latent_heat_flux.value > 0:
                    latent_at_saturation += 1
                crop = result.crop.advance(now, 3600.0)
            steps = days * 24
            daytime_cooling = min(delta_t)
            issues = []
            if converged < steps:
                issues.append({"code": "CONVERGENCE_FAILURE", "severity": "FAILURE", "message": f"{steps - converged} of {steps} steps did not converge"})
            if not finite:
                issues.append({"code": "NUMERICAL_FAILURE", "severity": "FAILURE", "message": "non-finite value in feedback loop"})
            if latent_at_saturation:
                issues.append({"code": "INVARIANT_VIOLATION", "severity": "FAILURE", "message": f"latent heat flux > 0 while indoor VPD = 0 (saturated air) in {latent_at_saturation} steps"})
            conductance = greenhouse_configuration.heat_loss_w_k + AIR_DENSITY_KG_M3 * AIR_SPECIFIC_HEAT_J_KG_K * greenhouse_configuration.volume_m3 * greenhouse_configuration.ventilation_ach / 3600.0
            time_constant_h = greenhouse_configuration.thermal_mass_kj_k * 1000.0 / conductance / 3600.0 if conductance > 0 else math.inf
            if daytime_cooling < -5.0:
                issues.append({"code": "PLAUSIBILITY_REVIEW", "severity": "WARNING", "message": f"indoor air up to {abs(daytime_cooling):.1f} C below outdoor without a cooling actuator (threshold 5 C, {ENGINEERING_TEST_THRESHOLD}); consistent with thermal inertia (tau = C/G = {time_constant_h:.1f} h lags the outdoor diurnal cycle) plus canopy latent cooling, not an energy-conservation violation"})
            failures = [issue for issue in issues if issue["severity"] == "FAILURE"]
            codes = {issue["code"] for issue in failures}
            status = (
                SyntheticValidationStatus.NUMERICAL_FAILURE if "NUMERICAL_FAILURE" in codes else
                SyntheticValidationStatus.INVARIANT_VIOLATION if "INVARIANT_VIOLATION" in codes else
                SyntheticValidationStatus.CONVERGENCE_FAILURE if "CONVERGENCE_FAILURE" in codes else
                SyntheticValidationStatus.PASS_WITH_WARNINGS if issues else SyntheticValidationStatus.PASS
            )
            runs[name] = {
                "status": status.value,
                "steps": steps,
                "converged_steps": converged,
                "max_iterations": max(iterations),
                "configured_max_iterations": loop.configuration.max_iterations,
                "mean_iterations": sum(iterations) / steps,
                "relaxation_alpha": loop.configuration.relaxation_alpha,
                "max_final_error": max(errors),
                "all_finite": finite,
                "temperature_trend_reversals_over_1c": reversals,
                "min_indoor_minus_outdoor_c": daytime_cooling,
                "max_indoor_minus_outdoor_c": max(delta_t),
                "co2_min_ppm": min(co2),
                "co2_max_ppm": max(co2),
                "latent_flux_at_saturation_steps": latent_at_saturation,
                "configured_ventilation_ach": greenhouse_configuration.ventilation_ach,
                "thermal_time_constant_h": time_constant_h,
                "issues": issues,
            }
        co2_run = runs["low_infiltration_0_3ach_co2"]
        memory = self._greenhouse_memory()
        co2_persists = memory["co2_state_carried_between_steps"]
        passed = all(run["status"] in {s.value for s in PASSING_STATUSES} for run in runs.values()) and memory["ventilation_monotonic"] and co2_persists
        return {
            "status": _section_status(passed, warnings=any(run["issues"] for run in runs.values()), failure=SyntheticValidationStatus.INVARIANT_VIOLATION),
            "backend": "SimplifiedGreenhouseModel (PRIMARY/REQUIRED)",
            "loop": "Weather -> Greenhouse -> Microclimate -> Crop -> transpiration/CO2/energy exchange -> Greenhouse (CropGreenhouseFeedbackLoop)",
            "runs": runs,
            "co2_enrichment_peak_ppm": co2_run["co2_max_ppm"],
            "greenhouse_state_memory": memory,
        }

    def _greenhouse_memory(self) -> dict[str, Any]:
        weather = WeatherState(22.0, 60.0, 500.0, 2.0, 180.0, 0.0, 1013.0)
        traces = {}
        for ventilation in (0.3, 1.5, 3.0):
            model = SimplifiedGreenhouseModel()
            prior = None
            trace = []
            for step in range(6):
                state = model.step(weather, GreenhouseConfiguration(ventilation_ach=ventilation), GreenhouseActuatorState(co2_supply_ppm=200.0 if step == 0 else 0.0), CropMicroclimateFeedback(), 3600.0, prior=prior)
                prior = state
                trace.append(state.co2_ppm)
            traces[ventilation] = trace
        distance = [abs(traces[v][1] - 420.0) for v in sorted(traces)]
        return {
            "co2_traces_ppm": {str(k): v for k, v in traces.items()},
            "co2_state_carried_between_steps": traces[0.3][1] > 420.0 + FLOAT_TOLERANCE,
            "ventilation_monotonic": all(a >= b - FLOAT_TOLERANCE for a, b in zip(distance, distance[1:])),
            "definition": "with an explicit prior state, enriched CO2 persists after supply stops and relaxes toward outdoor CO2 faster at higher ventilation (SimplifiedGreenhouseModel exchange term)",
        }

    @staticmethod
    def energyplus() -> dict[str, Any]:
        from agri_twin.infrastructure.energyplus_greenhouse import EnergyPlusGreenhouseModel, detect_energyplus

        availability = detect_energyplus()
        fixture = {"air_temperature_c": 24.0, "relative_humidity_pct": 65.0, "solar_radiation_w_m2": 450.0, "heating_energy_j": 0.0, "cooling_energy_j": 0.0, "co2_ppm": 430.0}
        state = EnergyPlusGreenhouseModel._to_microclimate(fixture, WeatherState(20.0, 60.0, 600.0, 2.0, 180.0, 0.0, 1013.0), GreenhouseActuatorState(), 3600.0)
        return {
            "status": SyntheticValidationStatus.NOT_APPLICABLE.value if availability.status.value != "AVAILABLE" else SyntheticValidationStatus.PASS.value,
            "role": "OPTIONAL/SECONDARY; never ground truth",
            "availability": availability.status.value,
            "detail": availability.detail,
            "integration_run": "not executed: requires an installed EnergyPlus runtime plus configured IDF and weather files",
            "adapter_contract_check": {
                "fixture": "ANALYTIC_ADAPTER_FIXTURE (not an EnergyPlus run)",
                "produces_microclimate_state": type(state).__name__ == "MicroclimateState",
                "vpd_kpa": state.vpd_kpa,
            },
        }

    # -- integration with earlier phases -------------------------------------------

    def integration_suites(self) -> tuple[dict[str, Any], dict[str, Any]]:
        from agri_twin.application.transferability_robustness import TransferabilityRobustnessSuite

        suite = TransferabilityRobustnessSuite(self.root, registry=self.registry)
        robustness = {}
        for environment in ("GREENHOUSE", "OUTDOOR"):
            results = suite.evaluate_robustness_suite(crop="tomato", environment=environment)
            robustness[environment] = [{"case_id": r.case_id, "passed": r.passed, "software_stability": r.software_stability, "physical_bounds_valid": r.physical_bounds_valid, "convergence": r.convergence} for r in results]
        all_cases = [case for cases in robustness.values() for case in cases]
        sources = suite.audit_sources()
        real_verified = sum(1 for source in sources if source.classification.value == "REAL_VERIFIED")
        readiness = suite.readiness()
        calibration = suite.calibration_report()
        post = suite.post_calibration_report()
        robustness_section = {
            "status": _section_status(all(case["passed"] for case in all_cases) and len(robustness["GREENHOUSE"]) == 12),
            "source": "Phase 5.22 ParameterSensitivityAnalyzer.analyze_robustness via Phase 5.28 TransferabilityRobustnessSuite.evaluate_robustness_suite",
            "cases_per_environment": {key: len(value) for key, value in robustness.items()},
            "passed": sum(case["passed"] for case in all_cases),
            "total": len(all_cases),
            "results": robustness,
        }
        transferability = {
            "status": SyntheticValidationStatus.DATA_INSUFFICIENT.value if real_verified == 0 else readiness.value,
            "readiness": readiness.value,
            "real_verified_sources": real_verified,
            "audited_sources": len(sources),
            "calibration_performed": bool(calibration.get("calibration_performed", False)),
            "post_calibration_validation_performed": bool(post.get("validation_performed", False)),
            "interpretation": "transferability/generalization remain not assessable scientifically without REAL_VERIFIED observations; synthetic integrated validation does not change this",
        }
        return robustness_section, transferability

    # -- mutation guard -----------------------------------------------------------

    def _mutation_fingerprint(self) -> dict[str, str]:
        files = sorted([*(self.root / "src").glob("*.json"), *(self.root / "src").glob("*.csv"), *(self.root / "config").glob("*.json")])
        return {
            "parameter_registry": _hash([record.to_dict() for record in self.registry.records]),
            "parameter_set_tomato": _hash(ParameterSet.from_registry(self.registry, crop="tomato").value_map()),
            "configuration_files": _hash({path.relative_to(self.root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}),
        }

    # -- report -------------------------------------------------------------------

    def configuration(self, cases: Sequence[SyntheticValidationCase]) -> dict[str, Any]:
        return {
            "version": VERSION,
            "seed": self.seed,
            "crops": list(self.crops),
            "include_extended": self.include_extended,
            "include_integration_suites": self.include_integration_suites,
            "timestep_seconds": 3600,
            "climate_profiles": {key: dict(value) for key, value in CLIMATE_PROFILES.items()},
            "crop_climate": {crop: CROP_CLIMATE[crop] for crop in self.crops},
            "baseline_irrigation_mm_h": BASELINE_IRRIGATION_MM_H,
            "dormancy_chilling": {"temperature_c": DORMANCY_CHILLING_TEMPERATURE_C, "days": DORMANCY_DAYS, "event": "ScenarioEvent cold"},
            "float_tolerance": FLOAT_TOLERANCE,
            "invariants": dict(INVARIANT_DEFINITIONS),
            "scenarios": [case.scenario.definition_dict() for case in cases],
        }

    def build_report(self) -> SyntheticValidationReport:
        started = time.perf_counter()
        before = self._mutation_fingerprint()
        cases = self.cases()
        results, raw = self.run_cases(cases)
        by_id = {case.case_id: case for case in cases}
        sections: dict[str, Any] = {}
        timer = time.perf_counter()
        sections["determinism"] = self.determinism(cases, {result.case_id: result.trajectory_hash for result in results})
        self._timings["determinism_seconds"] = time.perf_counter() - timer
        timer = time.perf_counter()
        restart_ids = [case_id for case_id in ("p529_tomato_outdoor_water_stress_recovery", "p529_plum_outdoor_normal_season", "p529_tomato_greenhouse_greenhouse_co2") if case_id in by_id]
        restarts = [self.restart_equivalence(by_id[case_id], raw[case_id]) for case_id in restart_ids]
        sections["restart"] = {"status": _section_status(bool(restarts) and all(item["status"] == "PASS" for item in restarts), failure=SyntheticValidationStatus.NON_DETERMINISTIC), "cases": restarts}
        self._timings["restart_seconds"] = time.perf_counter() - timer
        persistence_id = next(case.case_id for case in cases if case.scenario.kind is SyntheticScenarioKind.NORMAL_SEASON)
        sections["persistence"] = self.persistence(by_id[persistence_id], raw[persistence_id])
        timer = time.perf_counter()
        sections["multi_plot"] = self.multi_plot()
        sections["multi_cycle"] = self.multi_cycle()
        self._timings["multi_plot_cycle_seconds"] = time.perf_counter() - timer
        timer = time.perf_counter()
        sections["greenhouse"] = {
            "actuator_causal_path": self.actuator_causal_path(),
            "crop_greenhouse_feedback": self.feedback_loop(),
            "energyplus": self.energyplus(),
        }
        self._timings["greenhouse_seconds"] = time.perf_counter() - timer
        invariant_totals: dict[str, int] = {name: 0 for name in INVARIANT_DEFINITIONS}
        for result in results:
            for metric in result.metrics:
                if metric.name.startswith("invariant."):
                    invariant_totals[metric.name.split(".")[1]] += int(metric.value or 0)
        sections["invariant_results"] = {"status": _section_status(not any(invariant_totals.values()), failure=SyntheticValidationStatus.INVARIANT_VIOLATION), "violations_by_invariant": invariant_totals, "definitions": dict(INVARIANT_DEFINITIONS)}
        if self.include_integration_suites:
            timer = time.perf_counter()
            sections["robustness"], sections["transferability"] = self.integration_suites()
            self._timings["integration_suites_seconds"] = time.perf_counter() - timer
        sections["static_audit"] = static_audit(self.root)
        after = self._mutation_fingerprint()
        sections["mutation"] = {
            "status": _section_status(before == after, failure=SyntheticValidationStatus.INVARIANT_VIOLATION),
            "before": before,
            "after": after,
            "parameter_registry_unchanged": before["parameter_registry"] == after["parameter_registry"],
            "parameter_set_unchanged": before["parameter_set_tomato"] == after["parameter_set_tomato"],
            "configuration_files_unchanged": before["configuration_files"] == after["configuration_files"],
            "twin_state_repository": "every run uses an isolated InMemoryTwinStateRepository; TwinState is a frozen dataclass",
            "calibration_performed": False,
        }
        coverage = self._coverage(results)
        findings = self._findings(results, sections)
        summary = self._summary(results, sections, coverage)
        configuration = self.configuration(cases)
        self._timings["total_seconds"] = time.perf_counter() - started
        execution = {"timings_seconds": dict(self._timings), "cases": len(results), "note": "wall-clock durations for regression tracking only; excluded from hashes and from the canonical JSON"}
        return SyntheticValidationReport(VERSION, configuration, results, sections, coverage, findings, summary, _hash(configuration), execution)

    def _coverage(self, results: Sequence[SyntheticValidationResult]) -> tuple[dict[str, Any], ...]:
        rows = []
        for crop in self.crops:
            crop_results = [result for result in results if result.scenario.crop == crop]

            def cell(predicate: Callable[[SyntheticValidationResult], bool]) -> str:
                matching = [result for result in crop_results if predicate(result)]
                if not matching:
                    return SyntheticValidationStatus.NOT_APPLICABLE.value
                return SyntheticValidationStatus.PASS.value if all(r.status in PASSING_STATUSES for r in matching) else next(r.status.value for r in matching if r.status not in PASSING_STATUSES)

            rows.append({
                "crop": crop,
                "variety": _variety_for(crop),
                "life_cycle": "perennial" if crop in PERENNIAL_CROPS else "annual",
                "outdoor": cell(lambda r: r.scenario.environment == "outdoor"),
                "greenhouse": cell(lambda r: r.scenario.environment == "greenhouse") if crop in ANNUAL_CROPS else "NOT_APPLICABLE (not configured for perennial crops)",
                "stress": cell(lambda r: r.scenario.kind in {SyntheticScenarioKind.WATER_STRESS_RECOVERY, SyntheticScenarioKind.HEAT_WAVE_RECOVERY}),
                "recovery": cell(lambda r: r.scenario.kind in {SyntheticScenarioKind.WATER_STRESS_RECOVERY, SyntheticScenarioKind.HEAT_WAVE_RECOVERY}),
                "full_cycle": cell(lambda r: r.scenario.kind is SyntheticScenarioKind.NORMAL_SEASON),
                "variety_parameters": self.variety_resolution(crop, _variety_for(crop))["resolution"],
            })
        return tuple(rows)

    @staticmethod
    def _findings(results: Sequence[SyntheticValidationResult], sections: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
        findings: list[dict[str, Any]] = []
        warning_codes: dict[str, list[str]] = {}
        for result in results:
            for issue in result.warnings:
                warning_codes.setdefault(issue.code, []).append(result.case_id)
        for code, cases in sorted(warning_codes.items()):
            findings.append({"code": code, "type": "mechanistic", "severity": "WARNING", "cases": cases, "description": next(issue.message for result in results for issue in result.warnings if issue.code == code), "action": "open; documented"})
        feedback = sections["greenhouse"]["crop_greenhouse_feedback"]["runs"]
        for name, run in feedback.items():
            for issue in run["issues"]:
                severity = issue["severity"]
                findings.append({"code": "OPEN_PHYSICAL_ISSUE" if severity == "FAILURE" else issue["code"], "type": "greenhouse_feedback", "severity": severity, "cases": [name], "description": issue["message"], "action": "open; requires physical analysis before qualification"})
        # Documented limitations of the corrected (Phase 5.30) model; not defects.
        for code, description in (
            ("CO2_RESPONSE_CAPPED_AT_REFERENCE", "CropGrowthEngine.co2_response = min(1, CO2 / 420): depletion limits growth, enrichment above 420 ppm gives no benefit (existing engineering response, not extended)."),
            ("ORCHESTRATOR_EXCHANGE_NOT_ITERATED", "CropDigitalTwinOrchestrator feeds only LAI back to the greenhouse; transpiration/CO2-uptake coupling is iterated only in CropGreenhouseFeedbackLoop."),
            ("PERENNIAL_NEXT_CAMPAIGN_NOT_SUPPORTED", "No transition from post_harvest_dormancy back to dormancy/establishment exists in PhenologyEngine."),
            ("CONDENSATION_LATENT_HEAT_NEGLECTED", "Vapour above saturation condenses without releasing latent heat to the air; no longwave radiative exchange is modelled."),
        ):
            findings.append({"code": code, "type": "limitation", "severity": "INFO", "cases": [], "description": description, "action": "documented limitation"})
        return tuple(findings)

    def _summary(self, results: Sequence[SyntheticValidationResult], sections: Mapping[str, Any], coverage: Sequence[Mapping[str, Any]]) -> IntegratedValidationSummary:
        counts: dict[str, int] = {}
        for result in results:
            counts[result.status.value] = counts.get(result.status.value, 0) + 1
        passing = {status.value for status in PASSING_STATUSES}
        section_status = {name: value["status"] for name, value in sections.items() if isinstance(value, Mapping) and "status" in value}
        section_status["greenhouse.actuator_causal_path"] = sections["greenhouse"]["actuator_causal_path"]["status"]
        section_status["greenhouse.crop_greenhouse_feedback"] = sections["greenhouse"]["crop_greenhouse_feedback"]["status"]
        section_status["greenhouse.energyplus"] = sections["greenhouse"]["energyplus"]["status"]
        cases_ok = all(result.status in PASSING_STATUSES for result in results)

        def qualified(ok: bool) -> str:
            return "QUALIFIED" if ok else "NOT_QUALIFIED"

        greenhouse_cases_ok = all(result.status in PASSING_STATUSES for result in results if result.scenario.environment == "greenhouse")
        feedback_ok = section_status["greenhouse.crop_greenhouse_feedback"] in passing
        coupling_ok = greenhouse_cases_ok and section_status["greenhouse.actuator_causal_path"] in passing
        perennial_normal = [result for result in results if result.scenario.perennial and result.scenario.kind is SyntheticScenarioKind.NORMAL_SEASON]
        dormancy_ok = bool(perennial_normal) and all(result.status is SyntheticValidationStatus.PASS for result in perennial_normal)

        def physical(ok: bool) -> str:
            return "QUALIFIED" if ok else "OPEN_PHYSICAL_ISSUE"
        qualification = {
            "INTEGRATED_SYNTHETIC_VALIDATION": "READY",
            "SYNTHETIC_MODEL_CONSISTENCY": qualified(cases_ok and section_status["invariant_results"] in passing),
            "TEMPORAL_CONTINUITY": qualified(section_status["restart"] in passing and sections["invariant_results"]["violations_by_invariant"]["time_continuity"] == 0),
            "PERSISTENT_STATE_CONSISTENCY": qualified(section_status["persistence"] in passing),
            "MULTI_PLOT_CONSISTENCY": qualified(section_status["multi_plot"] in passing),
            "MULTI_CYCLE_CONSISTENCY": qualified(section_status["multi_cycle"] in passing),
            "GREENHOUSE_CROP_INTEGRATION": physical(coupling_ok and feedback_ok),
            "MICROCLIMATE_TO_CROP_COUPLING": physical(coupling_ok),
            "FEEDBACK_LOOP": physical(feedback_ok),
            "DORMANCY_PHENOLOGY_CONSISTENCY": physical(dormancy_ok) if perennial_normal else "NOT_EVALUATED",
            "ROBUSTNESS_SCENARIOS": qualified(section_status.get("robustness") in passing) if "robustness" in sections else "NOT_EVALUATED",
            "DETERMINISM": qualified(section_status["determinism"] in passing),
            "STATIC_AUDIT": qualified(section_status["static_audit"] in passing),
            "PARAMETER_IMMUTABILITY": qualified(section_status["mutation"] in passing),
        }
        transferability = sections.get("transferability", {})
        scientific = {
            "REAL_VERIFIED": transferability.get("real_verified_sources", 0),
            "REAL_AGRICULTURAL_DATA_VERIFIED": False,
            "CALIBRATION_PERFORMED": False,
            "EXPERIMENTAL_VALIDATION_PERFORMED": False,
            "DATA_ASSIMILATION_IMPLEMENTED": False,
            "BIOLOGICAL_VALIDITY_CLAIMED": False,
            "FIELD_ACCURACY_CLAIMED": False,
            "SCIENTIFIC_EXPERIMENTAL_VALIDATION": "DEFERRED_TO_FINAL_VALIDATION_STAGE",
            "scientific_validation_status": SyntheticValidationStatus.DATA_INSUFFICIENT.value,
        }
        return IntegratedValidationSummary(
            len(results), dict(sorted(counts.items())),
            tuple(sorted({result.scenario.crop for result in results})),
            tuple(sorted({result.scenario.variety for result in results})),
            tuple(sorted({result.scenario.environment for result in results})),
            tuple(sorted({result.scenario.kind.value for result in results})),
            dict(sorted(section_status.items())), qualification, scientific,
        )

    def write_report(self, report: SyntheticValidationReport, directory: str | Path | None = None) -> tuple[Path, Path]:
        output = Path(directory) if directory is not None else self.root / "data" / "validation"
        output.mkdir(parents=True, exist_ok=True)
        report_path = output / "integrated_synthetic_validation_report.json"
        readme_path = output / "integrated_synthetic_validation_README.md"
        payload = report.to_dict()
        report_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        summary = report.summary
        lines = [
            "# Integrated synthetic validation (Phase 5.29)",
            "",
            "Deterministic `SYNTHETIC_INTEGRATED_VALIDATION` artifact. It qualifies software and model consistency under controlled synthetic scenarios.",
            "It does not establish biological validity, field validity, experimental accuracy or transferability to real agricultural systems.",
            "",
            f"- version: `{report.version}`",
            f"- configuration hash: `{report.configuration_hash}`",
            f"- report hash: `{payload['report_hash']}`",
            f"- cases: `{summary.total_cases}`; status counts: `{json.dumps(summary.status_counts, sort_keys=True)}`",
            f"- REAL_VERIFIED: `{summary.scientific_status['REAL_VERIFIED']}`; calibration performed: `false`; experimental validation performed: `false`",
            "",
            "## Qualification",
            "",
            *[f"- {name}: `{value}`" for name, value in summary.qualification.items()],
            "",
            "## Open findings",
            "",
            *[f"- `{finding['code']}` ({finding['severity']}): {finding['description']}" for finding in report.findings],
            "",
        ]
        readme_path.write_text("\n".join(lines), encoding="utf-8")
        return report_path, readme_path


def _max_difference(first: Mapping[str, float], second: Mapping[str, float]) -> float:
    if first.keys() != second.keys():
        return math.inf
    return max(abs(value - second[key]) for key, value in first.items())


def _stage_entries(snapshots: Sequence[CropSimulationSnapshot]) -> dict[str, str]:
    entries: dict[str, str] = {}
    for snapshot in snapshots:
        entries.setdefault(snapshot.crop.current_stage, snapshot.simulation_time.isoformat())
    return entries


def _compress(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if not result or result[-1] != value:
            result.append(value)
    return result


__all__ = [
    "BEHAVIOURS",
    "CLIMATE_PROFILES",
    "ENGINEERING_TEST_THRESHOLD",
    "INVARIANT_DEFINITIONS",
    "IntegratedSyntheticValidationSuite",
    "IntegratedValidationSummary",
    "SOURCE_TYPE",
    "SyntheticScenarioKind",
    "SyntheticValidationCase",
    "SyntheticValidationIssue",
    "SyntheticValidationMetric",
    "SyntheticValidationReport",
    "SyntheticValidationResult",
    "SyntheticValidationScenario",
    "SyntheticValidationStatus",
    "VALIDATION_KIND",
    "ValidationCategory",
    "VarietyParameterResolution",
    "build_scenario",
    "checkpoint_payload",
    "default_cases",
    "restore_checkpoint",
    "resumed_scenario",
    "snapshot_numbers",
    "static_audit",
    "synthetic_weather_factory",
    "trajectory_hash",
    "twin_state_from_snapshot",
    "validate_trajectory",
    "weather_configuration",
]
