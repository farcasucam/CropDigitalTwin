"""Explicit crop-to-greenhouse physical exchange and bounded iteration."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from agri_twin.domain.crop_growth import CropGrowthEngine, CropGrowthInput, CropGrowthResult
from agri_twin.domain.greenhouse import (
    CropMicroclimateFeedback,
    GreenhouseActuatorState,
    GreenhouseConfiguration,
    GreenhousePhysicalModel,
    MicroclimateState,
)
from agri_twin.domain.models import CropGrowthState, DerivedEnvironmentState, SoilState, WeatherState
from agri_twin.domain.water_balance import WaterBalanceEngine


class CropGreenhouseFeedbackError(ValueError):
    """Raised when the feedback loop configuration or inputs are invalid."""


@dataclass(frozen=True, slots=True)
class PhysicalRate:
    value: float
    unit: str
    origin: str
    uncertainty: float | None = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.value) or self.value < 0:
            raise CropGreenhouseFeedbackError("physical rate must be finite and non-negative")
        if not self.unit or not self.origin:
            raise CropGreenhouseFeedbackError("physical rate unit and origin are required")
        if self.uncertainty is not None and (not math.isfinite(self.uncertainty) or self.uncertainty < 0):
            raise CropGreenhouseFeedbackError("uncertainty must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class CropPhysicalExchange:
    transpiration_rate: PhysicalRate
    latent_heat_flux: PhysicalRate
    sensible_heat_flux: PhysicalRate
    co2_uptake: PhysicalRate
    intercepted_radiation_w_m2: float
    leaf_area_index: float

    def __post_init__(self) -> None:
        for name in ("intercepted_radiation_w_m2", "leaf_area_index"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise CropGreenhouseFeedbackError(f"{name} must be finite and non-negative")

    def to_feedback(self) -> CropMicroclimateFeedback:
        return CropMicroclimateFeedback(
            leaf_area_index=self.leaf_area_index,
            transpiration_mm_h=self.transpiration_rate.value,
            intercepted_radiation_w_m2=self.intercepted_radiation_w_m2,
            latent_heat_w_m2=self.latent_heat_flux.value,
            sensible_heat_w_m2=self.sensible_heat_flux.value,
            co2_uptake_ppm=self.co2_uptake.value,
        )


@dataclass(frozen=True, slots=True)
class FeedbackConvergence:
    converged: bool
    iterations: int
    final_error: float
    reason: str


@dataclass(frozen=True, slots=True)
class CropGreenhouseStepResult:
    microclimate: MicroclimateState
    crop: CropGrowthState
    crop_growth: CropGrowthResult
    exchange: CropPhysicalExchange
    feedback: CropMicroclimateFeedback
    convergence: FeedbackConvergence


@dataclass(frozen=True, slots=True)
class CropGreenhouseFeedbackConfiguration:
    max_iterations: int = 8
    tolerance_temperature_c: float = 0.05
    tolerance_relative_humidity_pct: float = 0.2
    tolerance_co2_ppm: float = 1.0
    relaxation_alpha: float = 0.4
    latent_heat_j_kg: float = 2_450_000.0
    sensible_heat_transfer_w_m2_k: float = 5.0
    leaf_air_delta_per_intercepted_w_m2: float = 0.002
    co2_carbon_fraction: float = 0.45
    co2_molar_mass_ratio: float = 44.0 / 12.0
    air_density_kg_m3: float = 1.2
    air_volume_m3: float = 1000.0

    def __post_init__(self) -> None:
        if not isinstance(self.max_iterations, int) or self.max_iterations <= 0:
            raise CropGreenhouseFeedbackError("max_iterations must be a positive integer")
        for name in ("tolerance_temperature_c", "tolerance_relative_humidity_pct", "tolerance_co2_ppm", "latent_heat_j_kg", "sensible_heat_transfer_w_m2_k", "leaf_air_delta_per_intercepted_w_m2", "co2_carbon_fraction", "co2_molar_mass_ratio", "air_density_kg_m3", "air_volume_m3"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise CropGreenhouseFeedbackError(f"{name} must be finite and non-negative")
        if not 0 < self.relaxation_alpha <= 1:
            raise CropGreenhouseFeedbackError("relaxation_alpha must be in (0, 1]")
        if self.co2_carbon_fraction > 1:
            raise CropGreenhouseFeedbackError("feedback configuration fraction is invalid")


class CropPhysicalExchangeModel:
    """Convert existing crop/radiation/water outputs into physical exchanges.

    The fallback transpiration and leaf-air temperature proxy are engineering
    defaults pending crop/greenhouse observations; they are not calibration.
    """

    def __init__(self, configuration: CropGreenhouseFeedbackConfiguration | None = None, water: WaterBalanceEngine | None = None) -> None:
        self.configuration = configuration or CropGreenhouseFeedbackConfiguration()
        self.water = water or WaterBalanceEngine()

    def calculate(self, crop: CropGrowthState, growth: CropGrowthResult, microclimate: MicroclimateState, weather: WeatherState, dt_seconds: float, soil: SoilState | None = None) -> CropPhysicalExchange:
        if not math.isfinite(dt_seconds) or dt_seconds <= 0:
            raise CropGreenhouseFeedbackError("dt_seconds must be positive and finite")
        profile = CropGrowthEngine().radiation.profile_for(crop.crop_key)
        fraction_intercepted = 1.0 - math.exp(-profile.extinction_coefficient * max(0.0, growth.state.leaf_area_index))
        intercepted = max(0.0, microclimate.solar_radiation_w_m2 * fraction_intercepted)
        if soil is not None and crop.root_depth_m > 0:
            water_result = self.water.advance(soil, weather, dt_seconds, crop)
            hours = dt_seconds / 3600.0
            base_rate = water_result.transpiration_mm / max(hours, 1e-12)
            transpiration = base_rate
            origin = "WaterBalanceEngine; no second VPD correction"
        else:
            canopy = min(1.0, max(0.0, growth.state.leaf_area_index / 3.0))
            transpiration = max(0.0, (microclimate.vpd_kpa * 0.15 + microclimate.solar_radiation_w_m2 * 0.00005) * canopy)
            origin = "engineering_default simplified canopy demand"
        latent = transpiration * self.configuration.latent_heat_j_kg / 3600.0
        leaf_air_delta = min(5.0, max(-5.0, intercepted * self.configuration.leaf_air_delta_per_intercepted_w_m2))
        sensible = max(0.0, self.configuration.sensible_heat_transfer_w_m2_k * max(0.0, crop.leaf_area_index) * leaf_air_delta)
        growth_carbon_g_m2 = max(0.0, growth.actual_growth_g_m2) * self.configuration.co2_carbon_fraction
        co2_mass_g_m2 = growth_carbon_g_m2 * self.configuration.co2_molar_mass_ratio
        air_mass_kg_m2 = self.configuration.air_density_kg_m3 * self.configuration.air_volume_m3
        co2_ppm = co2_mass_g_m2 / 1000.0 / air_mass_kg_m2 * 1_000_000.0
        return CropPhysicalExchange(
            PhysicalRate(transpiration, "mm h-1", origin),
            PhysicalRate(latent, "W m-2", "transpiration x latent heat of vaporization"),
            PhysicalRate(sensible, "W m-2", "leaf-air heat transfer engineering default"),
            PhysicalRate(co2_ppm, "ppm timestep-1", "CropGrowthResult dry matter carbon proxy; pending calibration"),
            intercepted,
            max(0.0, growth.state.leaf_area_index),
        )


class CropGreenhouseFeedbackLoop:
    """Iterate one external timestep without advancing simulation time internally."""

    def __init__(self, greenhouse: GreenhousePhysicalModel, crop_engine: CropGrowthEngine | None = None, exchange: CropPhysicalExchangeModel | None = None, configuration: CropGreenhouseFeedbackConfiguration | None = None) -> None:
        self.greenhouse = greenhouse
        self.crop_engine = crop_engine or CropGrowthEngine()
        self.configuration = configuration or CropGreenhouseFeedbackConfiguration()
        self.exchange = exchange or CropPhysicalExchangeModel(self.configuration)

    def step(self, crop: CropGrowthState, weather: WeatherState, greenhouse_configuration: GreenhouseConfiguration, actuators: GreenhouseActuatorState, dt_seconds: float, soil: SoilState | None = None, simulation_time: datetime | None = None) -> CropGreenhouseStepResult:
        if not math.isfinite(dt_seconds) or dt_seconds <= 0:
            raise CropGreenhouseFeedbackError("dt_seconds must be positive and finite")
        time = simulation_time or crop.simulation_time
        if time.tzinfo is None:
            raise CropGreenhouseFeedbackError("simulation_time must be timezone-aware")
        zero_feedback = CropMicroclimateFeedback()
        current = self.greenhouse.step(weather, greenhouse_configuration, actuators, zero_feedback, dt_seconds)
        initial = current
        last_exchange = self.exchange.calculate(crop, self._grow(crop, weather, current, dt_seconds, time), current, weather, dt_seconds, soil)
        last_growth = self._grow(crop, weather, current, dt_seconds, time)
        error = math.inf
        converged = False
        reason = "maximum iterations reached"
        for iteration in range(1, self.configuration.max_iterations + 1):
            last_growth = self._grow(crop, weather, current, dt_seconds, time)
            last_exchange = self.exchange.calculate(crop, last_growth, current, weather, dt_seconds, soil)
            calculated = self.greenhouse.step(weather, greenhouse_configuration, actuators, last_exchange.to_feedback(), dt_seconds, prior=current if iteration == 1 else initial)
            next_state = self._relax(current, calculated)
            error = max(
                abs(next_state.temperature_c - current.temperature_c) / self.configuration.tolerance_temperature_c,
                abs(next_state.relative_humidity_pct - current.relative_humidity_pct) / self.configuration.tolerance_relative_humidity_pct,
                abs(next_state.co2_ppm - current.co2_ppm) / self.configuration.tolerance_co2_ppm,
            )
            current = next_state
            if error <= 1.0:
                converged = True
                reason = "converged"
                break
        feedback = last_exchange.to_feedback()
        return CropGreenhouseStepResult(current, last_growth.state, last_growth, last_exchange, feedback, FeedbackConvergence(converged, iteration, error, reason))

    def _grow(self, crop: CropGrowthState, weather: WeatherState, microclimate: MicroclimateState, dt_seconds: float, simulation_time: datetime) -> CropGrowthResult:
        crop_weather = WeatherState(microclimate.temperature_c, microclimate.relative_humidity_pct, microclimate.solar_radiation_w_m2, weather.wind_speed_m_s, weather.wind_direction_deg, weather.rain_rate_mm_h, microclimate.pressure_hpa)
        saturation = 0.6108 * math.exp(17.27 * microclimate.temperature_c / (microclimate.temperature_c + 237.3))
        vapor = saturation * microclimate.relative_humidity_pct / 100.0
        environment = DerivedEnvironmentState(microclimate.vpd_kpa, max(0.0, microclimate.temperature_c - 20.0) + microclimate.solar_radiation_w_m2 / 1000.0, saturation, vapor, 0.0, 0.0)
        co2_factor = min(1.0, max(0.0, microclimate.co2_ppm / 420.0))
        return self.crop_engine.advance(crop, CropGrowthInput(crop_weather, dt_seconds, environment=environment, co2_factor=co2_factor), simulation_time)

    def _relax(self, old: MicroclimateState, new: MicroclimateState) -> MicroclimateState:
        alpha = self.configuration.relaxation_alpha
        blend = lambda a, b: alpha * b + (1.0 - alpha) * a
        return MicroclimateState(air_temperature_c=blend(old.air_temperature_c, new.air_temperature_c), relative_humidity_pct=blend(old.relative_humidity_pct, new.relative_humidity_pct), vpd_kpa=blend(old.vpd_kpa, new.vpd_kpa), pressure_hpa=blend(old.pressure_hpa, new.pressure_hpa), solar_radiation_w_m2=blend(old.solar_radiation_w_m2, new.solar_radiation_w_m2), par_umol_m2_s=blend(old.par_umol_m2_s, new.par_umol_m2_s), co2_ppm=blend(old.co2_ppm, new.co2_ppm), wind_speed_m_s=blend(old.wind_speed_m_s, new.wind_speed_m_s), ventilation_fraction=blend(old.ventilation_fraction, new.ventilation_fraction), heating_kw=blend(old.heating_kw, new.heating_kw), cooling_kw=blend(old.cooling_kw, new.cooling_kw), shading_fraction=blend(old.shading_fraction, new.shading_fraction), temperature_c=blend(old.temperature_c, new.temperature_c))
