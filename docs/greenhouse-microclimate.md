# Phase 4.7.8 Greenhouse Microclimate and Actuators

`GreenhouseMicroclimateEngine` transforms outdoor `WeatherState` into the
`DerivedEnvironmentState` consumed by crop models. It supports three modes:
`outdoor`, `passive_greenhouse`, and `actuated_greenhouse`.

## Model

Outdoor mode is an exact bypass: temperature, relative humidity, and
radiation remain the outdoor values. Greenhouse modes use a stable lumped
relaxation rather than CFD or an internal substep loop:

- interior solar radiation = exterior radiation x cover transmission x
  `(1 - shade)`;
- solar gain raises the target interior temperature;
- heating and HVAC add kW, cooling subtracts kW, and heat loss/ventilation
  move the target toward outdoor temperature;
- thermal mass controls the explicit exponential relaxation over `dt_seconds`;
- humidity combines crop LAI, misting, and ventilation and is clipped to
  0..100%;
- VPD is recomputed from interior temperature and humidity;
- CO2 enrichment is optional and remains a ppm output only.

The default profile values are engineering approximations. Site geometry,
thermal mass, cover transmission, heat loss, ventilation, and actuator
capacities must be replaced by inventory or calibration data before operational
use.

## Actuators

`ActuatorControl` exposes requested value, minimum, maximum, capacity,
enabled/failed state, and energy consumption. Existing `ActuatorState` values
can also be passed directly. Failed or disabled actuators produce zero actual
effect; commands never mutate biomass. Supported controls are `ventilation`,
`shade`, `heating`, `cooling`, `hvac`, `misting`, `co2`, and `irrigation`.
Irrigation is reported as an applied mm amount for orchestration with the
water-balance service; it does not run that service internally.

The engine reads `CropGrowthState.leaf_area_index` only. The crop engine then
consumes the resulting environment, so the causal chain remains:

`Weather Engine -> GreenhouseMicroclimateEngine -> Crop/Water/Stress engines`

All components receive `dt_seconds` from the existing `SimulationClock` or
`SimulationScheduler`. No real-time calls or parallel clocks are used.