from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from agri_twin.application.real_validation import (
    DataSourceClassification,
    RealValidationSuite,
    ValidationReadiness,
    ValidationScope,
)
from agri_twin.domain.calibration import ParameterSet, SimulationPoint
from agri_twin.domain.validation import AlignmentPolicy, ValidationCase, ValidationStatus
from agri_twin.domain.observation_ingestion import ObservationIngestionError, QualityFlag

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 1, 2, tzinfo=timezone.utc)


def rows(**overrides):
    row = {
        "timestamp": "2026-01-01T12:00:00+00:00",
        "variable": "lai",
        "value": "1.0",
        "unit": "m2_m-2",
        "source": "synthetic_validation_fixture",
        "plot_id": "plot_12010",
        "crop": "tomato",
        "variety": "RAF",
        "cycle_id": "cycle_1",
        "environment": "GREENHOUSE",
        "quality": "VALID",
    }
    row.update(overrides)
    return [row]


def validation_case(suite: RealValidationSuite, dataset):
    return ValidationCase("tomato", "RAF", "plot_12010", START, END, dataset, ParameterSet((), "fixture"), alignment=AlignmentPolicy.EXACT)


def fixture_runner(case):
    return (SimulationPoint(datetime(2026, 1, 1, 12, tzinfo=timezone.utc), {"lai": 1.2}, {"lai": "m2_m-2"}),)


def test_source_audit_classifies_synthetic_forcing_literature_and_no_verified_real_data():
    suite = RealValidationSuite(ROOT)
    sources = suite.audit_sources()
    classifications = {source.classification for source in sources}
    assert DataSourceClassification.SYNTHETIC in classifications
    assert DataSourceClassification.SIMULATED_REAL_DATA_SUBSTITUTE in classifications
    assert DataSourceClassification.FORCING in classifications
    assert DataSourceClassification.LITERATURE in classifications
    assert DataSourceClassification.REAL_VERIFIED not in classifications
    assert suite.assess_readiness(sources) is ValidationReadiness.INSUFFICIENT_REAL_DATA


def test_ingestion_fixture_preserves_synthetic_provenance_and_validation_is_not_real():
    suite = RealValidationSuite(ROOT)
    ingestion = suite.ingest_fixture(rows())
    assert ingestion.dataset is not None
    assert ingestion.dataset.source_type == "synthetic_test_data"
    result = suite.evaluate(validation_case(suite, ingestion.dataset), source_status=DataSourceClassification.SYNTHETIC, scope=ValidationScope.OUT_OF_SAMPLE, runner=fixture_runner)
    assert result.readiness is ValidationReadiness.INSUFFICIENT_REAL_DATA
    assert result.data_source_status is DataSourceClassification.SYNTHETIC
    assert result.validation_scope is ValidationScope.OUT_OF_SAMPLE
    assert result.validation is not None
    assert result.validation.status is ValidationStatus.SUCCESS


def test_report_is_deterministic_and_marks_scientific_validation_unclaimed():
    suite = RealValidationSuite(ROOT)
    first = suite.build_report()
    second = RealValidationSuite(ROOT).build_report()
    assert first.to_json() == second.to_json()
    assert first.real_data_verified is False
    assert first.readiness is ValidationReadiness.INSUFFICIENT_REAL_DATA
    assert first.experimental_validation_status == "NOT_CLAIMED"
    assert first.configuration_hash == second.configuration_hash


def test_quality_flags_are_preserved_for_missing_duplicate_and_estimated_rows():
    suite = RealValidationSuite(ROOT)
    ingestion = suite.ingest_fixture(rows(), dataset_id="quality")
    assert ingestion.readiness.n_valid == 1
    duplicate = suite.ingest_fixture(rows() + rows(), dataset_id="duplicate")
    assert duplicate.readiness.n_valid == 1
    missing = suite.ingest_fixture(rows(quality="MISSING"), dataset_id="missing")
    assert any(issue.quality is QualityFlag.MISSING for issue in missing.qc)
    estimated = suite.ingest_fixture(rows(quality="ESTIMATED"), dataset_id="estimated")
    assert estimated.dataset is not None
    assert estimated.dataset.observations[0].quality == QualityFlag.ESTIMATED.value


def test_timezone_and_unit_errors_are_not_silently_corrected():
    suite = RealValidationSuite(ROOT)
    timezone_result = suite.ingest_fixture(rows(timestamp="2026-01-01T12:00:00"), dataset_id="timezone")
    assert any(issue.quality is QualityFlag.INVALID for issue in timezone_result.qc)
    unit_result = suite.ingest_fixture(rows(unit="unknown_unit"), dataset_id="unit")
    assert any(issue.quality is QualityFlag.UNIT_ERROR for issue in unit_result.qc)


def test_forcing_cannot_enter_observation_ingestion():
    suite = RealValidationSuite(ROOT)
    with pytest.raises(ObservationIngestionError):
        from agri_twin.domain.observation_ingestion import ingest_rows, ObservationSourceType
        ingest_rows(rows(), dataset_id="forcing", role=validation_case(suite, suite.ingest_fixture(rows()).dataset).dataset.role, source="weather", source_type=ObservationSourceType.FORCING)


def test_alignment_policy_and_metrics_are_retained():
    suite = RealValidationSuite(ROOT)
    ingestion = suite.ingest_fixture(rows())
    result = suite.evaluate(validation_case(suite, ingestion.dataset), source_status=DataSourceClassification.SYNTHETIC, scope=ValidationScope.TEMPORAL_HOLDOUT, runner=fixture_runner)
    assert result.alignment_policy is AlignmentPolicy.EXACT
    assert result.validation is not None
    assert result.validation.metrics
    assert result.validation.metrics[0].rmse is not None


def test_source_audit_does_not_mutate_registry():
    suite = RealValidationSuite(ROOT)
    before = tuple(record.to_dict() for record in suite.registry.records)
    suite.audit_sources()
    suite.build_report()
    assert tuple(record.to_dict() for record in suite.registry.records) == before
