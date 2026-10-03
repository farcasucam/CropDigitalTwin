"""Interactive simulation API and execution contract (Phase 5.37).

A thin application layer between a future frontend and the existing twin:

    frontend -> InteractiveSimulationService -> build_campaign / ScenarioRunner
             -> CropDigitalTwinOrchestrator -> existing engines

It validates and canonicalizes a request, resolves crop / environment / scenario /
weather / dormancy from the existing configurations, creates an isolated execution,
delegates to ``ScenarioRunner`` (one SimulationClock per run, created by the runner),
exposes operational progress, cooperative cancellation and checkpoint / resume
(the existing Phase 5.29 ``checkpoint_payload`` format), and returns serializable,
deterministic results. It adds no equation, engine, clock, scheduler, registry,
weather generator or scientific state representation: trajectories are the
orchestrator's snapshots and the observable state is the existing ``TwinState``.

The API layer reads no clock: operational timings exist only when the caller injects a
timer (Phase 5.36 keeps timing instrumentation out of src); they never enter a hash.
Every result is a software simulation under synthetic forcing: no real data,
calibration, experimental validation or biological validity is claimed.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from agri_twin.application.integrated_synthetic_validation import (
    SINGLETON_CLASSES,
    checkpoint_payload,
    restore_checkpoint,
    resumed_scenario,
    static_audit,
    trajectory_hash,
    twin_state_from_snapshot,
)
from agri_twin.application.orchestrator import CropSimulationSnapshot
from agri_twin.application.providers import SyntheticWeatherProvider
from agri_twin.application.scenarios import Scenario, ScenarioError, ScenarioRunner
from agri_twin.application.scientific_benchmark import KNOWN_CROPS, KNOWN_VARIETIES, PERENNIAL_CROPS
from agri_twin.application.seasonal_synthetic_campaign import (
    ANNUAL_GREENHOUSE_CROPS,
    BASE_PROFILE,
    DEFAULT_SEED,
    IRRIGATION_FACTOR,
    MANDATORY_SCENARIOS,
    PROFILE_SHIFTS,
    SUPPLEMENTARY_SCENARIOS,
    TIMESTEP_SECONDS,
    CampaignSpec,
    build_campaign,
    campaign_cycle,
    climate_profile,
    seasonal_weather_factory,
    weather_configuration,
)
from agri_twin.application.synthetic_dataset import SyntheticReferenceDatasetGenerator
from agri_twin.application.twin_state import TwinState
from agri_twin.application.weather import WeatherEngine
from agri_twin.domain.calibration import ParameterSet
from agri_twin.domain.greenhouse import PROFILES as GREENHOUSE_PROFILES
from agri_twin.domain.greenhouse import GreenhouseConfiguration
from agri_twin.domain.parameter_audit import ParameterRegistry
from agri_twin.domain.phenology import (
    APPROXIMATE_PROFILES,
    DEFAULT_DORMANCY_CONFIGURATION,
    MODEL_SPECS,
    ChillingModelType,
    DormancyChillingController,
    DormancyConfiguration,
    PhenologyEngine,
    PhenologyError,
    canonicalize_dormancy_configuration,
)

UTC = timezone.utc
VERSION = "5.37.0"
API_VERSION = "1.0"
CHECKPOINT_FORMAT = "agri_twin.checkpoint_payload/5.29"
DEFAULT_SCENARIO = "BASE_SEASON"
SCENARIOS = (*MANDATORY_SCENARIOS, *SUPPLEMENTARY_SCENARIOS)
ENVIRONMENTS = {"outdoor": "outdoor", "greenhouse": "passive_greenhouse"}  # API name -> orchestrator greenhouse_mode
WEATHER_SOURCES = ("SYNTHETIC_SEASONAL",)
WEATHER_GENERATOR = "WeatherEngine(seasonal + daily variability, seeded) + ScenarioEvent overlays (Phase 5.32)"
REQUEST_FIELDS = ("api_version", "crop", "variety", "environment", "plot", "scenario", "start_time", "end_time", "seed", "weather", "dormancy", "checkpoint", "options")
WEATHER_FIELDS = ("source", "profile_overrides")
OPTION_FIELDS = ("progress_interval_steps", "require_requested_chilling_model", "include_trajectory", "compute_trajectory_hash", "variables")
CHECKPOINT_FIELDS = ("format", "simulation_time", "payload", "sha256", "resume_hash")
DEFAULT_PROGRESS_INTERVAL_STEPS = 24  # one simulated day of hourly steps

# Advisory cost model for the execution-mode decision (no simulation is run to decide).
# Upper single-plot cost per hourly step measured by the Phase 5.36 audit
# (0.40-0.47 ms/step, the Phase 5.36 performance report under data/performance); machine-dependent.
COST_MODEL: Mapping[str, Any] = {
    "seconds_per_plot_step": 0.00047,
    "source": "Phase 5.36 performance audit, upper single-plot cost per hourly step (0.40-0.47 ms)",
    "interactive_max_seconds": 1.0,
    "interactive_with_progress_max_seconds": 10.0,
    "status": "ADVISORY_PERFORMANCE_MEASUREMENT (machine-dependent, not a contract)",
}

SCIENTIFIC_STATUS: Mapping[str, Any] = {
    "result_type": "SOFTWARE_SIMULATION",
    "forcing_classification": "SYNTHETIC",
    "REAL_VERIFIED": 0,
    "CALIBRATION_PERFORMED": False,
    "EXPERIMENTAL_VALIDATION_PERFORMED": False,
    "BIOLOGICAL_VALIDITY_CLAIMED": False,
    "FIELD_ACCURACY_CLAIMED": False,
    "DATA_ASSIMILATION_IMPLEMENTED": False,
    "parameter_status": "ENGINEERING_DEFAULTS_UNCALIBRATED",
    "statement": "Deterministic output of the implemented mechanistic-simplified model under synthetic forcing; "
                 "software behaviour only, not a prediction, calibration or validated agronomic result.",
}


def _hash(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


# ---------------------------------------------------------------------------
# Enumerations and the structured error model
# ---------------------------------------------------------------------------


class ExecutionStatus(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


TERMINAL_STATUSES = frozenset({ExecutionStatus.COMPLETED, ExecutionStatus.CANCELLED, ExecutionStatus.FAILED})


class ExecutionMode(StrEnum):
    INTERACTIVE = "INTERACTIVE"
    INTERACTIVE_WITH_PROGRESS = "INTERACTIVE_WITH_PROGRESS"
    BACKGROUND = "BACKGROUND"


class Availability(StrEnum):
    AVAILABLE = "AVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_SUPPORTED = "NOT_SUPPORTED"


class ErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    UNSUPPORTED_CROP = "UNSUPPORTED_CROP"
    UNSUPPORTED_ENVIRONMENT = "UNSUPPORTED_ENVIRONMENT"
    INVALID_TIME_RANGE = "INVALID_TIME_RANGE"
    INVALID_SCENARIO = "INVALID_SCENARIO"
    INVALID_CHECKPOINT = "INVALID_CHECKPOINT"
    MODEL_NOT_READY = "MODEL_NOT_READY"
    CANCELLATION_REQUESTED = "CANCELLATION_REQUESTED"
    INTERNAL_EXECUTION_ERROR = "INTERNAL_EXECUTION_ERROR"


# Error category keeps operational and software errors apart from model statements.
ERROR_CATEGORY = {
    ErrorCode.INVALID_REQUEST: "REQUEST", ErrorCode.INVALID_CONFIGURATION: "CONFIGURATION", ErrorCode.UNSUPPORTED_CROP: "CONFIGURATION",
    ErrorCode.UNSUPPORTED_ENVIRONMENT: "CONFIGURATION", ErrorCode.INVALID_TIME_RANGE: "REQUEST", ErrorCode.INVALID_SCENARIO: "CONFIGURATION",
    ErrorCode.INVALID_CHECKPOINT: "REQUEST", ErrorCode.MODEL_NOT_READY: "CONFIGURATION", ErrorCode.CANCELLATION_REQUESTED: "OPERATIONAL",
    ErrorCode.INTERNAL_EXECUTION_ERROR: "EXECUTION",
}


@dataclass(frozen=True, slots=True)
class SimulationError:
    code: ErrorCode
    message: str
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code.value, "category": ERROR_CATEGORY[self.code], "message": self.message, "path": self.path}


class SimulationApiError(ValueError):
    """Structured API error: one or more ``SimulationError`` with stable codes."""

    def __init__(self, errors: Sequence[SimulationError]) -> None:
        self.errors = tuple(errors)
        super().__init__("; ".join(f"{error.code.value}{f' at {error.path}' if error.path else ''}: {error.message}" for error in self.errors))

    @property
    def code(self) -> ErrorCode:
        return self.errors[0].code

    def to_dict(self) -> dict[str, Any]:
        return {"errors": [error.to_dict() for error in self.errors]}


def _fail(code: ErrorCode, message: str, path: str | None = None) -> SimulationApiError:
    return SimulationApiError((SimulationError(code, message, path),))


@dataclass(frozen=True, slots=True)
class SimulationWarning:
    category: str  # CONFIGURATION | SOFTWARE | MODEL_BEHAVIOR (never biological evidence)
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"category": self.category, "code": self.code, "message": self.message}


# ---------------------------------------------------------------------------
# Result variable catalogue (projection of existing snapshot fields only)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VariableSpec:
    name: str
    unit: str
    source: str
    description: str
    scope: str = "ALL"  # ALL | GREENHOUSE | PERENNIAL | NONE
    getter: Callable[[CropSimulationSnapshot], Any] | None = field(default=None, compare=False, repr=False)
    reason: str | None = None


def _water(name: str) -> Callable[[CropSimulationSnapshot], float]:
    return lambda s: getattr(s.water_balance, name)


VARIABLES: tuple[VariableSpec, ...] = (
    VariableSpec("crop_stage", "-", "crop.current_stage", "phenological stage", getter=lambda s: s.crop.current_stage),
    VariableSpec("maturity_index", "fraction", "crop.maturity_index", "maturity index", getter=lambda s: s.crop.maturity_index),
    VariableSpec("biomass_total_g_m2", "g_DM_m-2", "crop.biomass_total", "total dry biomass", getter=lambda s: s.crop.biomass_total),
    VariableSpec("biomass_fruit_g_m2", "g_DM_m-2", "crop.biomass_fruit", "fruit dry biomass", getter=lambda s: s.crop.biomass_fruit),
    VariableSpec("leaf_area_index", "m2_m-2", "crop.leaf_area_index", "leaf area index", getter=lambda s: s.crop.leaf_area_index),
    VariableSpec("soil_water_vwc_m3_m3", "m3_m-3", "soil.vwc_m3_m3", "root-zone volumetric water content", getter=lambda s: s.soil.vwc_m3_m3),
    VariableSpec("root_zone_water_mm", "mm", "soil.root_zone_water", "root-zone water storage", getter=lambda s: s.soil.root_zone_water),
    VariableSpec("irrigation_mm", "mm_per_step", "water_balance.irrigation_applied_mm", "irrigation applied in the step", getter=_water("irrigation_applied_mm")),
    VariableSpec("precipitation_mm", "mm_per_step", "water_balance.precipitation_mm", "precipitation reaching the crop in the step (0 indoors)", getter=_water("precipitation_mm")),
    VariableSpec("drainage_mm", "mm_per_step", "water_balance.drainage_mm", "drainage in the step", getter=_water("drainage_mm")),
    VariableSpec("transpiration_mm", "mm_per_step", "water_balance.transpiration_mm", "crop transpiration in the step", getter=_water("transpiration_mm")),
    VariableSpec("evaporation_mm", "mm_per_step", "water_balance.evaporation_mm", "soil evaporation in the step", getter=_water("evaporation_mm")),
    VariableSpec("et0_mm", "mm_per_step", "water_balance.et0_mm", "reference evapotranspiration in the step", getter=_water("et0_mm")),
    VariableSpec("temperature_c", "degC", "weather.temperature_c", "air temperature experienced by the crop (indoor in greenhouse modes)", getter=lambda s: s.weather.temperature_c),
    VariableSpec("relative_humidity_pct", "%", "weather.relative_humidity_pct", "relative humidity experienced by the crop", getter=lambda s: s.weather.relative_humidity_pct),
    VariableSpec("vpd_kpa", "kPa", "environment.vpd_kpa", "vapour pressure deficit of the crop environment", getter=lambda s: s.environment.vpd_kpa),
    VariableSpec("radiation_w_m2", "W_m-2", "weather.solar_radiation_w_m2", "solar radiation reaching the crop", getter=lambda s: s.weather.solar_radiation_w_m2),
    VariableSpec("water_stress", "fraction", "crop.water_stress", "water stress", getter=lambda s: s.crop.water_stress),
    VariableSpec("heat_stress", "fraction", "crop.heat_stress", "heat stress", getter=lambda s: s.crop.heat_stress),
    VariableSpec("cold_stress", "fraction", "crop.cold_stress", "cold stress", getter=lambda s: s.crop.cold_stress),
    VariableSpec("vpd_stress", "fraction", "crop.vpd_stress", "VPD stress", getter=lambda s: s.crop.vpd_stress),
    VariableSpec("radiation_stress", "fraction", "crop.radiation_stress", "radiation stress", getter=lambda s: s.crop.radiation_stress),
    VariableSpec("frost_damage", "fraction", "crop.frost_damage", "frost damage", getter=lambda s: s.crop.frost_damage),
    VariableSpec("accumulated_stress", "-", "crop.accumulated_stress", "accumulated stress", getter=lambda s: s.crop.accumulated_stress),
    VariableSpec("growth_factor", "fraction", "snapshot.growth_factor", "combined growth limitation factor of the step", getter=lambda s: s.growth_factor),
    VariableSpec("co2_ppm", "ppm", "microclimate.indoor_state.co2_ppm", "greenhouse air CO2", "GREENHOUSE", lambda s: s.microclimate.indoor_state.co2_ppm,
                 "outdoor runs do not simulate a CO2 state"),
    VariableSpec("outdoor_temperature_c", "degC", "outdoor_weather.temperature_c", "outdoor air temperature outside the greenhouse", "GREENHOUSE",
                 lambda s: s.outdoor_weather.temperature_c, "outdoor runs: the crop temperature is the outdoor temperature"),
    VariableSpec("greenhouse_ventilation_fraction", "fraction", "microclimate.indoor_state.ventilation_fraction", "greenhouse ventilation opening", "GREENHOUSE",
                 lambda s: s.microclimate.indoor_state.ventilation_fraction, "no greenhouse in outdoor runs"),
    VariableSpec("greenhouse_shading_fraction", "fraction", "microclimate.indoor_state.shading_fraction", "greenhouse shading", "GREENHOUSE",
                 lambda s: s.microclimate.indoor_state.shading_fraction, "no greenhouse in outdoor runs"),
    VariableSpec("greenhouse_heating_kw", "kW", "microclimate.indoor_state.heating_kw", "greenhouse heating power", "GREENHOUSE",
                 lambda s: s.microclimate.indoor_state.heating_kw, "no greenhouse in outdoor runs"),
    VariableSpec("greenhouse_cooling_kw", "kW", "microclimate.indoor_state.cooling_kw", "greenhouse cooling power", "GREENHOUSE",
                 lambda s: s.microclimate.indoor_state.cooling_kw, "no greenhouse in outdoor runs"),
    VariableSpec("dormancy_released", "bool", "crop.dormancy_released", "endodormancy released", "PERENNIAL", lambda s: s.crop.dormancy_released,
                 "annual crops have no endodormancy"),
    VariableSpec("chilling_accumulated", "effective chilling model unit", "crop.chilling_hours | crop.chilling_state.accumulated",
                 "chill accumulated by the effective chilling model (unit in the effective configuration)", "PERENNIAL",
                 lambda s: s.crop.chilling_state.accumulated if s.crop.chilling_state is not None else s.crop.chilling_hours,
                 "annual crops have no endodormancy"),
    VariableSpec("canopy_temperature_c", "degC", "-", "canopy / leaf temperature", "NONE", reason="not represented by the current model; no value is fabricated"),
    VariableSpec("photosynthesis_rate_umol_m2_s", "umol_m-2_s-1", "-", "instantaneous leaf photosynthesis", "NONE",
                 reason="the model uses radiation-use efficiency, not a photosynthesis state; no value is fabricated"),
    VariableSpec("fruit_count", "count_m-2", "-", "number of fruits", "NONE", reason="not represented by the current model; no value is fabricated"),
    VariableSpec("leaf_water_potential_mpa", "MPa", "-", "leaf water potential", "NONE", reason="not represented by the current model; no value is fabricated"),
)
VARIABLE_INDEX = {spec.name: spec for spec in VARIABLES}
FLUX_TOTALS = ("irrigation_mm", "precipitation_mm", "drainage_mm", "transpiration_mm", "evaporation_mm", "et0_mm")


def variable_availability(spec: VariableSpec, crop: str, environment: str) -> Availability:
    if spec.scope == "NONE":
        return Availability.NOT_SUPPORTED
    if spec.scope == "GREENHOUSE" and environment != "greenhouse":
        return Availability.NOT_APPLICABLE
    if spec.scope == "PERENNIAL" and crop not in PERENNIAL_CROPS:
        return Availability.NOT_APPLICABLE
    return Availability.AVAILABLE


# ---------------------------------------------------------------------------
# Canonical request
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExecutionOptions:
    progress_interval_steps: int | None = None  # None: derived from the execution mode
    require_requested_chilling_model: bool = False
    include_trajectory: bool = True
    compute_trajectory_hash: bool = True
    variables: tuple[str, ...] | None = None  # None: whole catalogue

    def to_dict(self) -> dict[str, Any]:
        return {"progress_interval_steps": self.progress_interval_steps, "require_requested_chilling_model": self.require_requested_chilling_model,
                "include_trajectory": self.include_trajectory, "compute_trajectory_hash": self.compute_trajectory_hash,
                "variables": list(self.variables) if self.variables is not None else None}


@dataclass(frozen=True, slots=True)
class SimulationCheckpoint:
    """API wrapper around the existing Phase 5.29 checkpoint payload (format unchanged)."""

    format: str
    simulation_time: datetime
    payload: str
    sha256: str
    resume_hash: str

    @classmethod
    def from_snapshot(cls, snapshot: CropSimulationSnapshot, resume_hash: str) -> "SimulationCheckpoint":
        payload = checkpoint_payload(snapshot)
        return cls(CHECKPOINT_FORMAT, snapshot.simulation_time, payload, hashlib.sha256(payload.encode("utf-8")).hexdigest(), resume_hash)

    def to_dict(self) -> dict[str, Any]:
        return {"format": self.format, "simulation_time": self.simulation_time.isoformat(), "payload": self.payload, "sha256": self.sha256, "resume_hash": self.resume_hash}


@dataclass(frozen=True, slots=True)
class SimulationRequest:
    """Canonical, validated simulation request. Build it with ``canonicalize_request``."""

    crop: str
    variety: str
    environment: str
    plot: str
    scenario: str
    start_time: datetime
    end_time: datetime
    seed: int
    weather_source: str
    profile_overrides: tuple[tuple[str, float], ...]
    dormancy: DormancyConfiguration
    checkpoint: SimulationCheckpoint | None = None
    options: ExecutionOptions = ExecutionOptions()
    api_version: str = API_VERSION

    @property
    def total_steps(self) -> int:
        return int((self.end_time - self.start_time).total_seconds()) // TIMESTEP_SECONDS

    def weather_dict(self) -> dict[str, Any]:
        return {"source": self.weather_source, "profile_overrides": dict(self.profile_overrides)}

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_version": self.api_version, "crop": self.crop, "variety": self.variety, "environment": self.environment, "plot": self.plot,
            "scenario": self.scenario, "start_time": self.start_time.isoformat(), "end_time": self.end_time.isoformat(), "seed": self.seed,
            "weather": self.weather_dict(), "dormancy": self.dormancy.to_dict()["dormancy"],
            "checkpoint": self.checkpoint.to_dict() if self.checkpoint is not None else None, "options": self.options.to_dict(),
        }

    def canonical_json(self) -> str:
        return _canonical_json(self.to_dict())

    @property
    def request_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def resume_identity(self) -> dict[str, Any]:
        """Everything that must match between a checkpoint's producer and its resume."""
        cycle_start = campaign_cycle(self.crop)[1]
        return {"api_version": self.api_version, "crop": self.crop, "variety": self.variety, "environment": self.environment, "plot": self.plot,
                "scenario": self.scenario, "seed": self.seed, "weather": self.weather_dict(), "dormancy_effective": self.dormancy.effective_dict(),
                "campaign_start": cycle_start.isoformat(), "timestep_seconds": TIMESTEP_SECONDS}

    @property
    def resume_hash(self) -> str:
        return _hash(self.resume_identity())


def _plot_for(crop: str):
    return next(plot for plot in SyntheticReferenceDatasetGenerator.DEFAULT_PLOTS if plot.crop == crop)


def _text(document: Mapping[str, Any], key: str, errors: list[SimulationError], code: ErrorCode = ErrorCode.INVALID_REQUEST) -> str | None:
    value = document[key]
    if not isinstance(value, str) or not value.strip():
        errors.append(SimulationError(code, f"{key} must be a non-empty string, got {type(value).__name__}", key))
        return None
    return value.strip()


def _instant(value: Any, path: str) -> datetime:
    if not isinstance(value, str):
        raise _fail(ErrorCode.INVALID_REQUEST, f"{path} must be an ISO-8601 string with a UTC offset, got {type(value).__name__}", path)
    try:
        instant = datetime.fromisoformat(value)
    except ValueError:
        raise _fail(ErrorCode.INVALID_REQUEST, f"{path} is not an ISO-8601 instant: {value!r}", path) from None
    if instant.tzinfo is None:
        raise _fail(ErrorCode.INVALID_REQUEST, f"{path} is ambiguous: an explicit UTC offset is required ({value!r})", path)
    return instant.astimezone(UTC)


def _options(raw: Any) -> ExecutionOptions:
    if raw is None:
        return ExecutionOptions()
    if not isinstance(raw, Mapping):
        raise _fail(ErrorCode.INVALID_REQUEST, f"options must be a mapping, got {type(raw).__name__}", "options")
    unknown = sorted(set(raw) - set(OPTION_FIELDS))
    if unknown:
        raise _fail(ErrorCode.INVALID_REQUEST, f"unknown fields: {', '.join(unknown)}; allowed: {', '.join(OPTION_FIELDS)}", f"options.{unknown[0]}")
    interval = raw.get("progress_interval_steps")
    if interval is not None and (isinstance(interval, bool) or not isinstance(interval, int) or interval < 1):
        raise _fail(ErrorCode.INVALID_REQUEST, "progress_interval_steps must be a positive integer or null", "options.progress_interval_steps")
    flags = {}
    for name, default in (("require_requested_chilling_model", False), ("include_trajectory", True), ("compute_trajectory_hash", True)):
        value = raw.get(name, default)
        if not isinstance(value, bool):
            raise _fail(ErrorCode.INVALID_REQUEST, f"{name} must be a boolean, got {type(value).__name__}", f"options.{name}")
        flags[name] = value
    variables = raw.get("variables")
    if variables is not None:
        if not isinstance(variables, (list, tuple)) or not variables:
            raise _fail(ErrorCode.INVALID_REQUEST, "variables must be a non-empty list of variable names or null", "options.variables")
        for index, name in enumerate(variables):
            if name not in VARIABLE_INDEX:
                raise _fail(ErrorCode.INVALID_REQUEST, f"unknown variable {name!r}; see the variable catalogue", f"options.variables[{index}]")
        if len(set(variables)) != len(variables):
            raise _fail(ErrorCode.INVALID_REQUEST, "variables contains duplicates", "options.variables")
        variables = tuple(sorted(variables, key=lambda name: [spec.name for spec in VARIABLES].index(name)))
    return ExecutionOptions(interval, flags["require_requested_chilling_model"], flags["include_trajectory"], flags["compute_trajectory_hash"], variables)


def _weather(raw: Any, scenario: str, seed: int) -> tuple[str, tuple[tuple[str, float], ...]]:
    if raw is None:
        return WEATHER_SOURCES[0], ()
    if not isinstance(raw, Mapping):
        raise _fail(ErrorCode.INVALID_REQUEST, f"weather must be a mapping, got {type(raw).__name__}", "weather")
    unknown = sorted(set(raw) - set(WEATHER_FIELDS))
    if unknown:
        raise _fail(ErrorCode.INVALID_REQUEST, f"unknown fields: {', '.join(unknown)}; allowed: {', '.join(WEATHER_FIELDS)}", f"weather.{unknown[0]}")
    source = raw.get("source", WEATHER_SOURCES[0])
    if source not in WEATHER_SOURCES:
        raise _fail(ErrorCode.INVALID_CONFIGURATION, f"weather source {source!r} is not supported by API {API_VERSION}; supported: {', '.join(WEATHER_SOURCES)}", "weather.source")
    overrides = raw.get("profile_overrides") or {}
    if not isinstance(overrides, Mapping):
        raise _fail(ErrorCode.INVALID_REQUEST, "profile_overrides must be a mapping", "weather.profile_overrides")
    canonical = []
    for key in sorted(overrides):
        value = overrides[key]
        if key not in BASE_PROFILE:
            raise _fail(ErrorCode.INVALID_CONFIGURATION, f"unknown synthetic climate profile key {key!r}; allowed: {', '.join(sorted(BASE_PROFILE))}", f"weather.profile_overrides.{key}")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise _fail(ErrorCode.INVALID_CONFIGURATION, f"{key} must be a finite number", f"weather.profile_overrides.{key}")
        canonical.append((key, float(value)))
    try:
        weather_configuration(effective_profile(scenario, tuple(canonical)), seed)
    except (ValueError, TypeError) as exc:
        raise _fail(ErrorCode.INVALID_CONFIGURATION, f"the effective synthetic climate profile is invalid: {exc}", "weather.profile_overrides") from None
    return source, tuple(canonical)


def effective_profile(scenario: str, overrides: Sequence[tuple[str, float]]) -> dict[str, float]:
    """Phase 5.32 scenario profile; overrides replace the effective (post-shift) values."""
    return {**climate_profile(scenario), **dict(overrides)}


def _dormancy(raw: Any) -> DormancyConfiguration:
    if raw is None:
        return DEFAULT_DORMANCY_CONFIGURATION
    try:
        return canonicalize_dormancy_configuration({"dormancy": raw})
    except PhenologyError as exc:
        raise _fail(ErrorCode.INVALID_CONFIGURATION, str(exc), "dormancy") from None


def _checkpoint(raw: Any) -> SimulationCheckpoint | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping) or set(raw) != set(CHECKPOINT_FIELDS):
        raise _fail(ErrorCode.INVALID_CHECKPOINT, f"checkpoint must be the mapping returned by the API with exactly {', '.join(CHECKPOINT_FIELDS)}", "checkpoint")
    if raw["format"] != CHECKPOINT_FORMAT:
        raise _fail(ErrorCode.INVALID_CHECKPOINT, f"unsupported checkpoint format {raw['format']!r}; expected {CHECKPOINT_FORMAT}", "checkpoint.format")
    payload = raw["payload"]
    if not isinstance(payload, str) or not isinstance(raw["sha256"], str) or not isinstance(raw["resume_hash"], str):
        raise _fail(ErrorCode.INVALID_CHECKPOINT, "payload, sha256 and resume_hash must be strings", "checkpoint")
    if hashlib.sha256(payload.encode("utf-8")).hexdigest() != raw["sha256"]:
        raise _fail(ErrorCode.INVALID_CHECKPOINT, "checkpoint payload does not match its sha256 (altered or truncated)", "checkpoint.sha256")
    instant = _instant(raw["simulation_time"], "checkpoint.simulation_time")
    try:
        restored_time = restore_checkpoint(payload)[0]
    except (ValueError, KeyError, TypeError) as exc:
        raise _fail(ErrorCode.INVALID_CHECKPOINT, f"checkpoint payload cannot be restored: {exc}", "checkpoint.payload") from None
    if restored_time != instant:
        raise _fail(ErrorCode.INVALID_CHECKPOINT, "checkpoint simulation_time differs from the payload time", "checkpoint.simulation_time")
    return SimulationCheckpoint(CHECKPOINT_FORMAT, instant, payload, raw["sha256"], raw["resume_hash"])


def canonicalize_request(document: SimulationRequest | Mapping[str, Any]) -> SimulationRequest:
    """Validate and canonicalize a request; defaults come only from existing configuration.

    Defaults: variety / plot / environment from the existing synthetic plot of the crop
    (``SyntheticReferenceDatasetGenerator.DEFAULT_PLOTS``), period from the crop's
    synthetic cycle (``campaign_cycle``), scenario ``BASE_SEASON``, seed and weather
    from Phase 5.32, dormancy from ``DEFAULT_DORMANCY_CONFIGURATION``. Unknown,
    ambiguous or inconsistent fields are rejected with a structured error and path.
    """
    if isinstance(document, SimulationRequest):
        document = document.to_dict()
    if not isinstance(document, Mapping):
        raise _fail(ErrorCode.INVALID_REQUEST, f"request must be a mapping, got {type(document).__name__}")
    unknown = sorted(set(document) - set(REQUEST_FIELDS))
    if unknown:
        raise _fail(ErrorCode.INVALID_REQUEST, f"unknown fields: {', '.join(unknown)}; allowed: {', '.join(REQUEST_FIELDS)}", unknown[0])
    if document.get("api_version", API_VERSION) != API_VERSION:
        raise _fail(ErrorCode.INVALID_REQUEST, f"api_version must be {API_VERSION!r}", "api_version")
    if "crop" not in document:
        raise _fail(ErrorCode.INVALID_REQUEST, "crop is required", "crop")
    errors: list[SimulationError] = []
    crop = _text(document, "crop", errors)
    if crop is None:
        raise SimulationApiError(errors)
    crop = crop.lower()
    if crop not in KNOWN_CROPS:
        raise _fail(ErrorCode.UNSUPPORTED_CROP, f"crop {crop!r} is not configured; supported: {', '.join(KNOWN_CROPS)}", "crop")
    plot = _plot_for(crop)
    environment = plot.environment
    if document.get("environment") is not None:
        environment = (_text(document, "environment", errors) or environment).lower()
    if environment not in ENVIRONMENTS:
        errors.append(SimulationError(ErrorCode.UNSUPPORTED_ENVIRONMENT, f"environment {environment!r} is not supported; supported: {', '.join(ENVIRONMENTS)}", "environment"))
    elif environment == "greenhouse" and crop not in ANNUAL_GREENHOUSE_CROPS:
        errors.append(SimulationError(ErrorCode.UNSUPPORTED_ENVIRONMENT, f"no greenhouse configuration exists for {crop}; greenhouse crops: {', '.join(ANNUAL_GREENHOUSE_CROPS)}", "environment"))
    variety = KNOWN_VARIETIES.get(crop, "UNSPECIFIED")
    if document.get("variety") is not None:
        given = _text(document, "variety", errors)
        if given is not None and given != variety:
            errors.append(SimulationError(ErrorCode.INVALID_CONFIGURATION, f"variety {given!r} has no configuration for {crop}; configured: {variety!r}", "variety"))
    if document.get("plot") is not None:
        given = _text(document, "plot", errors)
        if given is not None and given != plot.plot_id:
            errors.append(SimulationError(ErrorCode.INVALID_CONFIGURATION, f"plot {given!r} is not configured for {crop}; configured: {plot.plot_id!r}", "plot"))
    scenario = DEFAULT_SCENARIO
    if document.get("scenario") is not None:
        scenario = (_text(document, "scenario", errors, ErrorCode.INVALID_SCENARIO) or scenario).upper()
        if scenario not in SCENARIOS:
            errors.append(SimulationError(ErrorCode.INVALID_SCENARIO, f"scenario {scenario!r} is not defined; available: {', '.join(SCENARIOS)}", "scenario"))
    seed = document.get("seed", DEFAULT_SEED)
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        errors.append(SimulationError(ErrorCode.INVALID_REQUEST, "seed must be a non-negative integer", "seed"))
    if errors:
        raise SimulationApiError(errors)
    _, campaign_start, campaign_end = campaign_cycle(crop)
    checkpoint = _checkpoint(document.get("checkpoint"))
    start = campaign_start if document.get("start_time") is None else _instant(document["start_time"], "start_time")
    end = campaign_end if document.get("end_time") is None else _instant(document["end_time"], "end_time")
    if checkpoint is not None:
        if document.get("start_time") is not None and start != checkpoint.simulation_time:
            raise _fail(ErrorCode.INVALID_TIME_RANGE, "start_time must be omitted or equal to the checkpoint time when resuming", "start_time")
        start = checkpoint.simulation_time
    elif start != campaign_start:
        raise _fail(ErrorCode.INVALID_TIME_RANGE, f"start_time is fixed by the crop's synthetic cycle ({campaign_start.isoformat()}); set the horizon with end_time or resume from a checkpoint", "start_time")
    if end <= start:
        raise _fail(ErrorCode.INVALID_TIME_RANGE, f"end_time {end.isoformat()} must be after start {start.isoformat()}", "end_time")
    if end > campaign_end:
        raise _fail(ErrorCode.INVALID_TIME_RANGE, f"end_time {end.isoformat()} exceeds the synthetic campaign end {campaign_end.isoformat()}", "end_time")
    if (end - start).total_seconds() % TIMESTEP_SECONDS:
        raise _fail(ErrorCode.INVALID_TIME_RANGE, f"the horizon must be a whole number of {TIMESTEP_SECONDS} s steps", "end_time")
    source, overrides = _weather(document.get("weather"), scenario, seed)
    dormancy = _dormancy(document.get("dormancy"))
    options = _options(document.get("options"))
    if options.require_requested_chilling_model and dormancy.fallback_applied:
        raise _fail(ErrorCode.MODEL_NOT_READY, f"requested chilling model {dormancy.requested_chilling_model.value} is {dormancy.requested_model_status.value}: "
                                               f"no requirement in {MODEL_SPECS[dormancy.requested_chilling_model].unit.value}; the STRICT fallback would run "
                                               f"{dormancy.effective_chilling_model.value} and the request forbids it", "dormancy.chilling_model")
    request = SimulationRequest(crop, variety, environment, plot.plot_id, scenario, start, end, seed, source, overrides, dormancy, checkpoint, options)
    if checkpoint is not None:
        if checkpoint.resume_hash != request.resume_hash:
            raise _fail(ErrorCode.INVALID_CHECKPOINT, "checkpoint was produced by a different configuration (crop, environment, scenario, seed, weather or dormancy differ)", "checkpoint.resume_hash")
        if not campaign_start <= start < campaign_end:
            raise _fail(ErrorCode.INVALID_CHECKPOINT, f"checkpoint time {start.isoformat()} lies outside the campaign [{campaign_start.isoformat()}, {campaign_end.isoformat()})", "checkpoint.simulation_time")
    return request


# ---------------------------------------------------------------------------
# Execution plan (mode classification without running anything)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    mode: ExecutionMode
    plots: int
    total_steps: int
    estimated_seconds: float
    basis: str

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode.value, "plots": self.plots, "total_steps": self.total_steps, "estimated_seconds": self.estimated_seconds,
                "basis": self.basis, "requires_background_executor": self.mode is ExecutionMode.BACKGROUND,
                "executor": "SYNCHRONOUS_IN_PROCESS (a decoupled background executor is a future adapter)", "cost_model": dict(COST_MODEL)}


def plan_execution(requests: SimulationRequest | Sequence[SimulationRequest]) -> ExecutionPlan:
    """Classify from configuration only: plots, horizon steps and the measured cost per step."""
    items = (requests,) if isinstance(requests, SimulationRequest) else tuple(requests)
    if not items:
        raise _fail(ErrorCode.INVALID_REQUEST, "at least one request is required")
    steps = sum(request.total_steps for request in items)
    plots = len({(request.plot, request.crop, request.environment, request.scenario) for request in items})
    estimate = round(steps * COST_MODEL["seconds_per_plot_step"], 6)
    if len(items) > 1 or estimate > COST_MODEL["interactive_with_progress_max_seconds"]:
        mode, basis = ExecutionMode.BACKGROUND, "multi-plot / multi-request campaign or estimate above the progress band"
    elif estimate <= COST_MODEL["interactive_max_seconds"]:
        mode, basis = ExecutionMode.INTERACTIVE, "single plot, estimate within the direct-response band"
    else:
        mode, basis = ExecutionMode.INTERACTIVE_WITH_PROGRESS, "single plot, season-scale horizon: progress observable"
    return ExecutionPlan(mode, plots, steps, estimate, basis)


# ---------------------------------------------------------------------------
# Progress, result and response contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SimulationProgress:
    """Operational progress; never scientific evidence. ``elapsed_seconds`` is excluded from hashes."""

    simulation_id: str
    status: ExecutionStatus
    total_steps: int
    completed_steps: int
    simulated_time: datetime | None
    current_stage: str | None
    current_state: Mapping[str, Any] | None
    elapsed_seconds: float | None = None

    @property
    def fraction(self) -> float:
        return self.completed_steps / self.total_steps if self.total_steps else 0.0

    def deterministic_dict(self) -> dict[str, Any]:
        return {"simulation_id": self.simulation_id, "status": self.status.value, "total_steps": self.total_steps, "completed_steps": self.completed_steps,
                "fraction": self.fraction, "simulated_time": self.simulated_time.isoformat() if self.simulated_time else None,
                "current_stage": self.current_stage, "current_state": dict(self.current_state) if self.current_state is not None else None,
                "kind": "OPERATIONAL_PROGRESS_NOT_SCIENTIFIC_EVIDENCE"}

    def to_dict(self) -> dict[str, Any]:
        return {**self.deterministic_dict(), "elapsed_seconds": self.elapsed_seconds}


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """Visualizable model result: a projection of existing snapshot fields."""

    complete: bool
    steps: int
    start: datetime
    end: datetime | None
    variables: tuple[Mapping[str, Any], ...]
    trajectory: Mapping[str, Any] | None
    final_state: Mapping[str, Any] | None
    totals: Mapping[str, float]
    trajectory_hash: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"complete": self.complete, "steps": self.steps, "start": self.start.isoformat(), "end": self.end.isoformat() if self.end else None,
                "timestep_seconds": TIMESTEP_SECONDS, "variables": [dict(item) for item in self.variables], "trajectory": self.trajectory,
                "final_state": dict(self.final_state) if self.final_state is not None else None, "totals": dict(self.totals),
                "trajectory_hash": self.trajectory_hash, "result_type": "MODEL_RESULT"}

    @property
    def result_hash(self) -> str:
        return _hash(self.to_dict())


@dataclass(frozen=True, slots=True)
class SimulationResponse:
    simulation_id: str
    request: Mapping[str, Any]
    effective_configuration: Mapping[str, Any]
    execution_status: ExecutionStatus
    plan: Mapping[str, Any]
    progress: SimulationProgress
    result: SimulationResult | None
    diagnostics: Mapping[str, Any]
    warnings: tuple[SimulationWarning, ...]
    errors: tuple[SimulationError, ...]
    hashes: Mapping[str, str | None]
    checkpoint: SimulationCheckpoint | None
    operational: Mapping[str, Any] = field(default_factory=dict)

    def deterministic_dict(self) -> dict[str, Any]:
        """Everything except operational timings: equal for equal requests."""
        return {
            "api_version": API_VERSION, "simulation_id": self.simulation_id, "request": dict(self.request),
            "effective_configuration": dict(self.effective_configuration), "execution_status": self.execution_status.value, "plan": dict(self.plan),
            "progress": self.progress.deterministic_dict(), "result": self.result.to_dict() if self.result is not None else None,
            "diagnostics": dict(self.diagnostics), "warnings": [item.to_dict() for item in self.warnings], "errors": [item.to_dict() for item in self.errors],
            "hashes": dict(self.hashes), "checkpoint": self.checkpoint.to_dict() if self.checkpoint is not None else None,
            "scientific_status": dict(SCIENTIFIC_STATUS),
        }

    @property
    def response_hash(self) -> str:
        return _hash(self.deterministic_dict())

    def to_dict(self) -> dict[str, Any]:
        return {**self.deterministic_dict(), "response_hash": self.response_hash, "operational": {**self.operational, "progress_elapsed_seconds": self.progress.elapsed_seconds,
                                                                                                   "note": "PERFORMANCE_MEASUREMENT, machine-dependent, excluded from every hash"}}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, allow_nan=False)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


ProgressListener = Callable[[SimulationProgress], None]


@dataclass(slots=True)
class _Execution:
    """Mutable operational record of one execution (never scientific state)."""

    simulation_id: str
    request: SimulationRequest
    spec: CampaignSpec
    scenario: Scenario
    effective: dict[str, Any]
    plan: ExecutionPlan
    warnings: tuple[SimulationWarning, ...]
    status: ExecutionStatus = ExecutionStatus.CREATED
    cancel_requested: bool = False
    completed_steps: int = 0
    last_snapshot: CropSimulationSnapshot | None = None
    snapshots: tuple[CropSimulationSnapshot, ...] = ()
    errors: tuple[SimulationError, ...] = ()
    termination: str | None = None
    progress_events: int = 0
    listener_error: str | None = None
    started_at: float | None = None
    timings: dict[str, float] = field(default_factory=dict)
    response: SimulationResponse | None = None


class InteractiveSimulationService:
    """Application-level simulation API (in-memory, synchronous, one execution per request).

    Surface: ``create_simulation``, ``get_simulation``, ``start_simulation``,
    ``get_simulation_progress``, ``cancel_simulation``, ``get_simulation_result``,
    ``resume_simulation`` and ``run_simulation`` (create + start). A future HTTP or
    worker layer is an adapter over this class, not its core. Executions are isolated:
    each owns its CampaignSpec, Scenario and ScenarioRunner (which owns the run's
    SimulationClock); nothing global is written.
    """

    def __init__(self, *, timer: Callable[[], float] | None = None) -> None:
        self._timer = timer  # caller-injected operational timer (None: no timings); excluded from hashes
        self._executions: dict[str, _Execution] = {}
        self._sequence = 0

    def _tick(self) -> float | None:
        return self._timer() if self._timer is not None else None

    def _record(self, execution: _Execution, key: str, started: float | None) -> None:
        if started is not None and self._timer is not None:
            execution.timings[key] = self._timer() - started

    # -- creation -------------------------------------------------------------------

    def create_simulation(self, request: SimulationRequest | Mapping[str, Any]) -> SimulationResponse:
        started = self._tick()
        canonical = canonicalize_request(request)
        canonicalized = self._tick()
        spec, scenario = self._prepare(canonical)
        self._sequence += 1
        simulation_id = f"sim-{self._sequence:06d}-{canonical.request_hash[:12]}"
        execution = _Execution(simulation_id, canonical, spec, scenario, effective_configuration(canonical, spec, scenario), plan_execution(canonical), _configuration_warnings(canonical))
        if started is not None and canonicalized is not None:
            execution.timings["canonicalization_seconds"] = canonicalized - started
        self._record(execution, "preparation_seconds", canonicalized)
        self._executions[simulation_id] = execution
        return self._response(execution)

    def resume_simulation(self, request: SimulationRequest | Mapping[str, Any]) -> SimulationResponse:
        """Create a simulation that resumes from the request's checkpoint (required)."""
        canonical = canonicalize_request(request)
        if canonical.checkpoint is None:
            raise _fail(ErrorCode.INVALID_CHECKPOINT, "resume_simulation requires a checkpoint", "checkpoint")
        return self.create_simulation(canonical)

    def run_simulation(self, request: SimulationRequest | Mapping[str, Any], listener: ProgressListener | None = None) -> SimulationResponse:
        return self.start_simulation(self.create_simulation(request).simulation_id, listener)

    @staticmethod
    def _prepare(request: SimulationRequest) -> tuple[CampaignSpec, Scenario]:
        try:
            spec = build_campaign(request.crop, request.environment, request.scenario, seed=request.seed)
        except ScenarioError as exc:
            raise _fail(ErrorCode.INVALID_CONFIGURATION, str(exc)) from None
        scenario = spec.scenario
        if request.checkpoint is not None:
            restart_time, crop, soil, microclimate = restore_checkpoint(request.checkpoint.payload)
            if (crop.crop_key, crop.variety) != (request.crop, request.variety):
                raise _fail(ErrorCode.INVALID_CHECKPOINT, f"checkpoint holds {crop.crop_key}/{crop.variety}, request is {request.crop}/{request.variety}", "checkpoint.payload")
            for event in scenario.events:
                if event.start < restart_time < event.end and event.parameters.get("ramp_hours", 0.0) > 0.0:
                    raise _fail(ErrorCode.INVALID_CHECKPOINT, f"checkpoint {restart_time.isoformat()} lies inside the ramped event {event.event_id!r}; resuming there would "
                                                              "re-anchor the event ramp (existing resumed_scenario limitation), so exact equivalence cannot be guaranteed", "checkpoint.simulation_time")
            try:
                scenario = resumed_scenario(scenario, restart_time, crop, soil, microclimate)
            except ScenarioError as exc:
                raise _fail(ErrorCode.INVALID_CHECKPOINT, str(exc), "checkpoint.simulation_time") from None
        return spec, scenario

    # -- queries --------------------------------------------------------------------

    def _execution(self, simulation_id: str) -> _Execution:
        try:
            return self._executions[simulation_id]
        except (KeyError, TypeError):
            raise _fail(ErrorCode.INVALID_REQUEST, f"unknown simulation id {simulation_id!r}", "simulation_id") from None

    def get_simulation(self, simulation_id: str) -> SimulationResponse:
        execution = self._execution(simulation_id)
        return execution.response if execution.response is not None else self._response(execution)

    def get_simulation_progress(self, simulation_id: str) -> SimulationProgress:
        return self._progress(self._execution(simulation_id))

    def get_simulation_result(self, simulation_id: str) -> SimulationResult:
        execution = self._execution(simulation_id)
        if execution.status is ExecutionStatus.COMPLETED:
            return self.get_simulation(simulation_id).result  # type: ignore[return-value]
        if execution.status is ExecutionStatus.CANCELLED:
            raise _fail(ErrorCode.CANCELLATION_REQUESTED, f"simulation was cancelled after {execution.completed_steps}/{execution.plan.total_steps} steps and did not finish; "
                                                          "the partial trajectory and its checkpoint are in get_simulation()", "simulation_id")
        if execution.status is ExecutionStatus.FAILED:
            raise SimulationApiError(execution.errors)
        raise _fail(ErrorCode.INVALID_REQUEST, f"simulation is {execution.status.value}; no result yet", "simulation_id")

    # -- cancellation ----------------------------------------------------------------

    def cancel_simulation(self, simulation_id: str) -> SimulationResponse:
        """Cooperative cancellation, observed at the next step boundary (no thread, no scheduler)."""
        execution = self._execution(simulation_id)
        if execution.status in TERMINAL_STATUSES:
            raise _fail(ErrorCode.INVALID_REQUEST, f"simulation is already {execution.status.value}", "simulation_id")
        execution.cancel_requested = True
        if execution.status is ExecutionStatus.CREATED:
            execution.status, execution.termination = ExecutionStatus.CANCELLED, "CANCELLED_BEFORE_START"
            execution.errors = (_cancellation_error(execution),)
            execution.response = self._response(execution)
            return execution.response
        return self._response(execution)

    # -- execution -------------------------------------------------------------------

    def start_simulation(self, simulation_id: str, listener: ProgressListener | None = None) -> SimulationResponse:
        execution = self._execution(simulation_id)
        if execution.status is not ExecutionStatus.CREATED:
            raise _fail(ErrorCode.INVALID_REQUEST, f"simulation is {execution.status.value}; an execution runs once (create a new one)", "simulation_id")
        request = execution.request
        total = request.total_steps
        interval = request.options.progress_interval_steps
        if interval is None and execution.plan.mode is not ExecutionMode.INTERACTIVE:
            interval = DEFAULT_PROGRESS_INTERVAL_STEPS

        def observer(snapshot: CropSimulationSnapshot, completed: int) -> bool:
            execution.completed_steps, execution.last_snapshot = completed, snapshot
            if completed >= total:
                execution.termination = "HORIZON_REACHED"
                return False
            if listener is not None and interval is not None and completed % interval == 0:
                self._emit(execution, listener)
            if execution.listener_error is not None:
                execution.termination = "LISTENER_FAILED"
                return False
            if execution.cancel_requested:
                execution.termination = "CANCELLED"
                return False
            return True

        execution.status = ExecutionStatus.RUNNING
        execution.started_at = self._tick()
        phenology = None if request.dormancy == DEFAULT_DORMANCY_CONFIGURATION else PhenologyEngine(dormancy=DormancyChillingController(configuration=request.dormancy))
        runner = ScenarioRunner(_weather_factory(request))
        result = runner.run(execution.scenario, phenology=phenology, observer=observer)
        self._record(execution, "simulation_seconds", execution.started_at)
        execution.snapshots = result.snapshots
        if result.status == "FAILED":
            execution.status, execution.termination = ExecutionStatus.FAILED, "MODEL_OR_EXECUTION_ERROR"
            detail = "; ".join(result.warnings) or "unknown error"
            execution.errors = (SimulationError(ErrorCode.INTERNAL_EXECUTION_ERROR, f"execution stopped at step {len(result.snapshots) + 1}/{total}: {detail}"),)
        elif execution.termination == "LISTENER_FAILED":
            execution.status = ExecutionStatus.FAILED
            execution.errors = (SimulationError(ErrorCode.INTERNAL_EXECUTION_ERROR, f"progress listener raised: {execution.listener_error}; the model state was not affected"),)
        elif execution.termination == "CANCELLED":
            execution.status = ExecutionStatus.CANCELLED
            execution.errors = (_cancellation_error(execution),)
        elif execution.termination == "HORIZON_REACHED" or (result.status == "SUCCESS" and len(result.snapshots) == total):
            execution.status, execution.termination = ExecutionStatus.COMPLETED, "HORIZON_REACHED"
        else:
            execution.status, execution.termination = ExecutionStatus.FAILED, "INCOMPLETE"
            execution.errors = (SimulationError(ErrorCode.INTERNAL_EXECUTION_ERROR, f"runner ended with {len(result.snapshots)}/{total} steps (status {result.status})"),)
        if listener is not None and execution.listener_error is None:
            self._emit(execution, listener)
        execution.response = self._response(execution)
        return execution.response

    def _emit(self, execution: _Execution, listener: ProgressListener) -> None:
        try:
            listener(self._progress(execution))
            execution.progress_events += 1
        except Exception as exc:  # a frontend callback must not corrupt the run
            execution.listener_error = f"{type(exc).__name__}: {exc}"

    # -- projections -----------------------------------------------------------------

    def _progress(self, execution: _Execution) -> SimulationProgress:
        snapshot = execution.last_snapshot
        state = twin_state_from_snapshot(snapshot, execution.spec).to_dict() if snapshot is not None else None
        running = execution.started_at is not None and self._timer is not None and execution.status is ExecutionStatus.RUNNING
        elapsed = self._timer() - execution.started_at if running else execution.timings.get("simulation_seconds")  # type: ignore[misc, operator]
        return SimulationProgress(execution.simulation_id, execution.status, execution.plan.total_steps, execution.completed_steps,
                                  snapshot.simulation_time if snapshot else None, snapshot.crop.current_stage if snapshot else None, state, elapsed)

    def _response(self, execution: _Execution) -> SimulationResponse:
        request = execution.request
        result = checkpoint = None
        hashes: dict[str, str | None] = {"request_hash": request.request_hash, "configuration_hash": _hash(execution.effective), "resume_hash": request.resume_hash,
                                         "trajectory_hash": None, "result_hash": None, "checkpoint_sha256": None}
        warnings = execution.warnings
        if execution.status in TERMINAL_STATUSES and execution.snapshots:
            projected = self._tick()
            result = project_result(execution)
            self._record(execution, "result_projection_seconds", projected)
            checkpoint = SimulationCheckpoint.from_snapshot(execution.snapshots[-1], request.resume_hash)
            hashes.update(trajectory_hash=result.trajectory_hash, result_hash=result.result_hash, checkpoint_sha256=checkpoint.sha256)
            warnings = warnings + _behaviour_warnings(execution)
        diagnostics = {
            "kind": "EXECUTION_DIAGNOSTICS (software/operational, not biological)",
            "termination": execution.termination, "steps_executed": execution.completed_steps if execution.snapshots else 0, "total_steps": execution.plan.total_steps,
            "cancel_requested": execution.cancel_requested, "progress_events_emitted": execution.progress_events,
            "execution_path": "build_campaign -> ScenarioRunner.run -> CropDigitalTwinOrchestrator.step (existing engines)",
            "state_integrity": "orchestrator state is replaced atomically per step; a stop leaves the last completed step as the state",
        }
        return SimulationResponse(execution.simulation_id, request.to_dict(), execution.effective, execution.status, execution.plan.to_dict(), self._progress(execution),
                                  result, diagnostics, warnings, execution.errors, hashes, checkpoint, {"timings_seconds": dict(execution.timings)})


def _cancellation_error(execution: _Execution) -> SimulationError:
    return SimulationError(ErrorCode.CANCELLATION_REQUESTED, f"cancelled on request after {execution.completed_steps}/{execution.plan.total_steps} steps; the simulation did not finish. "
                                                             "Operational stop, not a model or scientific failure.")


def _weather_factory(request: SimulationRequest) -> Callable[[Scenario], SyntheticWeatherProvider]:
    if not request.profile_overrides:
        return seasonal_weather_factory  # exactly the Phase 5.32 base weather
    configuration = weather_configuration(effective_profile(request.scenario, request.profile_overrides), request.seed)
    return lambda _scenario: SyntheticWeatherProvider(WeatherEngine(configuration))


def effective_configuration(request: SimulationRequest, spec: CampaignSpec, scenario: Scenario) -> dict[str, Any]:
    """Resolved configuration actually executed (deterministic, hashed as configuration_hash)."""
    _, campaign_start, campaign_end = campaign_cycle(request.crop)
    effective_dormancy = request.dormancy.describe()
    return {
        "crop": request.crop, "variety": request.variety, "plot": request.plot, "environment": request.environment,
        "greenhouse_mode": ENVIRONMENTS[request.environment], "scenario": request.scenario, "seed": request.seed,
        "period": {"campaign_start": campaign_start.isoformat(), "campaign_end": campaign_end.isoformat(), "start": request.start_time.isoformat(),
                   "end": request.end_time.isoformat(), "timestep_seconds": TIMESTEP_SECONDS, "total_steps": request.total_steps,
                   "source": "existing synthetic crop cycle (SyntheticReferenceDatasetGenerator via campaign_cycle)"},
        "initial_state": {"source": "CHECKPOINT" if request.checkpoint else "SYNTHETIC_INITIAL_STATE (Phase 5.29 _initial_state)",
                          "checkpoint_sha256": request.checkpoint.sha256 if request.checkpoint else None},
        "weather": {"source": request.weather_source, "generator": WEATHER_GENERATOR, "seed": request.seed,
                    "profile": effective_profile(request.scenario, request.profile_overrides), "profile_overrides": dict(request.profile_overrides),
                    "classification": "SYNTHETIC_FORCING", "represents_real_climatology": False},
        "scenario_events": [{"event_id": event.event_id, "event_type": event.event_type, "start": event.start.isoformat(), "end": event.end.isoformat(),
                             "intensity": event.intensity, "parameters": dict(event.parameters)} for event in scenario.events],
        "irrigation_factor": IRRIGATION_FACTOR.get(request.scenario, 1.0),
        "dormancy": effective_dormancy, "dormancy_applicable": request.crop in PERENNIAL_CROPS,
        "chilling_unit": MODEL_SPECS[request.dormancy.effective_chilling_model].unit.value,
        "model": {"engines": "existing CropDigitalTwinOrchestrator engines (phenology, greenhouse, radiation growth, water, nutrients, climate stress)",
                  "parameter_status": SCIENTIFIC_STATUS["parameter_status"]},
        "scenario_config_hash": scenario.config_hash(),
    }


def _configuration_warnings(request: SimulationRequest) -> tuple[SimulationWarning, ...]:
    warnings = []
    if request.dormancy.fallback_applied:
        warnings.append(SimulationWarning("CONFIGURATION", "CHILLING_MODEL_FALLBACK", f"requested {request.dormancy.requested_chilling_model.value} has no requirement; "
                                                                                       f"STRICT fallback executes {request.dormancy.effective_chilling_model.value} (request kept in the configuration)"))
    if request.crop not in PERENNIAL_CROPS and request.dormancy != DEFAULT_DORMANCY_CONFIGURATION:
        warnings.append(SimulationWarning("CONFIGURATION", "DORMANCY_NOT_APPLICABLE", f"{request.crop} is annual: the dormancy configuration has no effect"))
    if request.dormancy.requirement is not None:
        warnings.append(SimulationWarning("CONFIGURATION", "SOFTWARE_TEST_ONLY_REQUIREMENT", "the chilling requirement is SOFTWARE_TEST_ONLY, not a species or cultivar requirement"))
    return tuple(warnings)


def _behaviour_warnings(execution: _Execution) -> tuple[SimulationWarning, ...]:
    """Model-behaviour notes about this output (never biological evidence)."""
    last = execution.snapshots[-1].crop
    if execution.request.crop in PERENNIAL_CROPS and not last.dormancy_released:
        return (SimulationWarning("MODEL_BEHAVIOR", "DORMANCY_NOT_RELEASED", "the implemented model did not release dormancy within the simulated period"),)
    return ()


def project_result(execution: _Execution) -> SimulationResult:
    request, snapshots = execution.request, execution.snapshots
    selected = request.options.variables or tuple(spec.name for spec in VARIABLES)
    catalogue, series = [], {}
    for name in selected:
        spec = VARIABLE_INDEX[name]
        availability = variable_availability(spec, request.crop, request.environment)
        unit = MODEL_SPECS[request.dormancy.effective_chilling_model].unit.value if name == "chilling_accumulated" else spec.unit
        catalogue.append({"name": name, "unit": unit, "availability": availability.value, "source": spec.source, "description": spec.description,
                          "reason": None if availability is Availability.AVAILABLE else spec.reason})
        if availability is Availability.AVAILABLE and request.options.include_trajectory:
            series[name] = [spec.getter(snapshot) for snapshot in snapshots]  # type: ignore[misc]
    trajectory = {"time": [snapshot.simulation_time.isoformat() for snapshot in snapshots], **series} if request.options.include_trajectory else None
    totals = {name: math.fsum(VARIABLE_INDEX[name].getter(snapshot) for snapshot in snapshots) for name in FLUX_TOTALS}  # type: ignore[misc]
    final_state = twin_state_from_snapshot(snapshots[-1], execution.spec).to_dict()
    digest = trajectory_hash(snapshots) if request.options.compute_trajectory_hash else None
    return SimulationResult(execution.status is ExecutionStatus.COMPLETED, len(snapshots), request.start_time, snapshots[-1].simulation_time,
                            tuple(catalogue), trajectory, final_state, totals, digest)


# ---------------------------------------------------------------------------
# Immutability fingerprint (configuration and registries the API must not change)
# ---------------------------------------------------------------------------


CONFIGURATION_FILES = ("src/crop_config.json", "src/farm_config.json", "src/growth_model_config.json", "src/crop_phenology.csv", "config/app.json")


def configuration_fingerprint(root: str | Path) -> dict[str, str]:
    root = Path(root)
    registry = ParameterRegistry.from_repository(root)
    return {
        "parameter_registry": _hash([record.to_dict() for record in registry.records]),
        "parameter_sets": _hash({crop: ParameterSet.from_registry(registry, crop=crop).value_map() for crop in KNOWN_CROPS}),
        "phenology_profiles": _hash({key: repr(profile) for key, profile in sorted(APPROXIMATE_PROFILES.items())}),
        "weather_profiles": _hash({"base": dict(BASE_PROFILE), "shifts": {key: dict(value) for key, value in PROFILE_SHIFTS.items()}, "irrigation_factor": dict(IRRIGATION_FACTOR)}),
        "greenhouse_configuration": _hash({"configuration": {f.name: repr(getattr(GreenhouseConfiguration(), f.name)) for f in fields(GreenhouseConfiguration)},
                                           "profiles": {key: repr(value) for key, value in sorted(GREENHOUSE_PROFILES.items())}}),
        "dormancy_default": DEFAULT_DORMANCY_CONFIGURATION.configuration_hash,
        "configuration_files": _hash({name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in CONFIGURATION_FILES if (root / name).exists()}),
    }


def contract_description() -> dict[str, Any]:
    """Machine-readable contract (what a frontend can rely on)."""
    return {
        "api_version": API_VERSION,
        "request_fields": list(REQUEST_FIELDS), "weather_fields": list(WEATHER_FIELDS), "option_fields": list(OPTION_FIELDS), "checkpoint_fields": list(CHECKPOINT_FIELDS),
        "crops": list(KNOWN_CROPS), "environments": dict(ENVIRONMENTS), "greenhouse_crops": list(ANNUAL_GREENHOUSE_CROPS), "scenarios": list(SCENARIOS),
        "weather_sources": list(WEATHER_SOURCES), "profile_keys": sorted(BASE_PROFILE), "chilling_models": [model.value for model in ChillingModelType],
        "statuses": [status.value for status in ExecutionStatus], "modes": [mode.value for mode in ExecutionMode],
        "availability": [item.value for item in Availability], "error_codes": {code.value: ERROR_CATEGORY[code] for code in ErrorCode},
        "variables": [{"name": spec.name, "unit": spec.unit, "scope": spec.scope, "source": spec.source} for spec in VARIABLES],
        "checkpoint_format": CHECKPOINT_FORMAT, "timestep_seconds": TIMESTEP_SECONDS,
        "surface": ["create_simulation", "get_simulation", "start_simulation", "get_simulation_progress", "cancel_simulation", "get_simulation_result",
                    "resume_simulation", "run_simulation", "plan_execution"],
    }


# ---------------------------------------------------------------------------
# Qualification suite (software contract checks; synthetic forcing only)
# ---------------------------------------------------------------------------


def _dynamic_software_test_dormancy() -> dict[str, Any]:
    # Phase 5.35 SOFTWARE_TEST_ONLY threshold (chilling_models_framework.TEST_REQUIREMENTS); not a species requirement.
    from agri_twin.application.chilling_models_framework import software_test_requirement

    return {"start_policy": "DORMANCY_STATE", "chilling_model": "DYNAMIC", "fallback_policy": "STRICT", "chilling_requirement": software_test_requirement("DYNAMIC")}


DETERMINISM_CASES: tuple[tuple[str, dict[str, Any]], ...] = (
    ("tomato_outdoor_7d", {"crop": "tomato", "environment": "outdoor", "end_time": "2026-02-22T00:00:00+00:00"}),
    ("lettuce_greenhouse_full_season", {"crop": "lettuce", "environment": "greenhouse"}),
    ("tomato_outdoor_heat_wave_full_season", {"crop": "tomato", "environment": "outdoor", "scenario": "HEAT_WAVE"}),
    ("pepper_greenhouse_full_season", {"crop": "pepper", "environment": "greenhouse"}),
    ("peach_dynamic_software_test_season", {"crop": "peach", "dormancy": "DYNAMIC_SOFTWARE_TEST"}),
    ("tomato_outdoor_weather_override_14d", {"crop": "tomato", "environment": "outdoor", "end_time": "2026-03-01T00:00:00+00:00",
                                             "weather": {"source": "SYNTHETIC_SEASONAL", "profile_overrides": {"temperature_max_c": 26.0}}}),
)
CHECKPOINT_CASES: tuple[tuple[str, dict[str, Any], str], ...] = (
    ("tomato_outdoor_base", {"crop": "tomato", "environment": "outdoor"}, "2026-04-10T00:00:00+00:00"),
    ("lettuce_greenhouse_base", {"crop": "lettuce", "environment": "greenhouse"}, "2026-01-20T12:00:00+00:00"),
    ("tomato_outdoor_heat_wave_before_window", {"crop": "tomato", "environment": "outdoor", "scenario": "HEAT_WAVE"}, "2026-04-20T00:00:00+00:00"),
    ("peach_chilling_hours_default", {"crop": "peach", "end_time": "2026-06-01T00:00:00+00:00"}, "2026-02-10T00:00:00+00:00"),
    ("peach_dynamic_software_test", {"crop": "peach", "dormancy": "DYNAMIC_SOFTWARE_TEST", "end_time": "2026-06-01T00:00:00+00:00"}, "2026-02-10T00:00:00+00:00"),
)
CANCEL_AT_STEP = 48
REQUIRED_RESULT_VARIABLES = ("crop_stage", "biomass_total_g_m2", "soil_water_vwc_m3_m3", "irrigation_mm", "precipitation_mm", "drainage_mm", "transpiration_mm",
                             "evaporation_mm", "temperature_c", "relative_humidity_pct", "vpd_kpa", "radiation_w_m2", "water_stress", "heat_stress")


def materialize(document: Mapping[str, Any]) -> dict[str, Any]:
    """Expand the DYNAMIC_SOFTWARE_TEST shorthand used by the qualification cases."""
    document = dict(document)
    if document.get("dormancy") == "DYNAMIC_SOFTWARE_TEST":
        document["dormancy"] = _dynamic_software_test_dormancy()
    return document


def negative_cases() -> tuple[tuple[str, Any, ErrorCode, str | None], ...]:
    base = {"crop": "tomato", "environment": "outdoor"}
    return (
        ("request_not_a_mapping", ["tomato"], ErrorCode.INVALID_REQUEST, None),
        ("missing_crop", {"environment": "outdoor"}, ErrorCode.INVALID_REQUEST, "crop"),
        ("unknown_field", {**base, "latitude": 38.0}, ErrorCode.INVALID_REQUEST, "latitude"),
        ("wrong_api_version", {**base, "api_version": "0.9"}, ErrorCode.INVALID_REQUEST, "api_version"),
        ("unknown_crop", {"crop": "banana"}, ErrorCode.UNSUPPORTED_CROP, "crop"),
        ("unknown_environment", {**base, "environment": "vertical_farm"}, ErrorCode.UNSUPPORTED_ENVIRONMENT, "environment"),
        ("actuated_greenhouse_not_exposed", {**base, "environment": "actuated_greenhouse"}, ErrorCode.UNSUPPORTED_ENVIRONMENT, "environment"),
        ("greenhouse_for_perennial", {"crop": "peach", "environment": "greenhouse"}, ErrorCode.UNSUPPORTED_ENVIRONMENT, "environment"),
        ("unconfigured_variety", {**base, "variety": "Cherry"}, ErrorCode.INVALID_CONFIGURATION, "variety"),
        ("unconfigured_plot", {**base, "plot": "plot_99999"}, ErrorCode.INVALID_CONFIGURATION, "plot"),
        ("unknown_scenario", {**base, "scenario": "MONSOON"}, ErrorCode.INVALID_SCENARIO, "scenario"),
        ("naive_timestamp", {**base, "end_time": "2026-03-01T00:00:00"}, ErrorCode.INVALID_REQUEST, "end_time"),
        ("unparseable_timestamp", {**base, "end_time": "1 March"}, ErrorCode.INVALID_REQUEST, "end_time"),
        ("end_before_start", {**base, "end_time": "2026-02-01T00:00:00+00:00"}, ErrorCode.INVALID_TIME_RANGE, "end_time"),
        ("end_equal_start", {**base, "end_time": "2026-02-15T00:00:00+00:00"}, ErrorCode.INVALID_TIME_RANGE, "end_time"),
        ("end_after_campaign", {**base, "end_time": "2026-12-31T00:00:00+00:00"}, ErrorCode.INVALID_TIME_RANGE, "end_time"),
        ("start_not_campaign_start", {**base, "start_time": "2026-03-01T00:00:00+00:00"}, ErrorCode.INVALID_TIME_RANGE, "start_time"),
        ("partial_step_horizon", {**base, "end_time": "2026-02-16T00:30:00+00:00"}, ErrorCode.INVALID_TIME_RANGE, "end_time"),
        ("negative_seed", {**base, "seed": -1}, ErrorCode.INVALID_REQUEST, "seed"),
        ("boolean_seed", {**base, "seed": True}, ErrorCode.INVALID_REQUEST, "seed"),
        ("unsupported_weather_source", {**base, "weather": {"source": "OPEN_METEO"}}, ErrorCode.INVALID_CONFIGURATION, "weather.source"),
        ("unknown_weather_field", {**base, "weather": {"source": "SYNTHETIC_SEASONAL", "station": "x"}}, ErrorCode.INVALID_REQUEST, "weather.station"),
        ("unknown_profile_key", {**base, "weather": {"profile_overrides": {"frost_days": 3}}}, ErrorCode.INVALID_CONFIGURATION, "weather.profile_overrides.frost_days"),
        ("non_finite_profile_value", {**base, "weather": {"profile_overrides": {"temperature_max_c": math.inf}}}, ErrorCode.INVALID_CONFIGURATION,
         "weather.profile_overrides.temperature_max_c"),
        ("inconsistent_profile", {**base, "weather": {"profile_overrides": {"temperature_min_c": 30.0, "temperature_max_c": 10.0}}}, ErrorCode.INVALID_CONFIGURATION,
         "weather.profile_overrides"),
        ("unknown_chilling_model", {"crop": "peach", "dormancy": {"start_policy": "DORMANCY_STATE", "chilling_model": "DYNAMIC_APPROX", "fallback_policy": "STRICT"}},
         ErrorCode.INVALID_CONFIGURATION, "dormancy"),
        ("literature_requirement_not_activated", {"crop": "peach", "dormancy": {**_dynamic_software_test_dormancy(),
                                                                                "chilling_requirement": {"value": 50.0, "unit": "chill_portions", "evidence": "LITERATURE"}}},
         ErrorCode.INVALID_CONFIGURATION, "dormancy"),
        ("requested_model_not_ready", {"crop": "peach", "dormancy": {"start_policy": "DORMANCY_STATE", "chilling_model": "UTAH", "fallback_policy": "STRICT"},
                                       "options": {"require_requested_chilling_model": True}}, ErrorCode.MODEL_NOT_READY, "dormancy.chilling_model"),
        ("unknown_option", {**base, "options": {"threads": 4}}, ErrorCode.INVALID_REQUEST, "options.threads"),
        ("unknown_variable", {**base, "options": {"variables": ["biomass_total_g_m2", "yield_t_ha"]}}, ErrorCode.INVALID_REQUEST, "options.variables[1]"),
        ("malformed_checkpoint", {**base, "checkpoint": {"payload": "{}"}}, ErrorCode.INVALID_CHECKPOINT, "checkpoint"),
    )


def _error_row(case_id: str, code: ErrorCode, path: str | None, call: Callable[[], Any]) -> dict[str, Any]:
    try:
        call()
        observed = observed_path = message = None
    except SimulationApiError as exc:
        observed, observed_path, message = exc.code.value, exc.errors[0].path, exc.errors[0].message
    return {"case": case_id, "expected_code": code.value, "expected_path": path, "code": observed, "path": observed_path, "message": message,
            "passed": observed == code.value and observed_path == path and bool(message)}


def _capture(call: Callable[[], Any]) -> str | None:
    try:
        call()
    except SimulationApiError as exc:
        return exc.code.value
    return None


def _twin_state(payload: Mapping[str, Any]) -> TwinState:
    return TwinState.from_dict(payload)


def _concatenation_equal(full: Mapping[str, list[Any]], first: Mapping[str, list[Any]], second: Mapping[str, list[Any]]) -> bool:
    return full.keys() == first.keys() == second.keys() and all(full[key] == first[key] + second[key] for key in full)


class InteractiveSimulationApiSuite:
    """Builds the Phase 5.37 qualification report for the interactive simulation API."""

    VERSION = VERSION

    def __init__(self, root: str | Path, *, repeats: int = 3, timer: Callable[[], float] | None = None) -> None:
        self.root = Path(root)
        self.repeats = repeats
        self.timer = timer

    def _service(self) -> InteractiveSimulationService:
        return InteractiveSimulationService(timer=self.timer)

    # -- canonical request / response -----------------------------------------------

    def canonical_request(self) -> dict[str, Any]:
        document = {"crop": " Tomato ", "environment": "OUTDOOR", "scenario": "heat_wave", "end_time": "2026-02-22T01:00:00+01:00",
                    "weather": {"profile_overrides": {"temperature_max_c": 26, "humidity_max_pct": 85.0}}}
        first, second = canonicalize_request(document), canonicalize_request(json.loads(json.dumps(document)))
        defaults = canonicalize_request({"crop": "tomato"})
        round_trip = canonicalize_request(json.loads(first.canonical_json()))
        plot = _plot_for("tomato")
        checks = {
            "names_normalized": (first.crop, first.environment, first.scenario) == ("tomato", "outdoor", "HEAT_WAVE"),
            "timestamps_normalized_to_utc": first.end_time.isoformat() == "2026-02-22T00:00:00+00:00",
            "numbers_normalized": dict(first.profile_overrides) == {"humidity_max_pct": 85.0, "temperature_max_c": 26.0},
            "same_request_same_json": first.canonical_json() == second.canonical_json(),
            "json_round_trip_identical": round_trip == first and round_trip.canonical_json() == first.canonical_json(),
            "request_hash_is_sha256_of_canonical_json": first.request_hash == hashlib.sha256(first.canonical_json().encode("utf-8")).hexdigest(),
            "defaults_from_existing_configuration": (defaults.variety, defaults.plot, defaults.environment, defaults.scenario, defaults.seed, defaults.dormancy)
            == (KNOWN_VARIETIES["tomato"], plot.plot_id, plot.environment, DEFAULT_SCENARIO, DEFAULT_SEED, DEFAULT_DORMANCY_CONFIGURATION),
            "different_requests_different_hash": len({canonicalize_request({"crop": "tomato", "seed": seed}).request_hash for seed in (1, 2)}) == 2,
            "no_execution_timestamp_in_request": set(first.to_dict()) == set(REQUEST_FIELDS),
        }
        return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "example_canonical_json": first.canonical_json(), "example_request_hash": first.request_hash}

    def canonical_response(self, response: SimulationResponse) -> dict[str, Any]:
        payload = json.loads(response.to_json())
        required = ("request", "effective_configuration", "execution_status", "progress", "result", "diagnostics", "warnings", "errors", "hashes", "scientific_status")
        checks = {
            "sections_present": all(key in payload for key in required),
            "status_in_contract": payload["execution_status"] in {status.value for status in ExecutionStatus},
            "response_json_round_trip": json.loads(json.dumps(payload, sort_keys=True)) == payload,
            "response_hash_excludes_operational": response.response_hash == _hash({key: value for key, value in payload.items() if key not in {"operational", "response_hash"}}),
            "model_result_separated_from_diagnostics": payload["result"]["result_type"] == "MODEL_RESULT" and payload["diagnostics"]["kind"].startswith("EXECUTION_DIAGNOSTICS"),
            "scientific_status_explicit": payload["scientific_status"] == dict(SCIENTIFIC_STATUS),
            "configuration_hash_matches": payload["hashes"]["configuration_hash"] == _hash(payload["effective_configuration"]),
        }
        return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks}

    # -- determinism and equivalence with the direct execution path -------------------

    def determinism(self) -> dict[str, Any]:
        rows = []
        for case_id, document in DETERMINISM_CASES:
            first, second = (self._service().run_simulation(materialize(document)) for _ in range(2))
            row: dict[str, Any] = {"case": case_id, "status": first.execution_status.value, "mode": first.plan["mode"], "steps": first.progress.completed_steps, **first.hashes,
                                   "response_hash": first.response_hash, "canonical_json_equal": first.request == second.request,
                                   "effective_configuration_equal": first.effective_configuration == second.effective_configuration,
                                   "serialized_response_equal": first.deterministic_dict() == second.deterministic_dict()}
            row.update({f"{name}_equal": first.hashes[name] == second.hashes[name] for name in ("request_hash", "configuration_hash", "trajectory_hash", "result_hash")})
            row["deterministic"] = first.execution_status is ExecutionStatus.COMPLETED and all(value for key, value in row.items() if key.endswith("_equal"))
            rows.append(row)
        return {"status": "PASS" if all(row["deterministic"] for row in rows) else "FAIL", "repetitions": 2, "rows": rows}

    def direct_equivalence(self) -> dict[str, Any]:
        """API trajectory == direct ScenarioRunner trajectory (same engines, no second path)."""
        rows = []
        for case_id, document in (("tomato_outdoor_full_season", {"crop": "tomato", "environment": "outdoor"}),
                                  ("lettuce_greenhouse_full_season", {"crop": "lettuce", "environment": "greenhouse"}),
                                  ("peach_dynamic_software_test_season", {"crop": "peach", "dormancy": "DYNAMIC_SOFTWARE_TEST"})):
            request = canonicalize_request(materialize(document))
            spec = build_campaign(request.crop, request.environment, request.scenario, seed=request.seed)
            phenology = None if request.dormancy == DEFAULT_DORMANCY_CONFIGURATION else PhenologyEngine(dormancy=DormancyChillingController(configuration=request.dormancy))
            direct = ScenarioRunner(seasonal_weather_factory).run(spec.scenario, phenology=phenology)
            api = self._service().run_simulation(request)
            short = self._service().run_simulation({**request.to_dict(), "end_time": (request.start_time + timedelta(days=7)).isoformat()})
            rows.append({"case": case_id, "direct_status": direct.status, "api_status": api.execution_status.value, "steps": len(direct.snapshots),
                         "trajectory_hash_equal": trajectory_hash(direct.snapshots) == api.hashes["trajectory_hash"],
                         "seven_day_horizon_is_exact_prefix": trajectory_hash(direct.snapshots[:7 * 24]) == short.hashes["trajectory_hash"]})
        passed = all(row["trajectory_hash_equal"] and row["seven_day_horizon_is_exact_prefix"] for row in rows)
        return {"status": "PASS" if passed else "FAIL", "rows": rows,
                "definition": "direct = build_campaign + ScenarioRunner(seasonal_weather_factory).run; the API horizon stops the same run at a step boundary (no event clipping)"}

    # -- checkpoint / resume ----------------------------------------------------------

    def checkpoint_resume(self) -> dict[str, Any]:
        rows = []
        for case_id, document, split in CHECKPOINT_CASES:
            document = materialize(document)
            service = self._service()
            full = service.run_simulation(document)
            partial = service.run_simulation({**document, "end_time": split})
            created = service.resume_simulation({**document, "checkpoint": partial.checkpoint.to_dict()})
            resumed = service.start_simulation(created.simulation_id)
            rows.append(self._resume_row(case_id, split, full, partial, resumed))
        rows.append(self._cancel_then_resume())
        return {"status": "PASS" if all(row["equivalent"] for row in rows) else "FAIL", "rows": rows,
                "format": "existing Phase 5.29 checkpoint_payload (crop, soil, microclimate JSON) wrapped with sha256 and resume_hash; restored with restore_checkpoint"}

    @staticmethod
    def _resume_row(case_id: str, split: str, full: SimulationResponse, partial: SimulationResponse, resumed: SimulationResponse) -> dict[str, Any]:
        row = {
            "case": case_id, "checkpoint_time": split, "checkpoint_sha256": partial.checkpoint.sha256, "checkpoint_format": partial.checkpoint.format,
            "steps_full": full.progress.completed_steps, "steps_partial_plus_resumed": partial.progress.completed_steps + resumed.progress.completed_steps,
            "trajectory_concatenation_equal": _concatenation_equal(full.result.trajectory, partial.result.trajectory, resumed.result.trajectory),
            "final_state_equal": full.result.final_state == resumed.result.final_state,
            "final_checkpoint_equal": full.checkpoint.payload == resumed.checkpoint.payload,
        }
        row["equivalent"] = row["steps_full"] == row["steps_partial_plus_resumed"] and row["trajectory_concatenation_equal"] and row["final_state_equal"] and row["final_checkpoint_equal"]
        return row

    def _cancel_then_resume(self) -> dict[str, Any]:
        service = self._service()
        document = {"crop": "tomato", "environment": "outdoor", "end_time": "2026-03-15T00:00:00+00:00", "options": {"progress_interval_steps": 1}}
        full = service.run_simulation(document)
        created = service.create_simulation(document)
        cancelled = service.start_simulation(created.simulation_id, lambda progress: service.cancel_simulation(progress.simulation_id) if progress.completed_steps >= 100 else None)
        resumed = service.run_simulation({**document, "checkpoint": cancelled.checkpoint.to_dict()})
        return self._resume_row("tomato_outdoor_cancelled_at_step_100_then_resumed", cancelled.checkpoint.simulation_time.isoformat(), full, cancelled, resumed)

    # -- progress and cancellation -------------------------------------------------------

    def progress(self) -> dict[str, Any]:
        service = self._service()
        season_events: list[SimulationProgress] = []
        season = service.run_simulation({"crop": "tomato", "environment": "outdoor"}, season_events.append)
        short_events: list[SimulationProgress] = []
        short = service.run_simulation({"crop": "tomato", "environment": "outdoor", "end_time": "2026-02-22T00:00:00+00:00"}, short_events.append)
        trajectory = season.result.trajectory
        fractions = [event.fraction for event in season_events]
        checks = {
            "season_mode_with_progress": season.plan["mode"] == ExecutionMode.INTERACTIVE_WITH_PROGRESS.value,
            "season_daily_events_plus_final": len(season_events) == math.ceil(season.progress.total_steps / DEFAULT_PROGRESS_INTERVAL_STEPS),
            "fraction_monotonic_to_one": fractions == sorted(fractions) and fractions[-1] == 1.0,
            "simulated_time_tracks_steps": all(event.simulated_time.isoformat() == trajectory["time"][event.completed_steps - 1] for event in season_events),
            "stage_matches_trajectory": all(event.current_stage == trajectory["crop_stage"][event.completed_steps - 1] for event in season_events),
            "current_state_is_twin_state": all(_twin_state(event.current_state).to_dict() == dict(event.current_state) for event in season_events),
            "interactive_emits_only_final": short.plan["mode"] == ExecutionMode.INTERACTIVE.value and len(short_events) == 1 and short_events[0].fraction == 1.0,
            "progress_query_after_completion": service.get_simulation_progress(season.simulation_id).completed_steps == season.progress.total_steps,
            "elapsed_time_operational_only": all("elapsed_seconds" not in event.deterministic_dict() for event in season_events),
        }
        return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "season_events": len(season_events), "interval_steps": DEFAULT_PROGRESS_INTERVAL_STEPS}

    def cancellation(self) -> dict[str, Any]:
        before = configuration_fingerprint(self.root)
        document = {"crop": "tomato", "environment": "outdoor"}

        def cancel_at(service: InteractiveSimulationService) -> SimulationResponse:
            created = service.create_simulation({**document, "options": {"progress_interval_steps": 1}})
            return service.start_simulation(created.simulation_id, lambda progress: service.cancel_simulation(progress.simulation_id) if progress.completed_steps >= CANCEL_AT_STEP else None)

        first, second = cancel_at(self._service()), cancel_at(self._service())
        service = self._service()
        early = service.cancel_simulation(service.create_simulation(document).simulation_id)
        reference = self._service().run_simulation({**document, "end_time": "2026-02-17T00:00:00+00:00"})
        checks = {
            "cancelled_at_step_boundary": first.execution_status is ExecutionStatus.CANCELLED and first.progress.completed_steps == CANCEL_AT_STEP,
            "deterministic_cancelled_state": first.deterministic_dict() == second.deterministic_dict(),
            "partial_result_marked_incomplete": first.result is not None and not first.result.complete,
            "partial_trajectory_equals_completed_prefix": first.result.trajectory == reference.result.trajectory and first.checkpoint.payload == reference.checkpoint.payload,
            "cancellation_is_operational_not_scientific": [error.to_dict()["category"] for error in first.errors] == ["OPERATIONAL"] and first.errors[0].code is ErrorCode.CANCELLATION_REQUESTED,
            "cancel_before_start": early.execution_status is ExecutionStatus.CANCELLED and early.result is None and early.checkpoint is None,
            "result_query_reports_cancellation": _capture(lambda: service.get_simulation_result(early.simulation_id)) == ErrorCode.CANCELLATION_REQUESTED.value,
            "terminal_cancel_rejected": _capture(lambda: service.cancel_simulation(early.simulation_id)) == ErrorCode.INVALID_REQUEST.value,
            "no_restart_of_terminal_execution": _capture(lambda: service.start_simulation(early.simulation_id)) == ErrorCode.INVALID_REQUEST.value,
            "registry_and_configuration_unchanged": configuration_fingerprint(self.root) == before,
        }
        return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "cancel_at_step": CANCEL_AT_STEP,
                "mechanism": "cooperative flag observed by the ScenarioRunner observer at the next step boundary; no thread, timer or scheduler"}

    # -- errors -------------------------------------------------------------------------

    def errors(self) -> dict[str, Any]:
        rows = [_error_row(case_id, code, path, lambda document=document: canonicalize_request(document)) for case_id, document, code, path in negative_cases()]
        rows += self._runtime_errors()
        return {"status": "PASS" if all(row["passed"] for row in rows) else "FAIL", "rows": rows,
                "codes_covered": sorted({row["code"] for row in rows if row["code"]}), "error_codes": [code.value for code in ErrorCode]}

    def _runtime_errors(self) -> list[dict[str, Any]]:
        service = self._service()
        base = {"crop": "tomato", "environment": "outdoor"}
        checkpoint = service.run_simulation({**base, "end_time": "2026-02-20T00:00:00+00:00"}).checkpoint.to_dict()
        tampered = {**checkpoint, "payload": checkpoint["payload"].replace('"vwc_m3_m3": 0.', '"vwc_m3_m3": 1.', 1)}
        heat = {**base, "scenario": "HEAT_WAVE"}
        window_start = build_campaign("tomato", "outdoor", "HEAT_WAVE").window[0]
        inside = service.run_simulation({**heat, "end_time": (window_start + timedelta(days=2)).isoformat()}).checkpoint.to_dict()
        rows = [
            _error_row("checkpoint_tampered_payload", ErrorCode.INVALID_CHECKPOINT, "checkpoint.sha256", lambda: canonicalize_request({**base, "checkpoint": tampered})),
            _error_row("checkpoint_other_configuration", ErrorCode.INVALID_CHECKPOINT, "checkpoint.resume_hash", lambda: canonicalize_request({**base, "seed": 7, "checkpoint": checkpoint})),
            _error_row("checkpoint_other_crop", ErrorCode.INVALID_CHECKPOINT, "checkpoint.resume_hash", lambda: canonicalize_request({"crop": "pepper", "environment": "outdoor", "checkpoint": checkpoint})),
            _error_row("start_time_conflicts_with_checkpoint", ErrorCode.INVALID_TIME_RANGE, "start_time",
                       lambda: canonicalize_request({**base, "start_time": "2026-02-15T00:00:00+00:00", "checkpoint": checkpoint})),
            _error_row("resume_without_checkpoint", ErrorCode.INVALID_CHECKPOINT, "checkpoint", lambda: service.resume_simulation({"crop": "tomato"})),
            _error_row("checkpoint_inside_ramped_event", ErrorCode.INVALID_CHECKPOINT, "checkpoint.simulation_time", lambda: service.create_simulation({**heat, "checkpoint": inside})),
            _error_row("unknown_simulation_id", ErrorCode.INVALID_REQUEST, "simulation_id", lambda: service.get_simulation("sim-000000-unknown")),
            _error_row("result_before_completion", ErrorCode.INVALID_REQUEST, "simulation_id", lambda: service.get_simulation_result(service.create_simulation({"crop": "lettuce"}).simulation_id)),
        ]

        def failing_listener(_progress: SimulationProgress) -> None:
            raise RuntimeError("frontend callback failure")

        failed = service.run_simulation({**base, "end_time": "2026-02-18T00:00:00+00:00", "options": {"progress_interval_steps": 12}}, failing_listener)
        rows.append({"case": "listener_failure_is_execution_error", "expected_code": ErrorCode.INTERNAL_EXECUTION_ERROR.value, "expected_path": None,
                     "code": failed.errors[0].code.value if failed.errors else None, "path": None, "message": failed.errors[0].message if failed.errors else None,
                     "passed": failed.execution_status is ExecutionStatus.FAILED and bool(failed.errors) and failed.errors[0].code is ErrorCode.INTERNAL_EXECUTION_ERROR
                     and failed.progress.completed_steps == 12})
        rows.append(_error_row("failed_result_query", ErrorCode.INTERNAL_EXECUTION_ERROR, None, lambda: service.get_simulation_result(failed.simulation_id)))
        return rows

    # -- result contract ----------------------------------------------------------------

    def result_contract(self) -> dict[str, Any]:
        rows = []
        for case_id, document in (("tomato_outdoor_14d", {"crop": "tomato", "environment": "outdoor", "end_time": "2026-03-01T00:00:00+00:00"}),
                                  ("tomato_greenhouse_14d", {"crop": "tomato", "environment": "greenhouse", "end_time": "2026-03-01T00:00:00+00:00"}),
                                  ("peach_outdoor_14d", {"crop": "peach", "end_time": "2026-02-15T00:00:00+00:00"})):
            result = self._service().run_simulation(document).result
            availability = {item["name"]: item["availability"] for item in result.variables}
            series = {key: value for key, value in result.trajectory.items() if key != "time"}
            numeric = [value for values in series.values() for value in values if isinstance(value, float)]
            rows.append({
                "case": case_id, "availability": availability,
                "series_only_for_available": set(series) == {name for name, value in availability.items() if value == Availability.AVAILABLE.value},
                "series_length_equals_steps": all(len(values) == result.steps for values in series.values()) and len(result.trajectory["time"]) == result.steps,
                "values_finite": all(math.isfinite(value) for value in numeric),
                "not_supported_never_fabricated": all(value == Availability.NOT_SUPPORTED.value for name, value in availability.items() if VARIABLE_INDEX[name].scope == "NONE"),
                "final_state_twin_state_round_trip": _twin_state(result.final_state).to_dict() == dict(result.final_state),
            })
        outdoor, greenhouse, perennial = (row["availability"] for row in rows)
        expectations = {
            "outdoor_co2_not_applicable": outdoor["co2_ppm"] == Availability.NOT_APPLICABLE.value,
            "greenhouse_co2_available": greenhouse["co2_ppm"] == Availability.AVAILABLE.value,
            "greenhouse_state_available_indoors": greenhouse["greenhouse_ventilation_fraction"] == Availability.AVAILABLE.value,
            "annual_chilling_not_applicable": outdoor["chilling_accumulated"] == Availability.NOT_APPLICABLE.value,
            "perennial_chilling_available": perennial["chilling_accumulated"] == Availability.AVAILABLE.value,
            "required_variables_available": all(outdoor[name] == Availability.AVAILABLE.value for name in REQUIRED_RESULT_VARIABLES),
        }
        selected = self._service().run_simulation({"crop": "tomato", "environment": "outdoor", "end_time": "2026-02-16T00:00:00+00:00",
                                                    "options": {"variables": ["vpd_kpa", "co2_ppm", "fruit_count", "biomass_total_g_m2"]}}).result
        expectations["variable_selection"] = [item["name"] for item in selected.variables] == ["biomass_total_g_m2", "vpd_kpa", "co2_ppm", "fruit_count"] \
            and set(selected.trajectory) == {"time", "biomass_total_g_m2", "vpd_kpa"}
        passed = all(expectations.values()) and all(value for row in rows for key, value in row.items() if key not in {"case", "availability"})
        return {"status": "PASS" if passed else "FAIL", "expectations": expectations, "rows": rows}

    # -- classification -----------------------------------------------------------------

    def classification(self) -> dict[str, Any]:
        def plan(*documents: Mapping[str, Any]) -> ExecutionPlan:
            return plan_execution(tuple(canonicalize_request(document) for document in documents))

        cases = {
            "tomato_outdoor_7d": (plan({"crop": "tomato", "environment": "outdoor", "end_time": "2026-02-22T00:00:00+00:00"}), ExecutionMode.INTERACTIVE),
            "lettuce_greenhouse_full_season": (plan({"crop": "lettuce", "environment": "greenhouse"}), ExecutionMode.INTERACTIVE),
            "tomato_outdoor_full_season": (plan({"crop": "tomato", "environment": "outdoor"}), ExecutionMode.INTERACTIVE_WITH_PROGRESS),
            "grape_outdoor_full_season": (plan({"crop": "grape"}), ExecutionMode.INTERACTIVE_WITH_PROGRESS),
            "seven_crops_multi_plot": (plan(*({"crop": crop} for crop in KNOWN_CROPS)), ExecutionMode.BACKGROUND),
            "tomato_eight_scenarios": (plan(*({"crop": "tomato", "environment": "outdoor", "scenario": scenario} for scenario in SCENARIOS[:8])), ExecutionMode.BACKGROUND),
        }
        rows = {name: {key: value for key, value in plan_.to_dict().items() if key != "cost_model"} | {"expected": expected.value, "passed": plan_.mode is expected}
                for name, (plan_, expected) in cases.items()}
        return {"status": "PASS" if all(row["passed"] for row in rows.values()) else "FAIL", "rows": rows, "cost_model": dict(COST_MODEL),
                "rule": "BACKGROUND if more than one request (multi-plot / campaign) or estimate > 10 s; INTERACTIVE if estimate <= 1 s; otherwise INTERACTIVE_WITH_PROGRESS. "
                        "Derived from configuration; no simulation is run to decide."}

    # -- immutability -------------------------------------------------------------------

    def immutability(self, before: Mapping[str, str]) -> dict[str, Any]:
        service = self._service()
        document = {"crop": "peach", "dormancy": _dynamic_software_test_dormancy(), "end_time": "2026-02-08T00:00:00+00:00", "options": {"progress_interval_steps": 24}}
        frozen_document = json.loads(json.dumps(document))
        spec_before = build_campaign("peach", "outdoor", DEFAULT_SCENARIO)
        events: list[SimulationProgress] = []
        response = service.run_simulation(document, events.append)
        resumed_input = response.checkpoint.to_dict()
        frozen_checkpoint = json.loads(json.dumps(resumed_input))
        service.run_simulation({**document, "end_time": "2026-02-12T00:00:00+00:00", "checkpoint": resumed_input})
        after = configuration_fingerprint(self.root)
        checks = {
            "fingerprint_unchanged": after == dict(before),
            "request_document_not_mutated": document == frozen_document,
            "checkpoint_input_not_mutated": resumed_input == frozen_checkpoint,
            "campaign_definition_unchanged": build_campaign("peach", "outdoor", DEFAULT_SCENARIO) == spec_before,
            "returned_twin_state_is_detached_copy": _twin_state(response.result.final_state).to_dict() == dict(response.result.final_state) and response.result.final_state is not response.progress.current_state,
            "progress_state_matches_trajectory": all(event.current_state["biomass_g_m2"] == response.result.trajectory["biomass_total_g_m2"][event.completed_steps - 1] for event in events),
            "default_dormancy_unchanged": DEFAULT_DORMANCY_CONFIGURATION.configuration_hash == dict(before)["dormancy_default"],
        }
        return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "before": dict(before), "after": after}

    # -- performance ------------------------------------------------------------------

    def performance(self) -> dict[str, Any]:
        """Requires an injected timer (the API layer itself reads no clock)."""
        if self.timer is None:
            raise ValueError("performance measurement needs an injected timer, e.g. time.perf_counter from the caller")
        rows = []
        for case_id, document in (("tomato_outdoor_7d", {"crop": "tomato", "environment": "outdoor", "end_time": "2026-02-22T00:00:00+00:00"}),
                                  ("lettuce_greenhouse_full_season", {"crop": "lettuce", "environment": "greenhouse"}),
                                  ("tomato_outdoor_full_season", {"crop": "tomato", "environment": "outdoor"})):
            request = canonicalize_request(document)
            scenario = build_campaign(request.crop, request.environment, request.scenario, seed=request.seed).scenario
            limit = request.total_steps
            direct_seconds = self._min(lambda: ScenarioRunner(seasonal_weather_factory).run(scenario, observer=lambda _snapshot, completed: completed < limit))
            measures: dict[str, list[float]] = {}
            for _ in range(self.repeats):
                for label, options in (("no_hash", {"compute_trajectory_hash": False}), ("with_hash", {})):
                    started = self.timer()
                    response = self._service().run_simulation({**document, "options": options})
                    total = self.timer() - started
                    serialized = self.timer()
                    text = response.to_json()
                    serialization = self.timer() - serialized
                    for key, value in {**response.operational["timings_seconds"], "api_total_seconds": total, "serialization_seconds": serialization, "response_bytes": float(len(text))}.items():
                        measures.setdefault(f"{label}.{key}", []).append(value)
            best = {key: min(values) for key, values in measures.items()}
            rows.append({
                "case": case_id, "steps": limit, "direct_execution_seconds": direct_seconds,
                "SIMULATION_TIME": best["no_hash.simulation_seconds"],
                "API_OVERHEAD": {"canonicalization_seconds": best["no_hash.canonicalization_seconds"], "preparation_seconds": best["no_hash.preparation_seconds"],
                                 "result_projection_seconds": best["no_hash.result_projection_seconds"],
                                 "api_total_minus_direct_seconds": best["no_hash.api_total_seconds"] - direct_seconds,
                                 "relative_to_direct": (best["no_hash.api_total_seconds"] - direct_seconds) / direct_seconds},
                "OPTIONAL_TRAJECTORY_HASH": {"result_projection_with_hash_seconds": best["with_hash.result_projection_seconds"],
                                             "api_total_minus_direct_seconds": best["with_hash.api_total_seconds"] - direct_seconds,
                                             "relative_to_direct": (best["with_hash.api_total_seconds"] - direct_seconds) / direct_seconds},
                "SERIALIZATION_TIME": {"to_json_seconds": best["no_hash.serialization_seconds"], "response_bytes": int(best["no_hash.response_bytes"])},
            })
        document = {"crop": "tomato", "environment": "outdoor", "scenario": "HEAT_WAVE", "weather": {"profile_overrides": {"temperature_max_c": 26.0}}}
        return {"rows": rows, "canonicalization_seconds_per_request": self._min(lambda: canonicalize_request(document), repeats=max(self.repeats, 50)), "repeats": self.repeats,
                "method": "caller-injected timer (time.perf_counter in the manual and tests), minimum of sequential repeats; direct = ScenarioRunner with the same horizon observer; machine-dependent, never hashed",
                "classification": "PERFORMANCE_MEASUREMENT"}

    def _min(self, function: Callable[[], Any], repeats: int | None = None) -> float:
        best = math.inf
        for _ in range(repeats or self.repeats):
            started = self.timer()
            function()
            best = min(best, self.timer() - started)
        return best

    # -- report -------------------------------------------------------------------------

    def build_report(self, *, include_performance: bool = True) -> "InteractiveSimulationApiReport":
        before = configuration_fingerprint(self.root)
        example = self._service().run_simulation({"crop": "tomato", "environment": "outdoor", "end_time": "2026-02-22T00:00:00+00:00"})
        sections: dict[str, dict[str, Any]] = {
            "canonical_request": self.canonical_request(),
            "canonical_response": self.canonical_response(example),
            "determinism": self.determinism(),
            "direct_equivalence": self.direct_equivalence(),
            "checkpoint_resume": self.checkpoint_resume(),
            "progress": self.progress(),
            "cancellation": self.cancellation(),
            "errors": self.errors(),
            "result_contract": self.result_contract(),
            "classification": self.classification(),
            "scientific_status": {"status": "PASS" if example.deterministic_dict()["scientific_status"] == dict(SCIENTIFIC_STATUS) and SCIENTIFIC_STATUS["REAL_VERIFIED"] == 0 else "FAIL",
                                  "propagated": dict(SCIENTIFIC_STATUS)},
            "static_audit": static_audit_api(self.root),
        }
        sections["immutability"] = self.immutability(before)
        return InteractiveSimulationApiReport(sections, self.performance() if include_performance and self.timer is not None else None)


# ---------------------------------------------------------------------------
# Static audit of the API layer
# ---------------------------------------------------------------------------


AUDITED_FILES = (
    "src/agri_twin/application/interactive_simulation.py",
    "src/agri_twin/application/scenarios.py",
    "src/agri_twin/application/integrated_synthetic_validation.py",
    "manual_phase5_37_interactive_simulation_api_test.py",
)
API_FORBIDDEN_CALLS = frozenset({"datetime.now", "datetime.utcnow", "datetime.today", "date.today", "time.time", "time.sleep", "asyncio.sleep", "sleep"})
API_FORBIDDEN_CALL_PREFIXES = ("random.", "np.random.", "numpy.random.")
API_FORBIDDEN_IMPORTS = frozenset({"random", "socket", "requests", "urllib", "http", "httpx", "aiohttp", "serial", "threading", "multiprocessing", "asyncio",
                                   "concurrent", "celery", "redis", "pika", "fastapi", "flask"})
CORE_CLASS_SUFFIXES = ("Engine", "Clock", "Scheduler", "Registry", "TwinState", "Orchestrator", "Runner")


def _dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def static_audit_api(root: str | Path) -> dict[str, Any]:
    """AST audit of the new/modified files plus the project-wide single-core-component audit."""
    root = Path(root)
    violations: list[dict[str, Any]] = []
    for name in AUDITED_FILES:
        path = root / name
        if not path.exists():
            violations.append({"file": name, "line": 0, "rule": "missing_file", "detail": name})
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                called = _dotted_name(node.func)
                if called in API_FORBIDDEN_CALLS or called.startswith(API_FORBIDDEN_CALL_PREFIXES):
                    violations.append({"file": name, "line": node.lineno, "rule": "wall_clock_sleep_or_global_random", "detail": called})
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                for module in modules:
                    if module.split(".")[0] in API_FORBIDDEN_IMPORTS or module.startswith("numpy.random"):
                        violations.append({"file": name, "line": node.lineno, "rule": "network_hardware_queue_or_concurrency_import", "detail": module})
            elif isinstance(node, ast.ClassDef) and name == AUDITED_FILES[0] and (node.name in SINGLETON_CLASSES or node.name.endswith(CORE_CLASS_SUFFIXES)):
                violations.append({"file": name, "line": node.lineno, "rule": "second_core_component", "detail": node.name})
    project = static_audit(root)
    passed = not violations and not project["violations"] and not project["duplicate_core_classes"] and not project["missing_core_classes"]
    return {
        "status": "PASS" if passed else "FAIL", "audited_files": list(AUDITED_FILES), "violations": violations,
        "project_static_audit": {key: project[key] for key in ("status", "scanned_files", "violations", "duplicate_core_classes", "missing_core_classes")},
        "single_core_components": sorted(name for name in SINGLETON_CLASSES if name not in project["duplicate_core_classes"]),
        "operational_timer": {"clock_reads_in_api_module": sum(isinstance(node, ast.Attribute) and node.attr in {"perf_counter", "process_time", "monotonic"}
                                                         for node in ast.walk(ast.parse((root / AUDITED_FILES[0]).read_text(encoding="utf-8")))),
                              "use": "none: callers inject a timer for operational timings, excluded from every hash"},
        "rules": {"forbidden_calls": sorted(API_FORBIDDEN_CALLS), "forbidden_call_prefixes": list(API_FORBIDDEN_CALL_PREFIXES),
                  "forbidden_imports": sorted(API_FORBIDDEN_IMPORTS), "core_class_suffixes": list(CORE_CLASS_SUFFIXES)},
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


LIMITATIONS = (
    "start_time is fixed by the crop's synthetic cycle; the horizon is set with end_time, a later start only through a checkpoint",
    "a checkpoint inside a ramped scenario event is rejected (INVALID_CHECKPOINT): the existing resumed_scenario re-anchors event ramps",
    "weather is the Phase 5.32 synthetic seasonal generator only; local CSV / downloaded weather is not exposed by API 1.0",
    "execution is synchronous and in-process; BACKGROUND plans are classified, a decoupled executor is a future adapter",
    "the execution-mode estimate uses the Phase 5.36 per-step cost measured on one machine (advisory)",
    "the actuated greenhouse mode is not exposed (no actuator schedule contract yet)",
    "one configured variety and plot per crop (the existing synthetic plots); other varieties are rejected, never invented",
)


def _json_ready(value: Any) -> Any:
    return None if value is None else json.loads(json.dumps(value, sort_keys=True, default=str))


@dataclass(frozen=True, slots=True)
class InteractiveSimulationApiReport:
    sections: Mapping[str, Mapping[str, Any]]
    performance: Mapping[str, Any] | None

    @property
    def status(self) -> str:
        return "PASS" if all(section.get("status") == "PASS" for section in self.sections.values()) else "FAIL"

    def deterministic_view(self) -> dict[str, Any]:
        """Report content without PERFORMANCE_MEASUREMENT (equal for repeated builds)."""
        return {"version": VERSION, "api_version": API_VERSION, "contract": contract_description(), "software_result": _json_ready(self.sections)}

    @property
    def deterministic_hash(self) -> str:
        return _hash(self.deterministic_view())

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": "5.37", "title": "Interactive simulation API and execution contract", "version": VERSION, "api_version": API_VERSION, "status": self.status,
            "contract": contract_description(), "software_result": _json_ready(self.sections), "performance_measurement": _json_ready(self.performance),
            "scientific_evidence": [], "deterministic_hash": self.deterministic_hash, "scientific_status": dict(SCIENTIFIC_STATUS),
            "real_agricultural_data_verified": False, "calibration_performed": False, "experimental_validation_performed": False,
            "biological_validity_claimed": False, "field_accuracy_claimed": False, "data_assimilation_implemented": False,
            "limitations": list(LIMITATIONS),
        }


def write_report(report: InteractiveSimulationApiReport, directory: str | Path) -> tuple[Path, Path]:
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    payload = report.to_dict()
    report_path, readme_path = output / "interactive_simulation_api_report.json", output / "interactive_simulation_api_README.md"
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    software = payload["software_result"]
    lines = [
        "# Interactive simulation API and execution contract (Phase 5.37)",
        "",
        "SOFTWARE_RESULT: contract, determinism, checkpoint/resume, cancellation, error, result, immutability and static-audit checks.",
        "PERFORMANCE_MEASUREMENT: machine-dependent timings, never hashed. SCIENTIFIC_EVIDENCE: none.",
        "",
        f"- status: `{payload['status']}`; deterministic hash: `{payload['deterministic_hash']}`; API version `{payload['api_version']}`",
        "",
        "## Sections",
        "",
        "| Section | Status |",
        "|---|---|",
        *[f"| {name} | {section['status']} |" for name, section in software.items()],
        "",
        "## Determinism (two executions per case)",
        "",
        "| Case | Mode | Steps | Trajectory hash | Deterministic |",
        "|---|---|---|---|---|",
        *[f"| {row['case']} | {row['mode']} | {row['steps']} | `{row['trajectory_hash'][:16]}` | {row['deterministic']} |" for row in software["determinism"]["rows"]],
        "",
        "## Checkpoint / resume (full == partial + checkpoint + resume)",
        "",
        "| Case | Checkpoint | Steps | Equivalent |",
        "|---|---|---|---|",
        *[f"| {row['case']} | {row['checkpoint_time']} | {row['steps_full']} | {row['equivalent']} |" for row in software["checkpoint_resume"]["rows"]],
    ]
    performance = payload["performance_measurement"]
    if performance:
        lines += [
            "", "## Performance (seconds; minimum of sequential repeats)", "",
            "| Case | Steps | Direct | API simulation | API overhead | Overhead % | With trajectory hash % | to_json | Bytes |",
            "|---|---|---|---|---|---|---|---|---|",
            *[f"| {row['case']} | {row['steps']} | {row['direct_execution_seconds']:.3f} | {row['SIMULATION_TIME']:.3f} | {row['API_OVERHEAD']['api_total_minus_direct_seconds']:.4f} | "
              f"{100 * row['API_OVERHEAD']['relative_to_direct']:.1f} | {100 * row['OPTIONAL_TRAJECTORY_HASH']['relative_to_direct']:.1f} | "
              f"{row['SERIALIZATION_TIME']['to_json_seconds']:.3f} | {row['SERIALIZATION_TIME']['response_bytes']} |" for row in performance["rows"]],
            "", f"Canonicalization per request: {1000 * performance['canonicalization_seconds_per_request']:.3f} ms.",
        ]
    lines += ["", "## Limitations", "", *[f"- {item}" for item in payload["limitations"]], "", "## Scientific status", "",
              "REAL_VERIFIED = 0; CALIBRATION_PERFORMED = false; EXPERIMENTAL_VALIDATION_PERFORMED = false; BIOLOGICAL_VALIDITY_CLAIMED = false; "
              "FIELD_ACCURACY_CLAIMED = false; DATA_ASSIMILATION_IMPLEMENTED = false.", ""]
    readme_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path, readme_path
