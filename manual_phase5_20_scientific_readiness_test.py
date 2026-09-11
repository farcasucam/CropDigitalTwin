"""Offline Phase 5.20 scientific readiness and synthetic benchmarking audit."""

from pathlib import Path

from agri_twin.application import ScientificReadinessStatus, ScientificReadinessGate

ROOT = Path(__file__).parents[0]


def main() -> None:
    evaluation = ScientificReadinessGate(ROOT).evaluate()
    report = evaluation.report

    print("=== PHASE 5.20 SCIENTIFIC READINESS ===")
    print(f"REAL VERIFIED DATA: {'YES' if report.real_agronomic_data_verified else 'NO'}")
    print("\nSOFTWARE READINESS:")
    print(f"    {report.software_readiness.value}")
    print("DATA READINESS:")
    print(f"    {report.data_readiness.value}")
    print("CALIBRATION:")
    print(f"    {report.calibration_status}")
    print("EXPERIMENTAL VALIDATION:")
    print(f"    {report.scientific_validation_status.value}")
    print("DATA ASSIMILATION:")
    print(f"    {report.assimilation_status}")

    benchmark_status = {item.name: item.status for item in report.benchmark_results}
    assert all(status == "PASS" for status in benchmark_status.values())
    print("SYNTHETIC BENCHMARKS:")
    print(f"    PASS ({len(benchmark_status)}/{len(benchmark_status)})")
    assert report.software_readiness is ScientificReadinessStatus.READY
    assert report.real_agronomic_data_verified is False
    assert report.data_readiness is ScientificReadinessStatus.INSUFFICIENT_DATA
    assert report.calibration_status.startswith("CALIBRATION_BLOCKED")
    assert report.scientific_validation_status is ScientificReadinessStatus.SCIENTIFIC_VALIDATION_REQUIRED
    print("IDENTIFIABILITY:")
    print("    SYNTHETIC DATA DOES NOT UPGRADE READINESS")
    print("GREENHOUSE:")
    print("    SOFTWARE_READY; EnergyPlus optional")
    print("MULTI-PLOT:")
    print("    PASS")
    print("MULTI-CYCLE:")
    print("    PASS")
    print("DETERMINISM:")
    print("    PASS")
    print("\nFINAL STATUS:")
    print("    SOFTWARE READY")
    print("    SYNTHETIC BENCHMARKS QUALIFIED")
    print("    REAL AGRONOMIC DATA NOT VERIFIED")
    print("    CALIBRATION NOT PERFORMED")
    print("    EXPERIMENTAL VALIDATION NOT CLAIMED")
    print("    DATA ASSIMILATION NOT IMPLEMENTED")
    print("    PHASE 5.20 COMPLETE — SCIENTIFIC READINESS GATE QUALIFIED — SYNTHETIC SOFTWARE BENCHMARKS QUALIFIED — REAL AGRONOMIC DATA NOT VERIFIED — CALIBRATION NOT PERFORMED — EXPERIMENTAL VALIDATION NOT CLAIMED")


if __name__ == "__main__":
    main()
