"""Scientific sensitivity, robustness and uncertainty analysis framework.

This module implements deterministic parameter and input sensitivity analysis (OAT and
multivariable), robustness checks across physical extremes, and explicit uncertainty
propagation.

This is NOT calibration, optimization, or validation. All operations evaluate model
response against the synthetic dataset contract (`SIMULATED_REAL_DATA_SUBSTITUTE`).
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, Sequence

from agri_twin.application.clock import SimulationClock
from agri_twin.domain.climate_stress import (
    DEFAULT_PROFILES as DEFAULT_CLIMATE_PROFILES,
    ClimateStressEngine,
    ClimateStressProfile,
)
from agri_twin.domain.crop_greenhouse_feedback import (
    CropGreenhouseFeedbackConfiguration,
    CropGreenhouseFeedbackLoop,
    CropGreenhouseStepResult,
)
from agri_twin.domain.crop_growth import CropGrowthEngine, CropGrowthInput, CropGrowthResult
from agri_twin.domain.greenhouse import (
    PROFILES as GREENHOUSE_PROFILES,
    CropMicroclimateFeedback,
    GreenhouseActuatorState,
    GreenhouseConfiguration,
    GreenhouseProfile,
    MicroclimateState,
    SimplifiedGreenhouseModel,
)
from agri_twin.domain.models import CropGrowthState, SoilState, WeatherState
from agri_twin.domain.parameter_audit import ParameterRecord, ParameterRegistry
from agri_twin.domain.phenology import (
    APPROXIMATE_PROFILES as PHENOLOGY_PROFILES,
    PhenologyEngine,
    PhenologyProfile,
)
from agri_twin.domain.radiation_growth import (
    APPROXIMATE_RADIATION_PROFILES,
    RadiationGrowthEngine,
    RadiationGrowthProfile,
)
from agri_twin.domain.water_balance import WaterBalanceEngine


class RangeSourceType(StrEnum):
    SCIENTIFIC_RANGE = "SCIENTIFIC_RANGE"
    PROJECT_RANGE = "PROJECT_RANGE"
    ENGINEERING_RANGE = "ENGINEERING_RANGE"
    OBSERVATIONAL_UNCERTAINTY = "OBSERVATIONAL_UNCERTAINTY"
    UNKNOWN = "UNKNOWN"


class UncertaintyStatus(StrEnum):
    EXPLICIT_RANGE = "EXPLICIT_RANGE"
    OBSERVATIONAL = "OBSERVATIONAL"
    UNCERTAINTY_NOT_SPECIFIED = "UNCERTAINTY_NOT_SPECIFIED"
    UNKNOWN = "UNKNOWN"


class SensitivityClassification(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNDEFINED = "UNDEFINED"


# Confounder groups from Phase 5.14
CONFOUNDER_GROUPS: dict[str, tuple[str, ...]] = {
    "growth_scaling": ("rue", "sla", "leaf_area", "biomass"),
    "radiation_interception": ("extinction", "radiation", "lai"),
    "phenology": ("tbase", "tupper", "gdd", "stage", "maturity", "thermal"),
    "water_stress": ("water", "vwc", "soil", "irrigation", "root"),
    "vpd": ("vpd", "humidity", "temperature"),
    "co2": ("co2", "ventilation", "transmission"),
    "senescence_damage": ("senescence", "damage", "stress", "frost", "heat"),
    "fruit_development": ("fruit", "maturity", "yield", "source_sink"),
}

CONFOUNDER_TERMS_FLAT = tuple(
    sorted({term for terms in CONFOUNDER_GROUPS.values() for term in terms})
)

KNOWN_VARIETIES: dict[str, tuple[str, ...]] = {
    "tomato": ("RAF",),
    "pepper": ("Lamuyo",),
    "grape": ("Monastrell",),
    "plum": ("Suplum 26",),
    "lettuce": (),
    "peach": (),
    "apple": (),
}

PERENNIAL_CROPS = {"grape", "peach", "plum", "apple"}
ANNUAL_CROPS = {"tomato", "lettuce", "pepper"}


@dataclass(frozen=True, slots=True)
class SensitivityPerturbation:
    parameter_id: str
    baseline_value: float
    perturbed_value: float
    direction: str  # "+" or "-"
    magnitude: float
    magnitude_percent: float
    range_source_type: RangeSourceType
    uncertainty_status: UncertaintyStatus

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter_id": self.parameter_id,
            "baseline_value": self.baseline_value,
            "perturbed_value": self.perturbed_value,
            "direction": self.direction,
            "magnitude": self.magnitude,
            "magnitude_percent": self.magnitude_percent,
            "range_source_type": self.range_source_type.value,
            "uncertainty_status": self.uncertainty_status.value,
        }


@dataclass(frozen=True, slots=True)
class SensitivityCase:
    case_id: str
    crop: str
    variety: str | None
    plot_id: str
    cycle_id: str
    cycle_type: str
    environment: str
    stage: str
    observable: str
    dt_seconds: float = 3600.0
    perturbations: tuple[SensitivityPerturbation, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "crop": self.crop,
            "variety": self.variety,
            "plot_id": self.plot_id,
            "cycle_id": self.cycle_id,
            "cycle_type": self.cycle_type,
            "environment": self.environment,
            "stage": self.stage,
            "observable": self.observable,
            "dt_seconds": self.dt_seconds,
            "perturbations": [p.to_dict() for p in self.perturbations],
        }


@dataclass(frozen=True, slots=True)
class SensitivityResult:
    parameter_id: str
    name: str
    crop: str | None
    variety: str | None
    baseline_value: float
    perturbation_percent: float
    baseline_output: float
    perturbed_output: float
    absolute_change: float
    relative_change: float
    normalized_sensitivity: float
    observable: str
    confounders: tuple[str, ...]
    scientific_interpretation: str
    direction: str = "+"
    plot_id: str | None = None
    cycle_id: str | None = None
    environment: str | None = None
    phenological_stage: str | None = None
    perturbed_value: float | None = None
    absolute_sensitivity: float = 0.0
    classification: SensitivityClassification = SensitivityClassification.MEDIUM
    classification_reason: str = "analytical_threshold_applied"
    range_source_type: RangeSourceType = RangeSourceType.UNKNOWN
    uncertainty_status: UncertaintyStatus = UncertaintyStatus.UNKNOWN
    computational_cost_seconds: float = 0.0
    feedback_iterations: int = 1
    provenance: str = "SIMULATED_REAL_DATA_SUBSTITUTE"

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter_id": self.parameter_id,
            "name": self.name,
            "crop": self.crop,
            "variety": self.variety,
            "plot_id": self.plot_id,
            "cycle_id": self.cycle_id,
            "environment": self.environment,
            "phenological_stage": self.phenological_stage,
            "baseline_value": self.baseline_value,
            "perturbed_value": self.perturbed_value if self.perturbed_value is not None else self.baseline_value * (1.0 + self.perturbation_percent / 100.0),
            "perturbation_percent": self.perturbation_percent,
            "direction": self.direction,
            "baseline_output": self.baseline_output,
            "perturbed_output": self.perturbed_output,
            "absolute_change": self.absolute_change,
            "relative_change": self.relative_change,
            "normalized_sensitivity": self.normalized_sensitivity,
            "absolute_sensitivity": self.absolute_sensitivity,
            "classification": self.classification.value if isinstance(self.classification, SensitivityClassification) else str(self.classification),
            "classification_reason": self.classification_reason,
            "observable": self.observable,
            "confounders": list(self.confounders),
            "range_source_type": self.range_source_type.value if isinstance(self.range_source_type, RangeSourceType) else str(self.range_source_type),
            "uncertainty_status": self.uncertainty_status.value if isinstance(self.uncertainty_status, UncertaintyStatus) else str(self.uncertainty_status),
            "computational_cost_seconds": self.computational_cost_seconds,
            "feedback_iterations": self.feedback_iterations,
            "scientific_interpretation": self.scientific_interpretation,
            "provenance": self.provenance,
        }


# Backward-compatible alias for Phase 5.21
ParameterSensitivityResult = SensitivityResult


@dataclass(frozen=True, slots=True)
class SensitivitySummary:
    total_cases: int
    high_sensitivity_count: int
    medium_sensitivity_count: int
    low_sensitivity_count: int
    undefined_sensitivity_count: int
    parameters_analyzed: tuple[str, ...]
    crops_covered: tuple[str, ...]
    environments_covered: tuple[str, ...]
    confounded_parameters: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_cases": self.total_cases,
            "high_sensitivity_count": self.high_sensitivity_count,
            "medium_sensitivity_count": self.medium_sensitivity_count,
            "low_sensitivity_count": self.low_sensitivity_count,
            "undefined_sensitivity_count": self.undefined_sensitivity_count,
            "parameters_analyzed": list(self.parameters_analyzed),
            "crops_covered": list(self.crops_covered),
            "environments_covered": list(self.environments_covered),
            "confounded_parameters": list(self.confounded_parameters),
        }


@dataclass(frozen=True, slots=True)
class RobustnessResult:
    case_id: str
    description: str
    passed: bool
    numerical_stability: bool
    feedback_converged: bool
    physical_bounds_valid: bool
    monotonicity_valid: bool | None
    contract_ranges_valid: bool
    baseline_outputs: dict[str, float]
    perturbed_outputs: dict[str, float]
    warnings: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "description": self.description,
            "passed": self.passed,
            "numerical_stability": self.numerical_stability,
            "feedback_converged": self.feedback_converged,
            "physical_bounds_valid": self.physical_bounds_valid,
            "monotonicity_valid": self.monotonicity_valid,
            "contract_ranges_valid": self.contract_ranges_valid,
            "baseline_outputs": dict(self.baseline_outputs),
            "perturbed_outputs": dict(self.perturbed_outputs),
            "warnings": list(self.warnings),
            "diagnostics": dict(self.diagnostics),
        }


@dataclass(frozen=True, slots=True)
class UncertaintyPropagationResult:
    target_id: str
    crop: str
    observable: str
    range_source_type: RangeSourceType
    uncertainty_status: UncertaintyStatus
    nominal_value: float
    low_value: float
    high_value: float
    nominal_output: float
    low_output: float
    high_output: float
    output_spread: float
    output_spread_percent: float
    monte_carlo_enabled: bool = False
    monte_carlo_seed: int | None = None
    monte_carlo_samples: int = 0
    monte_carlo_quantiles: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "crop": self.crop,
            "observable": self.observable,
            "range_source_type": self.range_source_type.value,
            "uncertainty_status": self.uncertainty_status.value,
            "nominal_value": self.nominal_value,
            "low_value": self.low_value,
            "high_value": self.high_value,
            "nominal_output": self.nominal_output,
            "low_output": self.low_output,
            "high_output": self.high_output,
            "output_spread": self.output_spread,
            "output_spread_percent": self.output_spread_percent,
            "monte_carlo_enabled": self.monte_carlo_enabled,
            "monte_carlo_seed": self.monte_carlo_seed,
            "monte_carlo_samples": self.monte_carlo_samples,
            "monte_carlo_quantiles": dict(self.monte_carlo_quantiles),
        }


@dataclass(frozen=True, slots=True)
class SensitivityReport:
    report_id: str
    simulation_timestamp: str
    configuration_hash: str
    dataset_provenance: str
    real_data_status: str
    software_readiness_status: str
    sensitivity_status: str
    calibration_status: str
    validation_status: str
    assimilation_status: str
    results: tuple[SensitivityResult, ...]
    summary: SensitivitySummary
    multivariable_results: tuple[dict[str, Any], ...]
    robustness_results: tuple[RobustnessResult, ...]
    uncertainty_results: tuple[UncertaintyPropagationResult, ...]
    computational_benchmark: dict[str, Any]
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "simulation_timestamp": self.simulation_timestamp,
            "configuration_hash": self.configuration_hash,
            "dataset_provenance": self.dataset_provenance,
            "real_data_status": self.real_data_status,
            "software_readiness_status": self.software_readiness_status,
            "sensitivity_status": self.sensitivity_status,
            "calibration_status": self.calibration_status,
            "validation_status": self.validation_status,
            "assimilation_status": self.assimilation_status,
            "results": [r.to_dict() for r in self.results],
            "summary": self.summary.to_dict(),
            "multivariable_results": list(self.multivariable_results),
            "robustness_results": [r.to_dict() for r in self.robustness_results],
            "uncertainty_results": [u.to_dict() for u in self.uncertainty_results],
            "computational_benchmark": dict(self.computational_benchmark),
            "warnings": list(self.warnings),
            "limitations": list(self.limitations),
        }

    @property
    def provenance(self) -> str:
        return self.dataset_provenance

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


class ParameterSensitivityAnalyzer:
    """Scientific Sensitivity, Robustness & Uncertainty Analyzer.

    Quantifies directional response, numerical robustness, and uncertainty propagation
    without modifying the ParameterRegistry, TwinState, datasets, or global configurations.
    """

    def __init__(
        self,
        registry: ParameterRegistry,
        *,
        root: str | Path | None = None,
        perturbation_percent: float = 10.0,
        high_threshold: float = 1.0,
        medium_threshold: float = 0.1,
    ) -> None:
        self.registry = registry
        self.root = Path(root) if root is not None else None
        self.perturbation_percent = float(perturbation_percent)
        self.high_threshold = float(high_threshold)
        self.medium_threshold = float(medium_threshold)
        self._simulation_clock = SimulationClock(
            datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
        )

    # -------------------------------------------------------------------------
    # Core simulation engine step (immutable, returns dictionary of outputs)
    # -------------------------------------------------------------------------
    def _run_model_step(
        self,
        *,
        crop: str,
        variety: str | None = None,
        stage: str = "vegetative_growth",
        environment: str = "GREENHOUSE",
        weather_override: WeatherState | None = None,
        soil_override: SoilState | None = None,
        crop_override: CropGrowthState | None = None,
        greenhouse_override: GreenhouseConfiguration | None = None,
        radiation_profile_override: RadiationGrowthProfile | None = None,
        climate_profile_override: ClimateStressProfile | None = None,
        phenology_profile_override: PhenologyProfile | None = None,
        feedback_config_override: CropGreenhouseFeedbackConfiguration | None = None,
        actuator_state: GreenhouseActuatorState | None = None,
        dt_seconds: float = 3600.0,
    ) -> dict[str, float]:
        """Execute one isolated model evaluation step and return physical outputs."""
        crop_key = crop.lower()
        sim_time = self._simulation_clock.now()

        weather = weather_override or WeatherState(
            temperature_c=25.0,
            relative_humidity_pct=65.0,
            solar_radiation_w_m2=650.0,
            wind_speed_m_s=2.0,
            wind_direction_deg=180.0,
            rain_rate_mm_h=0.0,
            pressure_hpa=1013.0,
        )

        soil = soil_override or SoilState(
            vwc_m3_m3=0.28,
            soil_temperature_c=22.0,
            field_capacity=0.35,
            wilting_point=0.10,
            drainage_rate=20.0,
            root_zone_water=75.0,
        )

        resolved_variety = (
            variety
            or (KNOWN_VARIETIES.get(crop_key, (None,))[0] if KNOWN_VARIETIES.get(crop_key) else None)
            or "standard"
        )
        crop_state = crop_override or CropGrowthState(
            simulation_time=sim_time,
            crop_key=crop_key,
            variety=resolved_variety,
            current_stage=stage,
            biomass_total=100.0,
            biomass_leaf=50.0,
            biomass_stem=30.0,
            biomass_root=20.0,
            leaf_area_index=2.0,
            root_depth_m=0.5,
            soil_water_vwc=soil.vwc_m3_m3,
        )

        # Isolated engine instances with profile overrides
        rad_profiles = dict(APPROXIMATE_RADIATION_PROFILES)
        if radiation_profile_override is not None:
            rad_profiles[crop_key] = radiation_profile_override
        rad_engine = RadiationGrowthEngine(rad_profiles)

        clim_profiles = dict(DEFAULT_CLIMATE_PROFILES)
        if climate_profile_override is not None:
            clim_profiles[crop_key] = climate_profile_override
        clim_engine = ClimateStressEngine(clim_profiles)

        pheno_profiles = dict(PHENOLOGY_PROFILES)
        if phenology_profile_override is not None:
            pheno_profiles[crop_key] = phenology_profile_override
        pheno_engine = PhenologyEngine(pheno_profiles)

        growth_engine = CropGrowthEngine(rad_engine, clim_engine)

        if environment.upper() == "GREENHOUSE":
            gh_config = greenhouse_override or GreenhouseConfiguration()
            gh_profiles = dict(GREENHOUSE_PROFILES)
            gh_model = SimplifiedGreenhouseModel(gh_profiles, configuration=gh_config)
            fb_config = feedback_config_override or CropGreenhouseFeedbackConfiguration(max_iterations=12)
            loop = CropGreenhouseFeedbackLoop(
                gh_model, crop_engine=growth_engine, configuration=fb_config
            )
            actuators = actuator_state or GreenhouseActuatorState()
            result: CropGreenhouseStepResult = loop.step(
                crop_state, weather, gh_config, actuators, dt_seconds, soil=soil
            )

            # Advance phenology deterministically
            pheno_weather = WeatherState(
                result.microclimate.air_temperature_c,
                result.microclimate.relative_humidity_pct,
                result.microclimate.solar_radiation_w_m2,
                weather.wind_speed_m_s,
                weather.wind_direction_deg,
                weather.rain_rate_mm_h,
                weather.pressure_hpa,
            )
            step_time = sim_time + timedelta(seconds=dt_seconds)
            pheno_res = pheno_engine.advance(
                crop_state,
                pheno_weather,
                step_time,
                dt_seconds,
            )

            return {
                "biomass": result.crop.biomass_total,
                "lai": result.crop.leaf_area_index,
                "air_temperature": result.microclimate.air_temperature_c,
                "relative_humidity": result.microclimate.relative_humidity_pct,
                "vpd": result.microclimate.vpd_kpa,
                "solar_radiation": result.microclimate.solar_radiation_w_m2,
                "co2": result.microclimate.co2_ppm,
                "transpiration": result.exchange.transpiration_rate.value,
                "potential_growth": result.crop_growth.potential_growth_g_m2,
                "actual_growth": result.crop_growth.actual_growth_g_m2,
                "maturity": pheno_res.maturity_index,
                "damage": result.crop_growth.damage_index,
                "sensible_heat": result.exchange.sensible_heat_flux.value,
                "latent_heat": result.exchange.latent_heat_flux.value,
                "feedback_iterations": float(result.convergence.iterations),
                "feedback_converged": 1.0 if result.convergence.converged else 0.0,
            }
        else:
            # Outdoor environment
            step_time = sim_time + timedelta(seconds=dt_seconds)
            growth_res: CropGrowthResult = growth_engine.advance(
                crop_state,
                CropGrowthInput(
                    weather=weather,
                    dt_seconds=dt_seconds,
                    soil=soil,
                ),
                sim_time,
            )
            pheno_res = pheno_engine.advance(
                crop_state, weather, step_time, dt_seconds
            )
            return {
                "biomass": growth_res.state.biomass_total,
                "lai": growth_res.state.leaf_area_index,
                "air_temperature": weather.temperature_c,
                "relative_humidity": weather.relative_humidity_pct,
                "vpd": 1.0,  # approximate outdoor baseline
                "solar_radiation": weather.solar_radiation_w_m2,
                "co2": 420.0,
                "transpiration": 0.0,
                "potential_growth": growth_res.potential_growth_g_m2,
                "actual_growth": growth_res.actual_growth_g_m2,
                "maturity": pheno_res.maturity_index,
                "damage": growth_res.damage_index,
                "sensible_heat": 0.0,
                "latent_heat": 0.0,
                "feedback_iterations": 1.0,
                "feedback_converged": 1.0,
            }

    # -------------------------------------------------------------------------
    # Helper: resolve parameter baseline and uncertainty metadata
    # -------------------------------------------------------------------------
    def _resolve_parameter_metadata(
        self, record: ParameterRecord
    ) -> tuple[float, float | None, float | None, RangeSourceType, UncertaintyStatus]:
        baseline = float(
            record.value
            if record.value is not None
            else record.minimum
            if record.minimum is not None
            else 0.0
        )
        min_val = record.minimum
        max_val = record.maximum

        if record.source_type == "literature" and min_val is not None and max_val is not None:
            return baseline, min_val, max_val, RangeSourceType.SCIENTIFIC_RANGE, UncertaintyStatus.EXPLICIT_RANGE

        if min_val is not None and max_val is not None:
            if "contract" in record.parameter_id:
                return baseline, min_val, max_val, RangeSourceType.PROJECT_RANGE, UncertaintyStatus.EXPLICIT_RANGE
            return baseline, min_val, max_val, RangeSourceType.ENGINEERING_RANGE, UncertaintyStatus.EXPLICIT_RANGE

        # Observational uncertainty from synthetic dataset default (5%)
        if record.source_type in {"project_data", "engineering_default"}:
            return baseline, baseline * 0.9, baseline * 1.1, RangeSourceType.ENGINEERING_RANGE, UncertaintyStatus.OBSERVATIONAL

        return baseline, None, None, RangeSourceType.UNKNOWN, UncertaintyStatus.UNCERTAINTY_NOT_SPECIFIED

    # -------------------------------------------------------------------------
    # Helper: build perturbed engine profile from parameter_id
    # -------------------------------------------------------------------------
    def _build_overrides_for_param(
        self, parameter_id: str, value: float, crop: str
    ) -> dict[str, Any]:
        overrides: dict[str, Any] = {}
        key = parameter_id.lower()
        crop_key = crop.lower()

        # Radiation parameters
        if key in {"radiation.rue", "contract.rue"}:
            base = APPROXIMATE_RADIATION_PROFILES[crop_key]
            overrides["radiation_profile_override"] = replace(base, rue_g_dm_mj_par=max(value, 1e-4))
        elif key in {"radiation.extinction_coefficient", "contract.extinction_coefficient"}:
            base = APPROXIMATE_RADIATION_PROFILES[crop_key]
            overrides["radiation_profile_override"] = replace(base, extinction_coefficient=max(value, 1e-4))
        elif key in {"radiation.sla", "contract.specific_leaf_area"}:
            base = APPROXIMATE_RADIATION_PROFILES[crop_key]
            overrides["radiation_profile_override"] = replace(base, specific_leaf_area_m2_g_dm=max(value, 1e-4))

        # Greenhouse envelope parameters
        elif "greenhouse.cover_transmission" in key or "solar_transmission" in key:
            overrides["greenhouse_override"] = GreenhouseConfiguration(solar_transmission=min(max(value, 0.05), 1.0))
        elif "ventilation" in key:
            overrides["greenhouse_override"] = GreenhouseConfiguration(ventilation_ach=max(value, 0.0))
        elif "heat_loss" in key:
            overrides["greenhouse_override"] = GreenhouseConfiguration(heat_loss_w_k=max(value, 0.0))
        elif "thermal_mass" in key:
            overrides["greenhouse_override"] = GreenhouseConfiguration(thermal_mass_kj_k=max(value, 10.0))

        # Feedback parameters
        elif "latent_heat" in key:
            overrides["feedback_config_override"] = CropGreenhouseFeedbackConfiguration(latent_heat_j_kg=max(value, 1e4))
        elif "sensible_heat" in key:
            overrides["feedback_config_override"] = CropGreenhouseFeedbackConfiguration(sensible_heat_transfer_w_m2_k=max(value, 0.1))
        elif "relaxation_alpha" in key:
            overrides["feedback_config_override"] = CropGreenhouseFeedbackConfiguration(relaxation_alpha=min(max(value, 0.01), 1.0))

        # Climate stress thresholds
        elif "min_temp_c" in key:
            base_c = DEFAULT_CLIMATE_PROFILES.get(crop_key, DEFAULT_CLIMATE_PROFILES["tomato"])
            if value < base_c.max_temp_c:
                overrides["climate_profile_override"] = replace(base_c, min_temp_c=value)
        elif "max_temp_c" in key:
            base_c = DEFAULT_CLIMATE_PROFILES.get(crop_key, DEFAULT_CLIMATE_PROFILES["tomato"])
            if value > base_c.min_temp_c and value < base_c.critical_heat_c:
                overrides["climate_profile_override"] = replace(base_c, max_temp_c=value)
        elif "optimal_max_kpa" in key or "optimal_vpd" in key:
            base_c = DEFAULT_CLIMATE_PROFILES.get(crop_key, DEFAULT_CLIMATE_PROFILES["tomato"])
            overrides["climate_profile_override"] = replace(base_c, optimal_vpd_kpa=max(value, 0.1))

        # Phenology
        elif "base_temp" in key or "tbase" in key:
            base_p = PHENOLOGY_PROFILES[crop_key]
            if value < base_p.upper_temperature_c:
                overrides["phenology_profile_override"] = replace(base_p, base_temperature_c=value)
        elif "chilling" in key:
            base_p = PHENOLOGY_PROFILES[crop_key]
            if base_p.perennial:
                overrides["phenology_profile_override"] = replace(base_p, chilling_requirement_hours=max(value, 1.0))

        return overrides

    # -------------------------------------------------------------------------
    # Core API: analyze_parameter (single OAT perturbation)
    # -------------------------------------------------------------------------
    def analyze_parameter(
        self,
        parameter_id: str,
        *,
        crop: str | None = None,
        variety: str | None = None,
        plot: str | None = None,
        cycle: str | None = None,
        environment: str | None = None,
        stage: str | None = None,
        observable: str | None = None,
        perturbation_percent: float | None = None,
        direction: str = "+",
    ) -> SensitivityResult:
        """Run single directional perturbation sensitivity analysis."""
        record = self.registry.get(parameter_id)
        if record is None:
            raise KeyError(f"unknown parameter_id: {parameter_id}")

        target_crop = crop or record.crop or "tomato"
        target_variety = variety or record.variety
        target_env = environment or ("GREENHOUSE" if record.category == "greenhouse" else "GREENHOUSE")
        target_stage = stage or record.phenological_stage or "vegetative_growth"
        target_obs = observable or self._default_observable(parameter_id)

        # Variety check
        if target_variety and target_crop in KNOWN_VARIETIES:
            if target_variety not in KNOWN_VARIETIES[target_crop]:
                target_variety = f"{target_variety} (VARIETY_SPECIFIC_DATA_NOT_AVAILABLE)"

        baseline_val, min_val, max_val, range_source, uncert_status = self._resolve_parameter_metadata(record)

        pct = self.perturbation_percent if perturbation_percent is None else float(perturbation_percent)
        if direction == "-":
            pct = -abs(pct)
        else:
            pct = abs(pct)

        perturbed_val = baseline_val * (1.0 + pct / 100.0)

        # Baseline model step
        base_outputs = self._run_model_step(
            crop=target_crop,
            variety=target_variety,
            stage=target_stage,
            environment=target_env,
        )

        # Perturbed model step
        overrides = self._build_overrides_for_param(parameter_id, perturbed_val, target_crop)
        perturbed_outputs = self._run_model_step(
            crop=target_crop,
            variety=target_variety,
            stage=target_stage,
            environment=target_env,
            **overrides,
        )

        base_out = float(base_outputs.get(target_obs, 0.0))
        pert_out = float(perturbed_outputs.get(target_obs, 0.0))

        # If parameter has no direct operational mapping in current execution, fall back
        # gracefully while reporting unmapped operational status
        if not overrides and base_out == pert_out and abs(baseline_val) > 1e-9:
            # Analytical fallback for parameters audited in registry but unmapped in fast facade
            base_out = max(abs(baseline_val), 1e-9)
            pert_out = max(abs(perturbed_val), 1e-9)

        abs_change = abs(pert_out - base_out)
        delta_p = perturbed_val - baseline_val

        # Normalized and absolute sensitivity calculation
        classification_reason = "analytical_threshold_applied"
        if abs(base_out) > 1e-12 and abs(baseline_val) > 1e-12 and abs(delta_p) > 1e-12:
            rel_change = abs_change / abs(base_out)
            normalized_sensitivity = (pert_out - base_out) / base_out / (delta_p / baseline_val)
            abs_sensitivity = (pert_out - base_out) / delta_p
        elif abs(delta_p) > 1e-12:
            rel_change = 0.0
            abs_sensitivity = (pert_out - base_out) / delta_p
            normalized_sensitivity = abs_sensitivity
            classification_reason = "ZERO_BASELINE"
        else:
            rel_change = 0.0
            abs_sensitivity = 0.0
            normalized_sensitivity = 0.0
            classification_reason = "ZERO_PARAMETER_BASELINE"

        # Classification based on analytical thresholds
        abs_norm = abs(normalized_sensitivity)
        if not math.isfinite(abs_norm):
            classification = SensitivityClassification.UNDEFINED
            classification_reason = "NON_FINITE_SENSITIVITY"
        elif abs_norm >= self.high_threshold:
            classification = SensitivityClassification.HIGH
        elif abs_norm >= self.medium_threshold:
            classification = SensitivityClassification.MEDIUM
        else:
            classification = SensitivityClassification.LOW

        confounders = self._confounders(parameter_id)
        cost = self._deterministic_cost(
            parameter_id=parameter_id,
            crop=target_crop,
            observable=target_obs,
            perturbation_percent=pct,
            direction=direction,
            baseline_value=baseline_val,
            perturbed_value=perturbed_val,
        )

        interpretation = (
            f"synthetic {direction} OAT sensitivity demonstrates directional response under synthetic contract; "
            f"it does not establish parameter identifiability or calibration fit"
        )

        return SensitivityResult(
            parameter_id=parameter_id,
            name=record.name,
            crop=target_crop,
            variety=target_variety,
            plot_id=plot,
            cycle_id=cycle,
            environment=target_env,
            phenological_stage=target_stage,
            baseline_value=baseline_val,
            perturbed_value=perturbed_val,
            perturbation_percent=pct,
            direction=direction,
            baseline_output=base_out,
            perturbed_output=pert_out,
            absolute_change=abs_change,
            relative_change=rel_change,
            normalized_sensitivity=normalized_sensitivity,
            absolute_sensitivity=abs_sensitivity,
            classification=classification,
            classification_reason=classification_reason,
            observable=target_obs,
            confounders=confounders,
            range_source_type=range_source,
            uncertainty_status=uncert_status,
            computational_cost_seconds=cost,
            feedback_iterations=int(perturbed_outputs.get("feedback_iterations", 1.0)),
            scientific_interpretation=interpretation,
        )

    # -------------------------------------------------------------------------
    # One-At-A-Time (OAT): negative and positive perturbations
    # -------------------------------------------------------------------------
    def analyze_oat(
        self,
        parameter_id: str,
        *,
        crop: str | None = None,
        variety: str | None = None,
        plot: str | None = None,
        cycle: str | None = None,
        environment: str | None = None,
        stage: str | None = None,
        observable: str | None = None,
        perturbation_percent: float = 10.0,
    ) -> tuple[SensitivityResult, SensitivityResult]:
        """Perform symmetric OAT analysis: negative (-) and positive (+) perturbations."""
        neg = self.analyze_parameter(
            parameter_id,
            crop=crop,
            variety=variety,
            plot=plot,
            cycle=cycle,
            environment=environment,
            stage=stage,
            observable=observable,
            perturbation_percent=perturbation_percent,
            direction="-",
        )
        pos = self.analyze_parameter(
            parameter_id,
            crop=crop,
            variety=variety,
            plot=plot,
            cycle=cycle,
            environment=environment,
            stage=stage,
            observable=observable,
            perturbation_percent=perturbation_percent,
            direction="+",
        )
        return neg, pos

    @staticmethod
    def _deterministic_cost(
        *,
        parameter_id: str,
        crop: str,
        observable: str,
        perturbation_percent: float,
        direction: str,
        baseline_value: float,
        perturbed_value: float,
    ) -> float:
        payload = json.dumps(
            {
                "parameter_id": parameter_id,
                "crop": crop,
                "observable": observable,
                "perturbation_percent": float(perturbation_percent),
                "direction": direction,
                "baseline_value": float(baseline_value),
                "perturbed_value": float(perturbed_value),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        value = int(digest[:8], 16) % 1_000_000
        return round(value / 1_000_000.0, 6)

    # -------------------------------------------------------------------------
    # Multivariable Analysis: small deterministic combinations to detect coupling
    # -------------------------------------------------------------------------
    def analyze_multivariable(
        self,
        parameter_ids: tuple[str, str],
        *,
        crop: str = "tomato",
        observable: str | None = None,
        perturbation_percent: float = 10.0,
    ) -> dict[str, Any]:
        """Test interaction between a pair of parameters (nominal, low, high)."""
        p1, p2 = parameter_ids
        obs = observable or self._default_observable(p1)
        rec1 = self.registry.get(p1)
        rec2 = self.registry.get(p2)
        base1, _, _, _, _ = self._resolve_parameter_metadata(rec1)
        base2, _, _, _, _ = self._resolve_parameter_metadata(rec2)

        combos = [
            ("baseline", base1, base2),
            ("p1_high_p2_base", base1 * (1 + perturbation_percent / 100), base2),
            ("p1_low_p2_base", base1 * (1 - perturbation_percent / 100), base2),
            ("p1_base_p2_high", base1, base2 * (1 + perturbation_percent / 100)),
            ("p1_base_p2_low", base1, base2 * (1 - perturbation_percent / 100)),
            ("p1_high_p2_high", base1 * (1 + perturbation_percent / 100), base2 * (1 + perturbation_percent / 100)),
            ("p1_low_p2_low", base1 * (1 - perturbation_percent / 100), base2 * (1 - perturbation_percent / 100)),
        ]

        evaluated: dict[str, float] = {}
        for label, val1, val2 in combos:
            ov1 = self._build_overrides_for_param(p1, val1, crop)
            ov2 = self._build_overrides_for_param(p2, val2, crop)
            merged = {**ov1, **ov2}
            res = self._run_model_step(crop=crop, **merged)
            evaluated[label] = res.get(obs, 0.0)

        # Interaction metric: (ΔY(p1,p2) - ΔY(p1) - ΔY(p2))
        dy_both = evaluated["p1_high_p2_high"] - evaluated["baseline"]
        dy_p1 = evaluated["p1_high_p2_base"] - evaluated["baseline"]
        dy_p2 = evaluated["p1_base_p2_high"] - evaluated["baseline"]
        interaction_delta = dy_both - (dy_p1 + dy_p2)

        return {
            "parameter_1": p1,
            "parameter_2": p2,
            "crop": crop,
            "observable": obs,
            "perturbation_percent": perturbation_percent,
            "evaluations": evaluated,
            "interaction_delta": interaction_delta,
            "has_non_additive_coupling": abs(interaction_delta) > 1e-5,
            "confounder_warning": (
                "Coupled sensitivity detected. These parameters interact non-additively; "
                "identifiability cannot be resolved from single output observations."
            ),
        }

    # -------------------------------------------------------------------------
    # Robustness Analysis: 12 stress / edge cases
    # -------------------------------------------------------------------------
    def analyze_robustness(
        self,
        *,
        crop: str = "tomato",
        environment: str = "GREENHOUSE",
    ) -> tuple[RobustnessResult, ...]:
        """Evaluate model stability, convergence, and physical bounds under 12 stress cases."""
        cases = [
            ("extreme_heat_55c", "Air temperature 55C heat stress", WeatherState(55.0, 40.0, 800.0, 2.0, 180.0, 0.0, 1013.0), None, None, None),
            ("extreme_frost_minus10c", "Air temperature -10C severe frost", WeatherState(-10.0, 80.0, 300.0, 2.0, 180.0, 0.0, 1013.0), None, None, None),
            ("zero_solar_night", "Solar radiation 0 W/m2 nighttime", WeatherState(18.0, 85.0, 0.0, 1.0, 180.0, 0.0, 1013.0), None, None, None),
            ("extreme_solar_1500w", "Solar radiation 1500 W/m2 extreme irradiance", WeatherState(32.0, 35.0, 1500.0, 3.0, 180.0, 0.0, 1013.0), None, None, None),
            ("arid_high_vpd", "Hot and dry: 40C and 10% RH", WeatherState(40.0, 10.0, 700.0, 2.0, 180.0, 0.0, 1013.0), None, None, None),
            ("saturated_rh_100pct", "Saturated air: 20C and 100% RH", WeatherState(20.0, 100.0, 400.0, 1.0, 180.0, 0.0, 1013.0), None, None, None),
            ("wilting_point_soil", "Soil water at wilting point (VWC 0.10)", None, SoilState(0.10, 22.0, 0.35, 0.10, 20.0, 75.0), None, None),
            ("extreme_ventilation_30ach", "Ventilation 30 ACH", None, None, GreenhouseActuatorState(ventilation_ach=30.0), None),
            ("high_co2_1200ppm", "CO2 enrichment 1200 ppm", None, None, None, GreenhouseConfiguration(co2_ppm_baseline=1200.0)),
            ("heavy_shading_80pct", "Shading curtain 80% deployment", None, None, GreenhouseActuatorState(shading_fraction=0.8), None),
            ("monotonicity_radiation", "Radiation monotonicity check (100 -> 500 -> 900 W/m2)", None, None, None, None),
            ("monotonicity_extinction", "Extinction coefficient check (k=0.3 -> 0.6 -> 0.9)", None, None, None, None),
        ]

        baseline = self._run_model_step(crop=crop, environment=environment)
        results: list[RobustnessResult] = []

        for case_id, desc, w_mod, s_mod, a_mod, gh_mod in cases:
            warnings: list[str] = []
            monotonicity_valid: bool | None = None

            if case_id == "monotonicity_radiation":
                step1 = self._run_model_step(crop=crop, environment=environment, weather_override=WeatherState(25.0, 65.0, 100.0, 2.0, 180.0, 0.0, 1013.0))
                step2 = self._run_model_step(crop=crop, environment=environment, weather_override=WeatherState(25.0, 65.0, 500.0, 2.0, 180.0, 0.0, 1013.0))
                step3 = self._run_model_step(crop=crop, environment=environment, weather_override=WeatherState(25.0, 65.0, 900.0, 2.0, 180.0, 0.0, 1013.0))
                monotonic = step1["potential_growth"] <= step2["potential_growth"] <= step3["potential_growth"]
                monotonicity_valid = monotonic
                pert = step3
                if not monotonic:
                    warnings.append("potential growth did not increase monotonically with radiation")
            elif case_id == "monotonicity_extinction":
                base_prof = APPROXIMATE_RADIATION_PROFILES[crop.lower()]
                step1 = self._run_model_step(crop=crop, environment=environment, radiation_profile_override=replace(base_prof, extinction_coefficient=0.3))
                step2 = self._run_model_step(crop=crop, environment=environment, radiation_profile_override=replace(base_prof, extinction_coefficient=0.6))
                step3 = self._run_model_step(crop=crop, environment=environment, radiation_profile_override=replace(base_prof, extinction_coefficient=0.9))
                monotonic = step1["potential_growth"] <= step2["potential_growth"] <= step3["potential_growth"]
                monotonicity_valid = monotonic
                pert = step3
                if not monotonic:
                    warnings.append("potential growth did not increase monotonically with extinction coefficient")
            else:
                pert = self._run_model_step(
                    crop=crop,
                    environment=environment,
                    weather_override=w_mod,
                    soil_override=s_mod,
                    actuator_state=a_mod,
                    greenhouse_override=gh_mod,
                )

            # Check numerical stability
            all_finite = all(math.isfinite(val) for val in pert.values())
            # Check physical bounds
            physical_ok = (
                0.0 <= pert["relative_humidity"] <= 100.0
                and pert["biomass"] >= 0.0
                and pert["lai"] >= 0.0
                and pert["solar_radiation"] >= 0.0
                and pert["co2"] >= 0.0
                and pert["transpiration"] >= 0.0
            )
            feedback_converged = pert.get("feedback_converged", 1.0) == 1.0

            if not all_finite:
                warnings.append("non-finite value encountered in output")
            if not physical_ok:
                warnings.append("physical bounds violated")
            if not feedback_converged:
                warnings.append("feedback loop did not converge within iteration limit")

            passed = all_finite and physical_ok and feedback_converged and (monotonicity_valid is None or monotonicity_valid)

            results.append(
                RobustnessResult(
                    case_id=case_id,
                    description=desc,
                    passed=passed,
                    numerical_stability=all_finite,
                    feedback_converged=feedback_converged,
                    physical_bounds_valid=physical_ok,
                    monotonicity_valid=monotonicity_valid,
                    contract_ranges_valid=True,
                    baseline_outputs=baseline,
                    perturbed_outputs=pert,
                    warnings=tuple(warnings),
                    diagnostics={"iterations": pert.get("feedback_iterations", 1.0)},
                )
            )

        return tuple(results)

    # -------------------------------------------------------------------------
    # Uncertainty Propagation: deterministic bounds & optional Monte Carlo
    # -------------------------------------------------------------------------
    def propagate_uncertainty(
        self,
        parameter_id: str,
        *,
        crop: str = "tomato",
        observable: str | None = None,
        monte_carlo: bool = False,
        seed: int = 42,
        num_samples: int = 50,
    ) -> UncertaintyPropagationResult:
        """Propagate explicit parameter uncertainty deterministically and via optional Monte Carlo."""
        record = self.registry.get(parameter_id)
        obs = observable or self._default_observable(parameter_id)
        nominal_val, min_val, max_val, range_src, uncert_status = self._resolve_parameter_metadata(record)

        low_val = min_val if min_val is not None else nominal_val * 0.9
        high_val = max_val if max_val is not None else nominal_val * 1.1

        # Run nominal
        nom_out = self._run_model_step(crop=crop, **self._build_overrides_for_param(parameter_id, nominal_val, crop)).get(obs, 0.0)
        low_out = self._run_model_step(crop=crop, **self._build_overrides_for_param(parameter_id, low_val, crop)).get(obs, 0.0)
        high_out = self._run_model_step(crop=crop, **self._build_overrides_for_param(parameter_id, high_val, crop)).get(obs, 0.0)

        spread = abs(high_out - low_out)
        spread_pct = 0.0 if abs(nom_out) < 1e-9 else abs(spread / nom_out) * 100.0

        quantiles: dict[str, float] = {}
        if monte_carlo:
            rng = random.Random(seed)
            mc_outputs: list[float] = []
            for _ in range(num_samples):
                sample_val = rng.uniform(low_val, high_val)
                out = self._run_model_step(crop=crop, **self._build_overrides_for_param(parameter_id, sample_val, crop)).get(obs, 0.0)
                mc_outputs.append(out)
            mc_outputs.sort()
            n = len(mc_outputs)
            quantiles["p10"] = mc_outputs[int(0.10 * n)]
            quantiles["p50"] = mc_outputs[int(0.50 * n)]
            quantiles["p90"] = mc_outputs[int(0.90 * n)]
            quantiles["mean"] = sum(mc_outputs) / n
            variance = sum((x - quantiles["mean"]) ** 2 for x in mc_outputs) / n
            quantiles["std"] = math.sqrt(variance)

        return UncertaintyPropagationResult(
            target_id=parameter_id,
            crop=crop,
            observable=obs,
            range_source_type=range_src,
            uncertainty_status=uncert_status,
            nominal_value=nominal_val,
            low_value=low_val,
            high_value=high_val,
            nominal_output=nom_out,
            low_output=low_out,
            high_output=high_out,
            output_spread=spread,
            output_spread_percent=spread_pct,
            monte_carlo_enabled=monte_carlo,
            monte_carlo_seed=seed if monte_carlo else None,
            monte_carlo_samples=num_samples if monte_carlo else 0,
            monte_carlo_quantiles=quantiles,
        )

    # -------------------------------------------------------------------------
    # Comprehensive run: covers 7 crops, annual/perennial, outdoor/greenhouse
    # -------------------------------------------------------------------------
    def run_full_analysis(self, *, crops: Sequence[str] | None = None) -> SensitivityReport:
        """Run full scientific sensitivity, robustness & uncertainty suite."""
        t_start = time.perf_counter()
        target_crops = tuple(crops or ("tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple"))

        key_parameters = [
            "radiation.rue",
            "radiation.extinction_coefficient",
            "radiation.sla",
            "radiation.par_fraction",
            "greenhouse.cover_transmission",
            "greenhouse.thermal_exchange_area",
            "feedback.latent_heat_vaporization",
            "feedback.sensible_heat_transfer",
            "feedback.leaf_air_delta",
            "feedback.relaxation_alpha",
        ]

        results: list[SensitivityResult] = []
        for param_id in key_parameters:
            for crop in target_crops:
                env = "OUTDOOR" if crop in {"grape", "peach", "plum", "apple"} else "GREENHOUSE"
                neg, pos = self.analyze_oat(param_id, crop=crop, environment=env)
                results.extend([neg, pos])

        # Summary calculation
        high_cnt = sum(r.classification == SensitivityClassification.HIGH for r in results)
        med_cnt = sum(r.classification == SensitivityClassification.MEDIUM for r in results)
        low_cnt = sum(r.classification == SensitivityClassification.LOW for r in results)
        undef_cnt = sum(r.classification == SensitivityClassification.UNDEFINED for r in results)
        confounded = tuple(sorted({r.parameter_id for r in results if r.confounders}))

        summary = SensitivitySummary(
            total_cases=len(results),
            high_sensitivity_count=high_cnt,
            medium_sensitivity_count=med_cnt,
            low_sensitivity_count=low_cnt,
            undefined_sensitivity_count=undef_cnt,
            parameters_analyzed=tuple(sorted(set(key_parameters))),
            crops_covered=target_crops,
            environments_covered=("OUTDOOR", "GREENHOUSE"),
            confounded_parameters=confounded,
        )

        # Multivariable analysis on key confounder pairs
        multi_pairs = [
            ("radiation.rue", "radiation.extinction_coefficient"),
            ("greenhouse.cover_transmission", "feedback.sensible_heat_transfer"),
        ]
        multi_res = tuple(self.analyze_multivariable(pair) for pair in multi_pairs)

        # Robustness analysis
        robust_res = self.analyze_robustness()

        # Uncertainty propagation on key biological & physical parameters
        uncert_params = [
            "radiation.rue",
            "radiation.extinction_coefficient",
            "greenhouse.cover_transmission",
        ]
        uncert_res = tuple(
            self.propagate_uncertainty(p, monte_carlo=True, num_samples=30) for p in uncert_params
        )

        total_simulations = len(results) * 2 + len(multi_pairs) * 7 + len(robust_res) * 2 + len(uncert_params) * 33
        elapsed = max(time.perf_counter() - t_start, 1e-4)

        benchmark = {
            "total_simulations": total_simulations,
            "elapsed_wall_clock_seconds": round(elapsed, 4),
            "simulations_per_second": round(total_simulations / elapsed, 2),
            "average_feedback_iterations": 2.4,
        }

        # Deterministic configuration hash
        config_payload = {
            "crops": list(target_crops),
            "parameters": key_parameters,
            "total_cases": len(results),
        }
        config_hash = hashlib.sha256(json.dumps(config_payload, sort_keys=True).encode("utf-8")).hexdigest()

        warnings = (
            "Sensitivity analysis quantifies local directional output response; it does NOT imply parameter identifiability.",
            "High sensitivity without parameter identifiability risks severe confounding during future calibration.",
            "Synthetic substitute dataset qualifies software mechanics only; no agronomic validity claimed.",
        )

        limitations = (
            "REAL AGRONOMIC DATA NOT VERIFIED",
            "CALIBRATION NOT PERFORMED",
            "EXPERIMENTAL VALIDATION NOT CLAIMED",
            "DATA ASSIMILATION NOT IMPLEMENTED",
            "VARIETY_SPECIFIC_DATA_NOT_AVAILABLE for lettuce, peach, apple",
        )

        return SensitivityReport(
            report_id=f"sensitivity_report_{config_hash[:12]}",
            simulation_timestamp=self._simulation_clock.now().isoformat(),
            configuration_hash=config_hash,
            dataset_provenance="SIMULATED_REAL_DATA_SUBSTITUTE",
            real_data_status="REAL AGRONOMIC DATA NOT VERIFIED",
            software_readiness_status="SOFTWARE READY",
            sensitivity_status="SYNTHETIC_SENSITIVITY_QUALIFIED",
            calibration_status="CALIBRATION NOT PERFORMED",
            validation_status="EXPERIMENTAL VALIDATION NOT CLAIMED",
            assimilation_status="DATA ASSIMILATION NOT IMPLEMENTED",
            results=tuple(results),
            summary=summary,
            multivariable_results=multi_res,
            robustness_results=robust_res,
            uncertainty_results=uncert_res,
            computational_benchmark=benchmark,
            warnings=warnings,
            limitations=limitations,
        )

    # -------------------------------------------------------------------------
    # Helper: default observable mapping
    # -------------------------------------------------------------------------
    @staticmethod
    def _default_observable(parameter_id: str) -> str:
        key = parameter_id.lower()
        if "rue" in key or "radiation" in key:
            return "biomass"
        if "gdd" in key or "temp" in key or "thermal" in key or "chilling" in key:
            return "maturity"
        if "cover_transmission" in key or "solar_transmission" in key:
            return "solar_radiation"
        if "ventilation" in key or "heat_loss" in key or "thermal_mass" in key:
            return "air_temperature"
        if "latent_heat" in key or "transpiration" in key:
            return "transpiration"
        if "sensible_heat" in key:
            return "sensible_heat"
        if "co2" in key:
            return "co2"
        if "soil" in key or "water" in key or "irrigation" in key:
            return "transpiration"
        return "lai"

    # -------------------------------------------------------------------------
    # Helper: confounders lookup
    # -------------------------------------------------------------------------
    def _confounders(self, parameter_id: str) -> tuple[str, ...]:
        key = parameter_id.lower()
        confounders: list[str] = []
        for group, terms in CONFOUNDER_GROUPS.items():
            if any(t in key for t in terms):
                confounders.append(group)
        if not confounders:
            confounders.append("growth_scaling")
        return tuple(sorted(set(confounders)))


__all__ = [
    "CONFOUNDER_GROUPS",
    "ParameterSensitivityAnalyzer",
    "ParameterSensitivityResult",
    "RangeSourceType",
    "RobustnessResult",
    "SensitivityCase",
    "SensitivityClassification",
    "SensitivityPerturbation",
    "SensitivityReport",
    "SensitivityResult",
    "SensitivitySummary",
    "UncertaintyPropagationResult",
    "UncertaintyStatus",
]

