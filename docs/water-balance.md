# Phase 4.7.5 Simplified Crop Water Balance

`WaterBalanceEngine` is a deterministic root-zone bucket for one explicit
weather interval. It receives `WeatherState`, `SoilState`, optional
`CropGrowthState`, an explicit `dt_seconds`, and a passive
`IrrigationRequest`. It does not own a clock, weather provider, irrigation
controller, or actuator state.

## Bucket and units

Rainfall and irrigation inputs are in mm. Rainfall is
`rain_rate_mm_h * dt_hours`. Root-zone storage is mm of water above wilting
point and below field capacity:

`capacity_mm = (field_capacity - wilting_point) * root_depth_m * 1000`

VWC is reconstructed from storage and root depth. The result is always
bounded by the configured wilting point and field capacity. `SoilState`
continues to carry `root_zone_water` as this storage value for compatibility.

The balance is:

`storage_next = storage_current + precipitation + irrigation_applied - evaporation - transpiration - drainage`

Excess over field capacity becomes drainage, limited by `soil.drainage_rate`
when that rate is configured. No implicit infiltration or runoff model is
added.

## ET and crop coupling

With the available weather fields, the model uses a Hargreaves-inspired
radiation approximation based on Allen et al. (FAO-56 context):

`ET0_mm = 0.0023 * (T + 17.8) * sqrt(10) * solar_energy_MJ_m2`

The missing daily minimum/maximum temperature and extraterrestrial radiation
are represented by the explicit 10 degC range and the supplied solar energy;
this is an engineering approximation, not a full FAO-56 implementation.

LAI scales canopy transpiration up to LAI 3.0 and exposes soil evaporation as
the complementary canopy fraction. Stage coefficients are simple model
parameters: establishment 0.7, vegetative 1.0, maturation 1.05, and
post-harvest 0.3. Root depth controls storage capacity. The output contains
ET0, evaporation, transpiration, drainage, precipitation, irrigation applied,
storage, VWC, and a linear water-stress factor.

## Irrigation

`IrrigationRequest` supports `none`, `manual`, `scheduled`, and `vwc_target`.
It accepts a target VWC and maximum applied volume. Efficiency is selected by
irrigation type and is deliberately not uniform: drip 0.95, hydroponic drip
0.99, subsurface drip 0.95, and overhead 0.75. Unknown types default to 1.0
only when explicitly supplied as an engineering request; site inventory and
controller policy remain future responsibilities.

The model does not implement irrigation scheduling, soil hydraulic functions,
nutrients, runoff, groundwater, HVAC, or complex plant damage. These can
later provide the limitation or irrigation inputs without changing the bucket
contract.