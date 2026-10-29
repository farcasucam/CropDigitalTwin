"""Level 0 of the nutrient line: the FERTILIZATION runtime event and the nutrient series, checked offline.

    python -u manual_phase7_nutrient_level0.py

WHAT IS NEW. The twin's reduced single-pool nutrient model (uncalibrated, ENGINEERING_APPROXIMATION) is now reachable from the interactive simulation: the runtime event FERTILIZATION states a TOTAL dose in kg/ha over
its interval, split evenly over the steps and ADDED to the available pool (events add up; the pool is capped at the reserve), and five series are exposed: pool, offered, extracted, leached, status. No model equation changed.
This script checks the contract and shows what the reduced model does with a dose (a response of the MODEL, not an agronomic response: nothing here is calibrated):
* the default run applies nothing; a dose is spread evenly and equals the total offered; two overlapping events add; a dose that does not fit above the reserve is discarded (the offered series still counts it);
* the dose-response of the end biomass and of the end pool for several doses (tomato, outdoor, DEV season 34, 336 h from hour 1500, dose over 24 h from window hour 100);
* the same total dose early (hour 20) against late (hour 280), a first look at timing.
Deterministic: the report is written under data/xai/ with its hash.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from tsxai.core import Intervention, ScenarioDescriptor, content_hash  # noqa: E402

from agri_twin.interfaces.xai_adapter import TwinSimulator  # noqa: E402

REPORT = ROOT / "data" / "xai" / "nutrient_level0.json"
DOSES = (0.0, 12.0, 24.0, 48.0, 100.0, 900.0)


def main() -> int:
    simulator = TwinSimulator()
    labels = {"crop": "tomato", "environment": "outdoor", "control": "off"}
    desc = ScenarioDescriptor(labels, 34, 1500, 336, simulator.scenario_options(labels, 34))
    base = simulator.run(desc, ())
    assert sum(base.series["nutrient_applied_kg_ha"]) == 0.0
    rows = []
    for dose in DOSES:
        run = base if dose == 0 else simulator.run(desc, (Intervention("FERTILIZATION", 100, 24, dose),))
        offered = sum(run.series["nutrient_applied_kg_ha"])
        assert abs(offered - dose) < 1e-9
        rows.append({"dose_kg_ha": dose, "offered": offered, "pool_end": run.series["nutrient_available_kg_ha"][-1], "status_end": run.series["nutrient_status"][-1],
                     "biomass_end_difference_g_m2": run.series["biomass_total_g_m2"][-1] - base.series["biomass_total_g_m2"][-1], "pool_maximum": max(run.series["nutrient_available_kg_ha"])})
    assert max(r["pool_maximum"] for r in rows) <= 200.0 + 1e-9  # the baseline reserve
    both = simulator.run(desc, (Intervention("FERTILIZATION", 100, 24, 12.0), Intervention("FERTILIZATION", 110, 24, 12.0)))
    assert abs(sum(both.series["nutrient_applied_kg_ha"]) - 24.0) < 1e-9
    timing = {}
    for name, start in (("early_hour_20", 20), ("late_hour_280", 280)):
        run = simulator.run(desc, (Intervention("FERTILIZATION", start, 24, 24.0),))
        timing[name] = {"pool_end": run.series["nutrient_available_kg_ha"][-1], "biomass_end_difference_g_m2": run.series["biomass_total_g_m2"][-1] - base.series["biomass_total_g_m2"][-1]}
    out = {"status": "DEVELOPMENT: contract check of the nutrient event and series; the reduced model is uncalibrated, the numbers are responses of the model, not agronomic results",
           "episode": {"crop": "tomato", "environment": "outdoor", "season": 34, "window_start_hour": 1500, "window_hours": 336}, "baseline": {"pool_start": base.series["nutrient_available_kg_ha"][0],
           "pool_end": base.series["nutrient_available_kg_ha"][-1], "status_end": base.series["nutrient_status"][-1]}, "dose_response": rows, "timing_24_kg_ha": timing}
    out["report_hash"] = content_hash(out)
    REPORT.write_text(json.dumps(out, indent=1, sort_keys=True, default=float) + "\n", encoding="utf-8")
    print(json.dumps({"baseline": out["baseline"], "dose_response": rows, "timing": timing}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
