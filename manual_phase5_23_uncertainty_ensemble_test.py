"""Offline delivery verification for Phase 5.23."""

from __future__ import annotations

from pathlib import Path

from agri_twin.application.uncertainty_ensemble import (
    ScenarioEnsembleGenerator,
    UncertaintyDefinition,
    UncertaintyDistribution,
    UncertaintySource,
)
from agri_twin.domain.parameter_audit import ParameterRegistry

ROOT = Path(__file__).resolve().parent


def main() -> None:
    print("=" * 80)
    print("PHASE 5.23 MANUAL DELIVERY VERIFICATION")
    print("Scientific Uncertainty & Scenario Ensemble Framework")
    print("=" * 80)

    registry = ParameterRegistry.from_repository(ROOT)
    before = tuple(record.parameter_id for record in registry.records)
    generator = ScenarioEnsembleGenerator(registry, seed=2026, sample_count=12, crop="tomato")

    definition = UncertaintyDefinition(
        parameter_id="radiation.rue",
        name="Radiation use efficiency",
        nominal_value=2.0,
        lower_bound=1.0,
        upper_bound=3.0,
        source=UncertaintySource.SCIENTIFIC,
        provenance="SIMULATED_REAL_DATA_SUBSTITUTE",
        distribution=UncertaintyDistribution.UNIFORM,
        unit="g_DM_MJ_PAR-1",
        context="parameter",
    )
    assert definition.nominal_value == 2.0
    print(f"[1] Uncertainty contract: {definition.parameter_id} / {definition.distribution.value}")

    corners = generator.generate(method="corners", parameter_ids=("radiation.rue", "greenhouse.cover_transmission"))
    monte_carlo = generator.generate(method="monte_carlo", parameter_ids=("radiation.rue", "greenhouse.cover_transmission"))
    repeated = ScenarioEnsembleGenerator(registry, seed=2026, sample_count=12, crop="tomato").generate(
        method="monte_carlo", parameter_ids=("radiation.rue", "greenhouse.cover_transmission")
    )
    assert monte_carlo.to_dict() == repeated.to_dict()
    assert corners.summary["total_members"] >= 2
    assert monte_carlo.summary["valid_members"] == 12
    print(f"[2] Deterministic ensembles: corners={len(corners.members)}, monte_carlo={len(monte_carlo.members)}")

    unknown = UncertaintyDefinition(
        parameter_id="unknown.parameter",
        name="Unspecified parameter",
        nominal_value=1.0,
        source=UncertaintySource.UNKNOWN,
        provenance="UNCERTAINTY_NOT_SPECIFIED",
        distribution=UncertaintyDistribution.UNCERTAINTY_NOT_SPECIFIED,
        unit="dimensionless",
        context="parameter",
    )
    assert generator._is_unknown_uncertainty(unknown)
    print("[3] Unknown uncertainty remains explicitly unspecified")

    report = generator.build_report(monte_carlo)
    assert report["configuration_hash"]
    assert report["dataset_provenance"] == "SIMULATED_REAL_DATA_SUBSTITUTE"
    assert report["calibration_status"] == "CALIBRATION NOT PERFORMED"
    assert report["validation_status"] == "EXPERIMENTAL VALIDATION NOT CLAIMED"
    assert tuple(record.parameter_id for record in registry.records) == before
    print(f"[4] Report hash: {report['configuration_hash'][:16]}...")
    print("[5] ParameterRegistry zero-mutation check: PASS")

    print("=" * 80)
    print("PHASE 5.23 COMPLETE")
    print("SYNTHETIC UNCERTAINTY ENSEMBLE QUALIFIED")
    print("REAL AGRONOMIC DATA NOT VERIFIED")
    print("CALIBRATION NOT PERFORMED")
    print("EXPERIMENTAL VALIDATION NOT CLAIMED")
    print("DATA ASSIMILATION NOT IMPLEMENTED")
    print("=" * 80)


if __name__ == "__main__":
    main()
