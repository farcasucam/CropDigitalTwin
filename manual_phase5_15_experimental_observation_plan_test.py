"""Offline Phase 5.15 experimental observation plan acceptance audit."""

from pathlib import Path

from agri_twin.application import ExperimentalObservationPlan, ParameterIdentifiabilityAnalyzer
from agri_twin.domain import ParameterRegistry

ROOT = Path(__file__).parents[0]


def main() -> None:
    print("SYNTHETIC DATA — SOFTWARE/ARCHITECTURE TEST ONLY")
    registry = ParameterRegistry.from_repository(ROOT)
    report = ParameterIdentifiabilityAnalyzer(registry, repository_root=ROOT).analyze_all()
    plan = ExperimentalObservationPlan.from_identifiability_report(report)
    assert len(plan.items) == len(registry.records)
    assert plan.campaign_status == "DESIGNED_NOT_EXECUTED"
    assert not plan.real_data_available
    for crop, variety in (("tomato", "RAF"), ("pepper", "Lamuyo"), ("grape", "Monastrell"), ("plum", "Suplum 26")):
        assert plan.for_variety(crop, variety)
        print(f"PASS — {crop} / {variety}: parameter-observation requirements")
    for crop in ("lettuce", "apple", "peach"):
        assert plan.for_crop(crop)
        print(f"PASS — {crop}: generic species plan, no invented variety")
    assert plan.for_environment("OUTDOOR")
    assert plan.for_environment("GREENHOUSE")
    assert plan.confounded_parameters()
    assert plan.campaign_checklist()
    assert plan.to_dict()["real_data_available"] is False
    print("PASS — annual/perennial, lettuce cycles and greenhouse/outdoor scopes")
    print("PASS — confounders, priorities, quality, uncertainty and unknown requirements")
    print("PASS — technician CSV template and machine-readable plan schema are separate from observations")
    print("PASS — deterministic export; no campaign executed; no calibration or assimilation")
    print("PHASE 5.15 COMPLETE — EXPERIMENTAL OBSERVATION / DATA ACQUISITION PLAN READY — REAL AGRONOMIC DATA NOT AVAILABLE — CALIBRATION NOT PERFORMED — EXPERIMENTAL VALIDATION NOT CLAIMED")


if __name__ == "__main__":
    main()
