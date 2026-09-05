"""Deterministic thermal-time phenology without a real-time dependency."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum

from agri_twin.domain.models import CropGrowthState, WeatherState


class PhenologyError(ValueError):
    """Raised when phenology inputs or profiles are invalid."""


class PhenologyEvidenceLevel(StrEnum):
    SCIENTIFIC_BASE = "SCIENTIFIC_BASE"
    ENGINEERING_APPROXIMATION = "ENGINEERING_APPROXIMATION"
    CALIBRATED = "CALIBRATED"


@dataclass(frozen=True, slots=True)
class PhenologyProfile:
    """Explicit profile; approximate defaults are never cultivar-specific."""

    crop_key: str
    perennial: bool
    base_temperature_c: float
    upper_temperature_c: float
    stage_gdd_targets: tuple[float, float, float]
    maturity_gdd_target: float
    evidence_level: PhenologyEvidenceLevel = PhenologyEvidenceLevel.ENGINEERING_APPROXIMATION
    chilling_requirement_hours: float | None = None
    chilling_min_temperature_c: float = 0.0
    chilling_max_temperature_c: float = 7.2

    def __post_init__(self) -> None:
        if not self.crop_key or not math.isfinite(self.base_temperature_c) or not math.isfinite(self.upper_temperature_c):
            raise PhenologyError("crop key and thermal limits must be valid")
        if self.upper_temperature_c <= self.base_temperature_c:
            raise PhenologyError("upper temperature must exceed base temperature")
        if len(self.stage_gdd_targets) != 3 or any(value <= 0 or not math.isfinite(value) for value in self.stage_gdd_targets):
            raise PhenologyError("three positive stage GDD targets are required")
        if self.maturity_gdd_target <= 0 or not math.isfinite(self.maturity_gdd_target):
            raise PhenologyError("maturity GDD target must be positive")
        if self.perennial and (self.chilling_requirement_hours is None or self.chilling_requirement_hours <= 0):
            raise PhenologyError("perennial profiles require chilling hours")
        if not self.perennial and self.chilling_requirement_hours is not None:
            raise PhenologyError("annual profiles cannot require chilling")


APPROXIMATE_PROFILES = {
    "tomato": PhenologyProfile("tomato", False, 10.0, 30.0, (250.0, 500.0, 900.0), 1200.0),
    "lettuce": PhenologyProfile("lettuce", False, 4.0, 28.0, (150.0, 350.0, 600.0), 750.0),
    "pepper": PhenologyProfile("pepper", False, 10.0, 30.0, (250.0, 550.0, 950.0), 1200.0),
    "grape": PhenologyProfile("grape", True, 5.0, 30.0, (200.0, 500.0, 900.0), 1100.0, chilling_requirement_hours=400.0),
    "peach": PhenologyProfile("peach", True, 4.5, 30.0, (200.0, 500.0, 900.0), 1100.0, chilling_requirement_hours=600.0),
    "plum": PhenologyProfile("plum", True, 4.5, 25.0, (200.0, 500.0, 850.0), 1050.0, chilling_requirement_hours=500.0),
    "apple": PhenologyProfile("apple", True, 4.0, 30.0, (200.0, 500.0, 900.0), 1100.0, chilling_requirement_hours=600.0),
}

STAGES = ("establishment", "vegetative_growth", "yield_maturation", "post_harvest_dormancy")


class PhenologyEngine:
    """Advance phenology only from provided weather and simulation time."""

    def __init__(self, profiles: dict[str, PhenologyProfile] | None = None) -> None:
        self._profiles = dict(APPROXIMATE_PROFILES if profiles is None else profiles)

    def profile_for(self, crop_key: str) -> PhenologyProfile:
        try:
            return self._profiles[crop_key.lower()]
        except KeyError as exc:
            raise PhenologyError(f"phenology profile not found: {crop_key}") from exc

    @staticmethod
    def degree_days(temperature_c: float, profile: PhenologyProfile, dt_seconds: float) -> float:
        if not math.isfinite(temperature_c) or not math.isfinite(dt_seconds) or dt_seconds < 0:
            raise PhenologyError("temperature and dt_seconds must be finite and non-negative")
        clipped_temperature = min(profile.upper_temperature_c, max(profile.base_temperature_c, temperature_c))
        return (clipped_temperature - profile.base_temperature_c) * dt_seconds / 86400.0

    def advance(
        self,
        state: CropGrowthState,
        weather: WeatherState,
        simulation_time: datetime,
        dt_seconds: float,
    ) -> CropGrowthState:
        if not isinstance(state, CropGrowthState):
            raise PhenologyError("state must be a CropGrowthState")
        if simulation_time.tzinfo is None:
            raise PhenologyError("simulation_time must be timezone-aware")
        if simulation_time != state.simulation_time + timedelta(seconds=dt_seconds):
            raise PhenologyError("simulation_time must advance by dt_seconds")
        profile = self.profile_for(state.crop_key)
        chilling = state.chilling_hours
        dormancy_released = state.dormancy_released
        if profile.perennial and not dormancy_released:
            if profile.chilling_min_temperature_c <= weather.temperature_c <= profile.chilling_max_temperature_c:
                chilling += dt_seconds / 3600.0
            dormancy_released = chilling >= profile.chilling_requirement_hours
            return replace(
                state,
                simulation_time=simulation_time,
                chilling_hours=chilling,
                dormancy_released=dormancy_released,
                phenology_model=profile.evidence_level.value,
            )
        gdd = state.gdd_accumulated + self.degree_days(weather.temperature_c, profile, dt_seconds)
        stage_index = STAGES.index(state.current_stage)
        while stage_index < len(profile.stage_gdd_targets) and gdd >= profile.stage_gdd_targets[stage_index]:
            stage_index += 1
        maturity = min(1.0, gdd / profile.maturity_gdd_target)
        return replace(
            state,
            simulation_time=simulation_time,
            current_stage=STAGES[stage_index],
            phenology_progress=self._stage_progress(gdd, profile, stage_index),
            gdd_accumulated=gdd,
            chilling_hours=chilling,
            dormancy_released=dormancy_released,
            maturity_index=max(state.maturity_index, maturity),
            phenology_model=profile.evidence_level.value,
        )

    @staticmethod
    def _stage_progress(gdd: float, profile: PhenologyProfile, stage_index: int) -> float:
        start = 0.0 if stage_index == 0 else profile.stage_gdd_targets[stage_index - 1]
        end = profile.maturity_gdd_target if stage_index == len(STAGES) - 1 else profile.stage_gdd_targets[stage_index]
        return min(1.0, max(0.0, (gdd - start) / (end - start)))