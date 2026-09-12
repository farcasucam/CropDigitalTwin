# Phase 5.26 - Conditional Scientific Calibration and Overfitting Control

## Result

The current repository follows the no-real-data branch of this phase:

```text
PHASE 5.26 COMPLETE
CALIBRATION PIPELINE READY
CALIBRATION NOT PERFORMED - INSUFFICIENT REAL DATA
SYNTHETIC CALIBRATION TESTS QUALIFIED AS SOFTWARE TESTS ONLY
REAL AGRONOMIC DATA NOT VERIFIED
EXPERIMENTAL VALIDATION NOT CLAIMED
DATA ASSIMILATION NOT IMPLEMENTED
```

No parameter was scientifically calibrated and no registry value was changed.

## Reused calibration architecture

`ScientificCalibrationSuite` is a readiness and transaction layer around the existing contracts:

- `ParameterRegistry` and `ParameterSet` remain the single parameter authority;
- `CalibrationCase`, `CalibrationObjective`, `ObservationComparator` and `GridSearchCalibrator` remain the calibration implementation;
- `RealValidationSuite` supplies source classification and the `REAL_VERIFIED` gate;
- `ParameterIdentifiabilityAnalyzer` supplies identifiability and confounder status;
- `ParameterSensitivityAnalyzer` is used only as an auxiliary audit signal;
- `ObservationDataset` and explicit calibration/holdout datasets remain the observation contract.

No second calibrator, registry, observation path, clock, scheduler or model engine is introduced.

## Data audit

The Phase 5.25 audit is reused. Current files classify as synthetic, simulated real-data substitute, forcing, literature, template or unknown. No `REAL_VERIFIED` source exists. Weather and forecast data remain forcing and cannot be used as independent crop-response observations. Synthetic fixtures are labelled `SYNTHETIC_SOFTWARE_TEST`.

## Readiness gate

Scientific calibration requires all of the following:

- at least one `REAL_VERIFIED` source;
- a measured-data observation dataset;
- an independent holdout with no observation-ID overlap;
- parameters allowed by the registry and bounded by traceable limits;
- identifiability status `CANDIDATE` or `IDENTIFIABLE`;
- no unresolved blocking confounder.

Without these conditions the result is `NOT_PERFORMED` with `INSUFFICIENT_DATA` and no calibrated `ParameterSet`.

## Parameter and sensitivity audit

Candidates are derived from the existing registry. The audit records unit, bounds, source and identifiability metadata indirectly through `CalibrationParameterAudit`. Parameters with `calibration_allowed=false`, missing bounds, `FIXED`, `NOT_CALIBRATABLE`, `INSUFFICIENT_DATA` or `CONFOUNDED` status are rejected. Sensitivity is informative only; it does not establish calibratability or causality.

## Calibration and holdout split

`CalibrationSplit` records observation IDs, split method, reason and overlap. A missing or overlapping holdout produces `NO_INDEPENDENT_HOLDOUT`. The current no-real-data branch does not create a scientific split. Independent validation interpretation remains reserved for Phase 5.27.

## Algorithm and transactionality

When the gate eventually opens, the suite passes a scoped immutable `ParameterSet` to the existing deterministic `GridSearchCalibrator`. Candidate evaluations use copies returned by `with_values`; the registry and original parameter set are never mutated. Bounds are enforced by `CalibrationParameter`. A failed evaluation returns a result without committing global state.

The software fixture helper can exercise the existing grid search using explicitly synthetic data. Its output is software-test evidence only and is never written as scientific calibration.

## Artefact

- `data/calibration/calibration_report.json`
- `data/calibration/README.md`

The report is deterministic and contains source audit, readiness, parameter candidates/rejections, identifiability, confounders, split, objective and calibrated-parameter lists. In the current state `calibration_performed=false` and `parameters_calibrated=[]`.

## Limitations

- No `REAL_VERIFIED` agronomic observations are available.
- No scientific calibration or biological parameter claim is made.
- No independent validation is performed; it belongs to Phase 5.27.
- No universal objective thresholds or scientific weights are invented.
- Synthetic grid-search outputs demonstrate software mechanics only.
