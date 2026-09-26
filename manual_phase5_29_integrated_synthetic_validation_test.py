"""Offline delivery verification for Phase 5.29: Integrated Synthetic Validation.

Runs the full synthetic suite twice, checks every section, writes the canonical
artifact and prints the scientific status. Known open findings (for example the
closed-greenhouse feedback defect) are expected to be *detected*; they are
reported, never hidden, and they keep the corresponding qualification open.
"""

from __future__ import annotations

import sys
from pathlib import Path

from agri_twin.application.integrated_synthetic_validation import IntegratedSyntheticValidationSuite

ROOT = Path(__file__).resolve().parent
PASSING = {"PASS", "PASS_WITH_WARNINGS"}
EXPECTED_OPEN_FINDINGS = {"greenhouse.crop_greenhouse_feedback": "INVARIANT_VIOLATION"}


def main() -> int:
    suite = IntegratedSyntheticValidationSuite(ROOT)
    report = suite.build_report()
    repeated = IntegratedSyntheticValidationSuite(ROOT).build_report()
    payload = report.to_dict()
    cases = {item["case_id"]: item for item in payload["cases"]}
    summary = payload["summary"]

    print("chain=weather -> greenhouse/outdoor -> microclimate -> crop -> stress -> recovery -> TwinState -> snapshot -> diagnostics -> integrated report")
    for case_id in (
        "p529_tomato_outdoor_normal_season",
        "p529_tomato_greenhouse_normal_season",
        "p529_lettuce_greenhouse_normal_season",
        "p529_pepper_outdoor_normal_season",
        "p529_grape_outdoor_normal_season",
        "p529_plum_outdoor_normal_season",
        "p529_peach_outdoor_normal_season",
        "p529_apple_outdoor_normal_season",
        "p529_tomato_outdoor_water_stress_recovery",
        "p529_tomato_outdoor_heat_wave_recovery",
        "p529_tomato_greenhouse_combined_stress",
    ):
        item = cases[case_id]
        observed = item["observed_outputs"]
        print(f"case={case_id} status={item['status']} stage={observed['final_stage']} maturity={observed['final_maturity']:.3f} biomass_g_m2={observed['final_biomass_g_m2']:.2f} peak_water_stress={observed['peak_water_stress']:.3f} peak_heat_damage={observed['peak_heat_damage']:.3f}")
    lettuce = payload["multi_cycle"]["lettuce_cycles"]
    print(f"lettuce_cycles={ {key: value['status_sequence'] for key, value in lettuce.items()} } second_cycle_fresh={payload['multi_cycle']['second_cycle_starts_from_fresh_state']}")
    print(f"restart={[(c['case_id'], [p['max_abs_difference'] for p in c['checkpoints']]) for c in payload['restart']['cases']]}")
    print(f"multi_plot combined_equals_isolated={payload['multi_plot']['combined_equals_isolated_runs']} perturbation_isolated={payload['multi_plot']['perturbation_isolated']}")
    feedback = payload["greenhouse"]["crop_greenhouse_feedback"]["runs"]
    for name, run in feedback.items():
        print(f"feedback={name} status={run['status']} converged={run['converged_steps']}/{run['steps']} max_iterations={run['max_iterations']} min_dT={run['min_indoor_minus_outdoor_c']:.2f} latent_at_saturation={run['latent_flux_at_saturation_steps']}")

    assert report.to_json() == repeated.to_json(), "integrated report is not deterministic"
    assert summary["total_cases"] == 30
    assert all(item["status"] in PASSING for item in payload["cases"]), "a synthetic validation case failed"
    assert set(summary["crops"]) == {"tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple"}
    assert {"RAF", "Lamuyo", "Monastrell", "Suplum 26"} <= set(summary["varieties"])
    assert payload["robustness"]["passed"] == payload["robustness"]["total"] == 24
    assert payload["transferability"]["real_verified_sources"] == 0
    assert payload["mutation"]["before"] == payload["mutation"]["after"]
    for section, status in summary["section_status"].items():
        expected = EXPECTED_OPEN_FINDINGS.get(section)
        if expected is not None:
            assert status == expected, f"{section}: expected open finding {expected}, got {status}"
        elif section == "transferability":
            assert status == "DATA_INSUFFICIENT"
        elif section == "greenhouse.energyplus":
            assert status in {"NOT_APPLICABLE", "PASS"}
        else:
            assert status in PASSING, f"{section} is {status}"

    report_path, readme_path = suite.write_report(report)
    print(f"artifact={report_path.relative_to(ROOT).as_posix()} readme={readme_path.relative_to(ROOT).as_posix()}")
    print(f"configuration_hash={report.configuration_hash} report_hash={payload['report_hash']}")
    timings = report.execution_metadata["timings_seconds"]
    print("performance=" + " ".join(f"{key}:{value:.1f}s" for key, value in timings.items()) + f" cost_per_case:{timings['scenario_execution_seconds'] / summary['total_cases']:.2f}s (regression tracking only)")
    for finding in payload["findings"]:
        print(f"finding={finding['code']} severity={finding['severity']}")
    qualification = summary["qualification"]
    scientific = summary["scientific_status"]
    print("PHASE 5.29 COMPLETE")
    print("INTEGRATED SYNTHETIC VALIDATION READY")
    for name, label in (
        ("SYNTHETIC_MODEL_CONSISTENCY", "SYNTHETIC MODEL CONSISTENCY"),
        ("TEMPORAL_CONTINUITY", "TEMPORAL CONTINUITY"),
        ("PERSISTENT_STATE_CONSISTENCY", "PERSISTENT STATE CONSISTENCY"),
        ("MULTI_PLOT_CONSISTENCY", "MULTI-PLOT CONSISTENCY"),
        ("MULTI_CYCLE_CONSISTENCY", "MULTI-CYCLE CONSISTENCY"),
        ("GREENHOUSE_CROP_INTEGRATION", "GREENHOUSE-CROP INTEGRATION"),
        ("ROBUSTNESS_SCENARIOS", "ROBUSTNESS SCENARIOS"),
    ):
        print(f"{label} {qualification[name].replace('_', ' ')}")
    print(f"REAL_VERIFIED = {scientific['REAL_VERIFIED']}")
    print("REAL AGRICULTURAL DATA NOT VERIFIED")
    print("SCIENTIFIC EXPERIMENTAL VALIDATION DEFERRED TO FINAL VALIDATION STAGE")
    print("BIOLOGICAL VALIDITY NOT CLAIMED")
    print("FIELD ACCURACY NOT CLAIMED")
    print(f"CALIBRATION_PERFORMED = {str(scientific['CALIBRATION_PERFORMED']).lower()}")
    print(f"EXPERIMENTAL_VALIDATION_PERFORMED = {str(scientific['EXPERIMENTAL_VALIDATION_PERFORMED']).lower()}")
    print("DATA ASSIMILATION NOT IMPLEMENTED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
