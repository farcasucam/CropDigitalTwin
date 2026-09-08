# Phase 5.8: real observation data readiness and ingestion

## 1. Objective

Phase 5.8 prepares a traceable bridge from external observations to the
existing `ObservationDataset`, calibration, and validation contracts. It does
not calibrate, validate experimentally, alter equations, or invent data.

## 2. Initial commit and baseline

The audit started at `59785c39cbfdf3de3b967913fcb74326e3381c7d`. The worktree was
already dirty from the previous scientific audit (`docs/phase5_x*`, `PHASES.md`,
registry changes, and generated `.pyc` artifacts). Baseline was **450 passed,
0 failed, 12 skipped** in 7.16 seconds. `git diff --check` passed.

## 3. Observation contract

The existing `Observation` and `ObservationDataset` classes remain the single
contract. `Observation` now supports optional dataset ID, source type, plot,
crop, variety, environment, measurement method, original unit, and duration
fields while preserving existing constructor compatibility. Ingestion requires
`timestamp`, `variable`, `value`, `unit`, and non-empty `source`.

The dataset retains its existing `DatasetRole` (`CALIBRATION`, `VALIDATION`, or
`TEST`) and adds provenance metadata. It can therefore feed `CalibrationCase`
and `ValidationCase` without a parallel observation system.

## 4. Forcing versus observation

`WeatherState` and weather CSVs are model forcing. They are never automatically
converted to observations. The ingestion API rejects `ObservationSourceType.FORCING`.
A sensor export may only be an observation when its role and independence are
explicitly classified. Derived variables, such as VPD calculated from forcing
temperature and RH, must be marked `derived` and must not be treated as
independent validation evidence.

## 5. Variables

The controlled observable catalog includes the requested phenology, LAI,
biomass, canopy, water, microclimate, CO2, and production variables. The
catalog describes possible observables; it does not claim that every variable
is simulated or scientifically validated.

## 6. Units

The importer normalizes only explicit, supported conversions: Fahrenheit to
Celsius, RH fraction to percent, percent VWC to fraction, micromolar PAR to
mol PAR, kg/m2 biomass to g/m2, and t/ha yield to kg/m2. Canonical units are
stored in `Observation.unit`; `unit_original` preserves the input. Unknown or
incompatible units produce `UNIT_ERROR`. No conversion is silent.

## 7. Temporal semantics and timezone

Timestamps must contain a timezone and are normalized to UTC. No wall-clock
value is assigned during import. `ObservationResolution` distinguishes instant,
hourly, subhourly, daily, weekly, and event records. Duration is optional and
explicit. Cumulative variables such as irrigation and yield are catalogued with
their own units and are not silently interpreted as instantaneous rates.

## 8. Quality control, missing values, and duplicates

Quality flags are `VALID`, `MISSING`, `INVALID`, `SUSPECT`, `ESTIMATED`,
`DUPLICATE`, `OUT_OF_RANGE`, and `UNIT_ERROR`. The importer recognizes empty,
NA, N/A, null, None, -999, and 9999 as missing values. Numeric finiteness and
basic physically defensible non-negative/range checks are applied. Duplicate
keys are `(plot_id, variable, timestamp)` and are reported, never averaged or
overwritten.

`ESTIMATED` remains distinguishable from measured data. No imputation is
performed.

## 9. Provenance and agronomic linkage

Every ingested row carries source, source type, dataset ID, original filename,
original/normalized units, and measurement method when supplied. Plot, crop,
variety, and environment are explicit fields. Variety is never inferred from a
filename. Missing plot linkage is retained as missing and affects readiness.
Environments are `OUTDOOR`, `GREENHOUSE`, or `UNKNOWN`.
The importer accepts an explicit timezone-aware `imported_at`; it never fills
that field from `datetime.now()`. Observation timestamps remain acquisition
timestamps from the input.

`plot_readiness()` reports only explicitly linked plots, their crop/variety/
environment, coverage, variables, and quality. A configured `Plot` with no
observation rows is not included as evidence.

## 10. Dataset readiness

`DatasetReadiness` reports `READY`, `PARTIAL`, `INSUFFICIENT_DATA`, or `INVALID`
and counts total, valid, invalid, missing, duplicate, variables, plots, crops,
varieties, and temporal coverage. A dataset with only invalid/missing rows does
not create a fake non-empty `ObservationDataset`.

## 11. Parameter readiness

`parameter_readiness()` reuses `ParameterRegistry` records and performs only a
screening diagnostic. It reports parameter ID, required/available observables,
valid count, temporal/spatial coverage, an explicit identifiability limitation,
and `NOT_READY`, `CANDIDATE`, or `READY_FOR_CALIBRATION`. `READY_FOR_CALIBRATION`
means data-contract readiness only; no fitting is performed and no parameter is
marked calibrated.

## 12. Crop/variety readiness

The current summary covers tomato/RAF, lettuce, pepper/Lamuyo, grape/Monastrell,
peach, plum/Suplum 26, and apple. It counts only ingested rows with explicit
linkage. Literature evidence, configured plots, and weather forcing do not
count as real agronomic observations.

## 13. Calibration/validation integration

`ingest_csv()` and `ingest_json()` return the existing `ObservationDataset`,
which can be passed to `CalibrationCase` when role is `CALIBRATION` or to
`ValidationCase` when role is `VALIDATION`. Existing separation rules remain in
force. Ingestion never invokes a calibrator or validation runner.

## 14. Schema and importer

The minimum row schema is [observation_dataset.schema.json](../schemas/observation_dataset.schema.json).
The deterministic importer is in `agri_twin.domain.observation_ingestion` and
supports CSV and JSON lists/`observations` payloads. It does not mutate the
model, registry, clock, scheduler, or global configuration.

## 15. Synthetic policy and current real-data status

Tests and the manual use clearly labelled `synthetic_test_data`. No synthetic
row is represented as measured data. The repository contains weather forcing
files and literature/evidence tables, but no real agronomic observation dataset.

**REAL AGRONOMIC OBSERVATIONS AVAILABLE: NO / INSUFFICIENT**

## 16. Limitations

This phase does not perform sensor fusion, imputation, database/API ingestion,
uncertainty propagation, independentness inference, psychrometric derivation,
advanced event reconciliation, or calibration. Derived observations remain
potentially circular if built from forcing and must be excluded from independent
claims.

## 17. Tests and manual verification

Focused tests are in `tests/test_observation_ingestion.py`. The manual is
`manual_phase5_8_real_observation_ingestion_test.py` and prints provenance,
normalization, QC, duplicates, missing data, linkage, readiness, and conceptual
calibration/validation compatibility with the explicit disclaimer:
`SYNTHETIC DATASET — DEMONSTRATION ONLY`.

## 18. Scientific status

The ingestion pipeline is ready for controlled data arrival. Its existence does
not imply real data availability, calibration, or experimental validation.

**OBSERVATION INGESTION PIPELINE READY — CALIBRATION NOT PERFORMED — EXPERIMENTAL VALIDATION NOT CLAIMED**
