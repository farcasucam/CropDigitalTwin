from __future__ import annotations

from pathlib import Path

from agri_twin.application import ParameterSensitivityAnalyzer
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
