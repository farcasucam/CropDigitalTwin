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
    CropGrowthState,
    FertilizationRequest,
    GreenhouseMicroclimateEngine,
    GreenhouseMicroclimateResult,
    IrrigationRequest,
    NutrientBalanceEngine,
    PhenologyEngine,
    RadiationGrowthEngine,
    SoilState,
    WaterBalanceEngine,
    WeatherState,
)


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


class CropDigitalTwinOrchestrator:
    """Coordinate all crop engines using one injected SimulationClock."""

    def __init__(self, clock: SimulationClock, weather_engine: WeatherEngine, crop: CropGrowthState, soil: SoilState, greenhouse_mode: str = "outdoor") -> None:
        self.clock = clock
        self.weather_engine = weather_engine
        normalized = replace(crop, root_depth_m=1.0) if crop.root_depth_m <= 0 else crop
        if normalized.biomass_total == 0 and normalized.leaf_area_index > 0:
            leaf_biomass = normalized.leaf_area_index / 0.02
            normalized = replace(normalized, biomass_total=leaf_biomass, biomass_leaf=leaf_biomass)
        self.crop = normalized
        self.soil = soil
        self.greenhouse_mode = greenhouse_mode
        self.phenology = PhenologyEngine()
        self.greenhouse = GreenhouseMicroclimateEngine()
        self.radiation = RadiationGrowthEngine()
        self.water = WaterBalanceEngine()
        self.nutrients = NutrientBalanceEngine()
        self.climate = ClimateStressEngine()
        self.last_snapshot: CropSimulationSnapshot | None = None

    @staticmethod
    def _with_radiation(weather: WeatherState, radiation_w_m2: float) -> WeatherState:
        return WeatherState(weather.temperature_c, weather.relative_humidity_pct, radiation_w_m2, weather.wind_speed_m_s, weather.wind_direction_deg, weather.rain_rate_mm_h, weather.pressure_hpa)

    def step(self, dt_seconds: float, actuators: Mapping[str, ActuatorControl] | None = None, irrigation: IrrigationRequest | None = None, fertilization: FertilizationRequest | None = None) -> CropSimulationSnapshot:
        if not math.isfinite(dt_seconds) or dt_seconds <= 0:
            raise CropSimulationError("dt_seconds must be positive and finite")
        self.clock.advance(dt_seconds)
        return self.step_at(self.clock.now(), dt_seconds, actuators, irrigation, fertilization)

    def step_at(self, simulation_time: datetime, dt_seconds: float, actuators: Mapping[str, ActuatorControl] | None = None, irrigation: IrrigationRequest | None = None, fertilization: FertilizationRequest | None = None) -> CropSimulationSnapshot:
        if simulation_time.tzinfo is None or not math.isfinite(dt_seconds) or dt_seconds <= 0:
            raise CropSimulationError("simulation time and dt_seconds are invalid")
        weather = self.weather_engine.generate(simulation_time)
        microclimate = self.greenhouse.advance(weather, self.crop, dt_seconds, self.greenhouse_mode, actuators)
        phenological = self.phenology.advance(self.crop, weather, simulation_time, dt_seconds)
        phenological = replace(phenological, soil_water_vwc=self.soil.vwc_m3_m3)
        crop_weather = self._with_radiation(weather, microclimate.indoor_state.radiation_w_m2)
        potential_state = self.radiation.advance(phenological, crop_weather, dt_seconds)
        potential_growth = potential_state.biomass_total - phenological.biomass_total
        water_result = self.water.advance(self.soil, crop_weather, dt_seconds, phenological, irrigation)
        nutrient_result = self.nutrients.advance(phenological, potential_growth, dt_seconds, fertilization)
        climate_result = self.climate.advance(nutrient_result.state, crop_weather, dt_seconds, microclimate.environment, water_result.water_stress, nutrient_result.nutrient_factor)
        combined = climate_result.temperature_factor * climate_result.radiation_factor * climate_result.water_factor * climate_result.vpd_factor * climate_result.nutrient_factor
        actual = self.radiation.advance(climate_result.state, crop_weather, dt_seconds, combined)
        actual_growth = actual.biomass_total - climate_result.state.biomass_total
        harvest_ready = actual.maturity_index >= 1.0 and actual.current_stage == "post_harvest_dormancy"
        self.crop = replace(actual, soil_water_vwc=water_result.soil.vwc_m3_m3, water_stress=water_result.water_stress, nutrient_status=nutrient_result.nutrient_status, harvest_ready=harvest_ready)
        self.soil = water_result.soil
        snapshot = CropSimulationSnapshot(simulation_time, crop_weather, microclimate.environment, microclimate, self.crop, self.soil, potential_growth, actual_growth, combined, harvest_ready)
        self.last_snapshot = snapshot
        return snapshot

    def register_scheduler_task(self, scheduler: SimulationScheduler, name: str = "crop-digital-twin") -> None:
        interval = scheduler.timestep.total_seconds()
        scheduler.register(name, interval, lambda timestamp: self.step_at(timestamp, interval))