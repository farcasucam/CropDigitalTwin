"""Offline delivery verification for Phase 5.27."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from agri_twin.application.post_calibration_validation import PostCalibrationValidationStatus, PostCalibrationValidationSuite, ValidationExecutionStatus
from agri_twin.domain.calibration import DatasetRole, Observation, ObservationDataset, ParameterSet, SimulationPoint

ROOT = Path(__file__).resolve().parent
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def fixture(name: str, role: DatasetRole, timestamp: datetime) -> ObservationDataset:
    observation = Observation(timestamp, "biomass", 1.0, "g_m-2", source="SYNTHETIC_SOFTWARE_TEST", source_type="synthetic_test_data", dataset_id=name, crop="tomato", variety="RAF", plot_id="plot_12010", cycle_id=name, environment="GREENHOUSE")
    return ObservationDataset(name, role, (observation,), source="SYNTHETIC_SOFTWARE_TEST", source_type="synthetic_test_data")


def main() -> None:
    suite = PostCalibrationValidationSuite(ROOT)
    calibration_report = suite.calibration_report()
    sources = suite.audit_sources()
    assert calibration_report.get("calibration_performed") is False
    assert not any(source.classification.value == "REAL_VERIFIED" for source in sources)

    calibration = fixture("calibration", DatasetRole.CALIBRATION, START)
    validation = fixture("validation", DatasetRole.VALIDATION, START + timedelta(days=1))
    independence = suite.independence(calibration, validation, basis=("cycle_id", "temporal_holdout"))
    assert independence.independent
    leaked = suite.independence(calibration, fixture("validation_leaked", DatasetRole.VALIDATION, START))
    assert not leaked.independent

    def runner(observations, _parameters):
        return (SimulationPoint(observations.observations[0].timestamp, {"biomass": 1.0}, {"biomass": "g_m-2"}),)

    result = suite.evaluate(calibration_dataset=calibration, validation_dataset=validation, baseline_parameters=ParameterSet((), "baseline"), calibrated_parameters=ParameterSet((), "calibrated"), baseline_runner=runner, calibrated_runner=runner, source_status=None, independence=independence)
    assert result.status is ValidationExecutionStatus.NOT_PERFORMED
    assert result.readiness is PostCalibrationValidationStatus.INSUFFICIENT_REAL_DATA
    report = suite.build_report(result)
    repeated = suite.build_report(result)
    assert report.validation_performed is False
    assert report.real_data_verified is False
    assert report.to_json() == repeated.to_json()
    paths = suite.write_report(report)
    assert all(path.exists() for path in paths)

    print("=" * 80)
    print("PHASE 5.27 COMPLETE")
    print("POST-CALIBRATION VALIDATION PIPELINE READY")
    print("VALIDATION NOT PERFORMED - INSUFFICIENT REAL DATA")
    print("NO SCIENTIFIC CALIBRATION AVAILABLE FOR VALIDATION")
    print("SYNTHETIC VALIDATION TESTS QUALIFIED AS SOFTWARE TESTS ONLY")
    print("REAL AGRICULTURAL DATA NOT VERIFIED")
    print("EXPERIMENTAL VALIDATION NOT CLAIMED")
    print("DATA ASSIMILATION NOT IMPLEMENTED")
    print("independence=PASS leakage_detection=PASS determinism=PASS")
    print("PASS")
    print("=" * 80)


if __name__ == "__main__":
    main()
