import json
from datetime import datetime, timezone
from pathlib import Path

from agri_twin.application import (
    ScientificReadinessGate,
    ScientificReadinessStatus,
    SyntheticBenchmarkSuite,
    evaluate_scientific_readiness,
)
from agri_twin.domain import ParameterRegistry

ROOT = Path(__file__).resolve().parents[1]


EXPECTED_BENCHMARKS = {
    "determinism",
    "temporal_consistency",
    "multi_plot_isolation",
    "multi_cycle_isolation",
    "perennial_lifecycle",
    "greenhouse_feedback_contract",
    "observation_defects",
    "known_synthetic_bias",
    "parameter_identifiability_conservatism",
    "backend_substitution",
}


def test_initial_readiness_has_no_verified_real_data():
    evaluation = evaluate_scientific_readiness(ROOT)
    report = evaluation.report
    assert report.real_data_available is False
    assert report.real_agronomic_data_verified is False
    assert report.data_readiness is ScientificReadinessStatus.INSUFFICIENT_DATA
    assert report.scientific_validation_status is ScientificReadinessStatus.SCIENTIFIC_VALIDATION_REQUIRED


def test_software_readiness_is_separate_from_scientific_validation():
    report = evaluate_scientific_readiness(ROOT).report
    assert report.software_readiness is ScientificReadinessStatus.READY
    assert report.scientific_validation_status is not ScientificReadinessStatus.READY
    assert report.calibration_status == "CALIBRATION_BLOCKED: REAL_AGRONOMIC_DATA_NOT_AVAILABLE"
    assert report.assimilation_status == "NOT_IMPLEMENTED"


def test_component_matrix_covers_required_areas():
    report = evaluate_scientific_readiness(ROOT).report
    names = {item.component for item in report.component_results}
    assert names == {"mechanistic_model", "phenology", "greenhouse", "observations", "instrumentation", "identifiability"}
    assert all(item.software_status is ScientificReadinessStatus.READY for item in report.component_results)
    assert all(item.scientific_status is ScientificReadinessStatus.SCIENTIFIC_VALIDATION_REQUIRED for item in report.component_results)


def test_synthetic_benchmark_suite_has_all_required_benchmarks():
    results = SyntheticBenchmarkSuite(ROOT).run()
    assert {item.name for item in results} == EXPECTED_BENCHMARKS
    assert all(item.status == "PASS" for item in results)
    assert all("not scientific validation" in item.limitations[0] for item in results)


def test_benchmark_reports_are_deterministic():
    first = tuple(item.to_dict() for item in SyntheticBenchmarkSuite(ROOT).run())
    second = tuple(item.to_dict() for item in SyntheticBenchmarkSuite(ROOT).run())
    assert first == second


def test_report_serialization_and_hash_are_deterministic():
    first = evaluate_scientific_readiness(ROOT).report
    second = evaluate_scientific_readiness(ROOT).report
    assert first.to_dict() == second.to_dict()
    assert first.configuration_hash() == second.configuration_hash()
    assert json.dumps(first.to_dict(), sort_keys=True)


def test_report_has_explicit_scientific_blockers_and_limitations():
    report = evaluate_scientific_readiness(ROOT).report
    assert "REAL_AGRONOMIC_DATA_NOT_AVAILABLE" in report.blocking_items
    assert "VERIFIED_REAL_DATA_REQUIRED_BEFORE_CALIBRATION" in report.blocking_items
    assert "INDEPENDENT_DATASET_REQUIRED_BEFORE_EXPERIMENTAL_VALIDATION" in report.blocking_items
    assert "REAL AGRONOMIC DATASET NOT VERIFIED" in report.limitations
    assert "THRESHOLD_NOT_DEFINED for scientific acceptance metrics" in report.limitations


def test_parameter_results_preserve_identifiability_and_synthetic_blockers():
    report = evaluate_scientific_readiness(ROOT).report
    assert report.parameter_results
    for item in report.parameter_results:
        assert "parameter_id" in item
        assert "identifiability_status" in item
        assert "confounders" in item
        assert item["data_available"] is False
        assert "SYNTHETIC_DATA_NOT_SCIENTIFIC_EVIDENCE" in item["scientific_blockers"]


def test_all_crops_and_known_varieties_are_reported_without_invention():
    report = evaluate_scientific_readiness(ROOT).report
    crops = {item["crop"] for item in report.crop_results}
    assert crops == {"tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple"}
    known = {(item["crop"], item["variety"]) for item in report.crop_results}
    assert ("tomato", "RAF") in known
    assert ("pepper", "Lamuyo") in known
    assert ("grape", "Monastrell") in known
    assert ("plum", "Suplum 26") in known
    assert ("lettuce", None) in known
    assert ("peach", None) in known
    assert ("apple", None) in known


def test_outdoor_and_greenhouse_are_separate_reported_environments():
    report = evaluate_scientific_readiness(ROOT).report
    assert {item["environment"] for item in report.environment_results} == {"OUTDOOR", "GREENHOUSE"}


def test_synthetic_evidence_is_explicitly_labeled():
    report = evaluate_scientific_readiness(ROOT).report
    assert any(item.startswith("SYNTHETIC:") for item in report.evidence)
    assert all(item.status == "PASS" for item in report.benchmark_results)
    assert report.real_agronomic_data_verified is False


def test_gate_does_not_mutate_parameter_registry():
    registry = ParameterRegistry.from_repository(ROOT)
    before = tuple(registry.records)
    evaluate_scientific_readiness(ROOT)
    assert before == tuple(registry.records)


def test_no_calibration_or_machine_learning_was_added():
    source = (ROOT / "src" / "agri_twin" / "application" / "scientific_readiness.py").read_text(encoding="utf-8")
    assert "GridSearchCalibrator(" not in source
    assert "CalibrationObjective(" not in source
    assert "tensorflow" not in source.lower()
    assert "torch" not in source.lower()
    assert "xgboost" not in source.lower()


def test_optional_energyplus_is_not_required_for_readiness():
    report = evaluate_scientific_readiness(ROOT).report
    greenhouse = next(item for item in report.component_results if item.component == "greenhouse")
    assert greenhouse.software_status is ScientificReadinessStatus.READY
    assert any("EnergyPlus optional" in blocker for blocker in greenhouse.blockers)
