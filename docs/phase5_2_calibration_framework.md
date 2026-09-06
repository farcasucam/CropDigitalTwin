# Phase 5.2 Calibration Framework

## Scope

This phase provides reproducible infrastructure to answer: “which permitted
parameters best reproduce a dataset?” It does not claim scientific
calibration, does not invent observations, and does not change the crop
physics. The framework is independent from `CropDigitalTwinOrchestrator` and
accepts a runner adapter, so the same contracts can later execute the real
digital twin.

## Contracts

`CalibrationCase` identifies crop, variety, plot, timezone-aware period,
calibration dataset, optional separate validation dataset, `ParameterSet`,
model name, configuration version and initial state.

`Observation` stores timezone-aware timestamp, variable, value, unit,
uncertainty, source, quality, resolution and observation type. Resolutions are
`instant`, `hourly`, `subhourly`, `daily`, `weekly`, and `event`. The
comparator matches daily observations by calendar day, weekly observations by
the surrounding week, and events by date semantics rather than exact hour.

`ParameterSet.from_registry()` selects only records allowed by the Phase 5.1
registry and carrying explicit numeric ranges. It can filter crop, variety,
stage and subsystem. It never creates a second parameter authority.

## Comparison and metrics

`ObservationComparator` produces timestamp, variable, observed, simulated,
residual, absolute error and uncertainty. Missing/out-of-period or unit-
incompatible values produce a record without a numeric residual. Continuous
metrics are MAE, RMSE, bias and R2 when variance permits. Phenological events
use absolute error in days and are not treated as continuous series.

`CalibrationObjective` combines variable metrics with explicit weights and
optional normalizers. Normalization prevents variables with large units from
dominating the objective.

## Simulation and Grid Search

`FunctionSimulationRunner` is the minimal adapter for deterministic synthetic
or future model functions. `ClockSimulationRunner` demonstrates execution
under an injected `SimulationClock`; it never uses wall-clock time. A future
adapter can call `CropDigitalTwinOrchestrator.step_at()` and map snapshots to
`SimulationPoint` values.

`GridSearchCalibrator` explores inclusive min/max ranges at explicit steps,
honours maximum evaluations and optional target-score stopping, and returns a
deterministic `CalibrationResult`. Empty parameter sets return
`INSUFFICIENT_DATA`; invalid setup raises `CalibrationError`. A validation
dataset is never automatically reused as calibration data, and validation
metrics are stored separately when supplied.

## Predictive-model boundary

`PredictionModel` defines future `fit`, `predict`, and `evaluate` contracts,
including target, past covariates, future covariates, timestamps, frequency
and horizon. It is intentionally abstract. Statistical, ML, foundation time
series, and hybrid adapters can implement it later without changing the
mechanistic simulator.

TimesFM is not a dependency, has no downloaded weights, and is not executed in
this phase. A later optional adapter may compare TimesFM with the mechanistic
model and statistical baselines using the same observations and metrics. A
future hybrid can forecast `observed - digital_twin` residuals, but ML must not
modify physiological parameters without an independent calibration protocol.

## Uncertainty and limitations

Observation uncertainty is stored and propagated to comparison records;
parameter, weather, model, and forecast uncertainty remain separate future
extensions. No real agronomic dataset is included here, so synthetic recovery
tests validate only framework mechanics, not tomato, lettuce, pepper, grape,
peach, plum, or apple scientific calibration.

## Verification

Unit tests are in `tests/test_calibration_framework.py`. The delivery audit is
`manual_phase5_2_calibration_test.py`. Full regression is run independently;
the framework is reproducible and ready for Phase 5.3+, but it is not a
scientific validation result.