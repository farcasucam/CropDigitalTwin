# Phase 4.7.9 Integrated Digital Twin Architecture

The integrated entry point is `CropDigitalTwinOrchestrator`. It owns one
injected `SimulationClock`, one `WeatherEngine`, the crop and soil state, and
the deterministic domain services from Phases 4.7.1 through 4.7.8.

The causal step is:

`SimulationClock -> WeatherEngine -> Greenhouse/OpenField -> Phenology -> Radiation potential -> Water -> Nutrients -> Climate stress -> Radiation actual biomass -> maturity/harvest`

`step(dt_seconds)` advances the clock exactly once and executes that chain.
`register_scheduler_task()` lets `SimulationScheduler` advance the same clock
and invoke the chain at its task interval, without a second clock or real-time
timer. `step_at()` is the scheduler callback boundary.

The greenhouse reads crop LAI but never mutates biomass. Water, nutrients,
and climate produce independent factors. Radiation is the sole biomass
producer; actual growth receives their product as `limitation_factor`.

Snapshots expose simulation time, weather, transformed environment,
microclimate, crop state, soil state, potential/actual growth, combined factor,
and harvest state. Crop state serialization remains JSON-ready through its
existing `to_dict()` method.