"""Offline delivery verification for Phase 5.32: season-scale synthetic campaigns.

Runs the full scenario x crop x environment matrix, prints the mandatory
showcase cases, writes the canonical artifact and exits 0 only if every
mandatory case passes. All values are synthetic model outputs.
"""

from __future__ import annotations

import sys
from pathlib import Path

from agri_twin.application.seasonal_synthetic_campaign import BEHAVIOR_CONSISTENT, CampaignStatus, SeasonalSyntheticCampaignSuite

ROOT = Path(__file__).resolve().parent
SHOWCASE = (
    ("1 BASE_SEASON", "p532_tomato_outdoor_base_season"),
    ("2 HEAT_WAVE", "p532_tomato_outdoor_heat_wave"),
    ("3 LOW_RADIATION", "p532_tomato_outdoor_low_radiation"),
    ("4 DRY_SEASON", "p532_pepper_outdoor_dry_season"),
    ("5 greenhouse season", "p532_tomato_greenhouse_base_season"),
    ("6 perennial season", "p532_plum_outdoor_base_season"),
)


def main() -> int:
    suite = SeasonalSyntheticCampaignSuite(ROOT)
    report = suite.build_report()
    runs = {result.spec.run_id: result for result in report.campaigns}
    directions = {row["run_id"]: row for row in report.sections["directions"]}
    for label, run_id in SHOWCASE:
        result = runs[run_id]
        m = result.metrics
        extra = f" direction={directions[run_id]['classification']}" if run_id in directions else ""
        print(f"{label}: {result.status.value} days={result.spec.days} biomass={m['final_biomass_g_m2']:.1f} lai={m['final_lai']:.3f} maturity={m['final_maturity']:.3f} "
              f"heat_stress_h={result.stress['heat']['hours']:.0f} water_stress_h={result.stress['water']['stress_hours']:.1f} mean_T={m['mean_crop_temperature_c']:.2f}{extra}")
    restart = report.sections["restart"]
    print(f"7 checkpoint/restart: {restart['status']} " + " ".join(f"{run['run_id']}:{[row['max_difference'] for row in run['checkpoints']]}" for run in restart["runs"]))
    print(f"8 deterministic replay: {report.sections['determinism']['status']} replayed={len(report.sections['determinism']['replayed_runs'])}")
    print(f"9 multi-plot: {report.sections['multi_plot']['status']} multi-cycle: {report.sections['multi_cycle']['status']}")
    summary = report.summary()
    print(f"campaigns={summary['campaigns']} status={summary['status_counts']} direction_rows={summary['direction_rows']} inconsistent={summary['inconsistent_rows']}")
    print(f"sections={summary['section_status']}")
    for item in report.open_decisions:
        print(f"OPEN_SCIENTIFIC_DECISION {item['crop']}: {item['decision']}")
    for item in report.unsupported:
        print(f"{item['status']} {item['capability']}")
    report_path, readme_path = suite.write_report(report)
    payload = report.to_dict()
    print(f"artifact={report_path.relative_to(ROOT).as_posix()} readme={readme_path.relative_to(ROOT).as_posix()} report_hash={payload['report_hash']}")
    print(f"performance: total={report.execution_metadata['total_seconds']:.1f}s per_simulated_day={report.execution_metadata['seconds_per_simulated_day']:.4f}s (execution metadata only)")
    mandatory_ok = (
        all(result.status is not CampaignStatus.FAIL for result in report.campaigns)
        and summary["inconsistent_rows"] == 0
        and all(status in {"PASS", "PASS_WITH_WARNINGS"} for status in summary["section_status"].values())
        and all(directions[run_id]["classification"] == BEHAVIOR_CONSISTENT for _, run_id in SHOWCASE if run_id in directions)
    )
    if not mandatory_ok or not summary["qualified"]:
        print("SEASON-SCALE SYNTHETIC CAMPAIGN FRAMEWORK NOT QUALIFIED")
        return 1
    for line in (
        "PHASE 5.32 COMPLETE",
        "SEASON-SCALE SYNTHETIC CAMPAIGN FRAMEWORK QUALIFIED",
        "SYNTHETIC CLIMATE SCENARIOS QUALIFIED",
        "FULL-CAMPAIGN TEMPORAL CONSISTENCY QUALIFIED",
        "STRESS RESPONSE CONSISTENCY QUALIFIED",
        "MULTI-PLOT CONSISTENCY QUALIFIED",
        "CHECKPOINT / RESTART CONSISTENCY QUALIFIED",
        "DETERMINISTIC REPLAY QUALIFIED",
        "GREENHOUSE SEASONAL COUPLING QUALIFIED",
        f"SEASON RESPONSES NOT CHARACTERISED (OPEN_SCIENTIFIC_DECISION): {', '.join(item['crop'] for item in report.open_decisions) or 'none'}",
        "REAL AGRICULTURAL DATA NOT VERIFIED",
        "REAL_VERIFIED = 0",
        "CALIBRATION NOT PERFORMED",
        "CALIBRATION_PERFORMED = false",
        "EXPERIMENTAL VALIDATION DEFERRED TO FINAL VALIDATION STAGE",
        "EXPERIMENTAL_VALIDATION_PERFORMED = false",
        "BIOLOGICAL VALIDITY NOT CLAIMED",
        "FIELD ACCURACY NOT CLAIMED",
        "DATA ASSIMILATION NOT IMPLEMENTED",
    ):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
