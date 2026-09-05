"""Continuous climate stress, exposure, recovery, and damage accounting."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from agri_twin.domain.models import CropGrowthState, DerivedEnvironmentState, WeatherState


class ClimateStressError(ValueError):
    """Raised when climate stress inputs are invalid."""


@dataclass(frozen=True, slots=True)
class ClimateStressProfile:
    min_temp_c: float
    max_temp_c: float
    critical_heat_c: float
    critical_frost_c: float
    optimal_vpd_kpa: float
    stress_vpd_kpa: float
    optimal_radiation_w_m2: float
    photoinhibition_w_m2: float
    stage_sensitivity: dict[str, float] | None = None

    def __post_init__(self) -> None:
        if self.min_temp_c >= self.max_temp_c or self.critical_heat_c <= self.max_temp_c or self.critical_frost_c >= self.min_temp_c:
            raise ClimateStressError("temperature thresholds are inconsistent")
        if not 0 <= self.optimal_vpd_kpa < self.stress_vpd_kpa:
            raise ClimateStressError("VPD thresholds are inconsistent")
        if not 0 <= self.optimal_radiation_w_m2 < self.photoinhibition_w_m2:
            raise ClimateStressError("radiation thresholds are inconsistent")
        if any(not math.isfinite(value) or value < 0 for value in (self.stage_sensitivity or {}).values()):
            raise ClimateStressError("stage sensitivity values are invalid")


@dataclass(frozen=True, slots=True)
class ClimateStressResult:
    state: CropGrowthState
    temperature_factor: float
    vpd_factor: float
    water_factor: float
    radiation_factor: float
    nutrient_factor: float
    climate_factor: float
    cold_stress: float
    heat_stress: float
    vpd_stress: float
    radiation_stress: float
    frost_damage: float
    heat_damage: float
    irreversible_damage: float
    growth_factor: float


DEFAULT_STAGE_SENSITIVITY = {
    "establishment": 0.8,
    "vegetative_growth": 1.0,
    "yield_maturation": 1.1,
    "post_harvest_dormancy": 0.6,
}


DEFAULT_PROFILES = {
    "tomato": ClimateStressProfile(12, 30, 34, 0, 1.2, 1.6, 800, 900),
    "lettuce": ClimateStressProfile(6, 22, 26, -2, 0.9, 1.3, 550, 700),
    "pepper": ClimateStressProfile(12, 29, 33, 0, 1.2, 1.6, 750, 880),
    "grape": ClimateStressProfile(12, 33, 36, 0, 1.6, 2.2, 880, 1000),
    "peach": ClimateStressProfile(8, 30, 34, 0, 1.4, 2.0, 800, 950),
    "plum": ClimateStressProfile(7, 30, 34, 0, 1.4, 1.9, 800, 950),
    "apple": ClimateStressProfile(6, 28, 32, 0, 1.3, 1.8, 800, 950),
}


class ClimateStressEngine:
    """Advance climate exposure using one explicit weather interval."""

    def __init__(self, profiles: dict[str, ClimateStressProfile] | None = None) -> None:
        self._profiles = dict(DEFAULT_PROFILES if profiles is None else profiles)

    def profile_for(self, crop_key: str) -> ClimateStressProfile:
        try:
            return self._profiles[crop_key.lower()]
        except KeyError as exc:
            raise ClimateStressError(f"climate profile not found: {crop_key}") from exc

    def advance(self, state: CropGrowthState, weather: WeatherState, dt_seconds: float, environment: DerivedEnvironmentState | None = None, water_stress: float | None = None, nutrient_factor: float | None = None) -> ClimateStressResult:
        if not isinstance(state, CropGrowthState):
            raise ClimateStressError("state must be a CropGrowthState")
        if not math.isfinite(dt_seconds) or dt_seconds < 0:
            raise ClimateStressError("dt_seconds must be finite and non-negative")
        profile = self.profile_for(state.crop_key)
        vpd = environment.vpd_kpa if environment is not None else self._vpd(weather)
        water_factor = 1.0 - (state.water_stress if water_stress is None else water_stress)
        nutrient = state.nutrient_status if nutrient_factor is None else nutrient_factor
        if not 0 <= water_factor <= 1 or not 0 <= nutrient <= 1:
            raise ClimateStressError("water and nutrient factors must be between 0 and 1")
        cold = self._ramp(profile.min_temp_c - weather.temperature_c, 0, profile.min_temp_c - profile.critical_frost_c) if weather.temperature_c < profile.min_temp_c else 0.0
        heat = self._ramp(weather.temperature_c - profile.max_temp_c, 0, profile.critical_heat_c - profile.max_temp_c) if weather.temperature_c > profile.max_temp_c else 0.0
        vpd_stress = self._ramp(vpd, profile.optimal_vpd_kpa, profile.stress_vpd_kpa)
        radiation_stress = self._ramp(weather.solar_radiation_w_m2, profile.optimal_radiation_w_m2, profile.photoinhibition_w_m2)
        sensitivity = (profile.stage_sensitivity or DEFAULT_STAGE_SENSITIVITY).get(state.current_stage, 1.0)
        cold = self._bounded(cold * sensitivity)
        heat = self._bounded(heat * sensitivity)
        vpd_stress = self._bounded(vpd_stress * sensitivity)
        radiation_stress = self._bounded(radiation_stress * sensitivity)
        hours = dt_seconds / 3600.0
        frost = weather.temperature_c < profile.critical_frost_c
        frost_hours = state.frost_exposure_hours + (hours if frost else 0.0)
        frost_intensity = max(state.frost_intensity_c, profile.critical_frost_c - weather.temperature_c) if frost else state.frost_intensity_c
        frost_increment = max(0.0, profile.critical_frost_c - weather.temperature_c) * hours / 240.0 if frost else 0.0
        frost_damage = min(1.0, max(0.0, state.frost_damage + frost_increment - (0.01 * dt_seconds / 86400.0 if not frost else 0.0)))
        irreversible = min(1.0, state.irreversible_damage + frost_increment * 0.2)
        heat_wave = weather.temperature_c > profile.max_temp_c
        heat_hours = state.heat_exposure_hours + (hours if heat_wave else -min(state.heat_exposure_hours, hours))
        heat_increment = max(0.0, weather.temperature_c - profile.max_temp_c) * hours / 480.0 if heat_wave else 0.0
        heat_damage = min(1.0, max(0.0, state.heat_damage + heat_increment - (0.02 * dt_seconds / 86400.0 if not heat_wave else 0.0)))
        temperature_factor = max(0.0, 1.0 - max(cold, heat, frost_damage, heat_damage, irreversible))
        climate_factor = temperature_factor * (1.0 - vpd_stress) * (1.0 - radiation_stress)
        accumulated = min(1.0, max(0.0, state.accumulated_stress + (1.0 - climate_factor) * hours / 24.0 - 0.01 * dt_seconds / 86400.0))
        next_state = replace(state, cold_stress=cold, heat_stress=heat, vpd_stress=vpd_stress, radiation_stress=radiation_stress, frost_damage=frost_damage, heat_damage=heat_damage, irreversible_damage=irreversible, frost_exposure_hours=frost_hours, frost_intensity_c=frost_intensity, heat_exposure_hours=max(0.0, heat_hours), accumulated_stress=accumulated)
        return ClimateStressResult(next_state, temperature_factor, 1.0 - vpd_stress, water_factor, 1.0 - radiation_stress, nutrient, climate_factor, cold, heat, vpd_stress, radiation_stress, frost_damage, heat_damage, irreversible, climate_factor * water_factor * nutrient)

    @staticmethod
    def combine_growth(potential_growth: float, result: ClimateStressResult, co2_factor: float = 1.0) -> float:
        if not math.isfinite(potential_growth) or potential_growth < 0 or not 0 <= co2_factor <= 1:
            raise ClimateStressError("growth and CO2 factor are invalid")
        return potential_growth * result.temperature_factor * result.radiation_factor * result.water_factor * result.vpd_factor * result.nutrient_factor * co2_factor

    @staticmethod
    def _ramp(value: float, low: float, high: float) -> float:
        return min(1.0, max(0.0, (value - low) / max(high - low, 1e-12)))

    @staticmethod
    def _bounded(value: float) -> float:
        return min(1.0, max(0.0, value))

    @staticmethod
    def _vpd(weather: WeatherState) -> float:
        saturation = 0.6108 * math.exp(17.27 * weather.temperature_c / (weather.temperature_c + 237.3))
        return max(0.0, saturation * (1.0 - weather.relative_humidity_pct / 100.0))