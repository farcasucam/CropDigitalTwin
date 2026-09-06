# Phase 5.4 Reproducible Agronomic Scenarios

## Purpose and scope

`Scenario` and `ScenarioRunner` provide a controlled experimental layer over
the existing `CropDigitalTwinOrchestrator`. Scenarios define crop/variety,
period, resolution, initial crop/soil state, weather baseline, greenhouse
mode, events, parameters, labels and classification. They do not add new
physics or calibration logic.

Every new delivery scenario is labelled `SYNTHETIC SCENARIO` and
`NOT SCIENTIFIC VALIDATION`. A synthetic response verifies software
coherence, stability and causal wiring only; it is not an observed experiment
or agronomic validation result.

## Events and reproducibility

`ScenarioEvent` records ID, type, start, end, intensity and parameters. The
current runner supports warm/heatwave, cold/frost, dry/drought, wet, VPD,
radiation, irrigation, fertilization, shade, heating, cooling, ventilation,
CO2 and misting inputs where existing engines support them. Actuators affect
microclimate or management inputs, never biomass directly.

The scenario hash is a canonical SHA-256 of all relevant configuration:
period, resolution, crop state, soil, weather, mode, seed, events and
parameter values. The runner advances only the injected `SimulationClock` and
uses no real-time calls, sleeps, global random state or hidden timers.

## Scenario matrix

The matrix is configuration data, not a hard-coded branch in the model. It
can express baseline, warm, cold, heat wave, frost, dry, wet, high VPD, low or
high radiation, water deficit/recovery, nutrient/fertilization, greenhouse,
shade, HVAC, and combined heat+drought/VPD/radiation events. Events preserve
their duration and intensity in `ScenarioResult`.

`compare_scenarios()` calculates available deltas for final biomass, LAI,
water stress, heat stress and maturity. Results export to the existing Phase
5.3 `ObservationDataset`/`SimulationPoint` contracts. Metrics are not
duplicated. `sweep_scenarios()` supports deterministic parameter collections
for future sensitivity analysis.

## Outdoor and greenhouse

`greenhouse_mode="outdoor"` uses the existing bypass. Passive and actuated
greenhouse modes flow through the existing microclimate engine. The scenario
layer only supplies modes and actuator events; it does not implement CFD,
greenhouse energy equations, or new physiological parameters.

## Integration boundaries

Scenario parameters can carry the Phase 5.2 `ParameterSet`, and scenario
outputs can become Phase 5.3 observations/test datasets. No automatic
calibration is performed. No historical, observational, validation or
calibration claim is inferred from a scenario kind.

## Limitations

`synthetic scenario != observed experiment` and `scenario response != validated
biological response`. Thresholds and baseline values remain those of existing
Phase 4 engines. Independent field/greenhouse observations are required to
validate quantitative responses. Advanced sensitivity statistics,
uncertainty propagation and real-data scenario ingestion remain future work.

## Verification

The unit and integration tests are in `tests/test_scenarios.py`; the delivery
audit is `manual_phase5_4_scenarios_test.py`. The audit explicitly reports
synthetic-only status and tests baseline, combined stress, sweep, validation
export and absence of real-time dependencies.