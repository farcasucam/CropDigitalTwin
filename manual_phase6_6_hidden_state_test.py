"""Phase 6.6, hidden latent state on the PLC reactor (the second host of tsxai, not the agricultural twin): two plants identical except for the interlock's trip temperature, which no series shows.

    python -u manual_phase6_6_hidden_state_test.py     # writes data/xai/hidden_state_report.json; no language model, no Spark

The interlock is the latent threshold of 6.3e: a regime switch the temperature reaches only after an operator moves the set-point up. HIDDEN pair: the explainer receives the two histories up to a cut-off placed before the targets
first differ, so they are identical and the right answer is to abstain. VISIBLE pair (the control): the cut-off is after they differ, so the difference is in the data and the right answer is to describe it.
Only the facts of each history reach the explainer; the setting (the oracle) never does. Synthetic teaching model, no quality claim. B1 abstains when no fact differs by construction, so the hidden pair is only discriminating
for a language model that is asked why the plants will end differently; this script reports what the two realisations without a model do, and that the construction is sound.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from tsxai.analysis import AnalyzerConfig, analyze_frame  # noqa: E402
from tsxai.bench import BenchmarkDesign, ScenarioSpec, divergences, hidden_setting_pairs  # noqa: E402
from tsxai.core import Intervention, ScenarioDescriptor, SimulatorSeriesSource, content_hash, time_scale_of  # noqa: E402
from tsxai.examples import PlcReactor  # noqa: E402
from tsxai.report.contrast import b0_list, b1_template, fact_difference, relevance_score, score_answer  # noqa: E402
from tsxai.semantics import DomainPack, SemanticEnricher, ordered  # noqa: E402
from tsxai.semantics.vocabulary import DEFAULT_VOCABULARY  # noqa: E402
from tsxai.verify import verify  # noqa: E402

TARGETS = ("temperature", "concentration", "cooling_duty")
TRIP_A, TRIP_B = 385.0, 372.0  # K: the default interlock and a plant that trips 13 K earlier (a design convention, no source)
PLAN = Intervention("SETPOINT", 300, 120, 375.0)  # the operator raises the set-point after the explainer's cut-off
UNITS, SEASONS, START, LENGTH = ("reactor_a", "reactor_b"), (1, 2, 3, 4), 100, 500
PACK = DomainPack("reactor", DEFAULT_VOCABULARY, {}, forbidden_claims=())  # no threshold: the trip temperature is the hidden setting and must not appear


def facts_of(source, scale, pair_spec, horizon):
    """Facts of the history the explainer has: the plant's frame cut at the horizon."""
    frame = source.frame(pair_spec.scenario, pair_spec.interventions).window(0, horizon)
    enricher = SemanticEnricher(PACK, scale.sample_hours, "SYNTHETIC")
    analyses = analyze_frame(frame, TARGETS, AnalyzerConfig.for_time_scale(scale))
    facts = [*enricher.quality(frame.quality()), *enricher.stage(frame.series["trip"][-1], "the interlock state at the cut-off", "trip")]
    for name in TARGETS:
        unit = frame.catalogue.variables[name].unit
        facts += [*enricher.changes(analyses[name], unit), *enricher.trends(analyses[name], unit)]
    return ordered(facts), {name: list(frame.series[name]) for name in TARGETS}


def run() -> dict:
    simulator = PlcReactor()
    source = SimulatorSeriesSource(simulator, "SYNTHETIC")
    scale = time_scale_of(simulator)
    design = BenchmarkDesign()
    rows = []
    built = skipped = 0
    for unit in UNITS:
        for season in SEASONS:
            spec = ScenarioSpec(f"{unit}-{season}", ScenarioDescriptor({"unit": unit}, season, START, LENGTH, {}), (PLAN,), (), "none", f"unit={unit}|season={season}", "dev")
            pairs = hidden_setting_pairs(simulator, spec, "trip", TRIP_A, TRIP_B, design)
            if not pairs:
                skipped += 1
                continue
            built += 1
            for pair in pairs:
                facts_a, series_a = facts_of(source, scale, pair.base, pair.horizon)
                facts_b, series_b = facts_of(source, scale, pair.variant, pair.horizon)
                both = ordered([*facts_a, *facts_b])
                affected = divergences(series_a, series_b, TARGETS)
                for matching, tolerance in (("strict", 0), ("tolerant", scale.tolerance)):  # tolerant: a finding may move by the host's own matching tolerance and stay the same finding
                    diff = fact_difference(facts_a, facts_b, window_tolerance=tolerance)
                    for language in ("en", "es"):
                        for realise in (b0_list, b1_template):
                            answer = realise(diff, PACK, language)
                            violations = len(verify(answer.explanation, both, PACK, language).violations)
                            score = {**score_answer(answer, diff, pair.expected, both), **relevance_score(answer, both, affected)}
                            rows.append({"unit": unit, "season": season, "kind": pair.kind, "matching": matching, "language": language, "expected": pair.expected, "horizon": pair.horizon,
                                         "first_divergence": pair.first_divergence, "differences": {"only_a": len(diff.only_a), "only_b": len(diff.only_b), "changed": len(diff.changed)},
                                         "claims": len(answer.explanation.claims), "verifier_violations": violations, "answer_hash": answer.explanation.content_hash, **score})
    summary: dict[str, dict] = {}
    for row in rows:
        c = summary.setdefault(f"{row['kind']}|{row['matching']}|{row['system']}", Counter())
        c["answers"] += 1
        c["correct"] += row["correct"]
        c["abstained"] += row["abstained"]
        c["invented_contrast"] += row["invented_contrast"]
        c["sensitivity_gap"] += row["sensitivity_gap"]
        c["cited_relevant"] += row["cited_relevant"]
        c["cited_irrelevant"] += row["cited_irrelevant"]
        c["verifier_violations"] += row["verifier_violations"]
    report = {"status": "MEASURED", "model": "none (B0 literal list, B1 template)", "plants": {"built": built, "no_pair": skipped}, "trip_a_k": TRIP_A, "trip_b_k": TRIP_B,
              "summary": {k: dict(v) for k, v in sorted(summary.items())}, "rows": rows,
              "statement": "behaviour of two realisations without a language model on constructed pairs of the PLC reactor: not a result for any language model, not a rate with an interval, no human evaluation"}
    report["report_hash"] = content_hash({k: v for k, v in report.items() if k != "statement"})
    return report


def main() -> int:
    report = run()
    assert run()["report_hash"] == report["report_hash"], "a second run must give the identical report"
    (ROOT / "data" / "xai" / "hidden_state_report.json").write_text(json.dumps(report, indent=1, sort_keys=True, allow_nan=False), encoding="utf-8")
    diffs = {(r["kind"], r["matching"]): [] for r in report["rows"]}
    for r in report["rows"]:
        if r["language"] == "en" and r["system"] == "B1":
            diffs[(r["kind"], r["matching"])].append(sum(r["differences"].values()))
    for key, value in sorted(diffs.items()):
        print(key, "differences per pair:", value)
    print(json.dumps({"plants": report["plants"], "summary": report["summary"], "report_hash": report["report_hash"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
