"""PT-2c: a grouping check on a design where three players overlap in time, so that the game can be coupled beyond one pair.

    python -u manual_phase7_pt2c_overlap_grouping.py

PT-2b found that merging any two players of PT-2's design changes nothing (maximum relative discrepancy 8e-8). That is expected by structure, not a property of Shapley shares: there the only interacting pair is the
heat wave and the radiation spell, the cold wave and the wind spell are additive or null, and merging inside an isolated pair keeps the total of that sub-game. To see whether the machinery shows a grouping
effect when it exists, one episode (tomato, seed 0) is run with three perturbations that overlap in the same 48 hours: a heat wave (+8 degC), a high-radiation spell (x1.3) and a cold wave (-6 degC, whose offset
adds to the heat wave's in the twin, so their net is +2 degC while the radiation multiplies). Eight coalitions per policy.

READING RULE, fixed before the run (same convention as PT-2b): a merge is a "material grouping effect" for an outcome when |merged share - sum of members' shares| / |contrast| exceeds 0.10, on outcomes whose |contrast|
is at least the declared minimum (1 kWh, 1 h, 0.05 K). One episode: this shows whether grouping can matter in this twin, not how often. A result of "no material effect" here would also be reported.
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import manual_phase7_pt2_effects_family as pt2  # noqa: E402
import manual_phase7_pt2b_grouping_power as pt2b  # noqa: E402
from tsxai.core import Intervention, ScenarioDescriptor, content_hash  # noqa: E402
from tsxai.effects import EffectQuery, Player, Policy, ResimulationEngine, coalition_values, grouping_discrepancy, relative_gap, shapley_exact  # noqa: E402

from agri_twin.application.seasonal_synthetic_campaign import campaign_cycle  # noqa: E402
from agri_twin.interfaces.xai_adapter import TwinSimulator  # noqa: E402

REPORT = ROOT / "data" / "xai" / "effects_pt2c_overlap_grouping.json"
PLAYERS = (Player("heat_wave", (Intervention("HEAT_WAVE", 48, 48, 8.0),)), Player("high_radiation", (Intervention("HIGH_RADIATION", 48, 48, 1.3),)),
           Player("cold_wave", (Intervention("COLD_WAVE", 48, 48, 6.0),)))


def main() -> int:
    simulator = TwinSimulator()
    labels = {"crop": "tomato", "environment": "greenhouse", "control": "on"}
    start = pt2.WINDOW_START["tomato"]
    desc = ScenarioDescriptor(labels, 0, start, pt2.WINDOW_HOURS, simulator.scenario_options(labels, 0))
    outs = pt2.outcomes("tomato", (campaign_cycle("tomato")[1] + timedelta(hours=start)).month)
    engine = ResimulationEngine(simulator)
    names = [p.name for p in PLAYERS]
    cells = []
    for label in ("reactive", "replayed"):
        report = engine.evaluate(EffectQuery(desc, outs, PLAYERS, policy=Policy(label)))
        for out in outs:
            o = report["outcomes"][out.name]
            total, minimum = o["total_effect"], pt2.MINIMUM[out.name]
            if abs(total) < minimum:
                continue
            values = coalition_values(report, out.name)
            row = {"policy": label, "outcome": out.name, "total_effect": total, "shapley": o["shapley"], "leave_one_out": o["leave_one_out"], "interaction_relative_gap": relative_gap(o["interaction_gap"], total, minimum), "merges": {}}
            for pair in combinations(names, 2):
                coarse_names, coarse = pt2b.merged_game(names, values, pair)
                shares = shapley_exact(coarse_names, coarse)
                merged = f"{pair[0]}+{pair[1]}"
                gap = grouping_discrepancy({merged: shares[merged]}, o["shapley"], {merged: pair})[merged]
                row["merges"][merged] = {"merged_share": shares[merged], "sum_of_members_shares": sum(o["shapley"][m] for m in pair), "relative_discrepancy": relative_gap(gap, total, minimum)}
            cells.append(row)
    worst = max((m["relative_discrepancy"] for c in cells for m in c["merges"].values()), default=None)
    report_out = {"status": "DEVELOPMENT: one episode, a demonstration of whether grouping can matter, not of how often", "episode": {"labels": labels, "season": 0, "window_start_hour": start, "players_overlap_hours": [48, 96]},
                  "cells": cells, "max_relative_discrepancy": worst, "material_merges_above_10_percent": sum(1 for c in cells for m in c["merges"].values() if m["relative_discrepancy"] is not None and m["relative_discrepancy"] > 0.10),
                  "merges": sum(len(c["merges"]) for c in cells)}
    report_out["report_hash"] = content_hash(report_out)
    REPORT.write_text(json.dumps(report_out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for c in cells:
        print(c["policy"], c["outcome"], "contrast", round(c["total_effect"], 3), "interaction gap", None if c["interaction_relative_gap"] is None else round(c["interaction_relative_gap"], 3),
              {k: None if v["relative_discrepancy"] is None else round(v["relative_discrepancy"], 3) for k, v in c["merges"].items()})
    print("max relative discrepancy", worst, "| material merges", report_out["material_merges_above_10_percent"], "of", report_out["merges"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
