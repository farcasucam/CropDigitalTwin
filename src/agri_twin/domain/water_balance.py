"""Lightweight, deterministic soil-plant-atmosphere water balance."""

from __future__ import annotations

import math
from dataclasses import dataclass

from agri_twin.domain.models import CropGrowthState, SoilState, WeatherState


class WaterBalanceError(ValueError):
    """Raised when water-balance inputs are invalid."""


IRRIGATION_EFFICIENCY = {
    "drip": 0.95,
    "drip_hydroponic": 0.99,
    "subsurface_drip": 0.95,
    "overhead": 0.75,
}


@dataclass(frozen=True, slots=True)
class IrrigationRequest:
    """Passive irrigation request supplied by a controller or schedule."""

    mode: str = "none"
    amount_mm: float = 0.0
    target_vwc: float | None = None
    maximum_mm: float | None = None
    irrigation_type: str = "drip"
    efficiency: float | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"none", "manual", "scheduled", "vwc_target"}:
            raise WaterBalanceError("irrigation mode is invalid")
        for name, value in (("amount_mm", self.amount_mm), ("maximum_mm", self.maximum_mm)):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise WaterBalanceError(f"{name} must be finite and non-negative")
        if self.target_vwc is not None and not 0 <= self.target_vwc <= 1:
            raise WaterBalanceError("target_vwc must be between 0 and 1")
        if self.mode == "vwc_target" and self.target_vwc is None:
            raise WaterBalanceError("vwc_target mode requires target_vwc")
        if self.efficiency is not None and not 0 < self.efficiency <= 1:
            raise WaterBalanceError("efficiency must be in (0, 1]")


@dataclass(frozen=True, slots=True)
class WaterBalanceResult:
    soil: SoilState
    water_stress: float
    et0_mm: float
    evaporation_mm: float
    transpiration_mm: float
    drainage_mm: float
    irrigation_applied_mm: float
    precipitation_mm: float
    storage_mm: float


class WaterBalanceEngine:
    """Advance a root-zone bucket using one explicit simulation interval."""

    def __init__(self, irrigation_efficiency: dict[str, float] | None = None) -> None:
        self._efficiency = dict(IRRIGATION_EFFICIENCY if irrigation_efficiency is None else irrigation_efficiency)

    def advance(
        self,
        soil: SoilState,
        weather: WeatherState,
        dt_seconds: float,
        crop: CropGrowthState | None = None,
        irrigation: IrrigationRequest | None = None,
        root_depth_m: float | None = None,
    ) -> WaterBalanceResult:
        if not math.isfinite(dt_seconds) or dt_seconds <= 0:
            raise WaterBalanceError("dt_seconds must be positive and finite")
        if soil.field_capacity < soil.wilting_point:
            raise WaterBalanceError("field capacity must not be below wilting point")
        depth = root_depth_m if root_depth_m is not None else (crop.root_depth_m if crop else 1.0)
        if not math.isfinite(depth) or depth <= 0:
            raise WaterBalanceError("root_depth_m must be positive and finite")
        request = irrigation or IrrigationRequest()
        hours = dt_seconds / 3600.0
        precipitation = weather.rain_rate_mm_h * hours
        irrigation_applied = self._irrigation_mm(request, soil, crop, depth)
        et0 = self._et0_mm(weather, dt_seconds)
        lai = crop.leaf_area_index if crop else 0.0
        canopy_factor = min(1.0, max(0.0, lai / 3.0))
        evaporation = et0 * (1.0 - canopy_factor) * 0.3
        stage_factor = {"establishment": 0.7, "vegetative_growth": 1.0, "yield_maturation": 1.05, "post_harvest_dormancy": 0.3}.get(crop.current_stage, 1.0) if crop else 0.0
        transpiration = et0 * canopy_factor * stage_factor
        incoming = precipitation + irrigation_applied
        available_storage = max(0.0, soil.vwc_m3_m3 - soil.wilting_point) * depth * 1000.0 + incoming
        demand = evaporation + transpiration
        storage_before_drainage = max(0.0, available_storage - demand)
        capacity = max(0.0, soil.field_capacity - soil.wilting_point) * depth * 1000.0
        drainage = max(0.0, storage_before_drainage - capacity)
        if soil.drainage_rate > 0:
            drainage = min(drainage, soil.drainage_rate * hours)
        storage = min(capacity, max(0.0, storage_before_drainage - drainage))
        next_vwc = soil.wilting_point + storage / (depth * 1000.0)
        stress = self._water_stress(next_vwc, soil.wilting_point, soil.field_capacity)
        next_soil = SoilState(next_vwc, weather.temperature_c, soil.field_capacity, soil.wilting_point, soil.drainage_rate, storage)
        return WaterBalanceResult(next_soil, stress, et0, evaporation, transpiration, drainage, irrigation_applied, precipitation, storage)

    def _irrigation_mm(self, request: IrrigationRequest, soil: SoilState, crop: CropGrowthState | None, depth: float) -> float:
        if request.mode == "none":
            return 0.0
        efficiency = request.efficiency or self._efficiency.get(request.irrigation_type, 1.0)
        if not 0 < efficiency <= 1:
            raise WaterBalanceError("irrigation efficiency must be in (0, 1]")
        amount = request.amount_mm
        if request.mode == "vwc_target":
            if request.target_vwc is None:
                raise WaterBalanceError("vwc_target mode requires target_vwc")
            amount = max(0.0, request.target_vwc - soil.vwc_m3_m3) * depth * 1000.0
        if request.maximum_mm is not None:
            amount = min(amount, request.maximum_mm)
        return amount * efficiency

    @staticmethod
    def _et0_mm(weather: WeatherState, dt_seconds: float) -> float:
        solar_mj = weather.solar_radiation_w_m2 * dt_seconds / 1_000_000.0
        temperature_range = 10.0
        return max(0.0, 0.0023 * (weather.temperature_c + 17.8) * math.sqrt(temperature_range) * solar_mj)

    @staticmethod
    def _water_stress(vwc: float, wilting_point: float, field_capacity: float) -> float:
        denominator = max(field_capacity - wilting_point, 1e-12)
        current_relative = (vwc - wilting_point) / denominator
        return min(1.0, max(0.0, 1.0 - current_relative))