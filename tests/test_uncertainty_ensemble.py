from __future__ import annotations

from pathlib import Path

import pytest

from agri_twin.application.uncertainty_ensemble import (
    ScenarioEnsembleGenerator,
    UncertaintyDefinition,
    UncertaintyDistribution,
    UncertaintySource,
)
from agri_twin.domain.parameter_audit import ParameterRegistry

ROOT = Path(__file__).resolve().parents[1]


def test_uncertainty_definition_validates_known_distribution_contracts():
    with pytest.raises(ValueError):
        UncertaintyDefinition(
            parameter_id="radiation.rue",
            name="RUE",
            nominal_value=2.0,
            lower_bound=1.0,
            upper_bound=3.0,
            source=UncertaintySource.SCIENTIFIC,
            provenance="SIMULATED_REAL_DATA_SUBSTITUTE",
            distribution=UncertaintyDistribution.NORMAL,
            unit="dimensionless",
            context="parameter",
            mean=None,
            std=None,
        )

    definition = UncertaintyDefinition(
        parameter_id="radiation.rue",
        name="RUE",
        nominal_value=2.0,
        lower_bound=1.0,
        upper_bound=3.0,
        source=UncertaintySource.SCIENTIFIC,
        provenance="SIMULATED_REAL_DATA_SUBSTITUTE",
        distribution=UncertaintyDistribution.UNIFORM,
        unit="dimensionless",
        context="parameter",
    )
    assert definition.nominal_value == pytest.approx(2.0)
    assert definition.distribution is UncertaintyDistribution.UNIFORM


def test_ensemble_generator_is_deterministic_and_state_isolated():
    registry = ParameterRegistry.from_repository(ROOT)
    before = tuple(record.parameter_id for record in registry.records)

    generator_a = ScenarioEnsembleGenerator(registry, seed=123, sample_count=12, crop="tomato")
    generator_b = ScenarioEnsembleGenerator(registry, seed=123, sample_count=12, crop="tomato")
    ensemble_a = generator_a.generate(method="monte_carlo", parameter_ids=("radiation.rue", "greenhouse.cover_transmission"))
    ensemble_b = generator_b.generate(method="monte_carlo", parameter_ids=("radiation.rue", "greenhouse.cover_transmission"))

    assert ensemble_a.to_dict() == ensemble_b.to_dict()
    assert tuple(record.parameter_id for record in registry.records) == before
    assert ensemble_a.summary["valid_members"] == ensemble_b.summary["valid_members"]


def test_unknown_uncertainty_remains_explicit_and_not_fabricated():
    generator = ScenarioEnsembleGenerator(ParameterRegistry.from_repository(ROOT), seed=99, sample_count=6, crop="lettuce")
    definition = UncertaintyDefinition(
        parameter_id="crop.lettuce.establishment.unknown",
        name="Unknown coastal threshold",
        nominal_value=1.0,
        lower_bound=None,
        upper_bound=None,
        source=UncertaintySource.UNKNOWN,
        provenance="UNCERTAINTY_NOT_SPECIFIED",
        distribution=UncertaintyDistribution.BOUNDED,
        unit="dimensionless",
        context="parameter",
        scientific_documented=False,
    )
    assert definition.source is UncertaintySource.UNKNOWN
    assert definition.provenance == "UNCERTAINTY_NOT_SPECIFIED"
    assert generator._is_unknown_uncertainty(definition) is True


def test_report_hash_and_ensemble_summary_are_stable():
    registry = ParameterRegistry.from_repository(ROOT)
    generator = ScenarioEnsembleGenerator(registry, seed=77, sample_count=10, crop="tomato")
    ensemble = generator.generate(method="corners", parameter_ids=("radiation.rue", "greenhouse.cover_transmission"))
    report = generator.build_report(ensemble)

    assert report["configuration_hash"]
    assert report["ensemble"]["summary"]["total_members"] >= 2
    assert report["ensemble"]["summary"]["valid_members"] >= 1
    assert report["dataset_provenance"] == "SIMULATED_REAL_DATA_SUBSTITUTE"
