# Phase 5.16: simulated acquisition and instrumentation readiness

## Objective and boundary

Phase 5.16 exercises the future acquisition pipeline without sensors, networks or real agronomic data:

```text
ExperimentalObservationPlan
  -> InstrumentationSpecification
  -> SimulatedAcquisitionBackend
  -> AcquisitionRecord
  -> ObservationIngestion
  -> ObservationDataset
  -> TemporalAlignment
  -> ErrorDiagnostics
```

The backend is an engineering verification tool. Synthetic output is never measured data, calibration evidence or experimental validation.

## Contracts

`InstrumentationSpecification` describes a future acquisition configuration and links to real `parameter_ids` and plan items. Unknown metrology remains `UNKNOWN`, `TO_BE_DEFINED` or `NOT_AVAILABLE`. It does not claim a sensor model, accuracy, sampling frequency, installation location or certificate.

`AcquisitionRecord` is raw acquisition data before normalization. It preserves instrument/device identity, timestamp, clock source, raw unit/value, crop-cycle context, quality, provenance, source type, backend and simulation seed. It is converted to rows for the existing `ObservationIngestion` contract; no second `Observation` or `ObservationDataset` is introduced.

`AcquisitionBackend` is intentionally small. The current `SimulatedAcquisitionBackend` is the only implemented backend. A future real sensor, CSV, IoT or database backend can emit the same `AcquisitionRecord` without changing the scientific pipeline. Those backends are not implemented here.

## Time and determinism

The backend requires timezone-aware explicit `start`, `end` and `interval_seconds` for test configuration. `SimulationClock` is injected and remains the only simulation clock; acquisition never advances it. `clock_source` metadata is `SimulationClock`, not a second clock. Same seed, window, specifications and faults produce identical records. No wall-clock, sleep or network access is used.

An explicit interval in a test is simulation configuration, not a validated sensor sampling requirement. Plan fields remain `TO_BE_DEFINED` where Phase 5.15 has no evidence.

## Variables, environments and cycles

The backend emits only variables selected from the plan or explicitly configured in a specification. Existing observables include climate, soil water, LAI, biomass, yield and fruit measures. Seven crop scopes and known varieties are preserved. Multiple plots and cycles remain metadata dimensions. Greenhouse actuator state and physical climate state are separate concepts; an actuator command is never relabelled as a physical measurement.

## Quality and units

`AcquisitionFaults` can inject deterministic missing, duplicate, out-of-range, invalid, unit-error and timestamp cases. Existing quality flags are retained. Raw units remain on the acquisition and normalization is delegated to `ObservationIngestion`, which preserves original and canonical units and provenance.

## End-to-end verification

The manual `manual_phase5_16_simulated_acquisition_test.py` builds the plan, creates instrument specifications, acquires deterministic records, injects quality faults, ingests them as `SYNTHETIC_TEST`, and exercises compatibility with `ObservationDataset`, `TemporalAlignment` and `ErrorDiagnostics`. This proves software contracts only.

## Templates and schema

- `data/templates/agricultural/instrumentation_specification.csv` is a blank technician/researcher configuration template.
- `schemas/instrumentation_readiness.schema.json` validates instrumentation specification metadata only.
- `schemas/observation_dataset.schema.json` remains the observation schema and is not duplicated.

## Scientific status and limitations

No real sensor deployment, hardware driver, IoT integration, network acquisition, calibration, data assimilation or independent validation is performed. Frequencies, precision, accuracy, uncertainty, installation depth/height, calibration certificates, maintenance and representativeness remain unknown until a real campaign specifies them. Synthetic acquisition must not upgrade parameter identifiability or scientific readiness.

**REAL AGRONOMIC DATA NOT AVAILABLE**  
**SIMULATED ACQUISITION ONLY**  
**INSTRUMENTATION READINESS PREPARED**  
**REAL SENSOR DEPLOYMENT NOT EXECUTED**  
**CALIBRATION NOT PERFORMED**  
**DATA ASSIMILATION NOT IMPLEMENTED**  
**EXPERIMENTAL VALIDATION NOT CLAIMED**

**PHASE 5.16 COMPLETE — MODULAR INSTRUMENTATION READINESS READY — SIMULATED ACQUISITION BACKEND READY — REAL AGRONOMIC DATA NOT AVAILABLE — REAL SENSOR DEPLOYMENT NOT EXECUTED — CALIBRATION NOT PERFORMED — EXPERIMENTAL VALIDATION NOT CLAIMED**
