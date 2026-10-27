"""PT-2b: every pairwise merge of the four players, the grouping test PT-2 could not make powerful.

    python -u manual_phase7_pt2b_grouping_power.py

PT-2 merged the heat wave and the radiation spell, but the cold wave and the wind spell barely interact with anything (separated in time, and the wind spell has no material effect), so that merge was almost certain to
leave the shares unchanged: a test with little power. Here, for each of the nine episodes and both policies, the base game's 16 coalition values give the game of any merge of two players (the merged player is ON when
both members are), so all six pairs are tested with no new kind of run. For each pair and each material outcome: |share of the merged player - sum of its members' shares in the fine game| / |contrast|, and how the
shares of the other players move.

READING RULE, fixed before the runs (same convention as PT-2's R4): a pair is a "material grouping effect" for an outcome when that relative discrepancy exceeds 0.10; a cell is MATERIAL when |contrast| is at least the
outcome's declared minimum (1 kWh, 1 h, 0.05 K). Results are counts and ranges, per pair, with no test and no claim beyond these nine cells of one synthetic generator. Control: merging a player with a null player
must give exactly zero, and any merge must keep the total (efficiency).
"""

from __future__ import annotations

import json
import statistics
import sys
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import manual_phase7_pt2_effects_family as pt2  # noqa: E402
from tsxai.core import ScenarioDescriptor, content_hash  # noqa: E402
from tsxai.effects import EffectQuery, Policy, ResimulationEngine, coalition_values, grouping_discrepancy, relative_gap, shapley_exact  # noqa: E402

from agri_twin.application.seasonal_synthetic_campaign import campaign_cycle  # noqa: E402
from agri_twin.interfaces.xai_adapter import TwinSimulator  # noqa: E402
from datetime import timedelta  # noqa: E402

OUT_DIR = ROOT / "data" / "xai" / "effects_pt2_groupings"
SUMMARY = ROOT / "data" / "xai" / "effects_pt2_groupings_summary.json"


def merged_game(names: list[str], values: dict, pair: tuple[str, str]) -> tuple[list[str], dict]:
    """The game in which ``pair`` is one player: a coalition of the new players is ON for the union of their members."""
    merged = f"{pair[0]}+{pair[1]}"
    coarse_names = [merged] + [n for n in names if n not in pair]
    coarse = {}
    for size in range(len(coarse_names) + 1):
        for chosen in combinations(coarse_names, size):
            fine = frozenset(m for n in chosen for m in (pair if n == merged else (n,)))
            coarse[frozenset(chosen)] = values[fine]
    return coarse_names, coarse


def run_episode(crop: str, season: int) -> dict:
    simulator = TwinSimulator()
    labels = {"crop": crop, "environment": "greenhouse", "control": "on"}
    start = pt2.WINDOW_START[crop]
    desc = ScenarioDescriptor(labels, season, start, pt2.WINDOW_HOURS, simulator.scenario_options(labels, season))
    outs = pt2.outcomes(crop, (campaign_cycle(crop)[1] + timedelta(hours=start)).month)
    engine = ResimulationEngine(simulator)
    players = pt2.base_players()
    names = [p.name for p in players]
    cells = []
    for label in ("reactive", "replayed"):
        report = engine.evaluate(EffectQuery(desc, outs, players, policy=Policy(label)))
        for out in outs:
            o = report["outcomes"][out.name]
            total, minimum = o["total_effect"], pt2.MINIMUM[out.name]
            if abs(total) < minimum:
                continue
            values = coalition_values(report, out.name)
            for pair in combinations(names, 2):
                coarse_names, coarse = merged_game(names, values, pair)
                shares = shapley_exact(coarse_names, coarse)
                merged = f"{pair[0]}+{pair[1]}"
                gap = grouping_discrepancy({merged: shares[merged]}, o["shapley"], {merged: pair})[merged]
                others = {n: shares[n] - o["shapley"][n] for n in coarse_names if n != merged}
                null_member = any(abs(o["shapley"][m]) < 1e-9 for m in pair)
                cells.append({"policy": label, "outcome": out.name, "pair": list(pair), "total_effect": total, "relative_discrepancy": relative_gap(gap, total, minimum),
                              "efficiency_residual": sum(shares.values()) - total, "other_players_share_change": others, "has_null_member": null_member})
    return {"episode": {"crop": crop, "season": season}, "cells": cells}


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    episodes = []
    for crop in pt2.CROPS:
        for season in pt2.SEASONS:
            path = OUT_DIR / f"{crop}_s{season}.json"
            if not path.exists():
                path.write_text(json.dumps(run_episode(crop, season), indent=1, sort_keys=True) + "\n", encoding="utf-8")
                print(f"{crop}:{season} done", flush=True)
            episodes.append(json.loads(path.read_text(encoding="utf-8")))
    cells = [dict(c, episode=f"{e['episode']['crop']}:{e['episode']['season']}") for e in episodes for c in e["cells"]]
    assert max(abs(c["efficiency_residual"]) for c in cells) < 1e-6, "a merge must keep the total"
    assert all(c["relative_discrepancy"] < 1e-6 for c in cells if c["has_null_member"]), "merging with a null player must change nothing"
    spread = lambda xs: {"n": len(xs), "min": min(xs), "median": statistics.median(xs), "max": max(xs)} if xs else {"n": 0}
    by_pair = {}
    for pair in sorted({tuple(c["pair"]) for c in cells}):
        rel = [c["relative_discrepancy"] for c in cells if tuple(c["pair"]) == pair]
        by_pair["+".join(pair)] = {"cells": len(rel), "relative_discrepancy": spread(rel), "material_above_10_percent": sum(1 for r in rel if r > 0.10)}
    non_null = [c["relative_discrepancy"] for c in cells if not c["has_null_member"]]
    summary = {
        "status": "DEVELOPMENT: nine cells of one synthetic generator; counts and ranges only",
        "material_outcome_cells": len({(c["episode"], c["policy"], c["outcome"]) for c in cells}), "merge_cells": len(cells),
        "all_merges": {"relative_discrepancy": spread([c["relative_discrepancy"] for c in cells]), "material_above_10_percent": sum(1 for c in cells if c["relative_discrepancy"] > 0.10)},
        "merges_without_a_null_member": {"relative_discrepancy": spread(non_null), "material_above_10_percent": sum(1 for r in non_null if r > 0.10), "cells": len(non_null)},
        "by_pair": by_pair,
        "max_abs_efficiency_residual": max(abs(c["efficiency_residual"]) for c in cells),
    }
    summary["summary_hash"] = content_hash(summary)
    SUMMARY.write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
