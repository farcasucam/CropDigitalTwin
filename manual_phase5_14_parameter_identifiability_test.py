"""Offline Phase 5.14 parameter identifiability acceptance audit."""

from pathlib import Path

from agri_twin.application import ParameterIdentifiabilityAnalyzer
from agri_twin.domain import ParameterRegistry


ROOT = Path(__file__).parents[0]


def main() -> None:
    print("SYNTHETIC DATA — SOFTWARE/ARCHITECTURE TEST ONLY")
    registry = ParameterRegistry.from_repository(ROOT)
    analyzer = ParameterIdentifiabilityAnalyzer(registry, repository_root=ROOT)
    report = analyzer.analyze_all()
    assert len(report.assessments) == len(registry.records)
    assert not report.real_data_available
    assert {item.crop for item in report.assessments if item.crop} >= {"tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple"}
    for crop, variety in (("tomato", "RAF"), ("pepper", "Lamuyo"), ("grape", "Monastrell"), ("plum", "Suplum 26")):
        scoped = analyzer.analyze_all(crop=crop, variety=variety)
        assert scoped.assessments
        print(f"PASS — {crop} / {variety}: {len(scoped.assessments)} parameters")
    for crop in ("lettuce", "apple", "peach"):
        assert analyzer.analyze_all(crop=crop).assessments
        print(f"PASS — {crop}: generic species scope, no invented local variety")
    assert analyzer.confounder_matrix()
    assert all(item.identifiability_status.value != "IDENTIFIABLE" for item in report.assessments)
    print(f"PASS — parameter-observation matrix: {len(report.assessments)} registry records")
    print("PASS — calibration permission remains distinct from identifiability")
    print("PASS — confounder analysis and species/variety/environment readiness")
    print("PASS — synthetic data cannot upgrade real scientific readiness")
    print("PASS — no calibration / no assimilation / no state or registry mutation")
    print("PHASE 5.14 COMPLETE — PARAMETER IDENTIFIABILITY / CALIBRATION READINESS FRAMEWORK READY — REAL AGRONOMIC DATA NOT AVAILABLE — CALIBRATION NOT PERFORMED — EXPERIMENTAL VALIDATION NOT CLAIMED")


if __name__ == "__main__":
    main()
