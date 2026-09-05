"""Reduced, deterministic nutrient availability and growth limitation model."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from agri_twin.domain.models import CropGrowthState


class NutrientBalanceError(ValueError):
    """Raised when nutrient model inputs are invalid."""


@dataclass(frozen=True, slots=True)
class FertilizationRequest:
    """Passive fertilizer input supplied by an operator or controller."""

    amount_kg_ha: float = 0.0
    efficiency: float = 1.0
    mode: str = "none"
    leaching_fraction: float = 0.0

    def __post_init__(self) -> None:
        if self.mode not in {"none", "manual", "scheduled"}:
            raise NutrientBalanceError("fertilization mode is invalid")
        for name, value in (("amount_kg_ha", self.amount_kg_ha), ("efficiency", self.efficiency), ("leaching_fraction", self.leaching_fraction)):
            if not math.isfinite(value):
                raise NutrientBalanceError(f"{name} must be finite")
        if self.amount_kg_ha < 0 or not 0 < self.efficiency <= 1 or not 0 <= self.leaching_fraction <= 1:
            raise NutrientBalanceError("fertilization values are outside their ranges")


@dataclass(frozen=True, slots=True)
class NutrientProfile:
    crop_key: str
    baseline_reserve_kg_ha: float = 200.0
    extraction_kg_per_kg_biomass: float = 0.02
    stage_factor: dict[str, float] | None = None
    evidence_status: str = "ENGINEERING_APPROXIMATION"
    requires_calibration: bool = True

    def __post_init__(self) -> None:
        if not self.crop_key or self.baseline_reserve_kg_ha <= 0 or self.extraction_kg_per_kg_biomass < 0:
            raise NutrientBalanceError("nutrient profile values are invalid")
        if self.evidence_status not in {"ENGINEERING_APPROXIMATION", "SCIENTIFIC_BASE", "CALIBRATED"}:
            raise NutrientBalanceError("nutrient evidence status is invalid")
        factors = self.stage_factor or {}
        if any(not math.isfinite(value) or value < 0 for value in factors.values()):
            raise NutrientBalanceError("stage nutrient factors are invalid")


APPROXIMATE_NUTRIENT_PROFILES = {
    crop: NutrientProfile(crop, stage_factor={
        "establishment": 0.7, "vegetative_growth": 1.0,
        "yield_maturation": 1.1, "post_harvest_dormancy": 0.3,
    })
    for crop in ("tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple")
}


@dataclass(frozen=True, slots=True)
class NutrientBalanceResult:
    state: CropGrowthState
    nutrient_status: float
    nutrient_stress: float
    nutrient_factor: float
    nutrient_reserve_kg_ha: float
    nutrient_available_kg_ha: float
    nutrient_applied_kg_ha: float
    nutrient_extracted_kg_ha: float
    nutrient_leached_kg_ha: float
    growth_potential_g_m2: float
    growth_actual_g_m2: float


class NutrientBalanceEngine:
    """Advance one available-nutrient pool using explicit biomass and dt."""

    def __init__(self, profiles: dict[str, NutrientProfile] | None = None) -> None:
        self._profiles = dict(APPROXIMATE_NUTRIENT_PROFILES if profiles is None else profiles)

    def profile_for(self, crop_key: str) -> NutrientProfile:
        try:
            return self._profiles[crop_key.lower()]
        except KeyError as exc:
            raise NutrientBalanceError(f"nutrient profile not found: {crop_key}") from exc

    def advance(
        self,
        state: CropGrowthState,
        growth_potential_g_m2: float = 0.0,
        dt_seconds: float = 0.0,
        fertilization: FertilizationRequest | None = None,
        leaching_fraction: float | None = None,
    ) -> NutrientBalanceResult:
        if not isinstance(state, CropGrowthState):
            raise NutrientBalanceError("state must be a CropGrowthState")
        if not math.isfinite(growth_potential_g_m2) or growth_potential_g_m2 < 0:
            raise NutrientBalanceError("growth_potential_g_m2 must be finite and non-negative")
        if not math.isfinite(dt_seconds) or dt_seconds < 0:
            raise NutrientBalanceError("dt_seconds must be finite and non-negative")
        profile = self.profile_for(state.crop_key)
        request = fertilization or FertilizationRequest()
        reserve = state.nutrient_reserve_kg_ha or profile.baseline_reserve_kg_ha
        available = min(reserve, state.nutrient_available_kg_ha)
        applied = request.amount_kg_ha * request.efficiency
        leach = leaching_fraction if leaching_fraction is not None else request.leaching_fraction
        if not 0 <= leach <= 1 or not math.isfinite(leach):
            raise NutrientBalanceError("leaching_fraction must be between 0 and 1")
        extracted = min(available + applied, growth_potential_g_m2 * 10.0 * profile.extraction_kg_per_kg_biomass * (profile.stage_factor or {}).get(state.current_stage, 1.0))
        next_available = min(reserve, max(0.0, available + applied - extracted))
        leached = next_available * leach
        next_available = max(0.0, next_available - leached)
        status = min(1.0, max(0.0, next_available / reserve))
        stress = 1.0 - status
        factor = status
        actual = growth_potential_g_m2 * factor
        next_state = replace(state, nutrient_reserve_kg_ha=reserve, nutrient_available_kg_ha=next_available, nutrient_status=status)
        return NutrientBalanceResult(next_state, status, stress, factor, reserve, next_available, applied, extracted, leached, growth_potential_g_m2, actual)

    @staticmethod
    def apply_growth_limit(growth_potential_g_m2: float, nutrient_factor: float) -> float:
        if not math.isfinite(growth_potential_g_m2) or growth_potential_g_m2 < 0 or not 0 <= nutrient_factor <= 1:
            raise NutrientBalanceError("growth potential or nutrient factor is invalid")
        return growth_potential_g_m2 * nutrient_factor