# Phase 5.18 — Synthetic Observation Campaign & Scientific Pipeline Qualification

## 1. Objective

Execute and qualify, end-to-end and exclusively with synthetic data, the full
scientific observation pipeline built across Phases 5.8-5.17:

```
ParameterRegistry
  -> ParameterIdentifiabilityAnalyzer
  -> ExperimentalObservationPlan
  -> InstrumentationSpecification
  -> SimulatedAcquisitionBackend
  -> AcquisitionRecord
  -> ObservationIngestion
  -> ObservationDataset
  -> TemporalAlignment
  -> ComparisonDataset
  -> ErrorDiagnostics
  -> ParameterIdentifiabilityAnalyzer (re-evaluation)
  -> CampaignQualityReport
```

This phase does **not** perform parameter calibration, does **not** perform
data assimilation, and does **not** claim experimental validation of the
model. It demonstrates that the software architecture works correctly end to
end, so that synthetic data can later be replaced by real observations
without changing the pipeline.

## 2. Architecture

A single new module, [`src/agri_twin/application/synthetic_campaign.py`](../src/agri_twin/application/synthetic_campaign.py),
adds a **campaign/qualification orchestration layer**. It introduces no
second `ObservationDataset`, `AcquisitionBackend`, `TemporalAlignment`,
`ErrorDiagnostics`, `ParameterRegistry`, `SimulationClock`/`SimulationScheduler`,
calibration framework or `TwinState` system. It only imports and coordinates
the existing ones:

- `ParameterRegistry.from_repository`, `ParameterIdentifiabilityAnalyzer` (5.1, 5.14)
- `ExperimentalObservationPlan` (5.15)
- `InstrumentationSpecification`, `SimulatedAcquisitionBackend`, `AcquisitionRecord`,
  `FakeExternalSensorSource`, `FutureRealAcquisitionAdapter` (5.16, 5.17)
- `ingest_rows` / `ObservationIngestionResult` / `ObservationDataset` (5.8)
- `InMemoryTwinStateRepository`, `TwinState`, `TwinSnapshot` (5.11)
- `TemporalAlignment`, `compare_dataset`, `ComparisonDataset` (5.12)
- `ErrorDiagnostics`, `diagnose` (5.13)

New types added by this phase:

- `CampaignCropSpec` — one synthetic plot/cycle scope (crop, variety, environment, cycle type, stage, variables).
- `CampaignConfiguration` — fully deterministic campaign inputs (seed, window, interval, crops, faults, alignment policy, controlled-defect knobs) with a `config_hash()`.
- `SyntheticObservationCampaign` — orchestrates the pipeline via `run()`.
- `CampaignResult` — raw pipeline artifacts (plan, specifications, acquisition records, ingestion result, twin repository, comparison, diagnostics, before/after identifiability, report).
- `CampaignQualityReport` — JSON-serializable, deterministic summary (see §7).
- `campaigns_are_deterministic(a, b)` — reproducibility check reusing the campaign's own `config_hash()` plus equality of downstream artifacts.

## 3. End-to-end flow

`SyntheticObservationCampaign.run()`:

1. Builds a `ParameterRegistry` from the repository and runs `ParameterIdentifiabilityAnalyzer.analyze_all()` (before).
2. Builds an `ExperimentalObservationPlan` from that report.
3. Resolves `InstrumentationSpecification` objects per crop/plot/cycle/variable, reusing `InstrumentationSpecification.from_plan_item` and falling back to a minimal synthetic-only plan item for variables not tied to any registry parameter (e.g. `relative_humidity`).
4. Runs `SimulatedAcquisitionBackend` twice with the same `SimulationClock` and seed: once with no faults (the "truth" pass used only to synthesize a `TwinState` history) and once with the configured `AcquisitionFaults` (the "observation" pass).
5. Applies controlled, deterministic defects (known bias / temporal shift) to the observation pass only.
6. Optionally routes acquisition records through `FakeExternalSensorSource` + `FutureRealAcquisitionAdapter` to demonstrate backend substitution.
7. Ingests acquisition records with `ingest_rows` into an `ObservationDataset`.
8. Builds an `InMemoryTwinStateRepository` from the "truth" pass (never from observations).
9. Runs `compare_dataset` (`TemporalAlignment`) to build a `ComparisonDataset`.
10. Runs `diagnose` to build `ErrorDiagnostics`.
11. Re-runs `ParameterIdentifiabilityAnalyzer.analyze_all(dataset)` (after).
12. Produces a `CampaignQualityReport`.

## 4. Synthetic data

### Crops and varieties

All 7 project crops are covered by `default_campaign_crops()`:

| Crop | Variety | Environment | Cycle |
|---|---|---|---|
| tomato | RAF | GREENHOUSE | annual |
| lettuce | (generic) | GREENHOUSE | annual, `cycle_1` |
| lettuce | (generic) | GREENHOUSE | annual, `cycle_2` (second plot to avoid ingestion dedup collisions — see §6) |
| pepper | Lamuyo | GREENHOUSE | annual |
| grape | Monastrell | OUTDOOR | perennial |
| peach | (generic) | OUTDOOR | perennial |
| plum | Suplum 26 | OUTDOOR | perennial |
| apple | (generic) | OUTDOOR | perennial |

No variety is invented beyond the ones already established in
`farm_config.json` (tomato/RAF, pepper/Lamuyo, grape/Monastrell, plum/Suplum 26).

### Observable variables

Only variables already supported by `SimulatedAcquisitionBackend` and directly
comparable to an existing `TwinState` field are used by default:
`air_temperature`, `relative_humidity`, `solar_radiation`, `co2`, `lai`,
`biomass`, `soil_water_content`.

## 5. Determinism

Nothing in this module calls `datetime.now()`, `time.time()`, `sleep()`, or
`random.random()`. All time comes from `SimulationClock`; all randomness is
seeded (`AcquisitionFaults` + `seed` passed straight into
`SimulatedAcquisitionBackend`). `CampaignConfiguration.config_hash()` hashes
a canonical JSON payload with `hashlib.sha256` (the same pattern already used
by `Scenario.config_hash()` in `scenarios.py`).
`campaigns_are_deterministic()` proves two runs with identical configuration
produce identical acquisition records, observations, comparisons,
diagnostics and reports.

## 6. Controlled defects

Cases B-E reuse the existing `AcquisitionFaults` mechanism from Phase 5.16
unchanged (`missing_every`, `duplicate_every`, `out_of_range_every`,
`invalid_every`, `unit_error_every`); no new fault-injection mechanism was
added. Cases F and G add two narrowly-scoped, deterministic, test-only knobs
on `CampaignConfiguration`:

- `known_bias_variable` / `known_bias_offset` — adds `observed = simulated + offset` to a chosen variable's *observation* pass only (the "truth" pass used for `TwinState` stays unbiased), so `ErrorDiagnostics.by_variable()` reports the exact configured `bias`/`mae`/`rmse`.
- `temporal_shift_variable` / `temporal_shift_seconds` — shifts a chosen variable's observation timestamps, exercising `TemporalAlignment` (`EXACT`, `SAME_DAY`, `NEAREST`, tolerance) exactly as specified in Phase 5.12.

One architectural detail worth noting: `ObservationIngestion` deduplicates by
`(plot_id, variable, timestamp)`, not `(plot_id, cycle_id, variable, timestamp)`.
Two concurrent lettuce cycles on the *same* plot would therefore be
(correctly) flagged as duplicates by the existing ingestion rules. The
campaign avoids this by giving `cycle_1`/`cycle_2` distinct plot ids, which
also matches real greenhouse practice (concurrent cycles usually occupy
different physical plots/beds).

## 7. Backend substitution

`CampaignConfiguration(use_future_real_adapter=True)` routes valid acquisition
records through `FakeExternalSensorSource` (deterministic test double) and
`FutureRealAcquisitionAdapter` before ingestion, proving that
`AcquisitionRecord -> ObservationIngestion -> ObservationDataset` is agnostic
to which backend produced the record. No hardware, network, IoT or external
API is contacted.

## 8. Identifiability

The campaign re-runs the *unmodified* `ParameterIdentifiabilityAnalyzer`
after ingesting synthetic observations. Because the dataset's
`source_type` is `synthetic_test_data` (or `measured_data` only in the
backend-substitution demo, itself sourced from `FakeExternalSensorSource`),
the existing analyzer logic — unchanged by this phase — keeps every
assessment at `INSUFFICIENT_DATA`/`CANDIDATE`/`CONFOUNDED` and never promotes
a parameter to `IDENTIFIABLE` purely because synthetic data was supplied.
This is verified by `test_identifiability_recomputation_does_not_force_favorable_status`.

## 9. Campaign quality report

`CampaignQualityReport` is a frozen, JSON-serializable dataclass with:
`campaign_id`, `configuration_hash`, `synthetic` (always `True`),
`forcing_source`, `observation_count`, `acquisition_count`,
`comparison_count`, `valid_comparison_count`, `quality_counts`,
`diagnostic_summary`, `identifiability_summary`, `determinism_status`,
`backend_substitution_status`, `pipeline_status`, `scientific_status`,
`limitations`.

## 10. Scientific limits — what this phase has NOT done

```
REAL AGRONOMIC DATA NOT AVAILABLE
SIMULATED ACQUISITION ONLY
CALIBRATION NOT PERFORMED
DATA ASSIMILATION NOT IMPLEMENTED
EXPERIMENTAL VALIDATION NOT CLAIMED
```

Explicitly out of scope and never invoked by this module: `GridSearchCalibrator`,
any parameter-fitting/optimizer routine, any Kalman/EnKF/particle-filter/nudging
state-correction mechanism, and any write path from `Observation` back into
`TwinState`. Comparisons only flow `TwinState -> Observation`, never the
reverse. `ParameterRegistry` and `TwinState` are read-only throughout a
campaign run (see `test_parameter_registry_not_mutated`,
`test_no_twin_state_mutation_from_observations`).

## 11. Replacing synthetic acquisition with real acquisition (future work)

`SimulatedAcquisitionBackend` implements the same `AcquisitionBackend`
protocol/`AcquisitionRecord` contract as `RealAcquisitionAdapter`/
`FutureRealAcquisitionAdapter`. A future real deployment only needs to:

1. implement a real sensor/telemetry adapter that produces `ExternalAcquisitionPayload` objects (or directly `AcquisitionRecord`s);
2. set `CampaignConfiguration.use_future_real_adapter=True` (or call the real adapter directly instead of `SimulatedAcquisitionBackend`);
3. everything downstream (`ObservationIngestion`, `TemporalAlignment`, `ErrorDiagnostics`, `ParameterIdentifiabilityAnalyzer`) requires no changes.

Only then — once real agronomic data exists — can calibration and
experimental validation phases be scientifically justified.
