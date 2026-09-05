# Phase 4.7.7 Climate Stress and Accumulated Damage

`ClimateStressEngine` is a deterministic domain service for continuous
climate stress. It receives one `WeatherState`, an explicit `dt_seconds`, the
persistent `CropGrowthState`, and optional derived VPD, water-stress, and
nutrient inputs. It owns no clock and does not acquire weather.

## Continuous factors

For the current crop profile it produces independent factors in `[0, 1]`:

- `temperature_factor`, from continuous cold/heat ramps and accumulated damage;
- `vpd_factor`, from VPD above the stage optimum up to its stress limit;
- `radiation_factor`, from radiation above the stage optimum up to the
  photoinhibition threshold;
- `water_factor`, from `1 - water_stress`;
- `nutrient_factor`, from the nutrient engine's continuous factor.

The compositional growth helper is:

`potential_growth * temperature_factor * radiation_factor * water_factor * VPD_factor * nutrient_factor * CO2_factor`

`CO2_factor` is an explicit input and defaults to `1.0`; no CO2 model is
invented in this phase.

## Extreme events

Frost stores exposure duration in hours and maximum intensity in degC below
the critical frost threshold. Frost damage increments with both intensity and
duration, so a ten-hour exposure is not equivalent to a ten-minute exposure.
Recoverable frost damage decreases during non-frost intervals. A fraction is
stored as `irreversible_damage` and never decreases.

Heat exposure above the stage maximum accumulates in hours and `heat_damage`
increases with supra-optimal intensity and duration. Consecutive hot intervals
therefore have a larger effect than an isolated interval. Heat damage recovers
slowly under normal temperatures in this deliberately simple model.

`accumulated_stress` is a bounded history term with slow recovery. Current
cold, heat, VPD, and radiation stress remain separately observable in the
persistent state. All fields are continuous rather than event flags.

## Scope and calibration

Threshold profiles are crop-level approximations derived from the existing
stage threshold concepts, with an optional stage-sensitivity multiplier so
the same exposure can have different impact during establishment, vegetative
growth, maturation, or dormancy. They are not variety-specific and must be
replaced or calibrated with plot observations before operational use. The model does
not implement canopy energy balance, mechanistic frost damage, CFD,
photochemistry, CO2 response, or a separate internal timestep loop.