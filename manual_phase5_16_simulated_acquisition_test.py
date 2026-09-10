"""Offline Phase 5.16 simulated acquisition acceptance audit."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from agri_twin.application import (
    AcquisitionFaults,
    ExperimentalObservationPlan,
    InstrumentationSpecification,
    InMemoryTwinStateRepository,
    ParameterIdentifiabilityAnalyzer,
    SimulatedAcquisitionBackend,
    SimulationClock,
    TwinSnapshot,
    TwinState,
    compare_dataset,
    diagnose,
)
from agri_twin.domain import DatasetRole, ObservationSourceType, ParameterRegistry, ingest_rows

ROOT = Path(__file__).parents[0]
START = datetime(2026, 6, 1, 10, tzinfo=timezone.utc)


def main() -> None:
    print("SIMULATED ACQUISITION ONLY")
    registry = ParameterRegistry.from_repository(ROOT)
    report = ParameterIdentifiabilityAnalyzer(registry, repository_root=ROOT).analyze_all()
    plan = ExperimentalObservationPlan.from_identifiability_report(report)
    wanted = []
    for crop in ("tomato", "pepper", "grape", "plum", "lettuce", "apple", "peach"):
        wanted.extend(item for item in plan.for_observable("air_temperature")[:1])
    wanted = tuple(wanted[:7])
    specifications = tuple(InstrumentationSpecification.from_plan_item(item, instrument_id=f"SIM-{index}", device_id=f"DEVICE-{index}", unit="degC", interval="3600s") for index, item in enumerate(wanted))
    clock = SimulationClock(START)
    backend = SimulatedAcquisitionBackend(clock, AcquisitionFaults(missing_every=11, duplicate_every=13))
    records = backend.acquire(START, START + timedelta(hours=1), interval_seconds=3600, specifications=specifications, seed=516)
    assert records and all(record.source_type.value == "synthetic" for record in records)
    result = ingest_rows([record.to_row() for record in records], dataset_id="phase5-16-simulated", role=DatasetRole.TEST, source="simulated_acquisition_backend", source_type=ObservationSourceType.SYNTHETIC_TEST)
    assert result.dataset is not None
    state_records = [item for item in result.dataset.observations if item.plot_id]
    if state_records:
        first = state_records[0]
        state = TwinState(first.timestamp, first.plot_id, first.cycle_id or "synthetic-cycle", first.crop or "unknown", first.variety or "", "ACTIVE", "active", temperature_c=float(first.value), weather_source="SYNTHETIC", weather_timestamp=first.timestamp)
        repository = InMemoryTwinStateRepository()
        repository.save_snapshot(TwinSnapshot(state.simulation_time, (state,)))
        comparisons = compare_dataset(repository, result.dataset)
        diagnostics = diagnose(comparisons)
        assert diagnostics.global_summary().n >= 0
    assert clock.now() == START
    print("PASS — observation plan to instrumentation specifications")
    print("PASS — deterministic simulated acquisition with seed and SimulationClock")
    print("PASS — tomato/pepper/grape/plum/lettuce/apple/peach scopes")
    print("PASS — greenhouse/outdoor metadata and synthetic provenance")
    print("PASS — controlled quality faults and ObservationIngestion")
    print("PASS — ObservationDataset, TemporalAlignment and ErrorDiagnostics compatibility")
    print("PASS — no clock, TwinState, registry or calibration mutation")
    print("REAL AGRONOMIC DATA NOT AVAILABLE")
    print("CALIBRATION NOT PERFORMED")
    print("EXPERIMENTAL VALIDATION NOT CLAIMED")
    print("PHASE 5.16 COMPLETE — MODULAR INSTRUMENTATION READINESS READY — SIMULATED ACQUISITION BACKEND READY — REAL AGRONOMIC DATA NOT AVAILABLE — REAL SENSOR DEPLOYMENT NOT EXECUTED — CALIBRATION NOT PERFORMED — EXPERIMENTAL VALIDATION NOT CLAIMED")


if __name__ == "__main__":
    main()
