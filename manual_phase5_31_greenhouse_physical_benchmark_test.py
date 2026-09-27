"""Offline delivery verification for Phase 5.31: greenhouse physical benchmark.

Runs the analytical benchmark suite, prints a representative subset, writes the
canonical artifact and exits 0 only if every mandatory benchmark passes. All
values are synthetic model outputs; nothing is calibrated or observed.
"""

from __future__ import annotations

import sys
from pathlib import Path

from agri_twin.application.greenhouse_physical_benchmark import BenchmarkStatus, GreenhousePhysicalBenchmarkSuite

ROOT = Path(__file__).resolve().parent
SHOWCASE = (
    ("1 thermal equilibrium", "energy.identical_ambient_no_drift"),
    ("1 energy closure", "energy.radiation_energy_closure"),
    ("2 ventilation sweep", "ventilation.temperature_toward_outdoor"),
    ("3 saturation/VPD", "latent.saturated_air_no_cooling"),
    ("3 closed greenhouse regression", "humidity.closed_saturated_greenhouse_no_latent_regression"),
    ("4 radiation/shading", "radiation.shading"),
    ("5 CO2 single path", "co2.single_path_to_growth"),
    ("6 indoor crop temperature", "crop_microclimate.greenhouse_temperature"),
    ("7 feedback", "feedback.combined_convergence_determinism"),
    ("8 deterministic replay", "determinism.scenario_replay"),
)


def main() -> int:
    suite = GreenhousePhysicalBenchmarkSuite(ROOT)
    report = suite.build_report()
    repeated = GreenhousePhysicalBenchmarkSuite(ROOT).build_report()
    cases = {case.case_id: case for case in report.cases}
    for label, case_id in SHOWCASE:
        case = cases[case_id]
        print(f"{label}: {case.status.value} [{case.layer.value}] {case.actual_relation}")
    failures = [case for case in report.cases if case.mandatory and case.status is BenchmarkStatus.FAIL]
    for case in failures:
        print(f"FAIL {case.case_id} ({case.classification}): {case.actual_relation}")
    print(f"cases={len(report.cases)} counts={report.counts} invariants={report.invariants['status']} traceability={report.traceability['status']} static_audit={report.static_audit['status']} energyplus={report.energyplus['availability']}")
    deterministic = report.to_json() == repeated.to_json()
    print(f"deterministic_report={deterministic}")
    report_path, readme_path = suite.write_report(report)
    payload = report.to_dict()
    print(f"artifact={report_path.relative_to(ROOT).as_posix()} readme={readme_path.relative_to(ROOT).as_posix()} report_hash={payload['report_hash']}")
    if failures or not report.qualified or not deterministic:
        print("GREENHOUSE PHYSICAL BENCHMARKS NOT QUALIFIED")
        return 1
    for line in (
        "PHASE 5.31 COMPLETE",
        "GREENHOUSE PHYSICAL BENCHMARKS QUALIFIED",
        "GREENHOUSE ENERGY-BALANCE SOFTWARE CONSISTENCY QUALIFIED",
        "MICROCLIMATE TRANSFER QUALIFIED",
        "VENTILATION / HUMIDITY / CO2 RELATIONSHIPS QUALIFIED",
        "GREENHOUSE-CROP FEEDBACK PHYSICALLY CONSISTENT UNDER SYNTHETIC BENCHMARKS",
        "DETERMINISTIC REPLAY QUALIFIED",
        "REAL AGRICULTURAL DATA NOT VERIFIED",
        "CALIBRATION NOT PERFORMED",
        "EXPERIMENTAL VALIDATION DEFERRED TO FINAL VALIDATION STAGE",
        "BIOLOGICAL VALIDITY NOT CLAIMED",
        "FIELD ACCURACY NOT CLAIMED",
        "DATA ASSIMILATION NOT IMPLEMENTED",
    ):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
