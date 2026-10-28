"""PT-4a: the declared temporal graph of the twin (src/xai_declared_graph.json) tested by intervention.

    python -u manual_phase7_pt4a_graph_check.py

The graph was written from the orchestrator's update order BEFORE this check. A graph that is a hypothesis about the twin can be falsified here by re-simulation: one episode (tomato, season 0, greenhouse,
controller on, 336 h from hour 960), one intervention per factor at the benchmark's probe level (from window hour 48 for 72 h), compared with the unperturbed run.

For every intervention and policy the variables whose series CHANGE (any difference above 1e-9, or a different value for a categorical series) are compared with the DESCENDANTS of the intervention's entry
points in the declared graph (edges of any lag). Two kinds of disagreement, with different meaning:
* MISSING EDGE: a variable changed but is not a descendant. The graph is wrong or incomplete. This is the falsifying outcome.
* UNCHANGED DESCENDANT: predicted but the series did not move. Not a refutation: a threshold not crossed (a stress below its onset), a clipped quantity or a null effect in this episode; reported as a count and a list.
Policies: REACTIVE (the controller runs; its commands are descendants) and REPLAYED (the reference's commands imposed: the six command variables lose their incoming edges). The decision factors (irrigation,
shading, ventilation) are run reactive only, since replay would overwrite the very command they set.

READING RULE, fixed before the run: the graph is "consistent" for an intervention and policy when there is no missing edge. Any missing edge is reported with the variable, and the graph is corrected in a labelled
new version (never silently edited). Development, one episode: this tests the graph on this episode and these probe levels, not in general.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from tsxai.core import Intervention, ScenarioDescriptor, content_hash  # noqa: E402

from agri_twin.interfaces.xai_adapter import TwinSimulator  # noqa: E402

GRAPH = ROOT / "src" / "xai_declared_graph.json"
CROPS_START = {"tomato": 960, "pepper": 960, "lettuce": 336}  # the windows of PT-2
PROBE = {"HEAT_WAVE": 6.0, "COLD_WAVE": 6.0, "LOW_RADIATION": 0.5, "HIGH_RADIATION": 1.3, "WIND": 3.0, "RAIN": 4.0, "IRRIGATION": 2.0, "SHADING": 0.6, "VENTILATION": 1.0, "CO2": 1.0}
DECISION = {"IRRIGATION", "SHADING", "VENTILATION"}
COMMANDS = {"control_vent_opening", "control_extractor_level", "greenhouse_shading_fraction", "greenhouse_heating_kw", "greenhouse_cooling_kw", "irrigation_mm"}
TOL = 1e-9


def children_map(graph: dict, drop_into: set[str]) -> dict[str, set[str]]:
    kids: dict[str, set[str]] = {}
    for child, parents in graph["edges"].items():
        if child in drop_into:
            continue
        for p in parents:
            kids.setdefault(p.rstrip("?").split("@")[0], set()).add(child)
    return kids


def descendants(entry: list[str], kids: dict[str, set[str]]) -> set[str]:
    seen, stack = set(entry), list(entry)
    while stack:
        for c in kids.get(stack.pop(), ()):
            if c not in seen:
                seen.add(c)
                stack.append(c)
    return seen


def changed(reference: dict, other: dict) -> set[str]:
    out = set()
    for name in reference.keys() & other.keys():
        for a, b in zip(reference[name], other[name]):
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                if abs(a - b) > TOL:
                    out.add(name)
                    break
            elif a != b:
                out.add(name)
                break
    return out


def main() -> int:
    crop, season = (sys.argv[1], int(sys.argv[2])) if len(sys.argv) == 3 else ("tomato", 0)
    start = CROPS_START[crop]
    report_path = ROOT / "data" / "xai" / f"effects_pt4a_graph_check_{crop}{season}.json"
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    simulator = TwinSimulator()
    labels = {"crop": crop, "environment": "greenhouse", "control": "on"}
    desc = ScenarioDescriptor(labels, season, start, 336, simulator.scenario_options(labels, season))
    ref, trace = simulator.run_traced(desc)
    known = set(ref.series)
    declared = set(graph["edges"]) | {p.rstrip("?").split("@")[0] for ps in graph["edges"].values() for p in ps}
    rows = []
    for factor, level in PROBE.items():
        iv = (Intervention(factor, 48, 72, level),)
        for policy in ("reactive", "replayed"):
            if policy == "replayed" and factor in DECISION:
                continue
            result = simulator.run(desc, iv) if policy == "reactive" else simulator.run_traced(desc, iv, trace)[0]
            moved = changed(ref.series, result.series)
            kids = children_map(graph, COMMANDS if policy == "replayed" else set())
            predicted = descendants(graph["intervention_entry_points"][factor], kids) & known
            missing = sorted(moved - predicted)
            unchanged = sorted(predicted - moved)
            rows.append({"factor": factor, "policy": policy, "changed": len(moved), "predicted_descendants": len(predicted), "missing_edge_variables": missing, "unchanged_descendants": unchanged, "consistent": not missing})
            print(f"{factor:15s} {policy:9s} changed {len(moved):2d} predicted {len(predicted):2d} | MISSING {missing} | unchanged descendants {len(unchanged)}", flush=True)
    undeclared = sorted(known - declared)
    out = {"graph_version": graph["version"], "status": "DEVELOPMENT: one episode, probe levels; a test of the declared graph, not a proof", "episode": {"labels": labels, "season": season, "window_start_hour": start, "window_hours": 336}, "series_not_in_the_graph": undeclared,
           "rows": rows, "consistent": sum(r["consistent"] for r in rows), "of": len(rows)}
    out["report_hash"] = content_hash(out)
    report_path.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print("series not covered by the graph:", undeclared)
    print("consistent:", out["consistent"], "of", out["of"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
