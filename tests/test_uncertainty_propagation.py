"""Tests for explicit uncertainty propagation in Phase 5.22."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from agri_twin.application.sensitivity import (
    ParameterSensitivityAnalyzer,
    RangeSourceType,
    UncertaintyPropagationResult,
    UncertaintyStatus,
)
from agri_twin.domain.parameter_audit import ParameterRegistry

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def analyzer() -> ParameterSensitivityAnalyzer:
    registry = ParameterRegistry.from_repository(ROOT)
    return ParameterSensitivityAnalyzer(registry, root=ROOT)


def test_uncertainty_propagation_deterministic_bounds(analyzer: ParameterSensitivityAnalyzer):
    res = analyzer.propagate_uncertainty("radiation.rue", crop="tomato")
    assert res.target_id == "radiation.rue"
    assert res.crop == "tomato"
    assert res.nominal_value > 0
    assert res.low_value < res.nominal_value < res.high_value
    assert res.output_spread >= 0
    assert math.isfinite(res.nominal_output)
    assert math.isfinite(res.low_output)
    assert math.isfinite(res.high_output)


def test_uncertainty_propagation_reproducible_monte_carlo(analyzer: ParameterSensitivityAnalyzer):
    res1 = analyzer.propagate_uncertainty(
        "radiation.rue", crop="tomato", monte_carlo=True, seed=12345, num_samples=25
    )
    res2 = analyzer.propagate_uncertainty(
        "radiation.rue", crop="tomato", monte_carlo=True, seed=12345, num_samples=25
    )
    assert res1.monte_carlo_enabled
    assert res1.monte_carlo_quantiles["mean"] == pytest.approx(res2.monte_carlo_quantiles["mean"])
    assert res1.monte_carlo_quantiles["p50"] == pytest.approx(res2.monte_carlo_quantiles["p50"])
    assert res1.monte_carlo_quantiles["std"] == pytest.approx(res2.monte_carlo_quantiles["std"])
    assert res1.monte_carlo_quantiles["p10"] <= res1.monte_carlo_quantiles["p50"] <= res1.monte_carlo_quantiles["p90"]


def test_uncertainty_propagation_unspecified_range_handles_unknown(analyzer: ParameterSensitivityAnalyzer):
    param_id = "crop.tomato.establishment.stress_thresholds.min_temp_c"
    res = analyzer.propagate_uncertainty(param_id, crop="tomato")
    assert res.target_id == param_id
    assert res.range_source_type is RangeSourceType.UNKNOWN
    assert res.uncertainty_status is UncertaintyStatus.UNCERTAINTY_NOT_SPECIFIED


def test_uncertainty_propagation_serializable_to_dict(analyzer: ParameterSensitivityAnalyzer):
    res = analyzer.propagate_uncertainty(
        "greenhouse.cover_transmission", crop="tomato", monte_carlo=True, seed=42, num_samples=10
    )
    data = res.to_dict()
    assert isinstance(data, dict)
    assert data["target_id"] == "greenhouse.cover_transmission"
    assert "nominal_output" in data
    assert "monte_carlo_quantiles" in data
    assert "p50" in data["monte_carlo_quantiles"]
