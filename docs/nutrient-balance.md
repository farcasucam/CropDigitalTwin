# Phase 4.7.6 Simplified Nutrient Availability

`NutrientBalanceEngine` is a deliberately reduced nutrient limitation model.
It tracks one primary nutrient, nitrogen, as a non-negative pool in
`kg_N/ha`. It does not claim to represent complete N-P-K chemistry, mineral
forms, root uptake kinetics, cultivar requirements, or soil laboratory data.

## State and balance

`CropGrowthState` persists `nutrient_reserve_kg_ha`,
`nutrient_available_kg_ha`, and `nutrient_status` in `[0, 1]`. The reserve is
the configured pool ceiling; availability is the extractable pool. For each
explicit interval:

`N_next = clamp(N_current + N_applied - N_extracted - N_leached, 0, N_reserve)`

Fertilizer application is `amount_kg_ha * efficiency`. Manual and scheduled
requests are passive inputs. Optional leaching is an explicit fraction; no
unrequested fertilizer or controller schedule is generated.

Biomass from the radiation model is `g dry matter/m2`. It is converted to
`kg dry matter/ha` by multiplying by 10 before applying the approximate
extraction coefficient. Stage factors are explicit and currently represent
relative demand only: establishment 0.7, vegetative 1.0, maturation 1.1,
and post-harvest 0.3.

## Stress and growth

`nutrient_status = N_available / N_reserve`, clipped to `[0, 1]`.
`nutrient_stress = 1 - nutrient_status` and
`nutrient_factor = nutrient_status`. The factor is continuous and the
growth contract is:

`growth_actual = growth_potential * nutrient_factor`

The recommended orchestration is radiation potential first, nutrient balance
second, then radiation growth with `limitation_factor=nutrient_factor` (or the
product with water and other future limitation factors).

## Evidence and calibration

The baseline reserve and extraction coefficient are marked
`ENGINEERING_APPROXIMATION` and `requires_calibration=true` in
`src/growth_model_config.json`. All seven crop profiles are present but
unset, so no cultivar-specific N/P/K values are invented. Field nutrient
measurements, fertilization history, tissue analysis, and crop-specific
calibration are required before replacing the baseline with scientific or
local values.

The service accepts explicit `dt_seconds` and has no real-time clock. It is
deterministic for the same state, potential growth, fertilization, leaching,
and timestep. Timestep size does not create an internal substep loop.