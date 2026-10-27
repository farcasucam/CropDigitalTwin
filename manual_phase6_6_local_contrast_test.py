"""Phase 6.6, local analysis of the contrast under sensor noise, on the PLC reactor pairs of manual_phase6_6_hidden_state_test.py (no language model, no Spark).

    python -u manual_phase6_6_local_contrast_test.py     # writes data/xai/local_contrast_report.json

The explainer receives the OBSERVED series of each plant (independent sensor noise per plant, levels none, low, medium of the bench) up to the cut-off. Two ways to find what differs:
GLOBAL compares the facts of one analysis of each whole series (what the previous scripts did); LOCAL first finds, from the two observed series alone, the stretch where they differ (``differing_stretch``), analyses both
only there (60 samples of context on each side) and compares those facts; if no stretch is found it reports no difference. The oracle is the exact series: the hidden pair is identical in truth (right answer: abstain), the
visible pair differs (right answer: describe), and a cited fact is relevant when its variable is affected and its window overlaps the true divergence. With no noise the local stretch is the oracle's, so the figure at level none
is true by construction; the levels with noise are where it can fail. Synthetic teaching model; a handful of plants; no rate with an interval; not a language-model result.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from tsxai.analysis import AnalyzerConfig, analyze_frame  # noqa: E402
from tsxai.bench import BenchmarkDesign, ScenarioSpec, divergences, hidden_setting_pairs, observation, run_scenario  # noqa: E402
from tsxai.core import MultivariateFrame, ScenarioDescriptor, content_hash, time_scale_of  # noqa: E402
from tsxai.examples import PlcReactor  # noqa: E402
from tsxai.report.contrast import FactDifference, b0_list, b1_template, differing_stretch, fact_difference, relevance_score, score_answer  # noqa: E402
from tsxai.semantics import SemanticEnricher, ordered  # noqa: E402

from manual_phase6_6_hidden_state_test import PACK, PLAN, SEASONS, START, LENGTH, TARGETS, TRIP_A, TRIP_B, UNITS  # noqa: E402

LEVELS = ("none", "low", "medium")
CONTEXT = 60  # samples of context on each side of the stretch


def facts_in(frame, scale, start, stop):
    """Facts of the analysis of ``frame[start:stop]``, with windows in the frame's own sample indexing."""
    window = frame.window(start, stop)
    enricher = SemanticEnricher(PACK, scale.sample_hours, "SYNTHETIC")
    analyses = analyze_frame(window, TARGETS, AnalyzerConfig.for_time_scale(scale))
    facts = [*enricher.quality(window.quality())]
    for name in TARGETS:
        unit = window.catalogue.variables[name].unit
        facts += [*enricher.changes(analyses[name], unit), *enricher.trends(analyses[name], unit)]
    return ordered([replace(f, window=(f.window[0] + start, f.window[1] + start)) if f.window else f for f in facts])


def run() -> dict:
    simulator = PlcReactor()
    scale = time_scale_of(simulator)
    design = BenchmarkDesign()
    catalogue = simulator.catalogue()
    rows = []
    for unit in UNITS:
        for season in SEASONS:
            spec = ScenarioSpec(f"{unit}-{season}", ScenarioDescriptor({"unit": unit}, season, START, LENGTH, {}), (PLAN,), (), "none", f"unit={unit}|season={season}", "dev")
            records = {}
            for pair in hidden_setting_pairs(simulator, spec, "trip", TRIP_A, TRIP_B, design):
                for side, pair_spec in (("a", pair.base), ("b", pair.variant)):
                    records.setdefault(pair_spec.scenario_id, run_scenario(simulator, pair_spec, catalogue))
                exact_a, exact_b = (records[s.scenario_id]["series"] for s in (pair.base, pair.variant))
                affected = divergences({n: exact_a[n][:pair.horizon] for n in TARGETS}, {n: exact_b[n][:pair.horizon] for n in TARGETS}, TARGETS)
                for level in LEVELS:
                    seen = [observation(records[s.scenario_id], design, level)["series"] for s in (pair.base, pair.variant)]
                    cut = [{n: tuple(obs[n][:pair.horizon]) for n in TARGETS} for obs in seen]
                    frames = [MultivariateFrame(tuple(records[s.scenario_id]["time"][:pair.horizon]), series, catalogue, {n: "SYNTHETIC" for n in TARGETS}, {}) for s, series in zip((pair.base, pair.variant), cut)]
                    expected = "distinguish" if pair.identifiable[level] else "abstain"
                    stretch = differing_stretch(cut[0], cut[1], TARGETS)
                    methods = {"global": (0, pair.horizon), "local": None if stretch is None else (max(0, stretch[0] - CONTEXT), min(pair.horizon, stretch[1] + 1 + CONTEXT))}
                    for method, bounds in methods.items():
                        if bounds is None:
                            diff, both = FactDifference((), (), ()), []
                        else:
                            fa, fb = (facts_in(frame, scale, *bounds) for frame in frames)
                            diff, both = fact_difference(fa, fb, window_tolerance=scale.tolerance), ordered([*fa, *fb])
                        for realise in (b0_list, b1_template):
                            answer = realise(diff, PACK, "en")
                            rows.append({"unit": unit, "season": season, "kind": pair.kind, "level": level, "method": method, "expected": expected, "stretch": stretch, "horizon": pair.horizon,
                                         "differences": len(diff.only_a) + len(diff.only_b) + len(diff.changed), **score_answer(answer, diff, expected, both), **relevance_score(answer, both, affected)})
    summary: dict[str, Counter] = {}
    for row in rows:
        c = summary.setdefault(f"{row['kind']}|{row['level']}|{row['method']}|{row['system']}", Counter())
        for key in ("correct", "abstained", "invented_contrast", "cited_relevant", "cited_irrelevant"):
            c[key] += row[key]
        c["answers"] += 1
        c["differences"] += row["differences"]
        c["expected_distinguish"] += row["expected"] == "distinguish"
        c["stretch_found"] += row["stretch"] is not None
    report = {"status": "MEASURED", "model": "none (B0 literal list, B1 template)", "levels": list(LEVELS), "context": CONTEXT, "summary": {k: dict(v) for k, v in sorted(summary.items())}, "rows": rows,
              "statement": "behaviour of two realisations without a language model on constructed pairs of the PLC reactor with sensor noise: not a result for any language model, not a rate with an interval, no human evaluation"}
    report["report_hash"] = content_hash({k: v for k, v in report.items() if k != "statement"})
    return report


def main() -> int:
    report = run()
    assert run()["report_hash"] == report["report_hash"], "a second run must give the identical report"
    (ROOT / "data" / "xai" / "local_contrast_report.json").write_text(json.dumps(report, indent=1, sort_keys=True, allow_nan=False), encoding="utf-8")
    print("kind|level|method|system  answers correct abstained invented relevant/irrelevant differences expected-distinguish stretch-found")
    for key, c in report["summary"].items():
        print(f"{key:44s} {c['answers']:3d} {c['correct']:3d} {c['abstained']:3d} {c['invented_contrast']:3d}   {c['cited_relevant']:3d}/{c['cited_irrelevant']:3d}   {c['differences']:4d}  {c['expected_distinguish']:3d}  {c['stretch_found']:3d}")
    print(report["report_hash"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
