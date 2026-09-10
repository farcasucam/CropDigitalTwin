from datetime import datetime, timezone
from pathlib import Path

from agri_twin.application import (
    AcquisitionFaults,
    AcquisitionSourceType,
    InstrumentationSpecification,
    ParameterIdentifiabilityAnalyzer,
    SimulatedAcquisitionBackend,
    ExperimentalObservationPlan,
    SimulationClock,
)
from agri_twin.domain import DatasetRole, ObservationSourceType, ParameterRegistry, ingest_rows

ROOT = Path(__file__).parents[1]
START = datetime(2026, 6, 1, 10, tzinfo=timezone.utc)


def specs():
    report = ParameterIdentifiabilityAnalyzer(ParameterRegistry.from_repository(ROOT), repository_root=ROOT).analyze_all()
    plan = ExperimentalObservationPlan.from_identifiability_report(report)
    wanted = list(plan.for_observable("air_temperature"))[:2]
    return tuple(InstrumentationSpecification.from_plan_item(item, instrument_id=f"I-{index}", device_id=f"D-{index}", unit="degC", interval="3600s") for index, item in enumerate(wanted))


def test_specification_links_to_plan_and_defaults_are_explicit():
    specification = specs()[0]
    assert specification.parameter_ids
    assert specification.clock_source == "SimulationClock"
    assert specification.calibration_status == "NOT_AVAILABLE"
    assert specification.accuracy == "UNKNOWN"


def test_simulated_acquisition_is_deterministic_and_does_not_advance_clock():
    clock = SimulationClock(START)
    backend = SimulatedAcquisitionBackend(clock)
    first = backend.acquire(START, START + __import__("datetime").timedelta(hours=1), interval_seconds=3600, specifications=specs(), seed=4)
    second = backend.acquire(START, START + __import__("datetime").timedelta(hours=1), interval_seconds=3600, specifications=specs(), seed=4)
    changed = backend.acquire(START, START, interval_seconds=3600, specifications=specs(), seed=5)
    assert first == second
    assert first != changed
    assert clock.now() == START
    assert all(record.source_type is AcquisitionSourceType.SYNTHETIC for record in first)
    assert all(record.clock_source == "SimulationClock" for record in first)


def test_acquisitions_flow_through_existing_ingestion_and_keep_provenance():
    records = SimulatedAcquisitionBackend(SimulationClock(START)).acquire(START, START, interval_seconds=3600, specifications=specs(), seed=1)
    result = ingest_rows([record.to_row() for record in records], dataset_id="sim-acq", role=DatasetRole.TEST, source="simulated_backend", source_type=ObservationSourceType.SYNTHETIC_TEST)
    assert result.dataset is not None
    assert all(item.source_type == ObservationSourceType.SYNTHETIC_TEST.value for item in result.dataset.observations)


def test_controlled_faults_are_reproducible_and_quality_aware():
    faults = AcquisitionFaults(missing_every=2, duplicate_every=3, out_of_range_every=3)
    records = SimulatedAcquisitionBackend(SimulationClock(START), faults).acquire(START, START + __import__("datetime").timedelta(hours=2), interval_seconds=3600, specifications=specs(), seed=1)
    assert records == SimulatedAcquisitionBackend(SimulationClock(START), faults).acquire(START, START + __import__("datetime").timedelta(hours=2), interval_seconds=3600, specifications=specs(), seed=1)
    assert any(record.quality.value == "MISSING" for record in records)
    assert any(record.quality.value == "OUT_OF_RANGE" for record in records)
    assert len(records) > len(specs())
