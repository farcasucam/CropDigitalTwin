# Phase 5.3 Scientific Validation and Benchmarking

## Purpose

This phase evaluates how closely a simulation or prediction reproduces
independent observations. It is deliberately separate from Phase 5.2
calibration: calibration fits permitted parameters, while validation evaluates
an already selected parameter set against data it did not use.

`ValidationCase` records crop, variety, plot, period, dataset, parameters,
model/version, variables, resolution, alignment policy, period/stage labels,
and experiment ID. `ValidationResult` records status, metrics, warnings,
missing data, event errors, limitations, policy and independence.

`DatasetRole.CALIBRATION` cannot be used to construct a validation case. This
prevents accidental reuse. If an in-sample evaluation is needed for diagnostic
purposes, it must be represented explicitly outside independent validation and
reported as `IN_SAMPLE_ONLY`, never as scientific validation.

## Alignment and missing data

`ValidationComparator` supports `exact`, `same_day`, `nearest`,
`aggregation_window`, and `event` policies. The selected policy is stored in
the result. No interpolation or imputation occurs by default. Missing
simulation matches, duplicate observations, and unit incompatibilities become
warnings or missing comparison records rather than silently fabricated values.

Observation resolution remains explicit: hourly/subhourly data preserve
timestamps, daily data can use calendar-day matching, weekly data remains a
distinct resolution, and phenological events are compared as dates.

## Metrics

Continuous variables reuse the Phase 5.2 metric structures: MAE, RMSE, bias,
and R2 only when observed variance is non-zero. Event variables are retained as
`event_errors_days` and are not converted into artificial continuous series.
Observation uncertainty is preserved in comparison records for future weighted
metrics. Acceptance criteria are not universal: temperature, LAI, biomass,
flowering date, stress, and yield require variable/crop/application-specific
thresholds supplied by a scientific protocol.

The current result includes whole-period metrics and a period mapping, and is
ready for stage and stress-period slices once observations carry those labels.

## Benchmarking and baselines

`BenchmarkEngine` evaluates multiple runners against the same immutable dataset
and ranks them by mean available RMSE. `PersistenceBaseline` provides a simple
reference adapter. A low error is meaningful only in comparison with an
appropriate baseline and independent data.

The same interfaces can later compare the mechanistic Digital Twin,
statistical models, ML models, foundation time-series models, and hybrid
models. TimesFM is not installed, downloaded, or executed here. A future
`TimesFMAdapter` must use the same dataset, horizon, targets, covariates,
resolution, and metrics, while remaining outside the mechanistic core.

## Simulation, forecasting, and uncertainty

Simulation asks how the crop evolves under supplied conditions. Forecasting
asks what will be observed in the future. Validation asks how close either was
to observations. These operations must not be conflated. The framework stores
observation uncertainty; parameter, weather, model, and forecast uncertainty
remain separate future extensions.

No random cross-validation is implemented. Future splits must respect season,
plot, variety, and temporal order to avoid leakage. Synthetic tests validate
framework mechanics only; they are not agronomic evidence. Local independent
datasets are required before claiming scientific validation of any crop or
variety.

## Verification

Unit and integration tests are in `tests/test_validation_framework.py`. The
delivery audit is `manual_phase5_3_validation_test.py`. The complete suite is
run after implementation. The outcome “framework ready” must never be read as
“crop model scientifically validated”.