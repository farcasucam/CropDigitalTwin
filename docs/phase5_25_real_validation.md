# Phase 5.25 - Real Validation Readiness and Out-of-Sample Evaluation

## Result

The repository currently follows Case B of this phase:

```text
PHASE 5.25 COMPLETE
REAL VALIDATION FRAMEWORK READY
VALIDATION PIPELINE QUALIFIED ON SYNTHETIC FIXTURES
REAL AGRONOMIC DATA NOT VERIFIED
INSUFFICIENT REAL DATA FOR SCIENTIFIC VALIDATION
CALIBRATION NOT PERFORMED
EXPERIMENTAL VALIDATION NOT CLAIMED
DATA ASSIMILATION NOT IMPLEMENTED
```

No file in the audited project provides sufficient verified origin, experimental context, plot/cycle linkage, measurement method and independent agronomic response observations to be classified `REAL_VERIFIED`.

## Architecture

`RealValidationSuite` is a readiness and orchestration adapter. It reuses:

- `ObservationIngestion` and `ObservationDataset` for the canonical observation contract and QC;
- `ValidationCase` and `ValidationEngine` for validation semantics and existing metrics;
- `TemporalAlignment`/alignment policies through `ValidationCase.alignment`;
- `ScientificReadinessGate` for the existing global readiness state;
- `ParameterRegistry` without mutation;
- existing TwinState/alignment/diagnostics contracts when an actual simulation/observation comparison is supplied.

It does not create a second validation engine, observation dataset, clock, scheduler, metric implementation or calibration path.

## Data audit

The audit classifies files by evidence rather than filename:

- `SIMULATED_REAL_DATA_SUBSTITUTE`: `data/synthetic_real_substitute`, explicit substitute manifest;
- `SYNTHETIC`: `data/synthetic/phase5_9` and synthetic campaign/reference outputs;
- `FORCING`: weather/forecast files and Open-Meteo forecast metadata;
- `LITERATURE`: phenology evidence with source/DOI/URL metadata;
- `UNKNOWN`: templates and configuration files;
- `REAL_VERIFIED`: no source found.

Weather and forecast records remain forcing. They are not independent crop-response observations.

## Ingestion and quality

A real dataset must enter through `ObservationIngestion`. Timezone, canonical units, missing values, duplicate keys, invalid values, estimated values and out-of-range values remain visible in QC. Ambiguous units and timestamps are rejected or marked with the existing error flags; no silent imputation or correction is performed.

Synthetic fixtures in `tests/test_real_validation.py` use `ObservationSourceType.SYNTHETIC_TEST` and are never promoted to real evidence.

## Out-of-sample protocol

The result contract records `IN_SAMPLE`, `OUT_OF_SAMPLE`, `TEMPORAL_HOLDOUT`, `CYCLE_HOLDOUT`, `PLOT_HOLDOUT`, `VARIETY_HOLDOUT` or `ENVIRONMENT_HOLDOUT`. A future real execution must construct separate datasets and avoid using future observations to build the validation initial state. With the current repository, no real split can be executed because no `REAL_VERIFIED` dataset exists.

## Metrics and uncertainty

When observations and simulations are available, the existing validation metrics are retained. Baseline comparison, ensemble interval coverage and sensitivity interpretation must remain separate from causal claims. Reproducible synthetic fixtures demonstrate the pipeline only; they do not establish biological validity or scientifically valid prediction intervals.

## Artifacts

- `data/validation/validation_report.json`
- `data/validation/README.md`
- `manual_phase5_25_real_validation_test.py`

The report contains source classifications, readiness, synthetic fixture status, quality/split/alignment fields when a fixture is evaluated, hashes and limitations. Hashes exclude execution duration and wall-clock values.
