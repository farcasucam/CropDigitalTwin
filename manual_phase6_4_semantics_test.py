"""Phase 6.4 verification: the semantic layer on four scenarios of the twin: facts with an evidence level, Markdown in Spanish and English, traceability checked line by line and number by number.

    python -u manual_phase6_4_semantics_test.py     # writes data/xai/semantics_report.json and data/xai/semantics_golden/*.md

Needs the framework: pip install -e ../tsxai. Synthetic data; the exogenous weather is forcing; no quality claim.
* Thresholds come only from ``crop_config.json`` (per crop and stage, with their path as the source); the ON threshold of the controller demand is the device's, from the variable catalogue.
* The what-if of the second scenario carries the forecaster's effect at the MODEL_ESTIMATED level: the working twin and its perturbed variants do not exist yet (phase 6.5r), so nothing here is TWIN_CONFIRMED.
  The exact effect of the truth twin is recorded in the report for reference and never enters the text.
* Acceptance: 100 % of the lines and numbers of every text trace to a fact, both languages share the fact ids, and a second build is identical.
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
from tsxai.semantics import SemanticEnricher, SemanticFormatter, check_traceability, ordered  # noqa: E402

from agri_twin.interfaces.xai_adapter import TwinSimulator, crop_stage, intervention_plan_variables, semantic_pack, twin_series_source  # noqa: E402

CASES = (
    ("tomato", {"environment": "outdoor", "control": "off"}),
    ("tomato", {"environment": "greenhouse", "control": "off"}),
    ("pepper", {"environment": "greenhouse", "control": "on"}),
    ("pepper", {"environment": "greenhouse", "control": "on", "feedback": "on"}),
)
ANALYSED = ("temperature_c", "vpd_kpa", "soil_water_vwc_m3_m3")
CONTEXT, HORIZON, LENGTH, START = 120, 48, 240, 480
HEAT_WAVE = Intervention("HEAT_WAVE", 130, 24, 8.0)
DEVICE_SOURCE = "device rating, provisional 5 percent convention of xai_variable_roles.json"


def what_if(source, scenario, backend):
    """Forecaster effect of the heat wave on the indoor temperature (its forecast under the intervened forcing minus under the baseline, same past) and the exact effect of the truth twin."""
    pair = paired_frames(source, scenario, [HEAT_WAVE])
    cutoff = pair.first_changed_sample
    views = [frame.forecast_view(cutoff, HORIZON, plan=set()) for frame in (pair.baseline, pair.intervened)]
    trim = lambda v: type(v)({n: x[-CONTEXT:] for n, x in v.past.items()}, v.future_covariates, v.truth, v.past_time[-CONTEXT:], v.future_time, v.plan, v.catalogue)  # noqa: E731
    a, b = (backend.forecast(request_from_view(trim(v), HORIZON)) for v in views)
    predicted = [y - x for x, y in zip(a.median["temperature_c"], b.median["temperature_c"])]
    truth = pair.effect("temperature_c")[cutoff:cutoff + HORIZON]
    return pair, cutoff, max(predicted, key=abs), max(truth, key=abs)


def build(case_index, simulator, source, backend):
    crop, extra = CASES[case_index]
    labels = {"crop": crop, **extra}
    scenario = ScenarioDescriptor(labels, 1, START, LENGTH, simulator.scenario_options(labels, 1))
    scale = time_scale_of(simulator)
    observed = source.frame(scenario)
    forecaster_effect = truth_effect = cutoff = None
    if case_index == 1:  # the what-if case: the series that is explained is the one with the heat wave in it
        pair, cutoff, forecaster_effect, truth_effect = what_if(source, scenario, backend)
        observed = pair.intervened
    month = int(observed.time[0][5:7])
    pack = semantic_pack(crop, month)
    enricher = SemanticEnricher(pack, scale.sample_hours, "SYNTHETIC")
    analyses = analyze_frame(observed, ANALYSED, AnalyzerConfig.for_time_scale(scale))
    events = [{"index": cutoff, "source": "runtime_events", "kind": HEAT_WAVE.factor}] if cutoff else []
    facts = [*enricher.stage(crop_stage(crop, month), "crop_config.json", "crop_stage"), *enricher.quality(observed.quality())]
    constant = {f.variable for f in observed.quality() if f.kind == "CONSTANT"}
    for name in ANALYSED:
        unit = observed.catalogue.variables[name].unit
        facts += [*(f for f in enricher.changes(analyses[name], unit, events) if not (f.key == "analysis:constant" and name in constant)), *enricher.trends(analyses[name], unit), *enricher.exceedances(name, observed.series[name], unit)]
    for name, threshold in simulator.catalogue_for(scenario).activation_thresholds().items():
        facts += enricher.activations(name, observed.series[name], threshold, DEVICE_SOURCE, "kW", "kWh")
    view = observed.forecast_view(CONTEXT, HORIZON)
    facts += enricher.forecast("temperature_c", backend.forecast(request_from_view(view, HORIZON, quantiles=(0.1, 0.5, 0.9))), "degC", start=CONTEXT)
    if forecaster_effect is not None:
        facts += enricher.counterfactual("temperature_c", "the heat wave", (cutoff, cutoff + HORIZON - 1), "degC", forecaster_effect=forecaster_effect, ref="gate:ridge")
    return crop, extra, ordered(facts), pack, truth_effect


def main() -> int:
    simulator = TwinSimulator()
    source = twin_series_source(simulator)
    backend = LaggedRegressionBackend()
    golden = ROOT / "data" / "xai" / "semantics_golden"
    golden.mkdir(parents=True, exist_ok=True)
    rows = []
    for index in range(len(CASES)):
        crop, extra, facts, pack, truth_effect = build(index, simulator, source, backend)
        again = build(index, simulator, source, backend)[2]
        assert [f.fact_id for f in facts] == [f.fact_id for f in again], "a second build must give the same facts"
        name = f"{index}_{crop}_{'_'.join(f'{k}-{v}' for k, v in extra.items())}"
        texts, checks = {}, {}
        for language in ("en", "es"):
            text = SemanticFormatter(pack, language).render(facts, f"{crop} {' '.join(extra.values())}")
            assert text == SemanticFormatter(pack, language).render(facts, f"{crop} {' '.join(extra.values())}"), "rendering must be idempotent"
            report = check_traceability(text, facts, language, none_marker=pack.template("none", language))
            assert report["violations"] == [] and report["traceability"] == 1.0 and report["unrendered_facts"] == [], (name, language, report)
            (golden / f"{name}.{language}.md").write_text(text, encoding="utf-8", newline="\n")
            texts[language], checks[language] = text, {k: report[k] for k in ("lines", "traced_lines", "traceability")}
        assert {line.rsplit("[F:", 1)[1] for line in texts["en"].splitlines() if "[F:" in line} == {line.rsplit("[F:", 1)[1] for line in texts["es"].splitlines() if "[F:" in line}, "both languages share the fact ids"
        assert all(f.evidence_level != "TWIN_CONFIRMED" for f in facts), "no working twin exists yet (phase 6.5r)"
        rows.append({"case": name, "facts": len(facts), "by_level": dict(Counter(f.evidence_level for f in facts)), "by_kind": dict(Counter(f.kind for f in facts)), "traceability": checks,
                     "pack_hash": pack.content_hash, "facts_hash": content_hash([f.to_dict() for f in facts]), "text_hash": {k: content_hash(v) for k, v in texts.items()},
                     "truth_effect_for_reference": truth_effect, "thresholds": {v: {s: spec.source for s, spec in sides.items()} for v, sides in pack.thresholds.items()}})
        print(f"--- {name}: {len(facts)} facts, traceability {checks['en']['traceability']:.0%} ---")
        print(texts["en"])
    report = {"status": "PASS", "cases": rows, "convention_status": "provisional", "statement": "synthetic data; forcing is the exogenous weather; thresholds from crop_config.json; nothing TWIN_CONFIRMED until the working twin exists (6.5r); no quality claim"}
    report["report_hash"] = content_hash({"cases": rows})
    (ROOT / "data" / "xai" / "semantics_report.json").write_text(json.dumps(report, indent=1, sort_keys=True, allow_nan=False), encoding="utf-8")
    print(json.dumps({"status": "PASS", "cases": len(rows), "facts": [r["facts"] for r in rows], "report_hash": report["report_hash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
