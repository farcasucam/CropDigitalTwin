# Phase 5.20 — Scientific Readiness Gate & Synthetic Benchmarking

## Purpose

Phase 5.20 adds a reproducible scientific-readiness assessment around the
existing Phase 5.1-5.19 architecture. It answers whether the software is
prepared to receive real agronomic observations without converting synthetic
software evidence into scientific claims.

The central contract is
[`ScientificReadinessGate`](../src/agri_twin/application/scientific_readiness.py).
It composes, rather than replaces, `ParameterRegistry`,
`ParameterIdentifiabilityAnalyzer`, `ExperimentalObservationPlan`,
instrumentation, `SyntheticObservationCampaign`, observation ingestion,
`TwinState`, `TemporalAlignment`, and `ErrorDiagnostics`.

## Three separate meanings of readiness

| Concept | Meaning in Phase 5.20 |
|---|---|
| `SOFTWARE_READY` | The existing component contracts and synthetic integration benchmarks execute successfully. |
| `DATA_READY` | A sufficiently structured dataset exists for the particular assessment. Current status: `INSUFFICIENT_DATA`; no verified real dataset is present. |
| `SCIENTIFICALLY_VALIDATED` | Independent experimental evidence supports a scientific claim. Current status: `SCIENTIFIC_VALIDATION_REQUIRED`. |

The current global state is therefore:

```
SOFTWARE_READY = true
DATA_READY = insufficient_data
REAL_AGRONOMIC_DATA_VERIFIED = false
CALIBRATION = blocked
EXPERIMENTAL_VALIDATION = blocked/required
DATA_ASSIMILATION = not implemented
```

`ScientificReadinessStatus` is the single status enum for this layer:
`NOT_ASSESSED`, `READY`, `PARTIAL`, `BLOCKED`, `INSUFFICIENT_DATA`,
`NOT_APPLICABLE`, and `SCIENTIFIC_VALIDATION_REQUIRED`.

## Evidence and provenance

The report distinguishes evidence categories already present in the project:
`PROJECT_DATA`, `MEASURED_DATA`, `LITERATURE`, `SYNTHETIC`,
`ENGINEERING_DEFAULT`, and `CALIBRATED`. The report explicitly records
synthetic benchmark evidence as `SYNTHETIC`; it cannot be used to claim
measured or experimental evidence. Engineering defaults remain engineering
defaults, and literature evidence is not local calibration.

No verified real agronomic field or greenhouse dataset is currently present.
The files under `data/synthetic`, `data/templates`, and `data/weather` are not
classified as verified agronomic observations by this gate.

## Components assessed

The report contains component results for:

- mechanistic model: crop growth, radiation/APAR/RUE, LAI, water, VPD,
  radiation, nutrients, CO2, stress, damage, senescence and maturity contracts;
- phenology: engine and annual/perennial scopes, with local calibration and
  validation still blocked by missing verified observations;
- greenhouse: simplified physical model and crop-greenhouse feedback contract;
  EnergyPlus remains optional and is not a validation oracle;
- observations: ingestion, timezone/unit/provenance/context/quality,
  alignment, comparisons and diagnostics;
- instrumentation: simulated acquisition and future-real adapter contract;
- identifiability: the existing analyzer, with synthetic-only conservatism.

The readiness layer does not create a second subsystem for any of these areas.

## Synthetic benchmark suite

`SyntheticBenchmarkSuite` runs ten software-only benchmarks through the
existing `SyntheticObservationCampaign`:

1. determinism with equal configuration, seed and clock authority;
2. temporal consistency and snapshot creation;
3. multi-plot state isolation;
4. lettuce `cycle_1`/`cycle_2` isolation;
5. perennial crop/cycle representation for grape, peach, plum and apple;
6. greenhouse physical/feedback contract availability without mandatory EnergyPlus;
7. missing, duplicate, invalid, out-of-range and unit-error propagation;
8. controlled synthetic bias recovery by existing MAE/RMSE/bias diagnostics;
9. conservative synthetic-only identifiability;
10. simulated backend versus future-real adapter contract substitution.

A `PASS` means software behavior was exercised. It never means biological
correctness, prediction accuracy, calibration, generalization or experimental
validation. No scientific acceptance threshold is invented; metric thresholds
are explicitly `THRESHOLD_NOT_DEFINED`.

The seven project crops and established varieties are represented without
inventing varieties:

- tomato / RAF;
- lettuce / generic, including two independent cycles;
- pepper / Lamuyo;
- grape / Monastrell;
- peach / generic;
- plum / Suplum 26;
- apple / generic.

Both `OUTDOOR` and `GREENHOUSE` are covered.

## Parameters and observations

`parameter_results` preserves each analyzer assessment: parameter id,
identifiability status, calibration permission, required observations, linked
observables, confounders, data availability and scientific blockers. Synthetic
observations never promote a parameter to `IDENTIFIABLE`.

`observable_results`, crop results and environment results are report metadata,
not new observation or physiology contracts. Experimental observation planning
continues to be provided by `ExperimentalObservationPlan`.

## Calibration and validation gates

The report sets:

```
CALIBRATION_BLOCKED: REAL_AGRONOMIC_DATA_NOT_AVAILABLE
SCIENTIFIC_VALIDATION_REQUIRED
```

No optimizer, parameter fitting, `GridSearchCalibrator`, data assimilation or
state correction is called. The existing `CalibrationReadinessGate` from
Phase 5.19 remains the parameter-level gate; this phase adds only the global
readiness view. A future real dataset must first pass ingestion, quality,
context, temporal alignment and identifiability assessment. Only then may a
future phase study calibration with an independent holdout reserved for
validation.

`TwinState` and `TwinSnapshot` are comparison inputs only. Observations never
write back into them.

## Greenhouse and optional dependencies

The simplified greenhouse physical model and crop-feedback contracts are
software-ready. EnergyPlus/eppy are optional and may be `AVAILABLE` or
`UNAVAILABLE` depending on the environment. Their availability does not make
the crop model scientifically validated, and Phase 5.20 does not require them.

## Limitations and future real dataset requirements

A future dataset should provide, where available: source and file/record
reference, timestamp with explicit timezone, variable, value, original unit,
plot/crop/variety/cycle/environment, stage, method, sensor/device metadata,
uncertainty and quality. Missing fields remain unknown; no imputation,
smoothing, sensor fusion, outlier correction or interpolation is performed.

The future path is:

```
verified real data
  -> quality-controlled ingestion
  -> temporal/context alignment
  -> diagnostics
  -> identifiability and confounder assessment
  -> calibration readiness
  -> calibration (future phase)
  -> independent validation (future phase)
```

The following claims are not permitted in Phase 5.20:

```
MODEL VALIDATED
MODEL CALIBRATED
PREDICTIONS SCIENTIFICALLY VALIDATED
SYNTHETIC DATA ARE EXPERIMENTAL DATA
```

The correct conclusion is:

```
SOFTWARE READY
SYNTHETIC BENCHMARKS QUALIFIED
REAL AGRONOMIC DATA NOT VERIFIED
CALIBRATION NOT PERFORMED
EXPERIMENTAL VALIDATION NOT CLAIMED
DATA ASSIMILATION NOT IMPLEMENTED
```
