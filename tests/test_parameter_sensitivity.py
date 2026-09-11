from __future__ import annotations

import json
from pathlib import Path

import pytest

from agri_twin.application import (
    ParameterSensitivityAnalyzer,
    SensitivityClassification,
    SensitivityReport,
    SensitivityResult,
)
from agri_twin.domain import ParameterRegistry

ROOT = Path(__file__).resolve().parents[1]


def test_parameter_sensitivity_reports_confounders_and_baseline_change():
    registry = ParameterRegistry.from_repository(ROOT)
    analyzer = ParameterSensitivityAnalyzer(registry, root=ROOT)
    report = analyzer.analyze_parameter("radiation.rue")
    assert report.parameter_id == "radiation.rue"
    assert report.baseline_value != 0
    assert report.perturbation_percent in {-10.0, 10.0}
    assert report.absolute_change >= 0
    assert report.relative_change >= 0
    assert report.normalized_sensitivity >= 0 or report.normalized_sensitivity <= 0
    assert report.observable
    assert report.confounders


def test_parameter_sensitivity_oat_symmetric_perturbation():
    registry = ParameterRegistry.from_repository(ROOT)
    analyzer = ParameterSensitivityAnalyzer(registry, root=ROOT)
    neg, pos = analyzer.analyze_oat("radiation.rue", perturbation_percent=15.0)
    assert neg.direction == "-"
    assert neg.perturbation_percent == -15.0
    assert pos.direction == "+"
    assert pos.perturbation_percent == 15.0
    assert neg.baseline_value == pos.baseline_value
    assert neg.perturbed_value < neg.baseline_value < pos.perturbed_value


def test_parameter_sensitivity_normalized_and_absolute_scores():
    registry = ParameterRegistry.from_repository(ROOT)
    analyzer = ParameterSensitivityAnalyzer(registry, root=ROOT)
    res = analyzer.analyze_parameter("radiation.rue", observable="potential_growth")
    assert res.normalized_sensitivity > 0
    assert res.absolute_sensitivity > 0
    assert res.classification in {SensitivityClassification.HIGH, SensitivityClassification.MEDIUM, SensitivityClassification.LOW}


def test_parameter_sensitivity_confounder_groups():
    registry = ParameterRegistry.from_repository(ROOT)
    analyzer = ParameterSensitivityAnalyzer(registry, root=ROOT)
    res = analyzer.analyze_parameter("radiation.rue")
    assert "growth_scaling" in res.confounders


def test_parameter_sensitivity_covers_seven_crops():
    registry = ParameterRegistry.from_repository(ROOT)
    analyzer = ParameterSensitivityAnalyzer(registry, root=ROOT)
    crops = ("tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple")
    for crop in crops:
        env = "OUTDOOR" if crop in {"grape", "peach", "plum", "apple"} else "GREENHOUSE"
        res = analyzer.analyze_parameter("radiation.rue", crop=crop, environment=env)
        assert res.crop == crop
        assert res.baseline_output > 0


def test_parameter_sensitivity_variety_handling():
    registry = ParameterRegistry.from_repository(ROOT)
    analyzer = ParameterSensitivityAnalyzer(registry, root=ROOT)
    # Known variety
    res_raf = analyzer.analyze_parameter("radiation.rue", crop="tomato", variety="RAF")
    assert res_raf.variety == "RAF"
    # Unknown variety reports explicit notice
    res_unk = analyzer.analyze_parameter("radiation.rue", crop="lettuce", variety="UnknownCultivar")
    assert "VARIETY_SPECIFIC_DATA_NOT_AVAILABLE" in res_unk.variety


def test_parameter_sensitivity_annual_vs_perennial():
    registry = ParameterRegistry.from_repository(ROOT)
    analyzer = ParameterSensitivityAnalyzer(registry, root=ROOT)
    # Annual
    res_tom = analyzer.analyze_parameter("radiation.rue", crop="tomato", environment="GREENHOUSE")
    assert res_tom.crop == "tomato"
    # Perennial with chilling
    res_grape = analyzer.analyze_parameter("radiation.rue", crop="grape", environment="OUTDOOR")
    assert res_grape.crop == "grape"


def test_parameter_sensitivity_outdoor_vs_greenhouse():
    registry = ParameterRegistry.from_repository(ROOT)
    analyzer = ParameterSensitivityAnalyzer(registry, root=ROOT)
    gh = analyzer.analyze_parameter("greenhouse.cover_transmission", environment="GREENHOUSE")
    out = analyzer.analyze_parameter("greenhouse.cover_transmission", environment="OUTDOOR")
    assert gh.environment == "GREENHOUSE"
    assert out.environment == "OUTDOOR"


def test_parameter_sensitivity_multivariable_interaction():
    registry = ParameterRegistry.from_repository(ROOT)
    analyzer = ParameterSensitivityAnalyzer(registry, root=ROOT)
    multi = analyzer.analyze_multivariable(("radiation.rue", "radiation.extinction_coefficient"))
    assert "interaction_delta" in multi
    assert "evaluations" in multi
    assert "baseline" in multi["evaluations"]
    assert "p1_high_p2_high" in multi["evaluations"]


def test_parameter_sensitivity_zero_mutation_of_registry():
    registry = ParameterRegistry.from_repository(ROOT)
    rec_before = registry.get("radiation.rue")
    val_before = rec_before.value
    analyzer = ParameterSensitivityAnalyzer(registry, root=ROOT)
    _ = analyzer.analyze_parameter("radiation.rue", perturbation_percent=50.0)
    rec_after = registry.get("radiation.rue")
    assert rec_after.value == val_before


def test_parameter_sensitivity_report_serialization():
    registry = ParameterRegistry.from_repository(ROOT)
    analyzer = ParameterSensitivityAnalyzer(registry, root=ROOT)
    report = analyzer.run_full_analysis(crops=("tomato", "lettuce"))
    assert isinstance(report, SensitivityReport)
    assert report.provenance == "SIMULATED_REAL_DATA_SUBSTITUTE"
    assert report.real_data_status == "REAL AGRONOMIC DATA NOT VERIFIED"
    assert report.sensitivity_status == "SYNTHETIC_SENSITIVITY_QUALIFIED"
    json_str = report.to_json()
    assert isinstance(json_str, str)
    parsed = json.loads(json_str)
    assert parsed["report_id"] == report.report_id
    assert parsed["summary"]["total_cases"] == len(report.results)
    assert len(parsed["robustness_results"]) == 12
