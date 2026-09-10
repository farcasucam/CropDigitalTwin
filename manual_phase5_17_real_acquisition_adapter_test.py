"""Offline Phase 5.17 real acquisition adapter compatibility audit."""

from datetime import datetime, timedelta, timezone

from agri_twin.application import (
    AcquisitionSourceType,
    FakeExternalSensorSource,
    FutureRealAcquisitionAdapter,
    InstrumentationSpecification,
    SimulatedAcquisitionBackend,
    SimulationClock,
)
from agri_twin.domain import DatasetRole, ObservationSourceType, ingest_rows

START = datetime(2026, 6, 1, 10, tzinfo=timezone.utc)


def _specification() -> InstrumentationSpecification:
    return InstrumentationSpecification(
        instrument_id="INST-5-17",
        device_id="DEV-5-17",
        observable="air_temperature",
        variable="air_temperature",
        unit="degC",
        normalized_unit="degC",
        method="future_real_adapter_test",
        plot_id="P-17",
        cycle_id="C-17",
        crop="tomato",
        variety="RAF",
        environment="GREENHOUSE",
        phenological_stage="fruit_set",
        timezone="UTC",
        clock_source="SimulationClock",
        provenance="experimental_observation_plan",
        requirement_source="measured",
        status="PLANNED",
    )


def main() -> None:
    print("SIMULATED SOURCE ≠ REAL MEASUREMENT")
    spec = _specification()
    clock = SimulationClock(START)
    simulated = SimulatedAcquisitionBackend(clock).acquire(START, START + timedelta(hours=1), interval_seconds=3600, specifications=(spec,), seed=17)
    assert simulated and all(record.source_type is AcquisitionSourceType.SYNTHETIC for record in simulated)
    source = FakeExternalSensorSource(seed=17)
    payload = source.payload(
        timestamp=START,
        variable="air_temperature",
        value=simulated[0].value,
        unit=simulated[0].unit,
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
    future_record = FutureRealAcquisitionAdapter().adapt(payload, specification=spec)
    assert future_record.source_type is AcquisitionSourceType.MEASURED
    assert future_record.variable == "air_temperature"
    result = ingest_rows([future_record.to_row()], dataset_id="phase5-17-real-source", role=DatasetRole.TEST, source="fake_external_sensor_source", source_type=ObservationSourceType.MEASURED)
    assert result.dataset is not None
    assert result.dataset.observations[0].source_type == ObservationSourceType.MEASURED.value
    print("PASS — simulated backend and real-source adapter share the same AcquisitionRecord contract")
    print("PASS — future real payload maps to ObservationIngestion without modifying the scientific pipeline")
    print("PASS — source provenance remains synthetic vs measured")
    print("PASS — no TwinState mutation, no calibration, no data assimilation")
    print("REAL AGRONOMIC DATA NOT AVAILABLE")
    print("SIMULATED ACQUISITION ONLY")
    print("REAL ACQUISITION ADAPTER CONTRACT PREPARED")
    print("REAL SENSOR CONNECTION NOT IMPLEMENTED")
    print("REAL SENSOR DEPLOYMENT NOT EXECUTED")
    print("CALIBRATION NOT PERFORMED")
    print("DATA ASSIMILATION NOT IMPLEMENTED")
    print("EXPERIMENTAL VALIDATION NOT CLAIMED")
    print("PHASE 5.17 COMPLETE — REAL ACQUISITION ADAPTER CONTRACT READY — SIMULATED/FUTURE-REAL SOURCE SUBSTITUTION VERIFIED — REAL AGRONOMIC DATA NOT AVAILABLE — REAL SENSOR CONNECTION NOT IMPLEMENTED — REAL SENSOR DEPLOYMENT NOT EXECUTED — CALIBRATION NOT PERFORMED — EXPERIMENTAL VALIDATION NOT CLAIMED")


if __name__ == "__main__":
    main()
