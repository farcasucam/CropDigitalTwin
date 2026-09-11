"""Tests for physical and numerical robustness analysis in Phase 5.22."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from agri_twin.application.sensitivity import (
    ParameterSensitivityAnalyzer,
    RobustnessResult,
)
from agri_twin.domain.parameter_audit import ParameterRegistry

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def analyzer() -> ParameterSensitivityAnalyzer:
    registry = ParameterRegistry.from_repository(ROOT)
    return ParameterSensitivityAnalyzer(registry, root=ROOT)


def test_robustness_evaluates_twelve_stress_cases(analyzer: ParameterSensitivityAnalyzer):
    results = analyzer.analyze_robustness(crop="tomato", environment="GREENHOUSE")
    assert len(results) == 12
    case_ids = {r.case_id for r in results}
    expected = {
        "extreme_heat_55c",
        "extreme_frost_minus10c",
        "zero_solar_night",
        "extreme_solar_1500w",
        "arid_high_vpd",
        "saturated_rh_100pct",
        "wilting_point_soil",
        "extreme_ventilation_30ach",
        "high_co2_1200ppm",
        "heavy_shading_80pct",
        "monotonicity_radiation",
        "monotonicity_extinction",
    }
    assert case_ids == expected


def test_robustness_all_outputs_are_finite(analyzer: ParameterSensitivityAnalyzer):
    results = analyzer.analyze_robustness(crop="tomato", environment="GREENHOUSE")
    for res in results:
        assert res.numerical_stability, f"Numerical stability failed for {res.case_id}"
        for name, val in res.perturbed_outputs.items():
            assert math.isfinite(val), f"Output {name} is non-finite in {res.case_id}: {val}"


def test_robustness_physical_bounds_are_respected(analyzer: ParameterSensitivityAnalyzer):
    results = analyzer.analyze_robustness(crop="tomato", environment="GREENHOUSE")
    for res in results:
        assert res.physical_bounds_valid, f"Physical bounds failed for {res.case_id}: {res.warnings}"
        outputs = res.perturbed_outputs
        assert 0.0 <= outputs["relative_humidity"] <= 100.0
        assert outputs["biomass"] >= 0.0
        assert outputs["lai"] >= 0.0
        assert outputs["solar_radiation"] >= 0.0
        assert outputs["co2"] >= 0.0
        assert outputs["transpiration"] >= 0.0


def test_robustness_radiation_monotonicity(analyzer: ParameterSensitivityAnalyzer):
    results = analyzer.analyze_robustness(crop="tomato", environment="GREENHOUSE")
    rad_case = next(r for r in results if r.case_id == "monotonicity_radiation")
    assert rad_case.passed
    assert rad_case.monotonicity_valid is True


def test_robustness_extinction_monotonicity(analyzer: ParameterSensitivityAnalyzer):
    results = analyzer.analyze_robustness(crop="tomato", environment="GREENHOUSE")
    ext_case = next(r for r in results if r.case_id == "monotonicity_extinction")
    assert ext_case.passed
    assert ext_case.monotonicity_valid is True


def test_robustness_feedback_converges_under_stress(analyzer: ParameterSensitivityAnalyzer):
    results = analyzer.analyze_robustness(crop="tomato", environment="GREENHOUSE")
    for res in results:
        assert res.feedback_converged, f"Feedback did not converge for {res.case_id}"


def test_robustness_serializable_to_dict(analyzer: ParameterSensitivityAnalyzer):
    results = analyzer.analyze_robustness(crop="tomato", environment="GREENHOUSE")
    first = results[0]
    data = first.to_dict()
    assert isinstance(data, dict)
    assert data["case_id"] == first.case_id
    assert "baseline_outputs" in data
    assert "perturbed_outputs" in data
    assert data["passed"] is True
