"""Phase 6.6, contrastive pairs on the twin: for two situations that differ in one controlled thing (a heat wave present or absent, stronger or weaker, earlier or later, or no difference at all), what do the semantic facts
distinguish, and what do the two realisations without a language model (B0 literal list, B1 template with caveats and abstention) say?

    python -u manual_phase6_6_contrast_pairs_test.py     # writes data/xai/contrast_pairs_report.json; no language model, no Spark

The oracle is the exact observed series of the two situations: a pair is to be distinguished when any analysed series differs in the window the explainer receives, and to be abstained on when none does (the identical pair).
The explainer receives only the facts of each situation. Synthetic data, the exogenous weather is forcing; the forecaster's effect is MODEL_ESTIMATED (the working twin's confirmation is not applied here).
What is reported is behaviour on the facts: it is not a result for any language model, not a rate with an interval (a handful of constructed pairs), and not a human evaluation.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from tsxai.analysis import AnalyzerConfig, analyze_frame  # noqa: E402
from tsxai.core import Intervention, ScenarioDescriptor, content_hash, paired_frames, time_scale_of  # noqa: E402
from tsxai.forecast import LaggedRegressionBackend  # noqa: E402
from tsxai.forecast.evaluation import request_from_view  # noqa: E402
from tsxai.bench import divergences  # noqa: E402
from tsxai.report.contrast import b0_list, b1_template, fact_difference, relevance_score, score_answer  # noqa: E402
from tsxai.semantics import SemanticEnricher, ordered  # noqa: E402
from tsxai.verify import verify  # noqa: E402

from agri_twin.interfaces.xai_adapter import TwinSimulator, crop_stage, semantic_pack, twin_series_source  # noqa: E402
from manual_phase6_4_semantics_test import ANALYSED, CASES, CONTEXT, DEVICE_SOURCE, HORIZON, LENGTH, START  # noqa: E402

HEAT = lambda start, level: Intervention("HEAT_WAVE", start, 24, level)  # noqa: E731
# (name, kind, A, B): one controlled difference each; the identical pair is the control where the right answer is to abstain
PAIRS = (("presence", "presence", HEAT(130, 8.0), None), ("level", "level", HEAT(130, 8.0), HEAT(130, 3.0)), ("timing", "timing", HEAT(130, 8.0), HEAT(60, 8.0)), ("identical", "control", HEAT(130, 8.0), HEAT(130, 8.0)))
CASE_INDICES = (1, 2)  # tomato and pepper in the greenhouse


def situation(index, simulator, source, backend, heat):
    """The observed series of the case with ``heat`` applied (or none), its facts and its pack; the same recipe as the phase 6.4 build, with the intervention as a parameter."""
    crop, extra = CASES[index]
    labels = {"crop": crop, **extra}
    scenario = ScenarioDescriptor(labels, 1, START, LENGTH, simulator.scenario_options(labels, 1))
    scale = time_scale_of(simulator)
    observed = source.frame(scenario)
    forecaster_effect = cutoff = None
    if heat is not None:
        pair = paired_frames(source, scenario, [heat])
        cutoff = pair.first_changed_sample
        views = [frame.forecast_view(cutoff, HORIZON, plan=set()) for frame in (pair.baseline, pair.intervened)]
        trim = lambda v: type(v)({n: x[-CONTEXT:] for n, x in v.past.items()}, v.future_covariates, v.truth, v.past_time[-CONTEXT:], v.future_time, v.plan, v.catalogue)  # noqa: E731
        low, high = (backend.forecast(request_from_view(trim(v), HORIZON)) for v in views)
        forecaster_effect = max((y - x for x, y in zip(low.median["temperature_c"], high.median["temperature_c"])), key=abs)
        observed = pair.intervened
    month = int(observed.time[0][5:7])
    pack = semantic_pack(crop, month)
    enricher = SemanticEnricher(pack, scale.sample_hours, "SYNTHETIC")
    analyses = analyze_frame(observed, ANALYSED, AnalyzerConfig.for_time_scale(scale))
    events = [{"index": cutoff, "source": "runtime_events", "kind": heat.factor}] if heat is not None else []
    facts = [*enricher.stage(crop_stage(crop, month), "crop_config.json", "crop_stage"), *enricher.quality(observed.quality())]
    constant = {f.variable for f in observed.quality() if f.kind == "CONSTANT"}
    for name in ANALYSED:
        unit = observed.catalogue.variables[name].unit
        facts += [*(f for f in enricher.changes(analyses[name], unit, events) if not (f.key == "analysis:constant" and name in constant)), *enricher.trends(analyses[name], unit), *enricher.exceedances(name, observed.series[name], unit)]
    for name, threshold in simulator.catalogue_for(scenario).activation_thresholds().items():
        facts += enricher.activations(name, observed.series[name], threshold, DEVICE_SOURCE, "kW", "kWh")
    facts += enricher.forecast("temperature_c", backend.forecast(request_from_view(observed.forecast_view(CONTEXT, HORIZON), HORIZON, quantiles=(0.1, 0.5, 0.9))), "degC", start=CONTEXT)
    if forecaster_effect is not None:
        facts += enricher.counterfactual("temperature_c", "the heat wave", (cutoff, cutoff + HORIZON - 1), "degC", forecaster_effect=forecaster_effect, ref="gate:ridge")
    return pack, ordered(facts), {name: list(observed.series[name]) for name in ANALYSED}


def oracle(series_a, series_b) -> tuple[str, float]:
    """The right behaviour from the exact observed series: distinguish when any analysed series differs in the window, abstain when none does."""
    gap = max(abs(a - b) for name in ANALYSED for a, b in zip(series_a[name], series_b[name]))
    return ("distinguish" if gap > 1e-9 else "abstain"), gap


def run() -> dict:
    simulator = TwinSimulator()
    source = twin_series_source(simulator)
    backend = LaggedRegressionBackend()
    rows = []
    for index in CASE_INDICES:
        for name, kind, heat_a, heat_b in PAIRS:
            pack, facts_a, series_a = situation(index, simulator, source, backend, heat_a)
            _, facts_b, series_b = situation(index, simulator, source, backend, heat_b)
            expected, gap = oracle(series_a, series_b)
            diff = fact_difference(facts_a, facts_b)
            both = ordered([*facts_a, *facts_b])
            affected = divergences(series_a, series_b, ANALYSED)
            # the reference for precision: how relevant is a difference picked at random, i.e. all of them (the budget-free list)
            everything = relevance_score(b1_template(diff, pack, "en", max_claims=10_000), both, affected)
            for language in ("en", "es"):
                for realise in (b0_list, b1_template):
                    answer = realise(diff, pack, language)
                    verdict = verify(answer.explanation, both, pack, language)
                    score = {**score_answer(answer, diff, expected, both), **relevance_score(answer, both, affected, direction_valid=(kind == "presence"))}
                    rows.append({"case": f"{index}_{CASES[index][0]}", "pair": name, "kind": kind, "language": language, "expected": expected, "oracle_gap": round(gap, 6), "facts_a": len(facts_a), "facts_b": len(facts_b),
                                 "differences": {"only_a": len(diff.only_a), "only_b": len(diff.only_b), "changed": len(diff.changed)}, "verifier_violations": len(verdict.violations), "claims": len(answer.explanation.claims), "all_differences_precision": everything["precision"],
                                 "answer_hash": answer.explanation.content_hash, **score})
    by_system = {s: Counter() for s in ("B0", "B1")}
    for row in rows:
        c = by_system[row["system"]]
        c["answers"] += 1
        c["correct"] += row["correct"]
        c["invented_contrast"] += row["invented_contrast"]
        c["scope_missing"] += not row["scope_stated"]
        c["sensitivity_gap"] += row["sensitivity_gap"]
        c["verifier_violations"] += row["verifier_violations"]
        c["cited_relevant"] += row["cited_relevant"]
        c["cited_irrelevant"] += row["cited_irrelevant"]
        c["direction_checked"] += row["direction_checked"]
        c["direction_correct"] += row["direction_correct"]
        if row["all_differences_precision"] is not None:
            c["reference_precision_sum_x1000"] += round(1000 * row["all_differences_precision"])
            c["reference_answers"] += 1
        if row["coverage"] is not None:
            c["coverage_answers"] += 1
            c["coverage_sum_x1000"] += round(1000 * row["coverage"])
    report = {"status": "MEASURED", "model": "none (B0 literal list, B1 template)", "summary": {k: dict(v) for k, v in by_system.items()}, "rows": rows,
              "statement": "behaviour of two realisations without a language model on constructed pairs of the twin: not a result for any language model, not a rate with an interval, no human evaluation"}
    report["report_hash"] = content_hash({k: v for k, v in report.items() if k != "statement"})
    return report


def main() -> int:
    report = run()
    assert run()["report_hash"] == report["report_hash"], "a second run must give the identical report"
    (ROOT / "data" / "xai" / "contrast_pairs_report.json").write_text(json.dumps(report, indent=1, sort_keys=True, allow_nan=False), encoding="utf-8")
    for row in report["rows"]:
        if row["language"] == "en":
            print({k: row[k] for k in ("case", "pair", "system", "expected", "correct", "precision", "coverage", "affected_variables", "direction_checked", "direction_correct", "claims")})
    print(json.dumps({"summary": report["summary"], "report_hash": report["report_hash"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
