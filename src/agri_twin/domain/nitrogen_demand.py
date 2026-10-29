"""Optional nitrogen model of the nutrient line, level 1: demand driven uptake, a critical-dilution style nitrogen nutrition index and drainage driven leaching.

It replaces the reduced single-pool model ONLY when a request asks for it (model option ``nutrient_model = NITROGEN_DEMAND``); the default runs are unchanged. It keeps the same interface and result as
``NutrientBalanceEngine`` so the orchestrator, the series and the explanation layer treat both alike.

State: the soil mineral nitrogen pool (``nutrient_available_kg_ha``, no longer capped at a reserve) and the nitrogen held by the crop (``plant_nitrogen_kg_ha``).
Per step: the dose is added to the soil pool; the crop wants to reach the CRITICAL nitrogen of the biomass it is growing towards (potential growth of the step) and takes ``min(demand, soil pool)``; the soil pool then
loses a fraction (set by the drainage of the step, computed by the water balance) to leaching; the nitrogen nutrition index NNI = crop nitrogen / critical nitrogen (capped at 1) is the growth factor and the status.

Critical nitrogen (the form of a critical dilution curve): Nc[%] = a * W^-b for W >= 1 t/ha (dry biomass), Nc = a below; critical nitrogen [kg/ha] = 10 * Nc * W.

EVIDENCE STATUS: every number below is an UNSOURCED PLACEHOLDER chosen only to give the structure an order of magnitude; none was read from a publication or fitted to data, and none is claimed for any crop.
Results are to be read qualitatively (sign, order, compensation, timing), never as agronomic values. Simplifications that matter: one nitrogen pool, no mineralisation, no volatilisation, no root-depth dependence,
the index is evaluated against the potential growth of the step (the crop's actual growth is lower when it is limited), the crop starts at its critical nitrogen (NNI 1) at the first step.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from agri_twin.domain.models import CropGrowthState
from agri_twin.domain.nutrient_balance import FertilizationRequest, NutrientBalanceError, NutrientBalanceResult


@dataclass(frozen=True, slots=True)
class NitrogenParameters:
    critical_percent_at_one_t_ha: float = 4.0  # a of the curve (placeholder)
    critical_exponent: float = 0.5  # b of the curve (placeholder)
    leaching_fraction_per_mm_drainage: float = 0.005  # fraction of the soil pool lost per mm of drainage (placeholder)
    initial_soil_nitrogen_kg_ha: float | None = None  # None: the pool the state starts with; the user's value when given
    evidence_status: str = "UNSOURCED_PLACEHOLDER"
    requires_calibration: bool = True

    def __post_init__(self) -> None:
        if not (self.critical_percent_at_one_t_ha > 0 and 0 <= self.critical_exponent < 1 and self.leaching_fraction_per_mm_drainage >= 0):
            raise NutrientBalanceError("nitrogen parameters are invalid")
        if self.initial_soil_nitrogen_kg_ha is not None and self.initial_soil_nitrogen_kg_ha < 0:
            raise NutrientBalanceError("initial soil nitrogen must be non-negative")


class NitrogenDemandEngine:
    """Same interface as ``NutrientBalanceEngine.advance`` (the orchestrator passes the drainage-based leaching fraction)."""

    def __init__(self, parameters: NitrogenParameters | None = None) -> None:
        self.parameters = parameters or NitrogenParameters()
        self.leaching_per_mm = self.parameters.leaching_fraction_per_mm_drainage  # the orchestrator reads this to know the engine wants the drainage

    def critical_nitrogen_kg_ha(self, biomass_g_m2: float) -> float:
        tonnes = max(0.0, biomass_g_m2) / 100.0
        percent = self.parameters.critical_percent_at_one_t_ha * (tonnes ** -self.parameters.critical_exponent if tonnes >= 1.0 else 1.0)
        return 10.0 * percent * tonnes

    def advance(self, state: CropGrowthState, growth_potential_g_m2: float = 0.0, dt_seconds: float = 0.0, fertilization: FertilizationRequest | None = None,
                leaching_fraction: float | None = None) -> NutrientBalanceResult:
        if not isinstance(state, CropGrowthState):
            raise NutrientBalanceError("state must be a CropGrowthState")
        if not math.isfinite(growth_potential_g_m2) or growth_potential_g_m2 < 0 or not math.isfinite(dt_seconds) or dt_seconds < 0:
            raise NutrientBalanceError("growth potential and dt must be finite and non-negative")
        leach = 0.0 if leaching_fraction is None else leaching_fraction
        if not math.isfinite(leach) or not 0.0 <= leach <= 1.0:
            raise NutrientBalanceError("leaching_fraction must be between 0 and 1")
        request = fertilization or FertilizationRequest()
        first_step = state.plant_nitrogen_kg_ha is None
        soil = self.parameters.initial_soil_nitrogen_kg_ha if first_step and self.parameters.initial_soil_nitrogen_kg_ha is not None else state.nutrient_available_kg_ha
        plant = self.critical_nitrogen_kg_ha(state.biomass_total) if first_step else state.plant_nitrogen_kg_ha
        applied = request.amount_kg_ha * request.efficiency
        soil += applied
        critical = self.critical_nitrogen_kg_ha(state.biomass_total + growth_potential_g_m2)
        uptake = min(max(0.0, critical - plant), soil)
        soil -= uptake
        plant += uptake
        leached = soil * leach
        soil -= leached
        index = 1.0 if critical <= 0 else min(1.0, max(0.0, plant / critical))
        reserve = max(state.nutrient_reserve_kg_ha, soil)  # the state's invariant (pool <= reserve) is kept: here the reserve is only the largest pool seen, not a cap
        next_state = replace(state, nutrient_reserve_kg_ha=reserve, nutrient_available_kg_ha=soil, nutrient_status=index, plant_nitrogen_kg_ha=plant)
        return NutrientBalanceResult(next_state, index, 1.0 - index, index, reserve, soil, applied, uptake, leached, growth_potential_g_m2, growth_potential_g_m2 * index, plant, critical)
