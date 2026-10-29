"""Reproducible synthetic agronomic scenarios for controlled experiments."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Callable, Mapping, Protocol, Sequence

from agri_twin.application.clock import SimulationClock
from agri_twin.application.orchestrator import CropDigitalTwinOrchestrator, CropSimulationSnapshot
from agri_twin.application.weather import WeatherEngine
from agri_twin.domain import (
    ActuatorControl,
    CropGrowthState,
    FertilizationRequest,
    IrrigationRequest,
    ParameterSet,
    PhenologyEngine,
    SoilState,
    WeatherConfiguration,
    WeatherState,
)
from agri_twin.domain.greenhouse import GreenhouseMicroclimateState, saturation_vapour_pressure_kpa
from agri_twin.domain.calibration import DatasetRole, Observation, ObservationDataset, ObservationResolution, SimulationPoint


class ScenarioError(ValueError):
    """Raised when a scenario configuration is invalid."""


class WeatherProvider(Protocol):
    def get(self, timestamp: datetime) -> WeatherState: ...


class ScenarioKind(StrEnum):
    SYNTHETIC = "synthetic"
    HISTORICAL = "historical"
    OBSERVATIONAL = "observational"
    VALIDATION = "validation"
    CALIBRATION = "calibration"
    STRESS_TEST = "stress_test"
    BENCHMARK = "benchmark"


HALF_OPEN_INTERVAL = "half_open_interval"  # parameter set by runtime events (see ScenarioEvent.active)
HOLD_DEW_POINT = "hold_dew_point"          # parameter set by runtime temperature waves: the vapour pressure of the air is kept, so the relative humidity follows the temperature


def _humidity_holding_vapour_pressure(old_temperature_c: float, relative_humidity_pct: float, new_temperature_c: float) -> float:
    return min(100.0, max(0.0, relative_humidity_pct * saturation_vapour_pressure_kpa(old_temperature_c) / saturation_vapour_pressure_kpa(new_temperature_c)))


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
        """Whether an actuator command applies to the step that STARTS at ``timestamp``. Historical events: closed interval. Runtime events (``half_open_interval``): [start, end),
        so an event of N hours acts on exactly N steps."""
        if self.parameters.get(HALF_OPEN_INTERVAL):
            return self.start <= timestamp < self.end
        return self.start <= timestamp <= self.end

    def forcing_active(self, label: datetime) -> bool:
        """Whether a weather-forcing change applies to the step LABELLED ``label`` (the hour ending at ``label``). For runtime events that is (start, end]: the same N steps as the
        actuator commands, which are evaluated at the start of their step."""
        if self.parameters.get(HALF_OPEN_INTERVAL):
            return self.start < label <= self.end
        return self.active(label)


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
    initial_microclimate: GreenhouseMicroclimateState | None = None

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
        if self.initial_microclimate is not None:
            payload["initial_microclimate"] = self.initial_microclimate.to_dict()
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
    """Apply scenario events to constant base weather or to an optional base provider."""

    def __init__(self, scenario: Scenario, base_provider: WeatherProvider | None = None) -> None:
        self.scenario = scenario
        self.base_provider = base_provider

    @staticmethod
    def _ramp(event: ScenarioEvent, timestamp: datetime) -> float:
        """Event weight in [0, 1]: 1 inside the event, linear onset/decay over
        ``ramp_hours`` at both edges (weight 1 throughout when no ramp is set)."""
        ramp = event.parameters.get("ramp_hours", 0.0) * 3600.0
        if ramp <= 0.0:
            return 1.0
        elapsed = (timestamp - event.start).total_seconds()
        remaining = (event.end - timestamp).total_seconds()
        return max(0.0, min(1.0, elapsed / ramp, remaining / ramp))

    def get(self, timestamp: datetime) -> WeatherState:
        values = asdict(self.base_provider.get(timestamp) if self.base_provider is not None else self.scenario.base_weather)
        for event in self.scenario.events:
            if not event.forcing_active(timestamp):
                continue
            weight = self._ramp(event, timestamp)
            if event.event_type in {"warm", "heat_wave", "heat", "cold_wave"}:
                before = values["temperature_c"]
                offset = weight * event.parameters.get("temperature_offset_c", event.intensity)
                values["temperature_c"] += -offset if event.event_type == "cold_wave" else offset
                if event.parameters.get(HOLD_DEW_POINT):
                    values["relative_humidity_pct"] = _humidity_holding_vapour_pressure(before, values["relative_humidity_pct"], values["temperature_c"])
            elif event.event_type in {"cold", "frost"}:
                values["temperature_c"] = self._toward(values["temperature_c"], event.parameters.get("temperature_c", event.intensity), weight)
            elif event.event_type in {"dry", "drought"}:
                values["rain_rate_mm_h"] = 0.0
            elif event.event_type == "wet":
                values["rain_rate_mm_h"] = weight * event.parameters.get("rain_rate_mm_h", event.intensity)
            elif event.event_type in {"high_vpd", "low_vpd"}:
                values["relative_humidity_pct"] = self._toward(values["relative_humidity_pct"], event.parameters.get("relative_humidity_pct", event.intensity), weight)
            elif event.event_type in {"low_radiation", "high_radiation", "photoinhibition"}:
                multiplier = self._toward(1.0, event.parameters.get("radiation_multiplier", event.intensity or 1.0), weight)
                values["solar_radiation_w_m2"] = max(0.0, values["solar_radiation_w_m2"] * multiplier)
            elif event.event_type == "wind":
                multiplier = self._toward(1.0, event.parameters.get("speed_multiplier", event.intensity or 1.0), weight)
                values["wind_speed_m_s"] = max(0.0, values["wind_speed_m_s"] * multiplier)
        return WeatherState(**values)

    @staticmethod
    def _toward(base: float, target: float, weight: float) -> float:
        # Full weight returns the target exactly, so unramped events are unchanged.
        return target if weight >= 1.0 else base + weight * (target - base)


class ScenarioRunner:
    """Execute a scenario using one injected SimulationClock and no wall time.

    ``base_weather_factory`` optionally supplies time-varying base weather (for
    example a seeded ``WeatherEngine``); scenario events are applied on top of
    it exactly as they are applied to the constant ``Scenario.base_weather``.
    """

    def __init__(self, base_weather_factory: Callable[[Scenario], WeatherProvider] | None = None) -> None:
        self.base_weather_factory = base_weather_factory

    def run(self, scenario: Scenario, *, phenology: PhenologyEngine | None = None, observer: Callable[[CropSimulationSnapshot, int], bool] | None = None,
            greenhouse_engine_factory: Callable[[Scenario, WeatherProvider], object] | None = None, control: object | None = None,
            water_engine_factory: Callable[[Scenario, WeatherEngine], object] | None = None, co2_response: Callable[[float], float] | None = None, nutrient_engine: object | None = None) -> ScenarioResult:
        """Run the scenario step by step.

        ``phenology`` optionally configures the orchestrator's PhenologyEngine (for
        example a canonical DormancyConfiguration); None keeps the default engine.
        ``greenhouse_engine_factory`` optionally builds a replacement greenhouse engine from the scenario and its weather provider.
        ``control`` optionally is a ``ControlSession``: at each step its commands are computed from the state at the start of the step; manual
        events on the same actuator replace them. None keeps the unchanged historical behaviour.
        ``water_engine_factory`` optionally builds the water balance (e.g. with FAO-56 Penman-Monteith) from the scenario and its weather engine; None keeps the historical estimate.
        ``co2_response`` optionally replaces the growth response to CO2 (e.g. the logarithmic one); None keeps min(1, CO2/420).
        ``nutrient_engine`` optionally replaces the reduced single-pool nutrient model (e.g. the nitrogen demand model); None keeps it.
        ``observer`` is called after every completed step with the snapshot and the
        number of completed steps; returning False stops the run cooperatively at that
        step boundary (status ``STOPPED``, snapshots up to and including that step).
        Both default to None, which is the unchanged historical behaviour.
        """
        clock = SimulationClock(scenario.start)
        base = self.base_weather_factory(scenario) if self.base_weather_factory is not None else None
        provider = _ScenarioWeatherProvider(scenario, base)
        weather = WeatherEngine(WeatherConfiguration(simulation=WeatherConfiguration().simulation), provider=provider)
        engine = greenhouse_engine_factory(scenario, provider) if greenhouse_engine_factory is not None else None
        water = water_engine_factory(scenario, weather) if water_engine_factory is not None else None
        orchestrator = CropDigitalTwinOrchestrator(clock, weather, scenario.initial_crop, scenario.initial_soil, scenario.greenhouse_mode, scenario.initial_microclimate, phenology, engine, water, co2_response, nutrient_engine)
        snapshots: list[CropSimulationSnapshot] = []
        current = scenario.start
        try:
            while current < scenario.end:
                dt = min(scenario.resolution_seconds, int((scenario.end - current).total_seconds()))
                active = [event for event in scenario.events if event.active(current)]
                irrigation = self._irrigation(active)
                actuators = self._actuators(active)
                fertilization = self._fertilization(active, dt)
                record = None
                if control is not None:
                    actuators, planned_irrigation, record = control.plan(orchestrator, provider, current, dt, actuators)
                    irrigation = irrigation or planned_irrigation  # a manual irrigation event wins over the controller
                snapshots.append(orchestrator.step(dt, actuators, irrigation, fertilization, record))
                current += timedelta(seconds=dt)
                if observer is not None and not observer(snapshots[-1], len(snapshots)):
                    return ScenarioResult(scenario.scenario_id, scenario.config_hash(), "STOPPED", tuple(snapshots), scenario.events, seed=scenario.seed)
            return ScenarioResult(scenario.scenario_id, scenario.config_hash(), "SUCCESS", tuple(snapshots), scenario.events, seed=scenario.seed)
        except Exception as exc:
            return ScenarioResult(scenario.scenario_id, scenario.config_hash(), "FAILED", tuple(snapshots), scenario.events, (str(exc),), scenario.seed)

    @staticmethod
    def _irrigation(events: Sequence[ScenarioEvent]) -> IrrigationRequest | None:
        # The LAST active irrigation event wins: events are ordered base scenario first, then user events, so a user irrigation replaces the scheduled one
        # (taking the first used to make every user irrigation a no-op while the season's base irrigation was active).
        for event in reversed(events):
            if event.event_type == "irrigation":
                return IrrigationRequest("scheduled", event.parameters.get("amount_mm", event.intensity), irrigation_type="drip")
        return None

    @staticmethod
    def _fertilization(events: Sequence[ScenarioEvent], dt_seconds: float) -> FertilizationRequest | None:
        # A runtime event (half-open interval) states a TOTAL dose over its interval: every active one adds its share of this step, so events add up. A historical event keeps its old meaning
        # (the first one gives its amount in every step it is active).
        runtime = [event for event in events if event.event_type == "fertilization" and event.parameters.get(HALF_OPEN_INTERVAL)]
        legacy = next((event for event in events if event.event_type == "fertilization" and not event.parameters.get(HALF_OPEN_INTERVAL)), None)
        if not runtime and legacy is None:
            return None
        amount = sum(event.parameters.get("amount_kg_ha", event.intensity) * dt_seconds / (event.end - event.start).total_seconds() for event in runtime)
        if legacy is not None:
            amount += legacy.parameters.get("amount_kg_ha", legacy.intensity)
        return FertilizationRequest(amount, 1.0, "scheduled")

    @staticmethod
    def _actuators(events: Sequence[ScenarioEvent]) -> dict[str, ActuatorControl]:
        return actuator_controls(events)


def scenario_weather_provider(scenario: Scenario, base_weather_factory: Callable[[Scenario], WeatherProvider] | None = None) -> "_ScenarioWeatherProvider":
    """The weather a run of ``scenario`` sees (base weather plus scenario events), as a provider usable outside the runner."""
    base = base_weather_factory(scenario) if base_weather_factory is not None else None
    return _ScenarioWeatherProvider(scenario, base)


def actuator_controls(events: Sequence[ScenarioEvent]) -> dict[str, ActuatorControl]:
    """Actuator commands implied by the events active at one instant (shared by every greenhouse backend)."""
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