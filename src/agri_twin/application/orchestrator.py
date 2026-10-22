"""Deterministic orchestration of the Phase 4.7 crop digital twin."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Mapping

from agri_twin.application.clock import SimulationClock
from agri_twin.application.scheduler import SimulationScheduler
from agri_twin.application.weather import WeatherEngine
from agri_twin.domain import (
    ActuatorControl,
    ClimateStressEngine,
    CropGrowthEngine,
    CropGrowthState,
    FertilizationRequest,
    GreenhouseMicroclimateEngine,
    GreenhouseMicroclimateResult,
    GreenhouseMicroclimateState,
    IrrigationRequest,
    NutrientBalanceEngine,
    PhenologyEngine,
    RadiationGrowthEngine,
    SoilState,
    WaterBalanceEngine,
    WeatherState,
)
from agri_twin.domain.water_balance import WaterBalanceResult


class CropSimulationError(ValueError):
    """Raised when an integrated crop simulation input is invalid."""


@dataclass(frozen=True, slots=True)
class CropSimulationSnapshot:
    simulation_time: datetime
    weather: WeatherState
    environment: object
    microclimate: GreenhouseMicroclimateResult
    crop: CropGrowthState
    soil: SoilState
    potential_growth_g_m2: float
    actual_growth_g_m2: float
    growth_factor: float
    harvest_ready: bool
    outdoor_weather: WeatherState | None = None
    co2_factor: float = 1.0
    water_balance: WaterBalanceResult | None = None
    control: object | None = None  # ControlRecord of the step when a climate controller drove the actuators (None otherwise)


class CropDigitalTwinOrchestrator:
    """Coordinate all crop engines using one injected SimulationClock.

    ``weather`` in each snapshot is the environment the crop experienced: the
    outdoor WeatherState in outdoor mode, the indoor microclimate (temperature,
    RH, radiation, pressure; no rain) in greenhouse modes. The greenhouse
    microclimate is persistent state carried from step to step.
    """

    def __init__(self, clock: SimulationClock, weather_engine: WeatherEngine, crop: CropGrowthState, soil: SoilState, greenhouse_mode: str = "outdoor", microclimate: GreenhouseMicroclimateState | None = None, phenology: PhenologyEngine | None = None, greenhouse_engine: object | None = None, water_engine: WaterBalanceEngine | None = None, co2_response: "Callable[[float], float] | None" = None) -> None:
        self.clock = clock
        self.weather_engine = weather_engine
        normalized = replace(crop, root_depth_m=1.0) if crop.root_depth_m <= 0 else crop
        if normalized.biomass_total == 0 and normalized.leaf_area_index > 0:
            leaf_biomass = normalized.leaf_area_index / 0.02
            normalized = replace(normalized, biomass_total=leaf_biomass, biomass_leaf=leaf_biomass)
        self.crop = normalized
        self.soil = soil
        self.greenhouse_mode = greenhouse_mode
        self.phenology = phenology or PhenologyEngine()
        # an injected engine (e.g. the EnergyPlus timeline) replaces the simplified one; engines that need the step time say so
        self.greenhouse = greenhouse_engine if greenhouse_engine is not None else GreenhouseMicroclimateEngine()
        self.radiation = RadiationGrowthEngine()
        self.co2_response = co2_response if co2_response is not None else CropGrowthEngine.co2_response  # one response for the orchestrator and, with the crop exchange, for its growth proxy
        if hasattr(self.greenhouse, "use_co2_response") and co2_response is not None:
            self.greenhouse.use_co2_response(co2_response)
        self.water = water_engine if water_engine is not None else WaterBalanceEngine()
        if hasattr(self.greenhouse, "use_water_engine"):
            self.greenhouse.use_water_engine(self.water)
        self.nutrients = NutrientBalanceEngine()
        self.climate = ClimateStressEngine()
        self.microclimate = microclimate
        self.last_snapshot: CropSimulationSnapshot | None = None

    def _crop_environment(self, weather: WeatherState, indoor: GreenhouseMicroclimateState) -> WeatherState:
        """Outdoor mode: the outdoor WeatherState. Greenhouse: the resulting microclimate."""
        if self.greenhouse_mode == "outdoor":
            return weather
        return WeatherState(indoor.temperature_c, indoor.relative_humidity_pct, indoor.radiation_w_m2, weather.wind_speed_m_s, weather.wind_direction_deg, 0.0, indoor.pressure_hpa)

    def step(self, dt_seconds: float, actuators: Mapping[str, ActuatorControl] | None = None, irrigation: IrrigationRequest | None = None, fertilization: FertilizationRequest | None = None, control: object | None = None) -> CropSimulationSnapshot:
        if not math.isfinite(dt_seconds) or dt_seconds <= 0:
            raise CropSimulationError("dt_seconds must be positive and finite")
        self.clock.advance(dt_seconds)
        return self.step_at(self.clock.now(), dt_seconds, actuators, irrigation, fertilization, control)

    def step_at(self, simulation_time: datetime, dt_seconds: float, actuators: Mapping[str, ActuatorControl] | None = None, irrigation: IrrigationRequest | None = None, fertilization: FertilizationRequest | None = None, control: object | None = None) -> CropSimulationSnapshot:
        if simulation_time.tzinfo is None or not math.isfinite(dt_seconds) or dt_seconds <= 0:
            raise CropSimulationError("simulation time and dt_seconds are invalid")
        weather = self.weather_engine.generate(simulation_time)
        extra = {"simulation_time": simulation_time} if getattr(self.greenhouse, "requires_simulation_time", False) else {}
        if getattr(self.greenhouse, "requires_soil", False):
            extra["soil"] = self.soil
        microclimate = self.greenhouse.advance(weather, self.crop, dt_seconds, self.greenhouse_mode, actuators, prior=self.microclimate, **extra)
        crop_weather = self._crop_environment(weather, microclimate.indoor_state)
        phenological = self.phenology.advance(self.crop, crop_weather, simulation_time, dt_seconds)
        phenological = replace(phenological, soil_water_vwc=self.soil.vwc_m3_m3)
        potential_state = self.radiation.advance(phenological, crop_weather, dt_seconds)
        potential_growth = potential_state.biomass_total - phenological.biomass_total
        water_result = self.water.advance(self.soil, crop_weather, dt_seconds, phenological, irrigation, when=simulation_time, indoors=self.greenhouse_mode != "outdoor")
        nutrient_result = self.nutrients.advance(phenological, potential_growth, dt_seconds, fertilization)
        climate_result = self.climate.advance(nutrient_result.state, crop_weather, dt_seconds, microclimate.environment, water_result.water_stress, nutrient_result.nutrient_factor)
        co2_factor = self.co2_response(microclimate.indoor_state.co2_ppm)
        combined = climate_result.temperature_factor * climate_result.radiation_factor * climate_result.water_factor * climate_result.vpd_factor * climate_result.nutrient_factor * co2_factor
        if co2_factor > 1.0:  # enrichment raises the radiation use efficiency: it is an enhancement, not one of the (<= 1) limitations
            actual = self.radiation.advance(climate_result.state, crop_weather, dt_seconds, combined / co2_factor, co2_factor)
        else:
            actual = self.radiation.advance(climate_result.state, crop_weather, dt_seconds, combined)
        actual_growth = actual.biomass_total - climate_result.state.biomass_total
        harvest_ready = actual.maturity_index >= 1.0 and actual.current_stage == "post_harvest_dormancy"
        self.crop = replace(actual, soil_water_vwc=water_result.soil.vwc_m3_m3, water_stress=water_result.water_stress, nutrient_status=nutrient_result.nutrient_status, harvest_ready=harvest_ready)
        self.soil = water_result.soil
        self.microclimate = microclimate.indoor_state
        snapshot = CropSimulationSnapshot(simulation_time, crop_weather, microclimate.environment, microclimate, self.crop, self.soil, potential_growth, actual_growth, combined, harvest_ready, weather, co2_factor, water_result, control)
        self.last_snapshot = snapshot
        return snapshot

    def register_scheduler_task(self, scheduler: SimulationScheduler, name: str = "crop-digital-twin") -> None:
        interval = scheduler.timestep.total_seconds()
        scheduler.register(name, interval, lambda timestamp: self.step_at(timestamp, interval))