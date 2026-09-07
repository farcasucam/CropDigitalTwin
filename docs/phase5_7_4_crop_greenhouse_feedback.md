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
and converts the interval total to a rate. It applies an explicit engineering
VPD response multiplier bounded at three times the configured reference VPD:

`T_rate = T_water_balance * (0.5 + 0.5 * VPD / VPD_reference)`

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

### CO2

CO2 uptake is derived from positive `CropGrowthResult.actual_growth_g_m2`, a
default dry-matter carbon fraction of `0.45`, the CO2/carbon molar mass ratio,
and the configured greenhouse air volume:

`CO2 uptake = growth * 0.45 * (44/12) / (air_density * air_volume) * 1e6`

This is a concentration decrement proxy for one external timestep. It is not a
photosynthesis calibration and is marked pending calibration. The default air
volume is `1000 m3`, matching the existing greenhouse engineering default.

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

## Parameters and scientific status

Existing growth and water model outputs are model-derived. The VPD multiplier,
leaf heat-transfer coefficient, leaf-air proxy, carbon fraction, air density,
air volume, and default relaxation are engineering defaults. No parameter is
presented as calibrated. Experimental greenhouse, leaf-temperature,
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

The manual test uses tomato RAF and prints initial/final microclimate,
iterations, convergence, transpiration, latent/sensible heat, and CO2 uptake
for radiation, shading, and high-VPD scenarios. It is synthetic and does not
claim calibration or experimental validation.

Comparison benchmarks, systematic Simplified-versus-EnergyPlus studies,
performance sweeps, crop transpirational heat coupling beyond these explicit
approximations, and experimental validation remain deferred to 5.7.5 or later.
