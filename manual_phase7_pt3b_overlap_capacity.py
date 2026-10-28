"""PT-3b: do interactions, grouping and the interaction-free score matter when three perturbations overlap AND the cooling capacity is reduced?

    python -u manual_phase7_pt3b_overlap_capacity.py

PT-2 used a design in which only one pair interacts (grouping zero by structure) and a capacity at which the controller masks the temperature. PT-2c showed material grouping effects with three overlapping players at the
full capacity (tomato, seed 0). PT-3a showed the masking breaks when the capacity is reduced. Here the overlapping design of PT-2c (heat wave +8 degC, high-radiation x1.3, cold wave -6 degC, all hours 48-96 of the
window, the cold wave's offset adds to the heat wave's) is explained under both policies at cooling-capacity scales 1, 0.5, 0.3 and 0.15, for the three crops (seed 0): 8 coalitions per policy.

READING RULES, fixed before the runs (provisional conventions; same minimums as PT-2: 1 kWh, 1 h, 0.05 K):
* R2 interaction: |sum of leave-one-out effects - contrast| / |contrast| above 0.10 is a "material interaction" (material cells only).
* R4 grouping: |merged share - sum of members' shares| / |contrast| above 0.10 is a "material grouping effect", over the three pairwise merges.
* R3 interaction-free score: does the top player equal the exact one, and the largest |interaction-free - exact| / |contrast|.
* Results are counts and ranges per capacity scale; the question is whether saturation changes them. One seed per crop: no inference, no claim about greenhouses in general.
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import manual_phase7_pt2_effects_family as pt2  # noqa: E402
import manual_phase7_pt2b_grouping_power as pt2b  # noqa: E402
import manual_phase7_pt2c_overlap_grouping as pt2c  # noqa: E402
import manual_phase7_pt3_capacity_sweep as pt3  # noqa: E402
from tsxai.core import ScenarioDescriptor, content_hash  # noqa: E402
from tsxai.effects import EffectQuery, Policy, ResimulationEngine, coalition_values, grouping_discrepancy, relative_gap, shapley_exact, singleton_effects, top_player  # noqa: E402

from agri_twin.application.seasonal_synthetic_campaign import campaign_cycle  # noqa: E402
from agri_twin.interfaces.xai_adapter import TwinSimulator  # noqa: E402

REPORT = ROOT / "data" / "xai" / "effects_pt3b_overlap_capacity.json"
SCALES = (1.0, 0.5, 0.3, 0.15)
KEEP = ("cooling_energy", "hours_temperature_above_stage_max", "temperature_peak")


def run_cell(crop: str, scale: float) -> dict:
    simulator = TwinSimulator()
    labels = {"crop": crop, "environment": "greenhouse", "control": "on"}
    start = pt2.WINDOW_START[crop]
    options = pt3.scaled_options(dict(simulator.scenario_options(labels, 0)), scale)
    desc = ScenarioDescriptor(labels, 0, start, pt2.WINDOW_HOURS, options)
    outs = tuple(o for o in pt2.outcomes(crop, (campaign_cycle(crop)[1] + timedelta(hours=start)).month) if o.name in KEEP)
    engine = ResimulationEngine(simulator)
    names = [p.name for p in pt2c.PLAYERS]
    rows = []
    for label in ("reactive", "replayed"):
        report = engine.evaluate(EffectQuery(desc, outs, pt2c.PLAYERS, policy=Policy(label)))
        for out in outs:
            o = report["outcomes"][out.name]
            total, minimum = o["total_effect"], pt2.MINIMUM[out.name]
            if abs(total) < minimum:
                continue
            values = coalition_values(report, out.name)
            single = singleton_effects(report, out.name)
            tol = pt2.TIE_FRACTION * minimum
            merges = {}
            for pair in combinations(names, 2):
                cn, coarse = pt2b.merged_game(names, values, pair)
                shares = shapley_exact(cn, coarse)
                merged = f"{pair[0]}+{pair[1]}"
                gap = grouping_discrepancy({merged: shares[merged]}, o["shapley"], {merged: pair})[merged]
                merges[merged] = relative_gap(gap, total, minimum)
            rows.append({"policy": label, "outcome": out.name, "total_effect": total, "shapley": o["shapley"], "interaction_relative_gap": relative_gap(o["interaction_gap"], total, minimum),
                         "merge_relative_discrepancy": merges, "s1_top_agrees": top_player(o["shapley"], tol) == top_player(single, tol),
                         "s1_max_relative_error": max(abs(single[p] - o["shapley"][p]) for p in o["shapley"]) / abs(total), "efficiency_residual": o["efficiency_residual"]})
    return {"crop": crop, "scale": scale, "cooling_capacity_kw": options["control"]["equipment"]["cooling_capacity_kw"], "rows": rows}


def main() -> int:
    cells = []
    for crop in pt2.CROPS:
        for scale in SCALES:
            c = run_cell(crop, scale)
            cells.append(c)
            gaps = [r["interaction_relative_gap"] for r in c["rows"] if r["interaction_relative_gap"] is not None]
            merges = [v for r in c["rows"] for v in r["merge_relative_discrepancy"].values() if v is not None]
            print(crop, f"scale {scale:<5}", "material cells", len(c["rows"]), "| interaction gap max", None if not gaps else round(max(gaps), 3), ">0.10:", sum(g > 0.10 for g in gaps),
                  "| merges >0.10:", sum(m > 0.10 for m in merges), "of", len(merges), "max", None if not merges else round(max(merges), 3),
                  "| S1 top agrees", sum(r["s1_top_agrees"] for r in c["rows"]), "of", len(c["rows"]), "max err", None if not c["rows"] else round(max(r["s1_max_relative_error"] for r in c["rows"]), 3), flush=True)
    assert all(abs(r["efficiency_residual"]) < 1e-6 for c in cells for r in c["rows"])
    out = {"status": "DEVELOPMENT: one seed per crop, three overlapping perturbations, cooling capacity scaled; no inference", "scales": list(SCALES), "cells": cells}
    out["report_hash"] = content_hash(out)
    REPORT.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
