"""PT-10a: the effect queries on the Tennessee Eastman process (second domain), truth by re-simulation, reactive against replayed actuation.

    TEP_SRC=<source directory of the tep package> python -u manual_phase7_pt10a_tennessee.py

The simulator is the third-party Python backend of the Braatz-group TEP (see `src/process_twins/tennessee_eastman.py`); the technical check that preceded this package (seed, snapshot, replay of the manipulated variables)
is in the memory notes. DEVELOPMENT: no data-based method, no calibration, the plant is a benchmark of the literature, not a real plant.

DESIGN (fixed before the run). One sample per second; window of 1800 s starting at second 600 of the run (the plant has run 10 minutes of its closed loop with the seed's noise); seasons 1, 2, 3 = noise seeds 2, 3, 4.
Players (disturbances of the plant, each 1200 s long): idv1 (A/C feed ratio, step, from index 100), idv4 (reactor cooling water inlet temperature, step, from index 300), idv5 (condenser cooling water inlet temperature, step, from index 200).
Truth: exact Shapley over 8 coalitions, reference = no disturbance. Outcomes: maximum reactor pressure (xmeas_07, kPa), mean reactor temperature (xmeas_09, C), mean reactor level (xmeas_08, percent),
mean reactor cooling water valve (mv_10, percent: what the controller did about it). Policies: REACTIVE (the plant's controller everywhere); REPLAYED, source = the reference (all twelve manipulated variables imposed as the undisturbed run applied them);
COOLING REPLAYED (only mv_10 and mv_11, the two cooling water valves, imposed; the rest stays under the closed loop).

READING RULES, fixed before the run (per season, no inference):
* the engine's own check that replaying the source's trace reproduces the source run must hold;
* inviable coalitions (the plant shuts down) are reported with their reason, never dropped;
* per outcome and policy: total effect, Shapley shares, the interaction gap relative to the sum of absolute shares;
* CONTROLLER COMPENSATION: for each player and each outcome, the ratio of its share under the reactive policy to its share under the replayed one, and whether the sign is the same; the difference between the policies is the part of the
  explanation that exists only because the plant reacts. Counts and ranges over the seasons, no significance claims (three noise seeds, one disturbance design).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from tsxai.core import Intervention, ScenarioDescriptor, content_hash  # noqa: E402
from tsxai.effects import EffectQuery, Outcome, Player, Policy, ResimulationEngine  # noqa: E402

from process_twins.tennessee_eastman import TennesseeEastman  # noqa: E402

REPORT = ROOT / "data" / "xai" / "effects_pt10a_tennessee.json"
FIRST, COUNT, SEASONS = 600, 1800, (1, 2, 3)
PLAYERS = (Player("idv1", (Intervention("IDV1", 100, 1200),)), Player("idv4", (Intervention("IDV4", 300, 1200),)), Player("idv5", (Intervention("IDV5", 200, 1200),)))
OUTCOMES = (Outcome("reactor_pressure_max", "xmeas_07", "max", "kPa"), Outcome("reactor_temperature_mean", "xmeas_09", "mean", "C"),
            Outcome("reactor_level_mean", "xmeas_08", "mean", "percent"), Outcome("reactor_cooling_valve_mean", "mv_10", "mean", "percent"))
POLICIES = {"reactive": Policy("reactive"), "replayed_all": Policy("replayed"), "replayed_cooling": Policy("replayed", (), ("mv_10", "mv_11"))}


def summarise(report: dict) -> dict:
    out = {}
    for name, o in report["outcomes"].items():
        scale = sum(abs(v) for v in o["shapley"].values())
        out[name] = {"total_effect": o["total_effect"], "shapley": o["shapley"], "interaction_relative_to_sum_abs_shares": abs(o["interaction_gap"]) / scale if scale else 0.0}
    return {"outcomes": out, "policy_check": report["policy_check"],
            "inviable": [{"players": c["players"], "reason": c["reason"]} for c in report["coalitions"] if c["status"] != "ok"]}


def main() -> int:
    if not os.environ.get("TEP_SRC"):
        raise SystemExit("set TEP_SRC to the source directory of the tep package")
    host = TennesseeEastman()
    results = {}
    for season in SEASONS:
        t0 = time.time()
        desc = ScenarioDescriptor({"plant": "tennessee_eastman_base_case"}, season, FIRST, COUNT, {})
        engine = ResimulationEngine(host)
        results[str(season)] = {label: summarise(engine.evaluate(EffectQuery(desc, OUTCOMES, PLAYERS, policy=policy))) for label, policy in POLICIES.items()}
        print("season", season, round(time.time() - t0), "s,", engine.runs, "runs, snapshot hits", host.snapshot_hits, flush=True)
    compensation = {}
    for season, by_policy in results.items():
        for outcome in by_policy["reactive"]["outcomes"]:
            for player in (p.name for p in PLAYERS):
                r = by_policy["reactive"]["outcomes"][outcome]["shapley"][player]
                p = by_policy["replayed_all"]["outcomes"][outcome]["shapley"][player]
                compensation.setdefault(outcome, {}).setdefault(player, {})[season] = {"reactive": r, "replayed": p, "ratio": (r / p) if p else None, "same_sign": (r * p > 0) if (r and p) else None}
    out = {"status": "DEVELOPMENT: Tennessee Eastman (third-party python backend), truth by re-simulation, three noise seeds, one disturbance design, no data-based method", "window": [FIRST, COUNT], "seasons": list(SEASONS),
           "results": results, "compensation": compensation, "simulator": host.name}
    out["report_hash"] = content_hash(out)
    REPORT.write_text(json.dumps(out, indent=1, sort_keys=True, default=float) + "\n", encoding="utf-8")
    print(json.dumps({"checks": {s: {p: v["policy_check"] for p, v in by.items() if v["policy_check"]} for s, by in results.items()}}, default=float)[:1500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
