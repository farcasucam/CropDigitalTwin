# Phase 5.17: real acquisition adapter readiness

## Objective and scope

Phase 5.17 prepares the boundary between a deterministic simulated acquisition source and a future real sensor source without connecting to hardware or claiming agronomic evidence.

```text
ExperimentalObservationPlan
  -> InstrumentationSpecification
  -> AcquisitionBackend
  -> SimulatedAcquisitionBackend / FutureRealAcquisitionAdapter
  -> AcquisitionRecord
  -> ObservationIngestion
  -> ObservationDataset
  -> TemporalAlignment
  -> ErrorDiagnostics
```

The goal is architectural compatibility, not deployment. The repository still has no real agronomic dataset and no physical sensor deployment.

## Relationship with Phase 5.16

Phase 5.16 introduced the modular acquisition contract and the `SimulatedAcquisitionBackend`. Phase 5.17 adds a minimal future-real adapter layer that translates external payloads into the same `AcquisitionRecord` contract, so the downstream `ObservationIngestion` pipeline remains unchanged.

The scientific boundary remains intact:

- synthetic data stays synthetic;
- a future real measurement remains `source_type = measured` only when it is genuinely measured;
- simulation clock stays in the twin layer and is not replaced by a new hardware clock;
- no calibration, data assimilation or validation claim is introduced.

## Acquisition abstraction contract

The common boundary is the `AcquisitionRecord` shape. It keeps:

- `acquisition_id`;
- `instrument_id` and `device_id`;
- `timestamp`, `timezone` and `clock_source` metadata;
- `variable`, `value`, `unit` and `quality`;
- `plot_id`, `cycle_id`, `crop`, `variety` and `environment`;
- provenance, backend and source type.

This contract is already sufficient for a future external adapter and it remains the single translation layer before observation ingestion.

## Simulated backend and future real adapter

The application layer now includes:

- `AcquisitionConnectionStatus` for explicit future connection states;
- `ExternalAcquisitionPayload` for a future raw external payload;
- `FakeExternalSensorSource` as a deterministic test double only;
- `RealAcquisitionAdapter` and `FutureRealAcquisitionAdapter` as pure translation contracts;
- `SimulatedAcquisitionBackend` unchanged for deterministic software tests.

These contracts are intentionally non-invasive:

- no hardware, network, MQTT, serial, OPC-UA, Modbus or cloud service is implemented;
- no edge driver or external SDK is included;
- connection states are explicit `NOT_CONFIGURED`, `NOT_CONNECTED`, `NOT_AVAILABLE` and `ONLINE` only when required;
- a future real adapter cannot masquerade as a model calibration step or a scientific observation before `ObservationIngestion`.

## Payload mapping and provenance

An external payload is translated to the internal acquisition record as follows:

```text
external field -> ExternalAcquisitionPayload -> RealAcquisitionAdapter -> AcquisitionRecord -> ObservationIngestion
```

Required mapping metadata includes:

- `instrument_id` and `device_id`;
- `plot_id` and `cycle_id`;
- `crop`, `variety`, `environment` and `phenological_stage`;
- `variable`, `unit`, `value`, `timestamp` and `quality`;
- `source_metadata` and `external_quality`.

The adapter preserves provenance and never reuses a single identifier for all object types. Distinct identifiers remain separate for instrument/device/acquisition/observation/plot/cycle.

## Source distinction and scientific boundary

The synthetic and measured source paths are explicitly distinguishable:

```text
SimulatedAcquisitionBackend -> source_type = synthetic
FutureRealAcquisitionAdapter -> source_type = measured
```

This is not a claim of field evidence. It is only a contract-level distinction that preserves provenance downstream.

## Time, units and quality

Time handling remains centralized in the existing observation flow. The adapter accepts timezone-aware timestamps and stores them in UTC for the internal contract. It does not define or replace the simulation clock.

Units remain explicit through:

- `unit` as raw external unit;
- `normalized_unit` / canonical normalization in the ingestion pipeline;
- the existing `ObservationIngestion` conversion rules.

Quality flags remain the existing ones from `ObservationIngestion` and `QualityFlag`. External quality can be preserved as metadata, but it must still pass through the standard quality system when converted to observations.

## Sensor metrology and calibration metadata

The future adapter contract preserves metadata placeholders without pretending to know the device. Examples include:

- `calibration_status` -> `NOT_AVAILABLE`/`UNKNOWN`;
- `calibration_date` and `calibration_due` -> `NOT_AVAILABLE`;
- `accuracy`, `precision`, `resolution`, `uncertainty`, `range` and `drift` -> explicit unknowns or `TO_BE_DEFINED`.

This keeps `instrument calibration` separate from `crop model calibration`, which remains the responsibility of the scientific model layer and is intentionally not performed here.

## Greenhouse, outdoor and actuator separation

The contract still distinguishes:

- actuator command vs actuator state;
- physical measurement vs operational state;
- weather forcing vs agronomic observation;
- greenhouse climate vs outdoor climate.

It supports these categories without conflating them in a single device record.

## Deterministic fake external source

The `FakeExternalSensorSource` is a pure software test double. It is used to prove that a future raw external payload can translate into the same internal acquisition contract without network or hardware requirements.

The fake source is deterministic:

- no `random` without explicit seed;
- no wall-clock or `datetime.now()` usage;
- same payload and metadata yield the same `AcquisitionRecord`.

## Validation and integration scope

The fake external source is intentionally validated only through:

```text
AcquisitionRecord -> ObservationIngestion -> ObservationDataset -> TemporalAlignment -> ErrorDiagnostics
```

It does not mutate `TwinState`, `ParameterRegistry`, or perform calibration or assimilation.

## Known limitations

This phase intentionally does not define:

- a real protocol or transport layer;
- any real hardware vendor contract;
- external data source deployment;
- metrology validation certificates;
- sensor maintenance schedule;
- site-level antenna, gateway or polling logic;
- any real instrumentation inventory with calibration or maintenance status.

These remain `TO_BE_DEFINED` or `NOT_AVAILABLE` until actual evidence exists.

## Final status

**REAL AGRONOMIC DATA NOT AVAILABLE**
**SIMULATED ACQUISITION ONLY**
**REAL ACQUISITION ADAPTER CONTRACT PREPARED**
**REAL SENSOR CONNECTION NOT IMPLEMENTED**
**REAL SENSOR DEPLOYMENT NOT EXECUTED**
**CALIBRATION NOT PERFORMED**
**DATA ASSIMILATION NOT IMPLEMENTED**
**EXPERIMENTAL VALIDATION NOT CLAIMED**

**PHASE 5.17 COMPLETE — REAL ACQUISITION ADAPTER CONTRACT READY — SIMULATED/FUTURE-REAL SOURCE SUBSTITUTION VERIFIED — REAL AGRONOMIC DATA NOT AVAILABLE — REAL SENSOR CONNECTION NOT IMPLEMENTED — REAL SENSOR DEPLOYMENT NOT EXECUTED — CALIBRATION NOT PERFORMED — EXPERIMENTAL VALIDATION NOT CLAIMED**
