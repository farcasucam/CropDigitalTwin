from __future__ import annotations

import re
from pathlib import Path

from agri_twin.application.scientific_benchmark import (
    BenchmarkDefinition,
    BenchmarkStatus,
    ScientificBenchmarkSuite,
    _ensemble_summary,
)
from agri_twin.application.uncertainty_ensemble import EnsembleMember

ROOT = Path(__file__).resolve().parents[1]


def _minimal_definition(suite: ScientificBenchmarkSuite) -> BenchmarkDefinition:
    definition = suite.default_definition()
    return BenchmarkDefinition("minimal", definition.cases[:1])


def test_minimal_benchmark_integrates_scenario_sensitivity_uncertainty_and_ensemble():
    suite = ScientificBenchmarkSuite(ROOT)
    report = suite.run(_minimal_definition(suite))
    result = report.results[0]

    assert result.status is BenchmarkStatus.SUCCESS
    assert result.scenario_id
    assert result.start_time.tzinfo is not None
    assert result.end_time > result.start_time
    assert result.model_configuration_hash
    assert result.parameter_configuration_hash
    assert result.input_hash
    assert result.result_hash
    assert result.sensitivity["oat"]["parameter_id"] == "radiation.rue"
    assert result.sensitivity["multivariable"]["parameter_1"] == "radiation.rue"
    assert result.uncertainty["report"]["dataset_provenance"] == "SIMULATED_REAL_DATA_SUBSTITUTE"
    assert result.ensemble["valid_members"] == 6
    assert result.ensemble["statistics"]["mean"] >= result.ensemble["statistics"]["min"]


def test_benchmark_is_deterministic_and_hashes_are_stable():
    first_suite = ScientificBenchmarkSuite(ROOT)
    first = first_suite.run(_minimal_definition(first_suite))
    second_suite = ScientificBenchmarkSuite(ROOT)
    second = second_suite.run(_minimal_definition(second_suite))

    assert first.to_json() == second.to_json()
    assert first.configuration_hash == second.configuration_hash
    assert first.results[0].result_hash == second.results[0].result_hash


def test_matrix_covers_crops_plots_environments_and_lettuce_cycles():
    suite = ScientificBenchmarkSuite(ROOT)
    definition = suite.default_definition()
    cases = definition.cases
    assert {case.scenario.crop for case in cases} >= {"tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple"}
    assert {case.environment for case in cases} == {"outdoor", "greenhouse"}
    assert {case.plot_id for case in cases if case.plot_id} >= {"plot_14705", "plot_12010", "plot_30412", "plot_40811"}
    assert {case.cycle_id for case in cases if case.scenario.crop == "lettuce"} == {"annual-1", "annual-2", "annual-3"}
    assert next(case for case in cases if case.scenario.crop == "lettuce").scenario.variety is None


def test_baseline_comparison_is_explicitly_synthetic():
    suite = ScientificBenchmarkSuite(ROOT)
    result = suite.run(_minimal_definition(suite)).results[0]
    assert result.comparison is not None
    assert result.comparison.label == "SYNTHETIC_SOFTWARE_BENCHMARK"
    assert "not biological validation" in result.comparison.interpretation.lower()
    assert all(metric.category.value in {"software_metric", "scientific_metric", "robustness_metric"} for metric in result.metrics)


def test_invalid_ensemble_members_are_counted_without_being_treated_as_valid():
    ensemble = type("SyntheticEnsemble", (), {"members": (
        EnsembleMember("valid", {"p": 1.0}, {"biomass": 2.0}),
        EnsembleMember("invalid", {}, {}, False, "NON_CONVERGENCE"),
    )})()
    summary = _ensemble_summary(ensemble)
    assert summary["valid_members"] == 1
    assert summary["invalid_members"] == 1
    assert summary["failed_members"] == ["NON_CONVERGENCE"]


def test_energyplus_is_optional_and_wall_clock_is_absent_from_benchmark_module():
    suite = ScientificBenchmarkSuite(ROOT)
    assert suite.energyplus_status() in {"ENERGYPLUS_AVAILABLE", "ENERGYPLUS_UNAVAILABLE"}
    source = (ROOT / "src" / "agri_twin" / "application" / "scientific_benchmark.py").read_text(encoding="utf-8")
    forbidden = (
        "datetime." + "now",
        "datetime." + "utcnow",
        "time." + "time",
        "time." + "sleep",
        "perf_" + "counter",
        "numpy." + "random",
        "re" + "quests",
        "url" + "lib",
        "sock" + "et",
    )
    assert not any(token in source for token in forbidden)


def test_report_contains_required_scientific_guardrails():
    suite = ScientificBenchmarkSuite(ROOT)
    report = suite.run(_minimal_definition(suite))
    payload = report.to_dict()
    assert payload["artifact_status"] == "SYNTHETIC_SOFTWARE_BENCHMARK"
    assert payload["real_data_status"] == "REAL AGRONOMIC DATA NOT VERIFIED"
    assert payload["calibration_status"] == "CALIBRATION NOT PERFORMED"
    assert payload["validation_status"] == "EXPERIMENTAL VALIDATION NOT CLAIMED"
    assert payload["assimilation_status"] == "DATA ASSIMILATION NOT IMPLEMENTED"
