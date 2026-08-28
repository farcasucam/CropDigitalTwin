"""Deterministic, explainable crop stress evaluation."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Mapping

from agri_twin.domain.crop import CropDefinition, CropStageDefinition
from agri_twin.domain.models import CropState, DerivedEnvironmentState, SoilState, WeatherState


class CropEngineError(ValueError):
    """Raised when crop evaluation inputs are invalid."""


class CropEngine:
    """Evaluate crop stress from configured stage thresholds and environment.

    Stress indices use [0, 1]. ``cumulative_stress`` is the explicit MVP
    combination: the arithmetic mean of thermal, water and VPD stress.
    ``development_index`` is a bounded, timestep-based progress proxy, not a
    full phenology model.
    """

    def evaluate(
        self,
        crop: CropDefinition,
        stage: CropStageDefinition | str,
        weather: WeatherState,
        environment: DerivedEnvironmentState,
        soil: SoilState,
        timestamp: datetime,
        timestep_seconds: float = 0.0,
        previous: CropState | None = None,
    ) -> CropState:
        if timestamp.tzinfo is None:
            raise CropEngineError("timestamp must be timezone-aware")
        if not math.isfinite(timestep_seconds) or timestep_seconds < 0:
            raise CropEngineError("timestep_seconds must be finite and non-negative")
        resolved_stage = crop.resolve_stage(stage) if isinstance(stage, str) else stage
        if resolved_stage.stage_key not in crop.stages:
            raise CropEngineError("stage does not belong to crop")
        parameters = resolved_stage.parameters
        thermal = self._thermal_stress(weather.temperature_c, parameters["stress_thresholds"])
        water = self._water_stress(soil.vwc_m3_m3, parameters["vwc_thresholds"])
        vpd = self._vpd_stress(environment.vpd_kpa, parameters["vpd_thresholds"])
        total = (thermal + water + vpd) / 3
        growth = 1.0 - total
        previous_index = previous.development_index if previous else 0.0
        progress = min(1.0, previous_index + timestep_seconds / (86400.0 * 30.0) * growth)
        previous_biomass = previous.biomass if previous else 0.0
        biomass = previous_biomass + timestep_seconds / 86400.0 * growth
        previous_cumulative = previous.cumulative_stress if previous else 0.0
        return CropState(
            biomass=biomass,
            leaf_area_index=previous.leaf_area_index if previous else 0.0,
            development_stage=resolved_stage.stage_key,
            water_stress=water,
            temperature_stress=thermal,
            vpd_stress=vpd,
            cumulative_stress=max(previous_cumulative, total),
            development_index=progress,
        )

    @staticmethod
    def _thermal_stress(temperature: float, thresholds: Mapping[str, float]) -> float:
        minimum = thresholds["min_temp_c"]
        maximum = thresholds["max_temp_c"]
        frost = thresholds["critical_frost_c"]
        heat = thresholds["critical_heat_c"]
        if minimum <= temperature <= maximum:
            return 0.0
        if temperature < minimum:
            return CropEngine._clamp((minimum - temperature) / max(minimum - frost, 1e-9))
        return CropEngine._clamp((temperature - maximum) / max(heat - maximum, 1e-9))

    @staticmethod
    def _water_stress(vwc: float, thresholds: Mapping[str, float]) -> float:
        optimal = thresholds["optimal_min"]
        wilting = thresholds["wilting_point"]
        if vwc >= optimal:
            return 0.0
        return CropEngine._clamp((optimal - vwc) / max(optimal - wilting, 1e-9))

    @staticmethod
    def _vpd_stress(vpd: float, thresholds: Mapping[str, float]) -> float:
        optimal = thresholds["optimal_max_kpa"]
        maximum = thresholds["stress_max_kpa"]
        if vpd <= optimal:
            return 0.0
        return CropEngine._clamp((vpd - optimal) / max(maximum - optimal, 1e-9))

    @staticmethod
    def _clamp(value: float) -> float:
        return min(1.0, max(0.0, value))
