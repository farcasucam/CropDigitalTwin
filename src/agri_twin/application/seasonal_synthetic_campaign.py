"""Season-scale synthetic campaign validation (Phase 5.32).

Runs complete crop campaigns under plausible, deterministic synthetic climate
scenarios built from the existing ``WeatherEngine`` (optional seasonal and
day-to-day configuration) and the existing ``ScenarioEvent`` overlays (with
gradual onset/decay). It composes ``ScenarioRunner``/``SimulationClock``,
``CropDigitalTwinOrchestrator``, ``MultiPlotSimulation`` (through the Phase 5.29
suite), the Phase 5.29 trajectory validators and checkpoint helpers, and the
existing synthetic crop cycles. It adds no weather, crop, phenology, greenhouse
or water equations.

Outcomes are ``MODEL_BEHAVIOR_CONSISTENT`` at most: scenario response metrics
characterise the implemented model and are never accuracy, calibration or
biological validation.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from agri_twin.application.integrated_synthetic_validation import (
    IntegratedSyntheticValidationSuite,
    _initial_state,
    checkpoint_payload,
    restore_checkpoint,
    resumed_scenario,
    snapshot_numbers,
    static_audit,
    trajectory_hash,
    twin_state_from_snapshot,
    validate_trajectory,
)
from agri_twin.application.orchestrator import CropSimulationSnapshot
from agri_twin.application.providers import SyntheticWeatherProvider
from agri_twin.application.scenarios import Scenario, ScenarioError, ScenarioEvent, ScenarioKind, ScenarioResult, ScenarioRunner
from agri_twin.application.scientific_benchmark import KNOWN_CROPS, KNOWN_VARIETIES, PERENNIAL_CROPS
from agri_twin.application.synthetic_dataset import SyntheticCropCycle, SyntheticReferenceDatasetGenerator
from agri_twin.application.twin_state import InMemoryTwinStateRepository, TwinSnapshot, TwinState
from agri_twin.application.weather import WeatherEngine
from agri_twin.domain.calibration import ParameterSet
from agri_twin.domain.crop_growth import CropGrowthEngine
from agri_twin.domain.greenhouse import GreenhouseConfiguration
from agri_twin.domain.models import WeatherState
from agri_twin.domain.parameter_audit import ParameterRegistry
from agri_twin.domain.phenology import STAGES
from agri_twin.domain.radiation_growth import RadiationGrowthEngine
from agri_twin.domain.weather import (
    DailyVariabilityConfiguration,
    HumidityConfiguration,
    RadiationConfiguration,
    SeasonalConfiguration,
    TemperatureConfiguration,
    WeatherConfiguration,
    WeatherSimulationConfiguration,
)

UTC = timezone.utc
VERSION = "5.32.1"
DEFAULT_SEED = 532
TIMESTEP_SECONDS = 3600
BASE_IRRIGATION_MM_H = 0.4
EVENT_DAYS = 7
EVENT_RAMP_HOURS = 24.0
FLOAT_TOLERANCE = 1e-9
ANNUAL_GREENHOUSE_CROPS = ("tomato", "lettuce", "pepper")
MANDATORY_SCENARIOS = (
    "BASE_SEASON", "HOT_SEASON", "COLD_SEASON", "LOW_RADIATION", "HIGH_RADIATION", "DRY_SEASON",
    "HUMID_SEASON", "HEAT_WAVE", "COLD_WAVE", "HEAT_WAVE_WITH_DRYNESS", "HIGH_RADIATION_WITH_LOW_WATER",
    "RECOVERY_AFTER_STRESS",
)
SUPPLEMENTARY_SCENARIOS = ("WIND_SPELL", "RAIN_SPELL")
BEHAVIOR_CONSISTENT = "MODEL_BEHAVIOR_CONSISTENT"
BEHAVIOR_INCONSISTENT = "MODEL_BEHAVIOR_INCONSISTENT"

# Plausible synthetic base climate (scenario forcing, not crop parameters): an
# annual mean diurnal range, a continuous seasonal cycle with longer summer days,
# and seeded day-to-day anomalies. The Phase 2 per-day wave is disabled
# (variability 0) because it re-phases at midnight; continuity comes from the
# interpolated daily anomalies instead.
BASE_PROFILE: Mapping[str, float] = {
    "temperature_min_c": 11.5, "temperature_max_c": 24.0, "radiation_max_w_m2": 750.0,
    "humidity_min_pct": 40.0, "humidity_max_pct": 88.0,
    "seasonal_temperature_amplitude_c": 8.5, "seasonal_radiation_amplitude_fraction": 0.30,
    "seasonal_humidity_amplitude_pct": 8.0, "seasonal_daylength_amplitude_h": 4.0, "warmest_day_of_year": 200.0,
    "daily_temperature_c": 2.0, "daily_radiation_fraction": 0.15, "daily_humidity_pct": 5.0,
}
# Season-long profile shifts per scenario (offsets in C / %RH, radiation factor).
PROFILE_SHIFTS: Mapping[str, Mapping[str, float]] = {
    "HOT_SEASON": {"temperature_offset_c": 3.0},
    "COLD_SEASON": {"temperature_offset_c": -3.0},
    "LOW_RADIATION": {"radiation_factor": 0.7},
    "HIGH_RADIATION": {"radiation_factor": 1.2},
    "DRY_SEASON": {"humidity_offset_pct": -20.0},
    "HUMID_SEASON": {"humidity_offset_pct": 10.0},
}
IRRIGATION_FACTOR = {"DRY_SEASON": 0.5}


class CampaignStatus(StrEnum):
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class IssueClassification(StrEnum):
    SOFTWARE_BUG = "SOFTWARE_BUG"
    PHYSICAL_INCONSISTENCY = "PHYSICAL_INCONSISTENCY"
    SCENARIO_DESIGN_ISSUE = "SCENARIO_DESIGN_ISSUE"
    TRACEABILITY_GAP = "TRACEABILITY_GAP"
    MODEL_CAPABILITY_GAP = "MODEL_CAPABILITY_GAP"
    OPEN_PHYSICAL_ISSUE = "OPEN_PHYSICAL_ISSUE"
    OPEN_SCIENTIFIC_DECISION = "OPEN_SCIENTIFIC_DECISION"


def _hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def climate_profile(scenario_id: str) -> dict[str, float]:
    """Base profile with the scenario's season-long shift applied."""
    profile = dict(BASE_PROFILE)
    shift = PROFILE_SHIFTS.get(scenario_id, {})
    profile["temperature_min_c"] += shift.get("temperature_offset_c", 0.0)
    profile["temperature_max_c"] += shift.get("temperature_offset_c", 0.0)
    profile["radiation_max_w_m2"] *= shift.get("radiation_factor", 1.0)
    profile["humidity_min_pct"] = max(0.0, profile["humidity_min_pct"] + shift.get("humidity_offset_pct", 0.0))
    profile["humidity_max_pct"] = min(100.0, profile["humidity_max_pct"] + shift.get("humidity_offset_pct", 0.0))
    return profile


def weather_configuration(profile: Mapping[str, float], seed: int) -> WeatherConfiguration:
    return WeatherConfiguration(
        temperature=TemperatureConfiguration(minimum_c=profile["temperature_min_c"], maximum_c=profile["temperature_max_c"], variability_c=0.0),
        radiation=RadiationConfiguration(maximum_w_m2=profile["radiation_max_w_m2"], variability_w_m2=0.0),
        humidity=HumidityConfiguration(minimum_pct=profile["humidity_min_pct"], maximum_pct=profile["humidity_max_pct"], variability_pct=0.0),
        simulation=WeatherSimulationConfiguration(seed=seed),
        seasonal=SeasonalConfiguration(
            temperature_amplitude_c=profile["seasonal_temperature_amplitude_c"],
            radiation_amplitude_fraction=profile["seasonal_radiation_amplitude_fraction"],
            humidity_amplitude_pct=profile["seasonal_humidity_amplitude_pct"],
            daylength_amplitude_h=profile["seasonal_daylength_amplitude_h"],
            warmest_day_of_year=profile["warmest_day_of_year"],
        ),
        daily_variability=DailyVariabilityConfiguration(
            temperature_c=profile["daily_temperature_c"], radiation_fraction=profile["daily_radiation_fraction"], humidity_pct=profile["daily_humidity_pct"],
        ),
    )


def _label(scenario: Scenario, key: str) -> str:
    prefix = f"{key}="
    return next(label[len(prefix):] for label in scenario.labels if label.startswith(prefix))


def seasonal_weather_factory(scenario: Scenario) -> SyntheticWeatherProvider:
    """Seeded seasonal base weather selected by the scenario labels."""
    return SyntheticWeatherProvider(WeatherEngine(weather_configuration(climate_profile(_label(scenario, "climate")), int(_label(scenario, "weather_seed")))))


# ---------------------------------------------------------------------------
# Scenario / campaign definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SyntheticClimateScenario:
    scenario_id: str
    seed: int
    start: datetime
    end: datetime
    environment: str
    base_profile: Mapping[str, float]
    perturbations: tuple[ScenarioEvent, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "seed": self.seed,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "environment": self.environment,
            "base_profile": dict(self.base_profile),
            "perturbations": [asdict(event) | {"start": event.start.isoformat(), "end": event.end.isoformat(), "parameters": dict(event.parameters)} for event in self.perturbations],
            "metadata": dict(self.metadata),
        }

    @property
    def deterministic_hash(self) -> str:
        return _hash(self.to_dict())


@dataclass(frozen=True, slots=True)
class CampaignSpec:
    """One crop campaign under one climate scenario (duck-typed for the 5.29 validators)."""

    run_id: str
    climate: SyntheticClimateScenario
    crop: str
    variety: str
    plot_id: str
    cycle_id: str
    environment: str
    window: tuple[datetime, datetime] | None
    scenario: Scenario

    @property
    def start(self) -> datetime:
        return self.scenario.start

    @property
    def timestep_seconds(self) -> int:
        return self.scenario.resolution_seconds

    @property
    def initial_crop(self):
        return self.scenario.initial_crop

    @property
    def perennial(self) -> bool:
        return self.crop in PERENNIAL_CROPS

    @property
    def days(self) -> int:
        return (self.scenario.end - self.scenario.start).days


def campaign_cycle(crop: str) -> tuple[SyntheticCropCycle, datetime, datetime]:
    """Campaign dates from the existing synthetic cycles (first cycle per crop).

    Start: planting date, or 1 January of the campaign year for perennial cycles
    without one (dormancy season); end: the cycle's harvest end (inclusive).
    """
    plots = SyntheticReferenceDatasetGenerator.DEFAULT_PLOTS
    plot = next(item for item in plots if item.crop == crop)
    cycle = next(item for item in SyntheticReferenceDatasetGenerator._cycles((plot,)))
    start_date = cycle.planting_date or date(plot.campaign, 1, 1)
    end_date = (cycle.harvest_end or cycle.harvest_start) + timedelta(days=1)
    return cycle, datetime.combine(start_date, datetime.min.time(), tzinfo=UTC), datetime.combine(end_date, datetime.min.time(), tzinfo=UTC)


def _irrigation(event_id: str, start: datetime, end: datetime, amount: float) -> ScenarioEvent:
    return ScenarioEvent(event_id, "irrigation", start, end, amount, {"amount_mm": amount})


def _event(event_id: str, event_type: str, start: datetime, end: datetime, intensity: float, **parameters: float) -> ScenarioEvent:
    return ScenarioEvent(event_id, event_type, start, end, intensity, {**parameters, "ramp_hours": EVENT_RAMP_HOURS})


def build_campaign(crop: str, environment: str, scenario_id: str, *, seed: int = DEFAULT_SEED) -> CampaignSpec:
    if crop not in KNOWN_CROPS:
        raise ScenarioError(f"unknown crop: {crop}")
    if environment == "greenhouse" and crop not in ANNUAL_GREENHOUSE_CROPS:
        raise ScenarioError(f"greenhouse is not configured for {crop}")
    if scenario_id not in (*MANDATORY_SCENARIOS, *SUPPLEMENTARY_SCENARIOS):
        raise ScenarioError(f"unknown scenario: {scenario_id}")
    cycle, start, end = campaign_cycle(crop)
    days = (end - start).days
    window_start = start + timedelta(days=days // 2)
    window = (window_start, window_start + timedelta(days=EVENT_DAYS))
    irrigation = BASE_IRRIGATION_MM_H * IRRIGATION_FACTOR.get(scenario_id, 1.0)
    events: list[ScenarioEvent] = []
    gap = scenario_id in {"HEAT_WAVE_WITH_DRYNESS", "HIGH_RADIATION_WITH_LOW_WATER", "RECOVERY_AFTER_STRESS"}
    if gap:
        events += [_irrigation("irrigation_before", start, window[0], irrigation), _irrigation("irrigation_after", window[1], end, irrigation)]
    else:
        events.append(_irrigation("irrigation_season", start, end, irrigation))
    if scenario_id in {"HEAT_WAVE", "HEAT_WAVE_WITH_DRYNESS", "RECOVERY_AFTER_STRESS"}:
        events.append(_event("heat_wave", "heat", *window, 8.0, temperature_offset_c=8.0))
    if scenario_id == "COLD_WAVE":
        events.append(_event("cold_wave", "cold_wave", *window, 8.0, temperature_offset_c=8.0))
    if scenario_id == "HEAT_WAVE_WITH_DRYNESS":
        events.append(_event("dry_air", "high_vpd", *window, 20.0, relative_humidity_pct=20.0))
    if scenario_id == "HIGH_RADIATION_WITH_LOW_WATER":
        events.append(_event("bright_spell", "high_radiation", *window, 1.3, radiation_multiplier=1.3))
    if scenario_id == "WIND_SPELL":
        events.append(_event("wind_spell", "wind", *window, 3.0, speed_multiplier=3.0))
    if scenario_id == "RAIN_SPELL":
        events.append(ScenarioEvent("rain_spell", "wet", window[0], window[0] + timedelta(days=3), 2.0, {"rain_rate_mm_h": 2.0}))
    has_window = scenario_id not in {"BASE_SEASON", *PROFILE_SHIFTS}
    variety = KNOWN_VARIETIES.get(crop, "UNSPECIFIED")
    initial_crop, initial_soil = _initial_state(crop, variety, start)
    profile = climate_profile(scenario_id)
    climate = SyntheticClimateScenario(
        scenario_id, seed, start, end, environment, profile, tuple(event for event in events if event.event_type != "irrigation"),
        {"source_type": "SYNTHETIC", "generator": "WeatherEngine(seasonal + daily variability) + ScenarioEvent overlays with ramps", "irrigation_mm_h": irrigation, "represents_real_climatology": False},
    )
    plot = next(item for item in SyntheticReferenceDatasetGenerator.DEFAULT_PLOTS if item.crop == crop)
    run_id = f"p532_{crop}_{environment}_{scenario_id.lower()}"
    scenario = Scenario(
        run_id, run_id, f"Phase 5.32 synthetic {scenario_id} campaign", crop, variety, start, end, TIMESTEP_SECONDS,
        ScenarioKind.SYNTHETIC if scenario_id == "BASE_SEASON" else ScenarioKind.STRESS_TEST, initial_crop, initial_soil,
        WeatherState(20.0, 60.0, 0.0, 2.0, 180.0, 0.0, 1013.0), "passive_greenhouse" if environment == "greenhouse" else "outdoor",
        tuple(events), labels=(f"climate={scenario_id}", f"weather_seed={seed}"), seed=seed,
    )
    return CampaignSpec(run_id, climate, crop, variety, plot.plot_id, cycle.crop_cycle_id, environment, window if has_window else None, scenario)


def default_campaigns(crops: Sequence[str] = KNOWN_CROPS, scenarios: Sequence[str] = MANDATORY_SCENARIOS, *, seed: int = DEFAULT_SEED, supplementary: bool = True) -> tuple[CampaignSpec, ...]:
    specs = []
    for crop in crops:
        for environment in ("outdoor", "greenhouse") if crop in ANNUAL_GREENHOUSE_CROPS else ("outdoor",):
            for scenario_id in scenarios:
                specs.append(build_campaign(crop, environment, scenario_id, seed=seed))
    if supplementary and "tomato" in crops:
        specs += [build_campaign("tomato", "outdoor", scenario_id, seed=seed) for scenario_id in SUPPLEMENTARY_SCENARIOS]
    return tuple(specs)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def _max_abs_difference(resumed: Mapping[str, float], continuous: Mapping[str, float]) -> float:
    """max |resumed[k] - continuous[k]| over the resumed snapshot's keys (each snapshot flattened once)."""
    return max(abs(value - continuous[key]) for key, value in resumed.items())


def _indices(spec: CampaignSpec, start: datetime, end: datetime) -> range:
    return range(int((start - spec.start).total_seconds() // spec.timestep_seconds), int((end - spec.start).total_seconds() // spec.timestep_seconds))


def stress_exposure(snapshots: Sequence[CropSimulationSnapshot], indices: Sequence[int] | None = None) -> dict[str, dict[str, float]]:
    """Hours with each existing stress/limitation factor active (> 0) and its integral (stress-hours)."""
    selected = [snapshots[i] for i in indices] if indices is not None else list(snapshots)
    channels: dict[str, Callable[[CropSimulationSnapshot], float]] = {
        "heat": lambda s: s.crop.heat_stress,
        "cold": lambda s: s.crop.cold_stress,
        "water": lambda s: s.crop.water_stress,
        "vpd": lambda s: s.crop.vpd_stress,
        "radiation": lambda s: s.crop.radiation_stress,
        "nutrient": lambda s: 1.0 - s.crop.nutrient_status,
    }
    return {
        name: {"hours": float(sum(1 for s in selected if getter(s) > 0.0)), "stress_hours": sum(getter(s) for s in selected), "days_with_stress": float(len({s.simulation_time.date() for s in selected if getter(s) > 0.0}))}
        for name, getter in channels.items()
    }


def response_metrics(spec: CampaignSpec, snapshots: Sequence[CropSimulationSnapshot]) -> dict[str, Any]:
    rue = RadiationGrowthEngine().profile_for(spec.crop).rue_g_dm_mj_par
    final = snapshots[-1].crop
    water = [s.water_balance for s in snapshots if s.water_balance is not None]
    stage_entries: dict[str, str] = {}
    for snapshot in snapshots:
        stage_entries.setdefault(snapshot.crop.current_stage, snapshot.simulation_time.isoformat())
    maturity_time = next((s.simulation_time.isoformat() for s in snapshots if s.crop.maturity_index >= 1.0), None)
    mean = lambda getter: sum(getter(s) for s in snapshots) / len(snapshots)
    return {
        "final_biomass_g_m2": final.biomass_total,
        "final_lai": final.leaf_area_index,
        "final_maturity": final.maturity_index,
        "harvest_ready": final.harvest_ready,
        "cumulative_potential_growth_g_m2": sum(s.potential_growth_g_m2 for s in snapshots),
        "cumulative_actual_growth_g_m2": sum(s.actual_growth_g_m2 for s in snapshots),
        "cumulative_apar_mj_m2": sum(s.potential_growth_g_m2 for s in snapshots) / rue,
        "water_use_mm": sum(w.transpiration_mm + w.evaporation_mm for w in water),
        "irrigation_applied_mm": sum(w.irrigation_applied_mm for w in water),
        "precipitation_mm": sum(w.precipitation_mm for w in water),
        "min_soil_vwc": min(s.soil.vwc_m3_m3 for s in snapshots),
        "peak_heat_damage": max(s.crop.heat_damage for s in snapshots),
        "peak_frost_damage": max(s.crop.frost_damage for s in snapshots),
        "lai_senescence_after_peak": max(s.crop.leaf_area_index for s in snapshots) - final.leaf_area_index,
        "mean_crop_temperature_c": mean(lambda s: s.weather.temperature_c),
        "mean_crop_rh_pct": mean(lambda s: s.weather.relative_humidity_pct),
        "mean_vpd_kpa": mean(lambda s: s.environment.vpd_kpa),
        "mean_crop_radiation_w_m2": mean(lambda s: s.weather.solar_radiation_w_m2),
        "mean_co2_ppm": mean(lambda s: s.microclimate.indoor_state.co2_ppm),
        "maturity_time": maturity_time,
        "stage_entry_times": stage_entries,
        "dormancy_release_time": next((s.simulation_time.isoformat() for s in snapshots if s.crop.dormancy_released), None) if spec.perennial else None,
    }


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CampaignResult:
    spec: CampaignSpec
    status: CampaignStatus
    steps: int
    invariants: Mapping[str, int]
    extra_invariants: Mapping[str, Any]
    stress: Mapping[str, Any]
    window_stress: Mapping[str, Any] | None
    metrics: Mapping[str, Any]
    trajectory_hash: str
    warnings: tuple[str, ...]
    failures: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        spec = self.spec
        return {
            "run_id": spec.run_id,
            "scenario_id": spec.climate.scenario_id,
            "crop": spec.crop,
            "variety": spec.variety,
            "variety_parameters": "SPECIES_FALLBACK",
            "plot_id": spec.plot_id,
            "cycle_id": spec.cycle_id,
            "environment": spec.environment,
            "seed": spec.climate.seed,
            "start": spec.start.isoformat(),
            "end": spec.scenario.end.isoformat(),
            "campaign_days": spec.days,
            "event_window": [spec.window[0].isoformat(), spec.window[1].isoformat()] if spec.window else None,
            "climate_scenario_hash": spec.climate.deterministic_hash,
            "project_scenario_config_hash": spec.scenario.config_hash(),
            "status": self.status.value,
            "steps": self.steps,
            "invariant_violations": dict(self.invariants),
            "campaign_invariants": dict(self.extra_invariants),
            "stress_exposure": dict(self.stress),
            "window_stress_exposure": dict(self.window_stress) if self.window_stress else None,
            "response_metrics": dict(self.metrics),
            "trajectory_hash": self.trajectory_hash,
            "warnings": list(self.warnings),
            "failures": list(self.failures),
        }


# ---------------------------------------------------------------------------
# Suite
# ---------------------------------------------------------------------------


class SeasonalSyntheticCampaignSuite:
    VERSION = VERSION

    def __init__(self, root: str | Path, *, registry: ParameterRegistry | None = None, crops: Sequence[str] = KNOWN_CROPS, scenarios: Sequence[str] = MANDATORY_SCENARIOS, seed: int = DEFAULT_SEED, supplementary: bool = True, include_multi: bool = True) -> None:
        self.root = Path(root)
        self.registry = registry or ParameterRegistry.from_repository(self.root)
        self.crops = tuple(crops)
        self.scenarios = tuple(scenarios)
        self.seed = seed
        self.supplementary = supplementary
        self.include_multi = include_multi
        self.runner = ScenarioRunner(seasonal_weather_factory)
        self._timings: dict[str, float] = {}

    def campaigns(self) -> tuple[CampaignSpec, ...]:
        return default_campaigns(self.crops, self.scenarios, seed=self.seed, supplementary=self.supplementary)

    def run(self, spec: CampaignSpec) -> ScenarioResult:
        return self.runner.run(spec.scenario)

    # -- per-campaign evaluation ------------------------------------------------

    def evaluate(self, spec: CampaignSpec, result: ScenarioResult) -> CampaignResult:
        snapshots = result.snapshots
        expected = int((spec.scenario.end - spec.scenario.start).total_seconds() // spec.timestep_seconds)
        failures, warnings = [], []
        if result.status != "SUCCESS" or len(snapshots) != expected:
            failures.append(f"campaign incomplete: {len(snapshots)}/{expected} steps; {'; '.join(result.warnings)}")
        invariant_counts: dict[str, int] = {}
        extra: dict[str, Any] = {}
        stress, window_stress, metrics = {}, None, {}
        if snapshots:
            metric_list, issues = validate_trajectory(spec, snapshots)
            invariant_counts = {metric.name.split(".")[1]: int(metric.value or 0) for metric in metric_list}
            failures += [issue.message for issue in issues]
            extra = self._campaign_invariants(spec, snapshots)
            failures += [f"{name} violated" for name, ok in extra.items() if ok is False]
            stress = stress_exposure(snapshots)
            if spec.window is not None:
                window_stress = stress_exposure(snapshots, _indices(spec, *spec.window))
            metrics = response_metrics(spec, snapshots)
            if spec.perennial and metrics["dormancy_release_time"] is None:
                warnings.append("MODEL_BEHAVIOR: dormancy never released - the chilling requirement of the existing phenology profile was not met under this synthetic winter (no growth season follows)")
            elif metrics["maturity_time"] is None:
                warnings.append("SCENARIO_DESIGN_ISSUE: maturity not reached before the synthetic cycle's harvest date (calendar from the existing synthetic cycle, thermal time from the engineering phenology profile)")
        status = CampaignStatus.FAIL if failures else (CampaignStatus.PASS_WITH_WARNINGS if warnings else CampaignStatus.PASS)
        return CampaignResult(spec, status, len(snapshots), invariant_counts, extra, stress, window_stress, metrics, trajectory_hash(snapshots), tuple(warnings), tuple(failures))

    def _campaign_invariants(self, spec: CampaignSpec, snapshots: Sequence[CropSimulationSnapshot]) -> dict[str, Any]:
        times = [s.simulation_time for s in snapshots]
        greenhouse = spec.environment == "greenhouse"
        water_from_nothing = 0
        previous_storage = spec.scenario.initial_soil.root_zone_water
        for snapshot in snapshots:
            balance = snapshot.water_balance
            incoming = (balance.irrigation_applied_mm + balance.precipitation_mm) if balance else 0.0
            if snapshot.soil.root_zone_water - previous_storage > incoming + FLOAT_TOLERANCE:
                water_from_nothing += 1
            previous_storage = snapshot.soil.root_zone_water
        crop_uses_microclimate = all(
            (s.weather.temperature_c == s.microclimate.indoor_state.temperature_c and s.weather.relative_humidity_pct == s.microclimate.indoor_state.relative_humidity_pct
             and s.weather.solar_radiation_w_m2 == s.microclimate.indoor_state.solar_radiation_w_m2 and s.environment.vpd_kpa == s.microclimate.indoor_state.vpd_kpa
             and s.weather.rain_rate_mm_h == 0.0) if greenhouse else s.weather == s.outdoor_weather
            for s in snapshots
        )
        return {
            "timestamps_strictly_increasing": all(b > a for a, b in zip(times, times[1:])),
            "no_duplicate_steps": len(times) == len(set(times)),
            "uniform_timestep": all((b - a).total_seconds() == spec.timestep_seconds for a, b in zip(times, times[1:])),
            "no_soil_water_from_nothing": water_from_nothing == 0,
            "crop_consumes_correct_environment": crop_uses_microclimate,
            "co2_single_response": all(s.co2_factor == CropGrowthEngine.co2_response(s.microclimate.indoor_state.co2_ppm) for s in snapshots),
            "physical_ranges": all(s.environment.vpd_kpa >= 0 and 0 <= s.microclimate.indoor_state.relative_humidity_pct <= 100 and s.weather.solar_radiation_w_m2 >= 0 and s.microclimate.indoor_state.co2_ppm >= 0 for s in snapshots),
        }

    # -- direction checks vs BASE_SEASON ------------------------------------------

    def directions(self, results: Mapping[str, CampaignResult], raw: Mapping[str, ScenarioResult]) -> list[dict[str, Any]]:
        rows = []
        for run_id, result in sorted(results.items()):
            spec = result.spec
            scenario_id = spec.climate.scenario_id
            if scenario_id == "BASE_SEASON":
                continue
            base_id = f"p532_{spec.crop}_{spec.environment}_base_season"
            if base_id not in results:
                continue
            base, base_raw, snaps = results[base_id], raw[base_id].snapshots, raw[run_id].snapshots
            checks = self._direction_checks(spec, scenario_id, result, base, snaps, base_raw)
            deltas = {key: result.metrics[key] - base.metrics[key] for key in ("final_biomass_g_m2", "final_lai", "final_maturity", "cumulative_apar_mj_m2", "cumulative_potential_growth_g_m2", "water_use_mm")}
            deltas |= {f"{name}_stress_hours": result.stress[name]["stress_hours"] - base.stress[name]["stress_hours"] for name in result.stress}
            consistent = all(check["passed"] is not False for check in checks)
            rows.append({
                "run_id": run_id, "base_run_id": base_id, "scenario_id": scenario_id, "crop": spec.crop, "environment": spec.environment,
                "response_metric_deltas": deltas, "direction_checks": checks,
                "classification": BEHAVIOR_CONSISTENT if consistent else BEHAVIOR_INCONSISTENT,
                "biological_validation": "NOT_CLAIMED",
            })
        return rows

    def _direction_checks(self, spec: CampaignSpec, scenario_id: str, result: CampaignResult, base: CampaignResult, snaps, base_snaps) -> list[dict[str, Any]]:
        def check(name: str, value: Any, passed: bool | None, expectation: str) -> dict[str, Any]:
            return {"check": name, "value": value, "passed": passed, "expectation": expectation}

        m, b = result.metrics, base.metrics
        s, bs = result.stress, base.stress
        checks = []
        first_active = next((i for i, snapshot in enumerate(base_snaps) if snapshot.potential_growth_g_m2 > 0.0), None)
        if scenario_id == "HOT_SEASON":
            checks += [check("warmer_crop_environment", m["mean_crop_temperature_c"] - b["mean_crop_temperature_c"], m["mean_crop_temperature_c"] > b["mean_crop_temperature_c"], "season-long +3 C gives a warmer crop environment"),
                       check("heat_stress_not_lower", s["heat"]["stress_hours"] - bs["heat"]["stress_hours"], s["heat"]["stress_hours"] >= bs["heat"]["stress_hours"], "heat stress exposure does not decrease")]
        elif scenario_id == "COLD_SEASON":
            checks += [check("colder_crop_environment", m["mean_crop_temperature_c"] - b["mean_crop_temperature_c"], m["mean_crop_temperature_c"] < b["mean_crop_temperature_c"], "season-long -3 C gives a colder crop environment"),
                       check("cold_stress_not_lower", s["cold"]["stress_hours"] - bs["cold"]["stress_hours"], s["cold"]["stress_hours"] >= bs["cold"]["stress_hours"], "cold stress exposure does not decrease")]
        elif scenario_id in {"LOW_RADIATION", "HIGH_RADIATION"}:
            sign = -1 if scenario_id == "LOW_RADIATION" else 1
            if first_active is not None:
                delta = snaps[first_active].potential_growth_g_m2 - base_snaps[first_active].potential_growth_g_m2
                checks.append(check("controlled_apar_response", delta, delta * sign > 0, "at the first active step (identical crop state) APAR and potential growth move with radiation"))
            active = b["cumulative_apar_mj_m2"] > 0.0
            checks.append(check("cumulative_apar_delta", m["cumulative_apar_mj_m2"] - b["cumulative_apar_mj_m2"], (m["cumulative_apar_mj_m2"] < b["cumulative_apar_mj_m2"]) if sign < 0 and active else None, "lower radiation lowers cumulative APAR (not applicable without an active canopy); for higher radiation the cumulative value is reported only (other limitations may act)"))
        elif scenario_id == "DRY_SEASON":
            checks += [check("drier_air_higher_vpd", m["mean_vpd_kpa"] - b["mean_vpd_kpa"], m["mean_vpd_kpa"] > b["mean_vpd_kpa"], "lower humidity raises mean VPD"),
                       check("water_limitation_higher", s["water"]["stress_hours"] - bs["water"]["stress_hours"], (s["water"]["stress_hours"] > bs["water"]["stress_hours"]) if s["water"]["stress_hours"] > 0.0 or bs["water"]["stress_hours"] > 0.0 else None, "halved irrigation raises water-stress exposure when water becomes limiting (not applicable if irrigation still exceeds demand)")]
        elif scenario_id == "HUMID_SEASON":
            checks.append(check("humid_air_lower_vpd", m["mean_vpd_kpa"] - b["mean_vpd_kpa"], m["mean_vpd_kpa"] < b["mean_vpd_kpa"], "higher humidity lowers mean VPD"))
        if spec.window is not None:
            window = _indices(spec, *spec.window)
            # Weather is evaluated at step end: the step ending exactly at the window start may already see an unramped event.
            identical_before = all(snaps[i].crop == base_snaps[i].crop for i in range(max(0, window.start - 1)))
            checks.append(check("identical_before_event", identical_before, identical_before, "the scenario and BASE_SEASON coincide before the event window"))
            wm = result.window_stress or {}
            wb = stress_exposure(base_snaps, window)
            window_vpd = sum(snaps[i].environment.vpd_kpa for i in window) / len(window)
            base_window_vpd = sum(base_snaps[i].environment.vpd_kpa for i in window) / len(window)
            growth = sum(snaps[i].actual_growth_g_m2 for i in window)
            base_growth = sum(base_snaps[i].actual_growth_g_m2 for i in window)
            if scenario_id in {"HEAT_WAVE", "HEAT_WAVE_WITH_DRYNESS", "RECOVERY_AFTER_STRESS"}:
                checks += [check("window_heat_stress_not_lower", wm["heat"]["stress_hours"] - wb["heat"]["stress_hours"], wm["heat"]["stress_hours"] >= wb["heat"]["stress_hours"], "a heat wave does not lower heat stress"),
                           check("window_vpd_higher", window_vpd - base_window_vpd, window_vpd > base_window_vpd, "warmer (and drier) air raises VPD"),
                           check("window_growth_delta", growth - base_growth, None, "growth change reported, not imposed")]
            if scenario_id == "COLD_WAVE":
                checks.append(check("window_cold_stress_not_lower", wm["cold"]["stress_hours"] - wb["cold"]["stress_hours"], wm["cold"]["stress_hours"] >= wb["cold"]["stress_hours"], "a cold wave does not lower cold stress"))
            if scenario_id in {"HEAT_WAVE_WITH_DRYNESS", "HIGH_RADIATION_WITH_LOW_WATER", "RECOVERY_AFTER_STRESS"}:
                checks.append(check("window_water_stress_higher", wm["water"]["stress_hours"] - wb["water"]["stress_hours"], wm["water"]["stress_hours"] > wb["water"]["stress_hours"], "an irrigation gap raises water stress"))
            if scenario_id == "HIGH_RADIATION_WITH_LOW_WATER":
                potential = sum(snaps[i].potential_growth_g_m2 for i in window)
                base_potential = sum(base_snaps[i].potential_growth_g_m2 for i in window)
                checks.append(check("window_apar_higher", potential - base_potential, potential > base_potential if base_potential > 0 else None, "brighter spell raises APAR (potential growth) during the event"))
            if scenario_id in {"RECOVERY_AFTER_STRESS", "HEAT_WAVE_WITH_DRYNESS", "HIGH_RADIATION_WITH_LOW_WATER"}:
                peak = max(snaps[i].crop.water_stress for i in window)
                checks.append(check("stress_decreases_after_event", snaps[-1].crop.water_stress - peak, snaps[-1].crop.water_stress < peak, "water stress decreases after irrigation resumes"))
            if scenario_id in {"RECOVERY_AFTER_STRESS", "HEAT_WAVE_WITH_DRYNESS"}:
                checks.append(check("lost_biomass_not_restored", m["final_biomass_g_m2"] - b["final_biomass_g_m2"], m["final_biomass_g_m2"] <= b["final_biomass_g_m2"] + FLOAT_TOLERANCE, "biomass lost during a stress-only event does not reappear"))
            if scenario_id in {"WIND_SPELL", "RAIN_SPELL"}:
                checks.append(check("event_response_reported", m["final_biomass_g_m2"] - b["final_biomass_g_m2"], None, "wind/rain response reported (wind is not an input of the crop engines; rain adds soil water outdoors)"))
        return checks

    # -- climate profile checks ------------------------------------------------------

    def climate_profile_checks(self) -> dict[str, Any]:
        engine = WeatherEngine(weather_configuration(climate_profile("BASE_SEASON"), self.seed))
        start = datetime(2026, 1, 1, tzinfo=UTC)
        hours = [start + timedelta(hours=h) for h in range(365 * 24)]
        weather = [engine.generate(t) for t in hours]
        temps = [w.temperature_c for w in weather]
        jumps = [abs(b - a) for a, b in zip(temps, temps[1:])]
        epsilon = timedelta(seconds=1)  # WeatherEngine resolves time to the second
        midnight_gaps = []
        for day in range(1, 365):
            before, at = engine.generate(start + timedelta(days=day) - epsilon), engine.generate(start + timedelta(days=day))
            midnight_gaps.append(max(abs(before.temperature_c - at.temperature_c), abs(before.relative_humidity_pct - at.relative_humidity_pct)))
        month = lambda m: [w for t, w in zip(hours, weather) if t.month == m]
        january, july = month(1), month(7)
        daylight = lambda subset: sum(1 for w in subset if w.solar_radiation_w_m2 > 0) / (len(subset) / 24)
        night_zero = all(w.solar_radiation_w_m2 == 0.0 for t, w in zip(hours, weather) if t.hour in (0, 1, 2, 3, 22, 23))
        peak_hours = [max(range(24), key=lambda h: weather[d * 24 + h].solar_radiation_w_m2) for d in range(365)]
        min_hours = [min(range(24), key=lambda h: temps[d * 24 + h]) for d in range(365)]
        max_hours = [max(range(24), key=lambda h: temps[d * 24 + h]) for d in range(365)]
        replay = [WeatherEngine(weather_configuration(climate_profile("BASE_SEASON"), self.seed)).generate(t) for t in hours[:240]]
        other_seed = [WeatherEngine(weather_configuration(climate_profile("BASE_SEASON"), self.seed + 1)).generate(t) for t in hours[:240]]
        base_scenario = build_campaign("tomato", "outdoor", "BASE_SEASON", seed=self.seed).scenario
        heat_spec = build_campaign("tomato", "outdoor", "HEAT_WAVE", seed=self.seed)
        base_weather = seasonal_weather_factory(base_scenario)
        from agri_twin.application.scenarios import _ScenarioWeatherProvider

        heat_weather = _ScenarioWeatherProvider(heat_spec.scenario, seasonal_weather_factory(heat_spec.scenario))
        w0, w1 = heat_spec.window
        offsets = [heat_weather.get(t).temperature_c - base_weather.get(t).temperature_c for t in (w0 + timedelta(hours=h) for h in range(0, EVENT_DAYS * 24 + 1, 6))]
        after = [heat_weather.get(t).temperature_c == base_weather.get(t).temperature_c for t in (w1 + timedelta(hours=h) for h in range(1, 48))]
        checks = {
            "seasonal_gradient": {"passed": sum(w.temperature_c for w in july) / len(july) > sum(w.temperature_c for w in january) / len(january) + 10.0 and sum(w.solar_radiation_w_m2 for w in july) > sum(w.solar_radiation_w_m2 for w in january), "january_mean_c": sum(w.temperature_c for w in january) / len(january), "july_mean_c": sum(w.temperature_c for w in july) / len(july)},
            "seasonal_daylength": {"passed": daylight(july) > daylight(january), "january_daylight_h": daylight(january), "july_daylight_h": daylight(july)},
            "continuity_across_days": {"passed": max(midnight_gaps) < 0.01 and max(jumps) < 5.0, "max_hourly_jump_c": max(jumps), "max_gap_across_midnight_1s": max(midnight_gaps), "threshold": 0.01, "threshold_kind": "ENGINEERING_TEST_THRESHOLD (continuous slope over 1 s is ~0.002; a daily re-phasing would jump by several units)"},
            "night_radiation_zero": {"passed": night_zero},
            "radiation_peak_midday": {"passed": all(11 <= h <= 13 for h in peak_hours), "peak_hours": sorted(set(peak_hours))},
            "diurnal_temperature_phase": {"passed": all(3 <= h <= 7 for h in min_hours) and all(13 <= h <= 17 for h in max_hours), "min_hours": sorted(set(min_hours)), "max_hours": sorted(set(max_hours))},
            "physical_bounds": {"passed": all(0 <= w.relative_humidity_pct <= 100 and w.solar_radiation_w_m2 >= 0 for w in weather)},
            "daily_variability_reproducible": {"passed": replay == weather[:240] and other_seed != weather[:240]},
            "event_gradual_onset_and_decay": {"passed": abs(offsets[0]) < 1e-9 and abs(offsets[-1]) < 1e-9 and abs(max(offsets) - 8.0) < 1e-9 and all(-1e-9 <= o <= 8.0 + 1e-9 for o in offsets) and 0.0 < offsets[1] < 8.0, "offsets_c_every_6h": offsets},
            "return_to_base_after_event": {"passed": all(after)},
        }
        return {"status": "PASS" if all(item["passed"] for item in checks.values()) else "FAIL", "profile": dict(BASE_PROFILE), "seed": self.seed, "checks": checks}

    # -- checkpoint / restart ---------------------------------------------------------

    def restart(self, spec: CampaignSpec, continuous: ScenarioResult, fractions: Sequence[float] = (0.25, 0.5, 0.75)) -> dict[str, Any]:
        steps = len(continuous.snapshots)
        rows = []
        for fraction in fractions:
            index = int(steps * fraction)
            index = max(0, min(steps - 2, index - (index + 1 - 12) % 24))
            snapshot = continuous.snapshots[index]
            payload = checkpoint_payload(snapshot)
            restart_time, crop, soil, micro = restore_checkpoint(payload)
            resumed = self.runner.run(resumed_scenario(spec.scenario, restart_time, crop, soil, micro))
            tail = continuous.snapshots[index + 1:]
            aligned = len(resumed.snapshots) == len(tail) and all(a.simulation_time == b.simulation_time for a, b in zip(resumed.snapshots, tail))
            difference = max((_max_abs_difference(snapshot_numbers(a), snapshot_numbers(b)) for a, b in zip(resumed.snapshots, tail)), default=math.inf)
            rows.append({"checkpoint": restart_time.isoformat(), "fraction": fraction, "checkpoint_hash": hashlib.sha256(payload.encode("utf-8")).hexdigest(), "aligned": aligned, "max_difference": difference, "equivalent": aligned and difference <= FLOAT_TOLERANCE})
        return {"run_id": spec.run_id, "status": "PASS" if all(row["equivalent"] for row in rows) else "FAIL", "checkpoints": rows}

    # -- persistence -------------------------------------------------------------------

    def persistence(self, spec: CampaignSpec, result: ScenarioResult) -> dict[str, Any]:
        repository = InMemoryTwinStateRepository()
        mismatches = 0
        daily = [s for i, s in enumerate(result.snapshots) if (i + 1) % 24 == 0]
        for snapshot in daily:
            state = twin_state_from_snapshot(snapshot, spec)
            repository.save_snapshot(TwinSnapshot(snapshot.simulation_time, (state,)))
            stored = repository.get_exact(spec.plot_id, spec.cycle_id, snapshot.simulation_time)
            if stored != state or TwinState.from_dict(json.loads(json.dumps(stored.to_dict()))) != state or stored.lai != snapshot.crop.leaf_area_index:
                mismatches += 1
        return {"run_id": spec.run_id, "status": "PASS" if mismatches == 0 and len(repository.history(spec.plot_id, spec.cycle_id)) == len(daily) else "FAIL", "daily_states": len(daily), "mismatches": mismatches}

    # -- immutability ------------------------------------------------------------------

    def _fingerprint(self) -> dict[str, str]:
        return {
            "parameter_registry": _hash([record.to_dict() for record in self.registry.records]),
            "parameter_sets": _hash({crop: ParameterSet.from_registry(self.registry, crop=crop).value_map() for crop in KNOWN_CROPS}),
            "greenhouse_configuration": _hash({f.name: getattr(GreenhouseConfiguration(), f.name) for f in fields(GreenhouseConfiguration)}),
        }

    # -- report ------------------------------------------------------------------------

    def build_report(self) -> "SeasonalCampaignReport":
        started = time.perf_counter()
        before = self._fingerprint()
        specs = self.campaigns()
        raw: dict[str, ScenarioResult] = {}
        durations: dict[str, float] = {}
        for spec in specs:
            timer = time.perf_counter()
            raw[spec.run_id] = self.run(spec)
            durations[spec.run_id] = time.perf_counter() - timer
        results = {spec.run_id: self.evaluate(spec, raw[spec.run_id]) for spec in specs}
        by_id = {spec.run_id: spec for spec in specs}
        sections: dict[str, Any] = {"climate_profiles": self.climate_profile_checks(), "directions": self.directions(results, raw)}
        determinism_ids = sorted({run_id for run_id in results if run_id.startswith("p532_tomato_outdoor_")} | {run_id for run_id in results if run_id.endswith("_base_season")})
        mismatches = [run_id for run_id in determinism_ids if trajectory_hash(self.run(by_id[run_id]).snapshots) != results[run_id].trajectory_hash]
        sections["determinism"] = {"status": "PASS" if not mismatches else "FAIL", "replayed_runs": determinism_ids, "mismatches": mismatches, "method": "every scenario (tomato outdoor) and every crop/environment BASE_SEASON campaign is executed twice with the same seed, clock and scheduler; full trajectory hashes are compared"}
        restart_ids = [run_id for run_id in ("p532_tomato_outdoor_base_season", "p532_plum_outdoor_base_season", "p532_tomato_greenhouse_heat_wave") if run_id in results]
        restarts = [self.restart(by_id[r], raw[r]) for r in restart_ids]
        sections["restart"] = {"status": "PASS" if restarts and all(item["status"] == "PASS" for item in restarts) else "FAIL", "runs": restarts}
        persistence_id = next(iter(results))
        sections["persistence"] = self.persistence(by_id[persistence_id], raw[persistence_id])
        if self.include_multi:
            multi = IntegratedSyntheticValidationSuite(self.root, registry=self.registry, include_integration_suites=False)
            seasonal = weather_configuration(climate_profile("BASE_SEASON"), self.seed)
            sections["multi_plot"] = multi.multi_plot(weather=seasonal)
            sections["multi_cycle"] = multi.multi_cycle(weather=seasonal)
        greenhouse = [result for result in results.values() if result.spec.environment == "greenhouse"]
        sections["greenhouse"] = {
            "status": "PASS" if greenhouse and all(result.extra_invariants["crop_consumes_correct_environment"] and result.status is not CampaignStatus.FAIL for result in greenhouse) else ("NOT_APPLICABLE" if not greenhouse else "FAIL"),
            "campaigns": len(greenhouse),
            "chain": "Weather -> SimplifiedGreenhouseModel (persistent microclimate) -> MicroclimateState -> crop (indoor T, RH, VPD, radiation, CO2; no rain)",
        }
        sections["static_audit"] = static_audit(self.root)
        after = self._fingerprint()
        sections["immutability"] = {"status": "PASS" if before == after else "FAIL", "before": before, "after": after}
        total_days = sum(spec.days for spec in specs)
        execution = {
            "total_seconds": time.perf_counter() - started,
            "campaign_seconds": {k: round(v, 3) for k, v in durations.items()},
            "seconds_per_simulated_day": sum(durations.values()) / total_days if total_days else None,
            "campaigns": len(specs),
            "note": "wall-clock durations are execution metadata only; excluded from all hashes",
        }
        unsupported = [
            {"capability": "PERENNIAL_CONSECUTIVE_CAMPAIGNS", "status": "OPEN_MODEL_CAPABILITY", "classification": IssueClassification.MODEL_CAPABILITY_GAP.value, "detail": "PhenologyEngine has no transition from post_harvest_dormancy back to dormancy; one perennial campaign is simulated"},
            {"capability": "WIND_EFFECT_ON_CROP", "status": "NOT_SUPPORTED", "classification": IssueClassification.MODEL_CAPABILITY_GAP.value, "detail": "wind speed is not an input of the crop, stress or water-balance engines; WIND_SPELL is carried through the forcing only"},
            {"capability": "ACTUAL_EVAPOTRANSPIRATION_UNDER_DEFICIT", "status": "OPEN_MODEL_CAPABILITY", "classification": IssueClassification.MODEL_CAPABILITY_GAP.value, "detail": "WaterBalanceResult reports transpiration/evaporation demand even when soil water limits uptake; water_use_mm is a demand-based proxy"},
        ]
        open_decisions = []
        for crop in sorted({spec.crop for spec in specs if spec.perennial}):
            base = results.get(f"p532_{crop}_outdoor_base_season")
            if base is not None and base.metrics.get("dormancy_release_time") is None:
                open_decisions.append({
                    "decision": "PERENNIAL_CHILLING_SEASON_ONSET", "crop": crop, "classification": IssueClassification.OPEN_SCIENTIFIC_DECISION.value,
                    "detail": f"the existing synthetic cycle starts the {crop} campaign on {base.spec.start.date().isoformat()}; no chilling accumulation before that date is defined, and the existing chilling requirement is not met under BASE_SEASON, so its season-scale growth responses are not characterised (no date is invented)",
                })
        return SeasonalCampaignReport(VERSION, tuple(results.values()), sections, unsupported, self.seed, execution, tuple(open_decisions))

    def write_report(self, report: "SeasonalCampaignReport", directory: str | Path | None = None) -> tuple[Path, Path]:
        output = Path(directory) if directory is not None else self.root / "data" / "validation"
        output.mkdir(parents=True, exist_ok=True)
        report_path = output / "seasonal_synthetic_campaign_report.json"
        readme_path = output / "seasonal_synthetic_campaign_README.md"
        payload = report.to_dict()
        payload["execution_metadata"] = dict(report.execution_metadata)
        report_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        summary = report.summary()
        lines = [
            "# Seasonal synthetic campaign (Phase 5.32)",
            "",
            "Complete crop campaigns under plausible, deterministic synthetic climate scenarios. Results characterise the implemented model",
            "(scenario response metrics, MODEL_BEHAVIOR_CONSISTENT at most); they are not accuracy, calibration, biological validation or",
            "a representation of any real climatology.",
            "",
            f"- version: `{report.version}`; seed: `{report.seed}`",
            f"- campaigns: `{summary['campaigns']}`; status counts: `{json.dumps(summary['status_counts'], sort_keys=True)}`",
            f"- direction checks: `{summary['direction_rows']}` rows, inconsistent: `{summary['inconsistent_rows']}`",
            f"- qualified: `{summary['qualified']}`",
            f"- report hash: `{payload['report_hash']}` (execution metadata excluded)",
            "",
            "## Sections",
            "",
            *[f"- {name}: `{status}`" for name, status in summary["section_status"].items()],
            "",
            "## Open scientific decisions",
            "",
            *[f"- `{item['decision']}` ({item['crop']}): {item['detail']}" for item in report.open_decisions],
            "",
            "## Unsupported capabilities",
            "",
            *[f"- `{item['capability']}` ({item['status']}): {item['detail']}" for item in report.unsupported],
            "",
        ]
        readme_path.write_text("\n".join(lines), encoding="utf-8")
        return report_path, readme_path


@dataclass(frozen=True, slots=True)
class SeasonalCampaignReport:
    version: str
    campaigns: tuple[CampaignResult, ...]
    sections: Mapping[str, Any]
    unsupported: Sequence[Mapping[str, Any]]
    seed: int
    execution_metadata: Mapping[str, Any] = field(default_factory=dict, compare=False)
    open_decisions: Sequence[Mapping[str, Any]] = ()

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for result in self.campaigns:
            counts[result.status.value] = counts.get(result.status.value, 0) + 1
        directions = self.sections["directions"]
        section_status = {name: value["status"] for name, value in self.sections.items() if isinstance(value, Mapping) and "status" in value}
        inconsistent = sum(1 for row in directions if row["classification"] != BEHAVIOR_CONSISTENT)
        campaigns_ok = all(result.status is not CampaignStatus.FAIL for result in self.campaigns)
        sections_ok = all(status in {"PASS", "PASS_WITH_WARNINGS", "NOT_APPLICABLE"} for status in section_status.values())
        qualified = campaigns_ok and sections_ok and inconsistent == 0
        return {
            "campaigns": len(self.campaigns),
            "status_counts": dict(sorted(counts.items())),
            "crops": sorted({result.spec.crop for result in self.campaigns}),
            "varieties": sorted({result.spec.variety for result in self.campaigns}),
            "plots": sorted({result.spec.plot_id for result in self.campaigns}),
            "environments": sorted({result.spec.environment for result in self.campaigns}),
            "scenarios": sorted({result.spec.climate.scenario_id for result in self.campaigns}),
            "direction_rows": len(directions),
            "inconsistent_rows": inconsistent,
            "section_status": dict(sorted(section_status.items())),
            "qualified": qualified,
        }

    def to_dict(self) -> dict[str, Any]:
        summary = self.summary()
        qualified = summary["qualified"]
        mark = "QUALIFIED" if qualified else "NOT_QUALIFIED"
        payload = {
            "phase": "5.32",
            "version": self.version,
            "seed": self.seed,
            "campaigns": [result.to_dict() for result in self.campaigns],
            **{name: value for name, value in self.sections.items()},
            "unsupported_capabilities": [dict(item) for item in self.unsupported],
            "open_scientific_decisions": [dict(item) for item in self.open_decisions],
            "summary": summary,
            "scientific_status": {
                "SEASON_SCALE_SYNTHETIC_CAMPAIGN_FRAMEWORK": mark,
                "SYNTHETIC_CLIMATE_SCENARIOS": "QUALIFIED" if self.sections["climate_profiles"]["status"] == "PASS" else "NOT_QUALIFIED",
                "STRESS_RESPONSE_CONSISTENCY": "QUALIFIED" if summary["inconsistent_rows"] == 0 else "NOT_QUALIFIED",
                "outcome_classification": BEHAVIOR_CONSISTENT if summary["inconsistent_rows"] == 0 else BEHAVIOR_INCONSISTENT,
                "season_responses_not_characterised": sorted(item["crop"] for item in self.open_decisions),
                "REAL_VERIFIED": 0,
                "REAL_AGRICULTURAL_DATA_VERIFIED": False,
                "CALIBRATION_PERFORMED": False,
                "EXPERIMENTAL_VALIDATION_PERFORMED": False,
                "BIOLOGICAL_VALIDITY_CLAIMED": False,
                "FIELD_ACCURACY_CLAIMED": False,
                "DATA_ASSIMILATION_IMPLEMENTED": False,
                "meaning_of_qualified": "the software passed the synthetic scenarios and invariants of Phase 5.32; results do not quantitatively represent a real agricultural campaign",
            },
            "scientific_limitations": [
                "Synthetic climate scenarios are plausible software forcing, not real climatologies; no site is represented.",
                "Campaign calendars come from the existing synthetic cycles; thermal-time phenology is an engineering profile, so some cycles end before maturity.",
                "All crop parameters are species-level engineering defaults (SPECIES_FALLBACK); no varietal coefficients.",
                "Response metrics characterise the implemented model; they are not accuracy and carry no biological validation.",
                "Water use is demand-based (WaterBalanceEngine); wind does not act on crop engines; only one perennial campaign is supported.",
            ],
        }
        payload["report_hash"] = _hash(payload)
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, default=str)


__all__ = [
    "BASE_PROFILE",
    "CampaignResult",
    "CampaignSpec",
    "CampaignStatus",
    "MANDATORY_SCENARIOS",
    "SUPPLEMENTARY_SCENARIOS",
    "SeasonalCampaignReport",
    "SeasonalSyntheticCampaignSuite",
    "SyntheticClimateScenario",
    "build_campaign",
    "campaign_cycle",
    "climate_profile",
    "default_campaigns",
    "response_metrics",
    "seasonal_weather_factory",
    "stress_exposure",
    "weather_configuration",
]
