from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agri_twin.application.post_calibration_validation import (
    PostCalibrationValidationStatus,
    PostCalibrationValidationSuite,
    ValidationExecutionStatus,
)
from agri_twin.application.real_validation import DataSourceClassification
from agri_twin.domain.calibration import (
    CalibrationParameter,
    DatasetRole,
    Observation,
    ObservationDataset,
    ParameterSet,
    SimulationPoint,
)
from agri_twin.application.twin_state import InMemoryTwinStateRepository

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def dataset(name: str, role: DatasetRole, timestamp: datetime = START, value: float = 1.0) -> ObservationDataset:
    observation = Observation(
        timestamp,
        "biomass",
        value,
        "g_m-2",
        source="SYNTHETIC_SOFTWARE_TEST",
        source_type="synthetic_test_data",
        dataset_id=name,
        crop="tomato",
        variety="RAF",
        plot_id="plot_12010",
        cycle_id=name,
        environment="GREENHOUSE",
    )
    return ObservationDataset(name, role, (observation,), source="SYNTHETIC_SOFTWARE_TEST", source_type="synthetic_test_data")


def parameters(value: float) -> ParameterSet:
    item = CalibrationParameter("fixture.scale", value, value, 0.0, 2.0, 1.0, "dimensionless", "engineering_default", "candidate_for_calibration", True)
    return ParameterSet((item,), "fixture")


def runner(dataset_value: float):
    def evaluate(observations, _parameters):
        return (SimulationPoint(observations.observations[0].timestamp, {"biomass": dataset_value}, {"biomass": "g_m-2"}),)
    return evaluate


def test_current_state_blocks_post_calibration_validation_without_real_data_or_calibration():
    suite = PostCalibrationValidationSuite(ROOT)
    result = suite.evaluate(calibration_dataset=None, validation_dataset=None, baseline_parameters=None, calibrated_parameters=None)
    assert result.status is ValidationExecutionStatus.NOT_PERFORMED
    assert result.readiness is PostCalibrationValidationStatus.INSUFFICIENT_REAL_DATA
    assert result.validation_performed is False
    assert result.real_data_verified is False


def test_synthetic_substitute_is_not_scientific_validation():
    suite = PostCalibrationValidationSuite(ROOT)
    calibration = dataset("calibration", DatasetRole.CALIBRATION)
    validation = dataset("validation", DatasetRole.VALIDATION, START + timedelta(days=1))
    result = suite.evaluate(calibration_dataset=calibration, validation_dataset=validation, baseline_parameters=parameters(1.0), calibrated_parameters=parameters(1.2), baseline_runner=runner(1.0), calibrated_runner=runner(1.2), source_status=DataSourceClassification.SIMULATED_REAL_DATA_SUBSTITUTE)
    assert result.validation_performed is False
    assert result.readiness is PostCalibrationValidationStatus.INSUFFICIENT_REAL_DATA


def test_independence_and_leakage_are_explicit():
    suite = PostCalibrationValidationSuite(ROOT)
    calibration = dataset("calibration", DatasetRole.CALIBRATION)
    independent = dataset("validation", DatasetRole.VALIDATION, START + timedelta(days=1))
    split = suite.independence(calibration, independent, basis=("cycle_id", "temporal_holdout"))
    assert split.independent is True
    assert not split.overlap
    leaked = suite.independence(calibration, dataset("validation", DatasetRole.VALIDATION))
    assert leaked.independent is False
    result = suite.evaluate(calibration_dataset=calibration, validation_dataset=dataset("validation", DatasetRole.VALIDATION), baseline_parameters=parameters(1.0), calibrated_parameters=parameters(1.2), baseline_runner=runner(1.0), calibrated_runner=runner(1.2), source_status=DataSourceClassification.SYNTHETIC, independence=leaked)
    assert result.readiness is PostCalibrationValidationStatus.DATA_LEAKAGE
    assert result.data_leakage is True


def test_synthetic_fixture_compare_reuses_existing_metrics_and_is_deterministic():
    suite = PostCalibrationValidationSuite(ROOT)
    calibration = dataset("calibration", DatasetRole.CALIBRATION, START, 1.0)
    validation = dataset("validation", DatasetRole.VALIDATION, START + timedelta(days=1), 1.0)
    split = suite.independence(calibration, validation)
    first = suite.software_fixture_compare(calibration_dataset=calibration, validation_dataset=validation, baseline_parameters=parameters(1.0), calibrated_parameters=parameters(1.2), baseline_runner=runner(1.0), calibrated_runner=runner(1.2), independence=split)
    second = suite.software_fixture_compare(calibration_dataset=calibration, validation_dataset=validation, baseline_parameters=parameters(1.0), calibrated_parameters=parameters(1.2), baseline_runner=runner(1.0), calibrated_runner=runner(1.2), independence=split)
    assert first.status is ValidationExecutionStatus.SOFTWARE_TEST_ONLY
    assert first.baseline_metrics[0].rmse == 0.0
    assert first.calibrated_metrics[0].rmse == pytest.approx(0.2)
    assert first.to_dict() == second.to_dict()
    assert first.warnings == ("SYNTHETIC_SOFTWARE_TEST",)


def test_overfit_signal_is_diagnostic_only():
    suite = PostCalibrationValidationSuite(ROOT)
    calibration = dataset("calibration", DatasetRole.CALIBRATION, START, 1.0)
    validation = dataset("validation", DatasetRole.VALIDATION, START + timedelta(days=1), 1.0)
    split = suite.independence(calibration, validation)

    def baseline(observations, _parameters):
        value = 0.5 if observations.name == "calibration" else 1.0
        return (SimulationPoint(observations.observations[0].timestamp, {"biomass": value}, {"biomass": "g_m-2"}),)

    def calibrated(observations, _parameters):
        value = 1.0 if observations.name == "calibration" else 2.0
        return (SimulationPoint(observations.observations[0].timestamp, {"biomass": value}, {"biomass": "g_m-2"}),)

    result = suite.software_fixture_compare(calibration_dataset=calibration, validation_dataset=validation, baseline_parameters=parameters(1.0), calibrated_parameters=parameters(1.2), baseline_runner=baseline, calibrated_runner=calibrated, independence=split)
    assert result.overfit_diagnostics["label"] == "POTENTIAL_OVERFIT"
    assert result.readiness is PostCalibrationValidationStatus.INSUFFICIENT_REAL_DATA


def test_parameter_registry_and_twin_state_are_not_mutated():
    suite = PostCalibrationValidationSuite(ROOT)
    before = tuple(record.to_dict() for record in suite.registry.records)
    repository = InMemoryTwinStateRepository()
    calibration = dataset("calibration", DatasetRole.CALIBRATION)
    validation = dataset("validation", DatasetRole.VALIDATION, START + timedelta(days=1))
    suite.software_fixture_compare(calibration_dataset=calibration, validation_dataset=validation, baseline_parameters=parameters(1.0), calibrated_parameters=parameters(1.2), baseline_runner=runner(1.0), calibrated_runner=runner(1.2))
    assert tuple(record.to_dict() for record in suite.registry.records) == before
    assert repository.latest_snapshot() is None


def test_report_has_required_conservative_status_and_stable_hash():
    suite = PostCalibrationValidationSuite(ROOT)
    first = suite.build_report()
    second = PostCalibrationValidationSuite(ROOT).build_report()
    assert first.status is PostCalibrationValidationStatus.INSUFFICIENT_REAL_DATA
    assert first.validation_performed is False
    assert first.calibration_performed is False
    assert first.real_data_verified is False
    assert first.to_json() == second.to_json()
    assert "VALIDATED" not in first.to_json()
