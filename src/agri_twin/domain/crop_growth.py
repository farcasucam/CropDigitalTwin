"""Interpretable radiation-to-biomass crop growth facade."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime

from agri_twin.domain.climate_stress import ClimateStressEngine
from agri_twin.domain.models import CropGrowthState, DerivedEnvironmentState, SoilState, WeatherState
from agri_twin.domain.radiation_growth import RadiationGrowthEngine


class CropGrowthError(ValueError):
    """Raised for invalid crop-growth inputs."""


@dataclass(frozen=True, slots=True)
class CropGrowthInput:
    weather: WeatherState
    dt_seconds: float
    environment: DerivedEnvironmentState | None = None
    soil: SoilState | None = None
    nutrient_factor: float | None = None
    water_factor: float | None = None
    co2_factor: float = 1.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.dt_seconds) or self.dt_seconds < 0:
            raise CropGrowthError("dt_seconds must be finite and non-negative")
        for name, value in (("nutrient_factor", self.nutrient_factor), ("water_factor", self.water_factor), ("co2_factor", self.co2_factor)):
            if value is not None and (not math.isfinite(value) or not 0 <= value <= 1):
                raise CropGrowthError(f"{name} must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class CropGrowthResult:
    state: CropGrowthState
    par_mj_m2: float
    apar_mj_m2: float
    potential_growth_g_m2: float
    actual_growth_g_m2: float
    temperature_factor: float
    water_factor: float
    vpd_factor: float
    radiation_factor: float
    nutrient_factor: float
    co2_factor: float
    lai_growth: float
    lai_senescence: float
    lai_damage: float
    damage_index: float


class CropGrowthEngine:
    """Advance growth without owning weather, water, phenology or a clock."""

    def __init__(self, radiation: RadiationGrowthEngine | None = None, climate: ClimateStressEngine | None = None) -> None:
        self.radiation = radiation or RadiationGrowthEngine()
        self.climate = climate or ClimateStressEngine()

    def advance(self, state: CropGrowthState, inputs: CropGrowthInput, simulation_time: datetime | None = None) -> CropGrowthResult:
        if not isinstance(state, CropGrowthState):
            raise CropGrowthError("state must be a CropGrowthState")
        if simulation_time is not None and simulation_time.tzinfo is None:
            raise CropGrowthError("simulation_time must be timezone-aware")
        profile = self.radiation.profile_for(state.crop_key)
        climate = self.climate.advance(state, inputs.weather, inputs.dt_seconds, inputs.environment, 1.0 - inputs.water_factor if inputs.water_factor is not None else None, inputs.nutrient_factor)
        temperature_factor = climate.temperature_factor
        water_factor = climate.water_factor if inputs.water_factor is None else inputs.water_factor
        nutrient_factor = climate.nutrient_factor if inputs.nutrient_factor is None else inputs.nutrient_factor
        vpd_factor = climate.vpd_factor
        radiation_factor = climate.radiation_factor
        co2_factor = inputs.co2_factor
        par = self.radiation.par_mj_m2(inputs.weather.solar_radiation_w_m2, inputs.dt_seconds)
        apar = par * (1.0 - math.exp(-profile.extinction_coefficient * max(0.0, state.leaf_area_index)))
        potential = apar * profile.rue_g_dm_mj_par
        actual = potential * temperature_factor * water_factor * vpd_factor * radiation_factor * nutrient_factor * co2_factor
        if state.current_stage == "post_harvest_dormancy":
            actual = 0.0
        leaf_growth = actual * profile.partition_by_stage[state.current_stage][0]
        lai_growth = leaf_growth * profile.specific_leaf_area_m2_g_dm
        senescence = state.leaf_area_index * profile.senescence_rate_per_day * inputs.dt_seconds / 86400.0
        damage = state.leaf_area_index * min(1.0, state.frost_damage + state.heat_damage + state.radiation_stress * 0.1 + state.water_stress * 0.1)
        next_lai = max(0.0, min(profile.maximum_lai, state.leaf_area_index + lai_growth - senescence - damage))
        next_state = replace(climate.state, leaf_area_index=next_lai, maturity_index=max(state.maturity_index, min(1.0, state.maturity_index + state.phenology_progress * inputs.dt_seconds / (86400.0 * 30.0))))
        grown = self.radiation.advance(next_state, inputs.weather, inputs.dt_seconds, temperature_factor * water_factor * vpd_factor * radiation_factor * nutrient_factor * co2_factor)
        # RadiationGrowthEngine owns biomass partitioning; this facade reports the
        # same explicit APAR/RUE calculation and restores the LAI balance above.
        next_state = replace(grown, leaf_area_index=next_lai, maturity_index=next_state.maturity_index)
        return CropGrowthResult(next_state, par, apar, potential, actual, temperature_factor, water_factor, vpd_factor, radiation_factor, nutrient_factor, co2_factor, lai_growth, senescence, damage, min(1.0, state.frost_damage + state.heat_damage + state.radiation_stress))