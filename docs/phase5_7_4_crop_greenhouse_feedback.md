# Phase 5.7.4: crop to greenhouse feedback

## Architecture

`CropGreenhouseFeedbackLoop` is a domain service between the existing crop and
greenhouse contracts:

`MicroclimateState_n -> CropGrowthEngine -> CropPhysicalExchange -> GreenhousePhysicalModel -> MicroclimateState_n+1`

The loop receives any `GreenhousePhysicalModel`. The same code therefore
accepts `SimplifiedGreenhouseModel` and the `EnergyPlusGreenhouseModel`
boundary, without importing EnergyPlus into crop growth. The crop engine is
called from this service, not from an EnergyPlus API callback. The external
`SimulationClock` remains the only time authority; internal iterations reuse
the same `dt_seconds` and do not advance time.

## Existing mechanisms reused

- `CropGrowthEngine` supplies APAR/RUE growth, LAI change, and climate factors.
- `RadiationGrowthEngine` remains the source of intercepted radiation and crop
  growth potential.
- `WaterBalanceEngine` supplies the existing canopy transpiration approximation
  when a soil state and positive root depth are available.
- `CropMicroclimateFeedback` is the existing greenhouse input contract and is
  populated with explicit exchange values.

No direct `biomass -> temperature` relationship is introduced.

| Channel | Unit | Producer | Consumer/sign | Temporal meaning |
|---|---|---|---|---|
| transpiration | `mm h-1` | exchange / `WaterBalanceEngine` | humidity balance, positive vapor | rate over timestep |
| latent heat | `W m-2` | exchange model | thermal balance, negative cooling | flux over timestep |
| sensible heat | `W m-2` | exchange model | thermal balance, positive crop-to-air heat | flux over timestep |
| CO2 uptake | `ppm timestep-1` | exchange from growth | CO2 balance, negative | one external timestep |
| intercepted radiation | `W m-2` | exchange / crop growth | crop exchange | rate |
| LAI | `m2 m-2` | `CropGrowthEngine` | exchange geometry | candidate state |

## Exchanges and units

`PhysicalRate` carries a value, unit, origin, and optional uncertainty.
`CropPhysicalExchange` contains:

- transpiration: `mm h-1`;
- latent heat: `W m-2`;
- sensible heat: `W m-2`;
- CO2 uptake: `ppm timestep-1`;
- intercepted radiation: `W m-2`;
- LAI: `m2 leaf m-2 ground`.

### Transpiration

With soil, the implementation starts from `WaterBalanceEngine.transpiration_mm`
and converts the interval total to a rate. No second VPD multiplier is applied.
The audit of `WaterBalanceEngine` shows that its current transpiration depends
on radiation-derived ET0, LAI/canopy factor, crop stage, timestep and soil
storage; it does not currently model VPD. The feedback layer therefore does
not pretend to add a calibrated VPD response and records the origin as
`WaterBalanceEngine; no second VPD correction`.

Without soil, it uses the existing simplified demand shape:

`T_rate = canopy_factor * (0.15 * VPD + 0.00005 * radiation)`

The fallback is labelled `engineering_default simplified canopy demand` and is
pending calibration. These values are not crop-specific validation.

### Latent heat

Water is treated as 1 kg per mm per square metre and the default latent heat of
vaporization is `2,450,000 J kg-1`:

`lambda_E = T_rate * 2,450,000 / 3600`

The default is an engineering thermodynamic constant, not a calibrated crop
parameter.

### Sensible heat

No leaf temperature is currently observed. The implementation therefore uses a
bounded leaf-air temperature proxy from intercepted radiation and an explicit
engineering coefficient:

`H = h_c * LAI * delta_T_leaf-air`

where `h_c = 5 W m-2 K-1` and
`delta_T_leaf-air = clip(0.002 * intercepted_radiation, -5, 5) K`.
This is a transparent approximation pending leaf-temperature and canopy-energy
observations; it is not a fitted biological equation.

The simplified balance uses `thermal_exchange_area_m2=1 m2` as an explicit
engineering normalization because the existing `thermal_mass_kj_k` is a
whole-zone value while exchange inputs are fluxes. A site-specific canopy or
floor area must replace this default before scientific use.

In `SimplifiedGreenhouseModel`, the signed crop term is
`Q_crop = (sensible_heat_w_m2 - latent_heat_w_m2) * thermal_exchange_area_m2`.
The temperature contribution is `Q_crop * dt / (thermal_mass_kj_k * 1000)`:
positive sensible heat warms the air and positive latent heat cools it. The
same transpiration rate adds vapor to the bounded humidity balance.

### CO2

CO2 uptake is derived from positive `CropGrowthResult.actual_growth_g_m2`, a
default dry-matter carbon fraction of `0.45`, the CO2/carbon molar mass ratio,
and the configured greenhouse air volume:

`CO2 uptake = growth * 0.45 * (44/12) / (air_density * air_volume) * 1e6`

This is a concentration decrement proxy for one external timestep. It is not a
photosynthesis calibration and is marked pending calibration. The default air
volume is `1000 m3`, matching the existing greenhouse engineering default.
The simplified greenhouse carries the result dynamically:
`CO2_candidate = CO2_previous + supply + ventilation_fraction * (420 - CO2_previous) - uptake`.
Thus uptake is not recomputed against baseline on every iteration; the first
call of a timestep uses the previous microclimate state, and fixed-point
iterations all use the same timestep-start state.

## Iteration, relaxation, and non-convergence

Each iteration uses the same initial crop state and external timestep. The crop
is not advanced repeatedly in persistent state. Its candidate result produces
feedback, which is sent to the greenhouse model. The next microclimate is
relaxed as:

`x_relaxed = alpha * x_calculated + (1 - alpha) * x_old`

The default `alpha=0.4` is a numerical engineering default selected to damp the
simplified model's feedback; it is configurable in
`CropGreenhouseFeedbackConfiguration`. Convergence checks temperature,
relative humidity, and CO2 independently against configured tolerances and
reports the maximum normalized error.

When `max_iterations` is reached, the result explicitly contains
`converged=false`, iteration count, final error, reason, and the last stable
microclimate/crop/feedback state. No non-converged result is labelled
converged.

The fixed-point never commits crop growth or soil water during an iteration.
Each exchange evaluation receives the original timestep-start crop and soil
state. Only the returned candidate is available for the caller to commit.

## Parameters and scientific status

Existing growth and water model outputs are model-derived. The leaf heat-
transfer coefficient, leaf-air proxy, carbon fraction, air density, air volume,
thermal exchange area, latent heat constant, and default relaxation are
engineering defaults. No parameter is presented as calibrated. Experimental greenhouse, leaf-temperature,
transpiration, gas-exchange, and CO2 observations remain required for
calibration and validation.

## Tests and manual scenario

Focused tests cover exchange units, radiation/VPD/LAI/shading/ventilation
responses, CO2, convergence, non-convergence, relaxation, physical bounds,
determinism, `SimulationClock`, `SimulationScheduler`, the simplified backend,
and the EnergyPlus backend contract without requiring EnergyPlus.

```powershell
python -m pytest tests/test_crop_greenhouse_feedback.py
python manual_phase5_7_4_crop_greenhouse_feedback_test.py
```

The manual test uses tomato RAF and prints initial/final microclimate, CO2
supply, iterations, convergence error, transpiration, latent/sensible heat, and
CO2 uptake for radiation, shading, and high-VPD scenarios. It is synthetic and does not
claim calibration or experimental validation.

Comparison benchmarks, systematic Simplified-versus-EnergyPlus studies,
performance sweeps, crop transpirational heat coupling beyond these explicit
approximations, and experimental validation remain deferred to 5.7.5 or later.
