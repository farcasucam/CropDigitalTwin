from pathlib import Path

import pytest

from agri_twin.domain import ParameterAudit, ParameterAuditError, ParameterRecord, ParameterRegistry


ROOT = Path(__file__).resolve().parents[1]


def record(**changes):
    values = dict(
        parameter_id="test.parameter", name="test", description="test parameter", category="biological", subsystem="test",
        crop="tomato", variety=None, phenological_stage="vegetative_growth", unit="degC", value=10.0, minimum=0.0, maximum=20.0,
        source_type="engineering_default", source_reference=None, source_detail="test", evidence_level="none", confidence="low",
        calibration_status="candidate_for_calibration", calibration_allowed=True, observational_data_required="observations",
    )
    values.update(changes)
    return ParameterRecord(**values)


def test_valid_parameter_is_accepted():
    assert record().parameter_id == "test.parameter"


@pytest.mark.parametrize("changes", [
    {"unit": None},
    {"value": 30.0},
    {"source_type": "literature", "source_reference": None},
    {"source_type": "calibrated", "calibration_status": "not_calibrated"},
    {"crop": "unknown_crop"},
])
def test_invalid_parameter_metadata_is_rejected(changes):
    if changes == {"unit": None}:
        assert "missing unit: test.parameter" in ParameterAudit((record(**changes),)).validate()
    else:
        with pytest.raises(ParameterAuditError):
            record(**changes)


def test_engineering_default_is_explicit_and_duplicate_is_detected():
    audit = ParameterAudit((record(), record()))

    assert audit.validate() == ("duplicate parameter_id: test.parameter",)
    assert audit.summary["engineering_defaults"] == 2


def test_repository_covers_crops_and_generates_deterministic_audit(tmp_path):
    registry = ParameterRegistry.from_repository(ROOT)
    first = registry.audit()
    second = registry.audit()

    assert len(registry.records) > 100
    assert {record.crop for record in registry.records if record.crop} >= {"tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple"}
    assert first == second
    report = tmp_path / "audit.md"
    registry.write_report(report)
    assert report.read_text(encoding="utf-8").startswith("# Parameter Audit Report")


def test_traceability_for_external_evidence_preserves_generic_variety_scope():
    registry = ParameterRegistry.from_repository(ROOT)
    tomato_evidence = registry.get("evidence.tomato_tbase_001")

    assert tomato_evidence.source_type == "literature"
    assert tomato_evidence.variety is None
    assert tomato_evidence.calibration_status == "candidate_for_calibration"


def test_current_runtime_engines_remain_importable_after_audit():
    registry = ParameterRegistry.from_repository(ROOT)

    assert "PAR_FRACTION" in registry.get("radiation.par_fraction").used_by
    assert registry.get("radiation.rue").source_type == "engineering_default"