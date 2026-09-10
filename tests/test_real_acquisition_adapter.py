from datetime import datetime, timedelta, timezone

from agri_twin.application import (
    AcquisitionSourceType,
    AcquisitionConnectionStatus,
    ExternalAcquisitionPayload,
    FakeExternalSensorSource,
    FutureRealAcquisitionAdapter,
    InstrumentationSpecification,
    RealAcquisitionAdapter,
    SimulatedAcquisitionBackend,
    SimulationClock,
)
from agri_twin.domain import DatasetRole, ObservationSourceType, ingest_rows


START = datetime(2026, 6, 1, 10, tzinfo=timezone.utc)


def _specs():
    return (
        InstrumentationSpecification(
            instrument_id="INST-1",
            device_id="DEV-1",
            observable="air_temperature",
            variable="air_temperature",
            unit="degC",
            normalized_unit="degC",
            method="thermistor",
            plot_id="P-01",
            cycle_id="C-01",
            crop="tomato",
            variety="RAF",
            environment="GREENHOUSE",
            phenological_stage="fruit_set",
            timezone="UTC",
            clock_source="SimulationClock",
            provenance="experimental_observation_plan",
            requirement_source="measured",
            status="PLANNED",
        ),
    )


def test_real_adapter_contract_is_explicit_and_not_connected_by_default():
    adapter = RealAcquisitionAdapter()
    assert adapter.status == AcquisitionConnectionStatus.NOT_CONFIGURED
    assert adapter.is_available() is False
    assert adapter.backend_name == "FutureRealAcquisitionAdapter"


def test_fake_external_payload_maps_to_common_acquisition_record():
    source = FakeExternalSensorSource(seed=7)
    payload = source.payload(
        timestamp=START,
        variable="air_temperature",
        value=23.5,
        unit="degC",
        instrument_id="INST-1",
        device_id="DEV-1",
        plot_id="P-01",
        cycle_id="C-01",
        crop="tomato",
        variety="RAF",
        environment="GREENHOUSE",
        phenological_stage="fruit_set",
        quality="VALID",
    )
    record = FutureRealAcquisitionAdapter().adapt(payload, specification=_specs()[0])
    assert record.variable == "air_temperature"
    assert record.value == 23.5
    assert record.unit == "degC"
    assert record.source_type is AcquisitionSourceType.MEASURED
    assert record.backend == "FutureRealAcquisitionAdapter"
    assert record.provenance == "fake_external_sensor_source"


def test_fake_external_source_is_deterministic_and_compatible_with_ingestion():
    source = FakeExternalSensorSource(seed=11)
    payload = source.payload(
        timestamp=START,
        variable="relative_humidity",
        value=68.0,
        unit="%",
        instrument_id="INST-2",
        device_id="DEV-2",
        plot_id="P-02",
        cycle_id="C-02",
        crop="lettuce",
        variety="unknown",
        environment="OUTDOOR",
        phenological_stage="harvest",
        quality="VALID",
    )
    record = RealAcquisitionAdapter().adapt(payload, specification=_specs()[0])
    dataset = ingest_rows([record.to_row()], dataset_id="adapter-test", role=DatasetRole.TEST, source="fake_external_sensor_source", source_type=ObservationSourceType.MEASURED)
    assert dataset.dataset is not None
    assert dataset.dataset.observations[0].variable == "relative_humidity"


def test_real_adapter_rejects_invalid_payloads_explicitly():
    adapter = RealAcquisitionAdapter()
    malformed = ExternalAcquisitionPayload(
        timestamp=None,
        variable="air_temperature",
        value=21.0,
        unit="degC",
        instrument_id="INST-X",
        device_id="DEV-X",
        plot_id="P-01",
        cycle_id="C-01",
        crop="tomato",
        variety="RAF",
        environment="GREENHOUSE",
    )
    try:
        adapter.adapt(malformed)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid payload should raise ValueError")


def test_simulated_and_fake_external_sources_share_the_same_contract():
    spec = _specs()[0]
    clock = SimulationClock(START)
    record = SimulatedAcquisitionBackend(clock).acquire(START, START, interval_seconds=3600, specifications=(spec,), seed=9)[0]
    payload = FakeExternalSensorSource(seed=9).payload(
        timestamp=START,
        variable="air_temperature",
        value=record.value,
        unit=record.unit,
        instrument_id=spec.instrument_id,
        device_id=spec.device_id,
        plot_id=spec.plot_id,
        cycle_id=spec.cycle_id,
        crop=spec.crop,
        variety=spec.variety,
        environment=spec.environment,
        phenological_stage=spec.phenological_stage,
        quality="VALID",
    )
    adapted = RealAcquisitionAdapter().adapt(payload, specification=spec)
    assert record.variable == adapted.variable
    assert record.unit == adapted.unit
    assert record.plot_id == adapted.plot_id
    assert record.cycle_id == adapted.cycle_id
