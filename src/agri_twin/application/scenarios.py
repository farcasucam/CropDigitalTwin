"""Reproducible synthetic agronomic scenarios for controlled experiments."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Mapping, Sequence

from agri_twin.application.clock import SimulationClock
from agri_twin.application.orchestrator import CropDigitalTwinOrchestrator, CropSimulationSnapshot
from agri_twin.application.weather import WeatherEngine
from agri_twin.domain import (
    ActuatorControl,
    CropGrowthState,
    FertilizationRequest,
    IrrigationRequest,
    ParameterSet,
    SoilState,
    WeatherConfiguration,
    WeatherState,
)
from agri_twin.domain.calibration import DatasetRole, Observation, ObservationDataset, ObservationResolution, SimulationPoint


class ScenarioError(ValueError):
    """Raised when a scenario configuration is invalid."""


class ScenarioKind(StrEnum):
    SYNTHETIC = "synthetic"
    HISTORICAL = "historical"
    OBSERVATIONAL = "observational"
    VALIDATION = "validation"
    CALIBRATION = "calibration"
    STRESS_TEST = "stress_test"
    BENCHMARK = "benchmark"


@dataclass(frozen=True, slots=True)
class ScenarioEvent:
    event_id: str
    event_type: str
    start: datetime
    end: datetime
    intensity: float = 0.0
    parameters: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_id or not self.event_type or self.start.tzinfo is None or self.end.tzinfo is None or self.end <= self.start:
            raise ScenarioError("scenario event identity and interval are invalid")
        if not math.isfinite(self.intensity):
            raise ScenarioError("event intensity must be finite")

    def active(self, timestamp: datetime) -> bool:
        return self.start <= timestamp <= self.end


@dataclass(frozen=True, slots=True)
class Scenario:
    scenario_id: str
    name: str
    description: str
    crop: str
    variety: str | None
    start: datetime
    end: datetime
    resolution_seconds: int
    kind: ScenarioKind
    initial_crop: CropGrowthState
    initial_soil: SoilState
    base_weather: WeatherState
    greenhouse_mode: str = "outdoor"
    events: tuple[ScenarioEvent, ...] = ()
    parameters: ParameterSet | None = None
    labels: tuple[str, ...] = ()
    seed: int | None = None

    def __post_init__(self) -> None:
        if not self.scenario_id or not self.name or self.start.tzinfo is None or self.end <= self.start:
            raise ScenarioError("scenario identity and period are invalid")
        if self.resolution_seconds <= 0:
            raise ScenarioError("scenario resolution must be positive")
        if self.initial_crop.crop_key != self.crop:
            raise ScenarioError("scenario crop does not match initial state")
        if any(event.start < self.start or event.end > self.end for event in self.events):
            raise ScenarioError("scenario event lies outside scenario period")

    def config_hash(self) -> str:
        payload = {
            "scenario_id": self.scenario_id, "name": self.name, "crop": self.crop, "variety": self.variety,
            "start": self.start.isoformat(), "end": self.end.isoformat(), "resolution_seconds": self.resolution_seconds,
            "kind": self.kind.value, "greenhouse_mode": self.greenhouse_mode, "seed": self.seed,
            "base_weather": asdict(self.base_weather), "initial_crop": self.initial_crop.to_dict(), "initial_soil": asdict(self.initial_soil),
            "events": [asdict(event) | {"start": event.start.isoformat(), "end": event.end.isoformat()} for event in self.events],
            "parameters": self.parameters.value_map() if self.parameters else {},
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    scenario_id: str
    config_hash: str
    status: str
    snapshots: tuple[CropSimulationSnapshot, ...]
    events: tuple[ScenarioEvent, ...]
    warnings: tuple[str, ...] = ()
    seed: int | None = None

    def simulation_points(self) -> tuple[SimulationPoint, ...]:
        return tuple(SimulationPoint(snapshot.simulation_time, {
            "biomass": snapshot.crop.biomass_total,
            "biomass_fruit": snapshot.crop.biomass_fruit,
            "lai": snapshot.crop.leaf_area_index,
            "water_stress": snapshot.crop.water_stress,
            "heat_stress": snapshot.crop.heat_stress,
            "frost_damage": snapshot.crop.frost_damage,
            "maturity": snapshot.crop.maturity_index,
        }, {
            "biomass": "g_DM_m-2", "biomass_fruit": "g_DM_m-2", "lai": "m2_m-2",
            "water_stress": "fraction", "heat_stress": "fraction", "frost_damage": "fraction", "maturity": "fraction",
        }) for snapshot in self.snapshots)

    def observation_dataset(self, variables: Sequence[str] = ("biomass", "lai")) -> ObservationDataset:
        points = self.simulation_points()
        observations = tuple(Observation(point.timestamp, variable, point.variables[variable], point.units[variable], resolution=ObservationResolution.DAILY) for point in points for variable in variables)
        return ObservationDataset(self.scenario_id, DatasetRole.TEST, observations)


class _ScenarioWeatherProvider:
    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario

    def get(self, timestamp: datetime) -> WeatherState:
        values = asdict(self.scenario.base_weather)
        for event in self.scenario.events:
            if not event.active(timestamp):
                continue
            if event.event_type in {"warm", "heat_wave", "heat"}:
                values["temperature_c"] += event.parameters.get("temperature_offset_c", event.intensity)
            elif event.event_type in {"cold", "frost"}:
                values["temperature_c"] = event.parameters.get("temperature_c", event.intensity)
            elif event.event_type in {"dry", "drought"}:
                values["rain_rate_mm_h"] = 0.0
            elif event.event_type == "wet":
                values["rain_rate_mm_h"] = event.parameters.get("rain_rate_mm_h", event.intensity)
            elif event.event_type in {"high_vpd", "low_vpd"}:
                values["relative_humidity_pct"] = event.parameters.get("relative_humidity_pct", event.intensity)
            elif event.event_type in {"low_radiation", "high_radiation", "photoinhibition"}:
                values["solar_radiation_w_m2"] = max(0.0, values["solar_radiation_w_m2"] * event.parameters.get("radiation_multiplier", event.intensity or 1.0))
        return WeatherState(**values)


class ScenarioRunner:
    """Execute a scenario using one injected SimulationClock and no wall time."""

    def run(self, scenario: Scenario) -> ScenarioResult:
        clock = SimulationClock(scenario.start)
        weather = WeatherEngine(WeatherConfiguration(simulation=WeatherConfiguration().simulation), provider=_ScenarioWeatherProvider(scenario))
        orchestrator = CropDigitalTwinOrchestrator(clock, weather, scenario.initial_crop, scenario.initial_soil, scenario.greenhouse_mode)
        snapshots: list[CropSimulationSnapshot] = []
        current = scenario.start
        try:
            while current < scenario.end:
                dt = min(scenario.resolution_seconds, int((scenario.end - current).total_seconds()))
                active = [event for event in scenario.events if event.active(current)]
                irrigation = self._irrigation(active)
                actuators = self._actuators(active)
                fertilization = self._fertilization(active)
                snapshots.append(orchestrator.step(dt, actuators, irrigation, fertilization))
                current += timedelta(seconds=dt)
            return ScenarioResult(scenario.scenario_id, scenario.config_hash(), "SUCCESS", tuple(snapshots), scenario.events, seed=scenario.seed)
        except Exception as exc:
            return ScenarioResult(scenario.scenario_id, scenario.config_hash(), "FAILED", tuple(snapshots), scenario.events, (str(exc),), scenario.seed)

    @staticmethod
    def _irrigation(events: Sequence[ScenarioEvent]) -> IrrigationRequest | None:
        for event in events:
            if event.event_type == "irrigation":
                return IrrigationRequest("scheduled", event.parameters.get("amount_mm", event.intensity), irrigation_type="drip")
        return None

    @staticmethod
    def _fertilization(events: Sequence[ScenarioEvent]) -> FertilizationRequest | None:
        for event in events:
            if event.event_type == "fertilization":
                return FertilizationRequest(event.parameters.get("amount_kg_ha", event.intensity), 1.0, "scheduled")
        return None

    @staticmethod
    def _actuators(events: Sequence[ScenarioEvent]) -> dict[str, ActuatorControl]:
        controls = {}
        for event in events:
            if event.event_type in {"shade", "heating", "cooling", "ventilation", "co2", "misting"}:
                controls[event.event_type] = ActuatorControl(event.parameters.get("value", event.intensity), maximum=max(1.0, event.parameters.get("maximum", 1.0)), capacity=event.parameters.get("capacity", max(1.0, event.parameters.get("maximum", 1.0))))
        return controls


@dataclass(frozen=True, slots=True)
class ScenarioComparison:
    scenario_ids: tuple[str, ...]
    deltas: Mapping[str, Mapping[str, float]]


def compare_scenarios(results: Sequence[ScenarioResult]) -> ScenarioComparison:
    if len(results) < 2:
        raise ScenarioError("at least two scenario results are required")
    baseline = results[0]
    base = baseline.snapshots[-1].crop
    deltas = {}
    for result in results[1:]:
        crop = result.snapshots[-1].crop
        deltas[result.scenario_id] = {
            "biomass": crop.biomass_total - base.biomass_total,
            "lai": crop.leaf_area_index - base.leaf_area_index,
            "water_stress": crop.water_stress - base.water_stress,
            "heat_stress": crop.heat_stress - base.heat_stress,
            "maturity": crop.maturity_index - base.maturity_index,
        }
    return ScenarioComparison(tuple(result.scenario_id for result in results), deltas)


@dataclass(frozen=True, slots=True)
class ScenarioSweepResult:
    parameter: str
    values: tuple[float, ...]
    results: tuple[ScenarioResult, ...]


def sweep_scenarios(scenario: Scenario, parameter: str, values: Sequence[float], runner: ScenarioRunner | None = None) -> ScenarioSweepResult:
    if not values or any(not math.isfinite(value) for value in values):
        raise ScenarioError("sweep values must be finite and non-empty")
    runner = runner or ScenarioRunner()
    results = []
    for value in values:
        event = ScenarioEvent(f"sweep-{parameter}-{value}", parameter, scenario.start, scenario.end, value, {"value": value, parameter: value})
        results.append(runner.run(replace(scenario, scenario_id=f"{scenario.scenario_id}-{parameter}-{value}", events=scenario.events + (event,))))
    return ScenarioSweepResult(parameter, tuple(values), tuple(results))