"""Deterministic MVP physical environment models."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from agri_twin.domain.models import DerivedEnvironmentState, SoilState, WeatherState


class PhysicalModelError(ValueError):
    """Raised when a physical model input is invalid."""


@dataclass(frozen=True, slots=True)
class PhysicalEnvironmentResult:
    environment: DerivedEnvironmentState
    soil: SoilState


class PhysicalEnvironmentModel(Protocol):
    def evaluate(
        self,
        weather: WeatherState,
        soil: SoilState,
        timestep_seconds: float,
        irrigation_mm: float = 0.0,
    ) -> PhysicalEnvironmentResult: ...


class OpenFieldPhysicalModel:
    """Simple causal outdoor model suitable for the Phase 3 MVP."""

    def evaluate(
        self,
        weather: WeatherState,
        soil: SoilState,
        timestep_seconds: float,
        irrigation_mm: float = 0.0,
    ) -> PhysicalEnvironmentResult:
        if not math.isfinite(timestep_seconds) or timestep_seconds <= 0:
            raise PhysicalModelError("timestep_seconds must be positive and finite")
        if not math.isfinite(irrigation_mm) or irrigation_mm < 0:
            raise PhysicalModelError("irrigation_mm must be finite and non-negative")
        if soil.field_capacity < soil.wilting_point:
            raise PhysicalModelError("soil field capacity must not be below wilting point")
        saturation = self._saturation_vapor_pressure(weather.temperature_c)
        vapor = saturation * weather.relative_humidity_pct / 100
        vpd = max(0.0, saturation - vapor)
        thermal_load = max(0.0, weather.temperature_c - 20.0) + weather.solar_radiation_w_m2 / 1000
        transpiration = max(0.0, vpd * 0.15 + weather.solar_radiation_w_m2 * 0.00005)
        hours = timedelta(seconds=timestep_seconds).total_seconds() / 3600
        rainfall = weather.rain_rate_mm_h * hours
        evaporation = max(0.0, weather.solar_radiation_w_m2 * 0.00002 * hours)
        soil_loss = evaporation + transpiration * hours
        next_vwc = min(
            soil.field_capacity,
            max(soil.wilting_point, soil.vwc_m3_m3 + irrigation_mm / 1000 + rainfall / 1000 - soil_loss / 1000),
        )
        next_soil = SoilState(
            vwc_m3_m3=next_vwc,
            soil_temperature_c=weather.temperature_c,
            field_capacity=soil.field_capacity,
            wilting_point=soil.wilting_point,
            drainage_rate=max(0.0, soil.drainage_rate),
            root_zone_water=max(0.0, soil.root_zone_water + (irrigation_mm + rainfall - soil_loss) / 1000),
        )
        environment = DerivedEnvironmentState(
            vpd_kpa=vpd,
            thermal_load=thermal_load,
            saturation_vapor_pressure=saturation,
            vapor_pressure=vapor,
            estimated_transpiration=transpiration,
            evapotranspiration_proxy=evaporation + transpiration * hours,
        )
        return PhysicalEnvironmentResult(environment, next_soil)

    @staticmethod
    def _saturation_vapor_pressure(temperature_c: float) -> float:
        if not math.isfinite(temperature_c):
            raise PhysicalModelError("temperature must be finite")
        return 0.6108 * math.exp(17.27 * temperature_c / (temperature_c + 237.3))
