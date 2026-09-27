"""Offline delivery verification for Phase 5.33: dormancy / chilling framework.

Runs the eight manual cases, builds and writes the canonical artifact, and ends
with PASS for the software checks plus the explicit scientific decision (policy
uncertainty / open decisions), which is never converted into a PASS.
"""

from __future__ import annotations

import sys
from pathlib import Path

from agri_twin.application.dormancy_chilling_framework import DormancyChillingFrameworkSuite

ROOT = Path(__file__).resolve().parent


def main() -> int:
    suite = DormancyChillingFrameworkSuite(ROOT)
    report = suite.build_report()
    payload = report.to_dict()
    experiments = payload["experiments"]

    def row(location: str, crop: str) -> dict:
        return next(item for item in experiments["policy_matrix"]["rows"] if item["location_id"] == location and item["crop"] == crop and item["experiment"] == "DORMANCY_STATE")

    cases = [
        ("1 Peach - Northern Hemisphere", row("NH_38N_MEDITERRANEAN", "peach")),
        ("2 Peach - Southern Hemisphere", row("SH_35S_TEMPERATE", "peach")),
        ("3 Apple - Northern Hemisphere", row("NH_50N_CONTINENTAL", "apple")),
        ("4 Apple - Southern Hemisphere", row("SH_50S_COLD", "apple")),
        ("5 Plum - Northern Hemisphere", row("NH_38N_MEDITERRANEAN", "plum")),
        ("6 Plum - Southern Hemisphere", row("SH_35S_TEMPERATE", "plum")),
    ]
    for label, item in cases:
        print(f"{label}: {item['outcome']} first_chill={item['first_effective_chill']} release={item['dormancy_release']} budburst={item['budburst']} chill_at_release={item['chill_at_release_h']}")
    calendar = experiments["calendar_independence"]
    print(f"7 Same thermal sequence, shifted dates: {calendar['status']} identical_elapsed_trajectory={calendar['dormancy_state_calendar_independent']} fixed_date_depends_on_calendar={calendar['fixed_date_depends_on_calendar']}")
    late = [item for item in experiments["phase532_reproduction"]["rows"] if item["campaign_start"] == "01-Feb"]
    print("8 Campaign started too late: " + ", ".join(f"{item['crop']}={item['outcome']}" for item in late))
    inversion = experiments["hemisphere_inversion"]
    print(f"hemisphere inversion: {inversion['status']} differences_h={[r['release_elapsed_difference_h'] for r in inversion['rows']]} negative_control_detected={inversion['negative_control']['detected']}")
    print(f"sections: {payload['section_status']}")
    report_path, readme_path = suite.write_report(report)
    print(f"artifact={report_path.relative_to(ROOT).as_posix()} readme={readme_path.relative_to(ROOT).as_posix()} report_hash={payload['report_hash']}")
    software_ok = payload["status"] == "PASS" and all(item["outcome"] == "RELEASED" for _, item in cases) and all(item["outcome"] == "INSUFFICIENT_TEMPORAL_CONTEXT" for item in late if item["crop"] in {"peach", "apple"})
    print("SOFTWARE CHECKS: " + ("PASS" if software_ok else "FAIL"))
    decision = payload["scientific_decision"]
    print(f"SCIENTIFIC DECISION: {decision['outcome']} (universal start date {decision['universal_start_date']})")
    for item in payload["open_scientific_decisions"]:
        print(f"{item['classification']}: {item['decision']}")
    print(decision["statement"])
    return 0 if software_ok else 1


if __name__ == "__main__":
    sys.exit(main())
