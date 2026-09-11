from __future__ import annotations

from pathlib import Path

from agri_twin.application import (
    ParameterSensitivityAnalyzer,
    RealAgronomicDatasetProvider,
    ScientificReadinessGate,
    SyntheticAgronomicDatasetProvider,
)
from agri_twin.domain import ParameterRegistry

ROOT = Path(__file__).resolve().parents[1]


def test_synthetic_provider_exports_common_contract_and_provenance():
    provider = SyntheticAgronomicDatasetProvider(ROOT)
    dataset = provider.load()
    assert dataset.name.startswith("synthetic_real_data_substitute")
    assert dataset.source_type == "synthetic"
    assert dataset.observations
    assert {item.crop for item in dataset.observations if item.crop} >= {"tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple"}
    assert all(item.source_type == "synthetic" for item in dataset.observations)
    manifest = provider.manifest
    assert manifest.source_type == "synthetic"
    assert manifest.provenance == "SIMULATED_REAL_DATA_SUBSTITUTE"
    assert manifest.synthetic is True
    assert manifest.substitution_ready is True


def test_real_provider_substitutes_same_dataset_contract_without_changing_pipeline():
    synthetic = SyntheticAgronomicDatasetProvider(ROOT)
    synthetic_dataset = synthetic.load()
    real = RealAgronomicDatasetProvider(ROOT)
    real_dataset = real.load()
    assert synthetic_dataset.name == real_dataset.name
    assert synthetic_dataset.role == real_dataset.role
    assert synthetic_dataset.observations[0].variable == real_dataset.observations[0].variable


def test_sensitivity_is_deterministic_and_registry_immutable():
    registry = ParameterRegistry.from_repository(ROOT)
    before = tuple(record.parameter_id for record in registry.records)
    analyzer = ParameterSensitivityAnalyzer(registry, root=ROOT)
    first = analyzer.analyze_parameter("radiation.rue")
    second = analyzer.analyze_parameter("radiation.rue")
    assert first.to_dict() == second.to_dict()
    assert tuple(record.parameter_id for record in registry.records) == before
    assert first.parameter_id == "radiation.rue"
    assert first.normalized_sensitivity >= -1e9
    assert "synthetic" in first.scientific_interpretation.lower()


def test_readiness_gate_stays_conservative_with_synthetic_dataset():
    report = ScientificReadinessGate(ROOT).evaluate()
    assert report.data_readiness in {"INSUFFICIENT_DATA", "PARTIAL"}
    assert report.real_agronomic_data_verified is False
    assert report.calibration_status.startswith("CALIBRATION_BLOCKED")
