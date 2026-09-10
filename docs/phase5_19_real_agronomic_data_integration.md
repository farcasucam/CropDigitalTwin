# Phase 5.19 — Real Agronomic Data Integration & Calibration Readiness

## 1. Objective

Move from `SYNTHETIC OBSERVATION CAMPAIGN` (Phase 5.18) toward
`REAL AGRONOMIC OBSERVATIONS`, without performing parameter calibration or
claiming experimental validation:

```
REAL DATA SOURCE
  -> AcquisitionRecord / Observation
  -> ObservationIngestion
  -> ObservationDataset
  -> TemporalAlignment
  -> ComparisonDataset
  -> ErrorDiagnostics
  -> ParameterIdentifiabilityAnalyzer
  -> Calibration Readiness Gate
```

## 2. Scientific decisions fixed by this phase

- The first real dataset does not need to be complete, homogeneous or
  perfectly documented to enter the pipeline. Discovering its limitations is
  part of the phase's purpose.
- All real sources (project files, CSV, Excel, manual field records, real
  sensors, public datasets, future external sources) converge on the same
  contract: `AcquisitionRecord -> ObservationIngestion -> ObservationDataset`.
  No per-source pipeline was created.
- Missing information is never invented. Variety, cycle, unit, uncertainty or
  measurement method that are not documented stay `None`/`UNKNOWN` — the
  existing `Observation` contract already supports this (`variety=None`,
  `cycle_id=None`, `environment="UNKNOWN"`, `uncertainty=None`,
  `measurement_method=None`).
- A real observation must retain at minimum `timestamp`, `variable`, `value`,
  `unit`, `source` (`provenance`); agronomic context (`plot_id`, `crop`,
  `variety`, `cycle_id`, `environment`, `stage`) is retained whenever
  available (unchanged `Observation` dataclass from Phase 5.8).

## 3. Architecture

One new module,
[`src/agri_twin/application/real_data_integration.py`](../src/agri_twin/application/real_data_integration.py),
adds a manifest/quality-report/readiness-gate layer. It introduces **no**
second observation, ingestion, alignment, diagnostics, identifiability,
registry, calibration or clock system — it only imports and composes:

- `ingest_rows` / `ObservationIngestionResult` / `ObservationDataset` (5.8, unchanged contract)
- `TemporalAlignment`, `compare_dataset`, `ComparisonDataset` (5.12, unchanged)
- `ErrorDiagnostics`, `diagnose` (5.13, unchanged)
- `ParameterIdentifiabilityAnalyzer`, `IdentifiabilityReport`, `IdentifiabilityStatus` (5.14, unchanged)
- `parameter_readiness`, `ParameterReadinessStatus` (5.8, unchanged — reused as the data-availability half of the readiness gate)
- `ParameterRegistry` (5.1, unchanged, read-only)

New types added by this phase:

- `RealDatasetManifest` — traceable metadata for one real dataset import (provenance, coverage, units, timezone/quality policy).
- `plot_registration_status(root, plot_id)` — `REGISTERED` / `EXTERNAL_UNREGISTERED` / `UNKNOWN` lookup against the existing farm catalog; never blocks ingestion, never mutates the catalog.
- `RealDataQualityReport` — deterministic, JSON-serializable quality summary (§7).
- `CalibrationReadinessRecord` / `CalibrationReadinessGate` — a conservative, read-only synthesis of existing identifiability + data-readiness outputs (§9).
- `RealDataAssessment` / `assess_real_dataset(...)` — orchestrates alignment (if a twin history is supplied), diagnostics, identifiability and the readiness gate for one ingested real dataset.

## 4. One architectural fix: deduplication now includes `cycle_id`

Phase 5.18 documented an existing limitation: `ObservationIngestion`
deduplicated by `(plot_id, variable, timestamp)`, so two concurrent cycles on
the same plot (e.g. `plot_A/cycle_1` and `plot_A/cycle_2` sharing a
timestamp) would be incorrectly flagged as duplicates. Phase 5.19 audited
this and fixed the key in
[`observation_ingestion.py`](../src/agri_twin/domain/observation_ingestion.py)
to `(plot_id, cycle_id, variable, timestamp)`. This is backward compatible:
datasets without `cycle_id` keep exactly their previous behaviour, because
`cycle_id` is then `None` for every observation and does not change how keys
compare. No second deduplication mechanism was introduced; regression tests
(`test_duplicate_still_detected_without_cycle_id`,
`test_deduplication_respects_cycle_id`) cover both cases, and the existing
`test_duplicate_is_not_overwritten` test continues to pass unchanged.

## 5. Units

Unit handling reuses the unchanged Phase 5.8 normalization
(`_canonical_unit`, `_normalize_value`, `CANONICAL_UNITS`). Both the
normalized and original unit are retained on every `Observation`
(`unit`/`unit_original`). Unambiguous, deterministic conversions (e.g.
`degF -> degC`, `%`/`fraction`) are applied; anything that cannot be
resolved unambiguously raises `UNIT_ERROR` in the ingestion QC — no new
conversion table or ambiguous heuristic was added.

## 6. Timestamps

Timezone-aware ISO-8601 is still required by the unchanged
`_timestamp()` helper; a naive timestamp is rejected (flagged, not
silently assumed to be local or UTC) and the observation is not ingested.
Accepted timestamps are normalized to UTC, matching `SimulationClock`,
`ObservationIngestion` and `TemporalAlignment` conventions already
established in earlier phases.

## 7. Real data quality report

`RealDataQualityReport` wraps the existing `DatasetReadiness`/`ObservationQC`
outputs (no second quality taxonomy) into one deterministic, serializable
structure: `total_records`, `valid_records`, `invalid_records`,
`duplicate_records`, `missing_records`, `unit_error_records`,
`out_of_range_records`, `temporal_issue_records`, plus plot/crop/variety/
cycle/environment/variable coverage and time coverage.

## 8. Provenance

`RealDatasetManifest.provenance` is fixed to `REAL_IMPORTED`; ingested
observations keep `source_type = measured_data` (`ObservationSourceType.MEASURED`,
unchanged enum). Sensor calibration (measurement device accuracy) and
crop-model parameter calibration are different concerns: this phase never
conflates a sensor's calibration certificate with a crop-model parameter
being "calibrated" — the two words are kept in clearly separate contracts
(`measurement_method`/`uncertainty` on `Observation` vs. `calibration_status`
on `ParameterRecord`).

## 9. Calibration readiness gate

`assess_calibration_readiness(registry, dataset, identifiability_report)`
combines, purely by reading their existing outputs:

- `ParameterIdentifiabilityAnalyzer` status per parameter (`IDENTIFIABLE`,
  `CANDIDATE`, `CONFOUNDED`, `INSUFFICIENT_DATA`, ...) — unchanged logic;
- `parameter_readiness(registry, dataset)` per-parameter data availability
  (`NOT_READY`, `CANDIDATE`, `READY_FOR_CALIBRATION`) — unchanged logic,
  reused directly instead of duplicated.

A parameter's gate is `READY_FOR_CALIBRATION` only if it is
`IDENTIFIABLE`, has `READY_FOR_CALIBRATION` data readiness, and has **no**
confounders. Otherwise it is `NOT_READY`. `READY_FOR_CALIBRATION` means only
*"there is enough evidence to study a future calibration attempt"* — it does
not mean the model is calibrated or validated. No numeric threshold
(observation count, coverage percentage, RMSE bound) is invented;
`CalibrationReadinessGate.threshold_policy` is explicitly `"TO_BE_DEFINED"`.

## 10. What this phase has explicitly NOT done

```
CALIBRATION NOT PERFORMED
DATA ASSIMILATION NOT IMPLEMENTED
EXPERIMENTAL VALIDATION NOT CLAIMED
```

`real_data_integration.py` never imports or calls `GridSearchCalibrator`, any
optimizer, or any parameter-fitting routine. `TwinState`/`TwinSnapshot` are
never written from observations — `assess_real_dataset` only calls the
existing read-only `compare_dataset` (`TwinState -> Observation`, never the
reverse). `ParameterRegistry` is read-only throughout
(`test_parameter_registry_not_mutated`).

## 11. Future calibration procedure (not implemented here)

Once real, independent observations accumulate for a given
crop/variety/plot/parameter and its gate reaches `READY_FOR_CALIBRATION`,
a future phase can:

1. reserve a held-out validation subset (never used for fitting);
2. run `GridSearchCalibrator` (Phase 5.2) only on parameters that passed the
   gate;
3. run `ValidationEngine` (Phase 5.3) against the held-out subset;
4. only then consider claiming experimental validation, and only for the
   specific crop/variety/plot/parameter combination that was actually
   validated — never for the whole model.

## 12. Known limitations

- No verified real agronomic dataset exists in this repository yet; the
  manual acceptance test uses a small, explicitly-labeled illustrative
  example (`"illustrative example only; not a verified scientific field
  dataset"`), never presented as validated field data.
- The readiness gate's binary `NOT_READY`/`READY_FOR_CALIBRATION` outcome
  is deliberately coarse; refining it (e.g. per-environment or per-stage
  gates) is left to a future phase once real data volume justifies it.
