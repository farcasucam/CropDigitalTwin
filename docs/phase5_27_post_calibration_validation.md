# Phase 5.27 - Independent Post-Calibration Validation

## Current result

The repository remains on the conservative branch:

```text
PHASE 5.27 COMPLETE
POST-CALIBRATION VALIDATION PIPELINE READY
VALIDATION NOT PERFORMED - INSUFFICIENT REAL DATA
NO SCIENTIFIC CALIBRATION AVAILABLE FOR VALIDATION
SYNTHETIC VALIDATION TESTS QUALIFIED AS SOFTWARE TESTS ONLY
REAL AGRICULTURAL DATA NOT VERIFIED
EXPERIMENTAL VALIDATION NOT CLAIMED
DATA ASSIMILATION NOT IMPLEMENTED
```

The Phase 5.26 artifact reports `calibration_performed=false` and no calibrated parameters. The source audit reports no `REAL_VERIFIED` dataset. Therefore no scientific post-calibration validation is executed.

## Relationship to Phase 5.26

Phase 5.26 selects parameters using a calibration dataset and must retain an independent holdout. Phase 5.27 consumes only the resulting frozen `ParameterSet` and evaluates it against independent observations. It never recalibrates or updates parameters.

## Reused architecture

`PostCalibrationValidationSuite` reuses:

- `RealValidationSuite` for source classification and the `REAL_VERIFIED` gate;
- the Phase 5.26 calibration report and parameter provenance;
- `ObservationDataset`, `ObservationComparator` and `calculate_metrics`;
- existing validation/alignment contracts when a real evaluation becomes possible;
- `ParameterSet` as an immutable input.

No second validation engine, metric engine, calibration system, clock, scheduler or crop model is introduced.

## Independence and leakage

`ValidationIndependence` records calibration and validation observation IDs, split method, reason, basis, overlap and duplicate timestamps. Any overlap or shared timestamp is marked non-independent and returns `DATA_LEAKAGE`. A real future execution must use a scientifically meaningful split such as cycle, plot, temporal period, campaign, environment or variety holdout, depending on the experimental design.

## Baseline versus calibrated evaluation

When the gate opens, both frozen baseline and calibrated parameter sets are evaluated against the same independent observations. Metrics are taken from the existing comparator: count, MAE, RMSE, bias, R2 and event error where applicable. Delta metrics remain descriptive; no universal scientific acceptance threshold is invented.

Synthetic fixtures can exercise this comparison as `SOFTWARE_TEST_ONLY`. They never produce a scientific validation claim. A calibration improvement followed by validation degradation emits `POTENTIAL_OVERFIT` as a diagnostic signal, not as proof of causal overfitting.

## Quality, units and context

Observation ingestion remains responsible for timezone, units and quality flags. Invalid, duplicate, missing, estimated or incompatible observations are not silently converted into valid scientific evidence. Crop, variety, plot, cycle, environment and stage context remain part of the canonical observation contract.

## Uncertainty and diagnostics

Synthetic uncertainty intervals are not experimental uncertainty. Structural model uncertainty remains unquantified unless a future protocol supplies evidence. Diagnostic and multilevel evaluation are only scientifically interpretable when independent real observations exist; the current report records them as unavailable rather than fabricating results.

## Artefacts

- `data/validation/post_calibration_validation_report.json`
- `data/validation/post_calibration_validation_README.md`
- `tests/test_post_calibration_validation.py`
- `manual_phase5_27_post_calibration_validation_test.py`

The post-calibration report is separate from the Phase 5.25 validation readiness report and excludes execution time, current timestamps and machine-specific paths from its scientific identity.
