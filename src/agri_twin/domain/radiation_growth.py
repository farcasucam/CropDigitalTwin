"""Lightweight intercepted-radiation biomass growth model."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from agri_twin.domain.models import CropGrowthState, WeatherState


class RadiationGrowthError(ValueError):
    """Raised when radiation-growth inputs or profiles are invalid."""


@dataclass(frozen=True, slots=True)
class RadiationGrowthProfile:
    """Crop-level engineering approximation, never a variety calibration."""

    crop_key: str
    extinction_coefficient: float
    rue_g_dm_mj_par: float
    specific_leaf_area_m2_g_dm: float
    maximum_lai: float
    partition_by_stage: dict[str, tuple[float, float, float, float]]
    senescence_rate_per_day: float = 0.02

    def __post_init__(self) -> None:
        if not self.crop_key or min(self.extinction_coefficient, self.rue_g_dm_mj_par, self.specific_leaf_area_m2_g_dm, self.maximum_lai) <= 0:
            raise RadiationGrowthError("radiation-growth profile values must be positive")
        if not 0 <= self.senescence_rate_per_day <= 1:
            raise RadiationGrowthError("senescence rate must be between 0 and 1")
        for stage, fractions in self.partition_by_stage.items():
            if len(fractions) != 4 or any(value < 0 for value in fractions) or not math.isclose(sum(fractions), 1.0):
                raise RadiationGrowthError(f"partition fractions must sum to one: {stage}")


_PARTITION = {
    "establishment": (0.60, 0.15, 0.25, 0.00),
    "vegetative_growth": (0.45, 0.30, 0.20, 0.05),
    "yield_maturation": (0.20, 0.20, 0.15, 0.45),
    "post_harvest_dormancy": (0.00, 0.50, 0.50, 0.00),
}

APPROXIMATE_RADIATION_PROFILES = {
    crop: RadiationGrowthProfile(crop, 0.6, 2.0, 0.02, maximum_lai, _PARTITION)
    for crop, maximum_lai in {
        "tomato": 4.5, "lettuce": 3.5, "pepper": 4.0, "grape": 4.0,
        "peach": 4.0, "plum": 4.0, "apple": 4.5,
    }.items()
}


class RadiationGrowthEngine:
    """Convert interval radiation into biomass and LAI using Beer-Lambert."""

    PAR_FRACTION_OF_SHORTWAVE = 0.48

    def __init__(self, profiles: dict[str, RadiationGrowthProfile] | None = None) -> None:
        self._profiles = dict(APPROXIMATE_RADIATION_PROFILES if profiles is None else profiles)

    def profile_for(self, crop_key: str) -> RadiationGrowthProfile:
        try:
            return self._profiles[crop_key.lower()]
        except KeyError as exc:
            raise RadiationGrowthError(f"radiation-growth profile not found: {crop_key}") from exc

    @classmethod
    def par_mj_m2(cls, solar_radiation_w_m2: float, dt_seconds: float) -> float:
        if not math.isfinite(solar_radiation_w_m2) or solar_radiation_w_m2 < 0:
            raise RadiationGrowthError("solar radiation must be finite and non-negative")
        if not math.isfinite(dt_seconds) or dt_seconds < 0:
            raise RadiationGrowthError("dt_seconds must be finite and non-negative")
        return cls.PAR_FRACTION_OF_SHORTWAVE * solar_radiation_w_m2 * dt_seconds / 1_000_000.0

    def advance(
        self,
        state: CropGrowthState,
        weather: WeatherState,
        dt_seconds: float,
        limitation_factor: float = 1.0,
    ) -> CropGrowthState:
        """Return growth for one explicit weather interval at state's time.

        Call after phenology has advanced the state to the interval end. The
        optional limitation factor is intentionally supplied by later water,
        nutrient, or climate models rather than calculated here.
        """
        if not isinstance(state, CropGrowthState):
            raise RadiationGrowthError("state must be a CropGrowthState")
        if not math.isfinite(limitation_factor) or not 0 <= limitation_factor <= 1:
            raise RadiationGrowthError("limitation_factor must be between 0 and 1")
        profile = self.profile_for(state.crop_key)
        if state.current_stage == "post_harvest_dormancy":
            return self._senesce(state, profile, dt_seconds)
        par = self.par_mj_m2(weather.solar_radiation_w_m2, dt_seconds)
        intercepted_par = par * (1.0 - math.exp(-profile.extinction_coefficient * state.leaf_area_index))
        potential_biomass = intercepted_par * profile.rue_g_dm_mj_par
        actual_biomass = potential_biomass * limitation_factor
        leaf, stem, root, fruit = self._partition(actual_biomass, state, profile)
        leaf_area_index = min(profile.maximum_lai, leaf * profile.specific_leaf_area_m2_g_dm)
        return replace(
            state,
            biomass_leaf=leaf,
            biomass_stem=stem,
            biomass_root=root,
            biomass_fruit=fruit,
            biomass_total=leaf + stem + root + fruit,
            leaf_area_index=leaf_area_index,
        )

    @staticmethod
    def _partition(increment: float, state: CropGrowthState, profile: RadiationGrowthProfile) -> tuple[float, float, float, float]:
        fractions = profile.partition_by_stage[state.current_stage]
        additions = tuple(increment * fraction for fraction in fractions)
        leaf = state.biomass_leaf + additions[0]
        maximum_leaf_biomass = profile.maximum_lai / profile.specific_leaf_area_m2_g_dm
        overflow = max(0.0, leaf - maximum_leaf_biomass)
        leaf -= overflow
        return leaf, state.biomass_stem + additions[1] + overflow, state.biomass_root + additions[2], state.biomass_fruit + additions[3]

    @staticmethod
    def _senesce(state: CropGrowthState, profile: RadiationGrowthProfile, dt_seconds: float) -> CropGrowthState:
        if not math.isfinite(dt_seconds) or dt_seconds < 0:
            raise RadiationGrowthError("dt_seconds must be finite and non-negative")
        retained_leaf = state.biomass_leaf * max(0.0, 1.0 - profile.senescence_rate_per_day * dt_seconds / 86400.0)
        senesced_leaf = state.biomass_leaf - retained_leaf
        return replace(
            state,
            biomass_leaf=retained_leaf,
            biomass_stem=state.biomass_stem + senesced_leaf,
            leaf_area_index=retained_leaf * profile.specific_leaf_area_m2_g_dm,
        )