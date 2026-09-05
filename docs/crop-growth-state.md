# Phase 4.7.2 Persistent Crop Growth State

`CropGrowthState` is the immutable, persistent state contract for one crop on
one plot at an explicit `simulation_time`. It complements the existing
ephemeral `CropState`: the latter remains the current Crop Engine stress
result, while the new state retains the variables needed by later growth and
water-balance subphases.

## Contract

The state records crop identity and variety, current stage and phenology
progress, total and partitioned biomass, LAI, root depth, soil water, nutrient
status, current stress channels (water, heat, cold, VPD, radiation), frost
damage, accumulated stress, maturity, estimated yield, and harvest readiness.

All indices and stress values are dimensionless fractions in `[0, 1]`. Biomass
is a non-negative dry-matter quantity whose mass unit will be fixed with the
future RUE/calibration contract; this phase does not attach a false precision
unit. `leaf_area_index` is m2 leaf per m2 ground, `root_depth_m` is metres,
and `soil_water_vwc` is volumetric water content as a fraction.

`biomass_total` must exactly equal leaf + stem + root + fruit biomass.
`harvest_ready` requires `maturity_index == 1`. All aggregate values are
finite and non-negative, and crop identity, variety, stage, and timezone-aware
simulation time are required.

## Time and persistence

`advance(simulation_time, dt_seconds)` accepts a timestamp and explicit delta
from `SimulationClock` or `SimulationScheduler`. The supplied timestamp must
equal the prior timestamp plus `dt_seconds`; no real-time source, private
clock, weather lookup, or automatic stage transition exists in the state.
This makes zero-to-multi-day advances deterministic and safe to replay.

`to_dict()` produces a JSON-ready mapping with an ISO 8601 simulation time,
ready for embedding in the existing message envelope. The next growth engine
will calculate changed biomass, water, stress, and maturity from the prior
state, `WeatherState`, derived environment, soil, and explicit `dt`.