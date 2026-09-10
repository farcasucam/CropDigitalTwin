from datetime import datetime, timezone
from pathlib import Path

import pytest

from agri_twin.application import IdentifiabilityStatus, ParameterIdentifiabilityAnalyzer
from agri_twin.domain import DatasetRole, ObservationSourceType, ParameterRegistry, ingest_rows
from agri_twin.domain.parameter_audit import ParameterRecord

ROOT = Path(__file__).parents[1]


def analyzer():
    return ParameterIdentifiabilityAnalyzer(ParameterRegistry.from_repository(ROOT), repository_root=ROOT)


def synthetic_dataset():
    result = ingest_rows([
        dict(timestamp="2026-05-01T10:00:00+00:00", variable="lai", value="2", unit="m2/m2", source="synthetic", plot_id="plot_12010", crop="tomato", variety="RAF"),
    ], dataset_id="synthetic", role=DatasetRole.TEST, source="synthetic", source_type=ObservationSourceType.SYNTHETIC_TEST)
    return result.dataset


def test_reuses_registry_and_covers_all_crops_without_false_identifiability():
    registry = ParameterRegistry.from_repository(ROOT)
    report = analyzer().analyze_all()
    assert len(report.assessments) == len(registry.records)
    assert {item.crop for item in report.assessments if item.crop} >= {"tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple"}
    assert not report.real_data_available
    assert all(item.identifiability_status is not IdentifiabilityStatus.IDENTIFIABLE for item in report.assessments)


@pytest.mark.parametrize("crop,variety", [("tomato", "RAF"), ("pepper", "Lamuyo"), ("grape", "Monastrell"), ("plum", "Suplum 26")])
def test_known_variety_scope_is_preserved(crop, variety):
    report = analyzer().analyze_all(crop=crop, variety=variety)
    assert report.by_variety(crop, variety)
    assert all(item.variety in {None, variety} for item in report.assessments)


def test_synthetic_data_does_not_upgrade_scientific_readiness():
    report = analyzer().analyze_all(synthetic_dataset(), crop="tomato", variety="RAF")
    assert report.synthetic_data_only
    assert not report.real_data_available
    assert all(item.identifiability_status is not IdentifiabilityStatus.IDENTIFIABLE for item in report.assessments)
    assert any("synthetic" in warning.lower() for item in report.assessments for warning in item.scientific_warnings)


def test_calibration_permission_is_independent_from_identifiability():
    report = analyzer().analyze_all()
    allowed = next(item for item in report.assessments if item.calibration_allowed)
    assert allowed.identifiability_status in {IdentifiabilityStatus.INSUFFICIENT_DATA, IdentifiabilityStatus.CONFOUNDED, IdentifiabilityStatus.ENVIRONMENT_SPECIFIC, IdentifiabilityStatus.VARIETY_SPECIFIC}


def test_fixed_and_not_calibratable_states_are_explicit():
    fixed_record = ParameterRecord("fixed.test", "fixed", "fixed parameter", "engineering_default", "test", None, None, None, "u", 1.0, 0, 2, "engineering_default", None, "test", "none", "low", "fixed", False, "none")
    not_allowed = ParameterIdentifiabilityAnalyzer(ParameterRegistry((fixed_record,))).analyze_all()
    assert not_allowed.assessments[0].identifiability_status is IdentifiabilityStatus.FIXED

    na_record = ParameterRecord("na.test", "not applicable", "not applicable", "engineering_default", "test", None, None, None, "u", 1.0, 0, 2, "engineering_default", None, "test", "none", "low", "not_applicable", True, "none")
    assert ParameterIdentifiabilityAnalyzer(ParameterRegistry((na_record,))).analyze_all().assessments[0].identifiability_status is IdentifiabilityStatus.NOT_CALIBRATABLE


def test_unknown_parameter_is_controlled_and_confounders_are_explicit():
    with pytest.raises(ValueError):
        analyzer().analyze_parameter("does.not.exist")
    groups = analyzer().confounder_matrix()
    assert groups
    assert any(len(parameter_ids) > 1 for parameter_ids in groups.values())
    rue = next(item for item in analyzer().analyze_all().assessments if item.parameter_id == "radiation.rue")
    assert rue.confounders


def test_deterministic_serializable_and_read_only():
    registry = ParameterRegistry.from_repository(ROOT)
    before = registry.records
    first = analyzer().analyze_all().to_dict()
    second = analyzer().analyze_all().to_dict()
    assert first == second
    assert registry.records == before
    assert isinstance(first["assessments"], list)
