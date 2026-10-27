"""Phase 6.6, contrastive explanation with real language models: B0 to B4 on five kinds of pair of the PLC reactor (the second host of tsxai, not the agricultural twin).

    python -u manual_phase6_6_contrast_llm_test.py            # live: needs the Spark (SPARK_HOST, default 192.168.1.112); records the answers
    python -u manual_phase6_6_contrast_llm_test.py --replay   # offline: replays the recorded answers, same hashes

Pairs (8 plants: 2 units x 4 seasons, English only, temperature 0, seed 0): HIDDEN (identical histories, the interlock trip differs: right answer, abstain), VISIBLE (the same plants after they part: describe), THRESHOLD (two
set-point levels straddling a declared alarm level of 380 K: describe the crossing), EVIDENCE (identical data, an operator event declared in A and not in B: the same change point is associated in one and only observed in the
other; describe the difference in strength, state no cause), UNCERTAINTY (identical data, the forecast band three times wider in B: describe the wider band). Systems: B0 literal list, B1 template, B2 rule selection and model
wording, B3 = B2 with verification and fallback to B1, B4 model selection and wording; the models are Qwen2.5-7B, Llama-3.1-8B and Olmo-3-7B on the project's own containers.
What the explainer receives: for hidden, visible and threshold pairs the OBSERVED series with low sensor noise, analysed locally on the stretch where they differ (60 samples of context is too wide, so 30: a development
choice made after the sweep, declared) or globally when no stretch exists; for evidence and uncertainty the noiseless series (the two situations share it). The setting, the oracle, never reaches the model.
Every pair is synthetic and built by this project; 8 related plants; the figures are counts, not rates with an interval; no human has judged the texts; "causal wording" is a crude pattern count, not a judgement.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from tsxai.adapters import OpenAILanguageModel  # noqa: E402
from tsxai.adapters.http_forecast import ServiceError  # noqa: E402
from tsxai.analysis import AnalyzerConfig, analyze_frame  # noqa: E402
from tsxai.bench import BenchmarkDesign, ScenarioSpec, divergences, hidden_setting_pairs, observation, run_scenario, threshold_pair  # noqa: E402
from tsxai.core import Intervention, MultivariateFrame, ScenarioDescriptor, content_hash, time_scale_of  # noqa: E402
from tsxai.core.errors import PortError  # noqa: E402
from tsxai.examples import PlcReactor  # noqa: E402
from tsxai.forecast import LaggedRegressionBackend  # noqa: E402
from tsxai.forecast.evaluation import request_from_view  # noqa: E402
from tsxai.llm import RecordedLanguageModel, RecordingLanguageModel  # noqa: E402
from tsxai.report.contrast import FactDifference, b0_list, b1_template, differing_stretch, fact_difference, relevance_score, score_answer  # noqa: E402
from tsxai.report.contrast_llm import contrast_explain, to_b3  # noqa: E402
from tsxai.semantics import DomainPack, SemanticEnricher, ThresholdSpec, ordered  # noqa: E402
from tsxai.semantics.vocabulary import DEFAULT_VOCABULARY  # noqa: E402
from tsxai.verify import verify  # noqa: E402

HOST = os.environ.get("SPARK_HOST", "192.168.1.112")
PORTS = (8010, 8011, 8012)
NAMES = (("qwen2.5-7b", "Qwen/Qwen2.5-7B-Instruct"), ("llama-3.1-8b", "meta-llama/Llama-3.1-8B-Instruct"), ("olmo-3-7b", "allenai/Olmo-3-7B-Instruct"))
MODELS = {key: (port, model_id) for port, (key, model_id) in zip(PORTS, NAMES)}
SERVER_CONFIG = {"structured_outputs": "xgrammar, no free whitespace"}
RECORDS = ROOT / "data" / "xai" / "llm_records_contrast"
REPORT = ROOT / "data" / "xai" / "contrast_llm_report.json"
MAX_TOKENS, MAX_CLAIMS = 1536, 6  # max_model_len is 8192; the longest B4 prompt (the facts of two long histories) takes about 5.2k tokens, so the answer is capped

TARGETS = ("temperature", "concentration", "cooling_duty")
TRIP_A, TRIP_B, ALARM = 385.0, 372.0, 380.0
PLAN = Intervention("SETPOINT", 300, 120, 375.0)
UNITS, SEASONS, START, LENGTH = ("reactor_a", "reactor_b"), (1, 2, 3, 4), 100, 500
LOCAL_CONTEXT, NOISE = 30, "low"
GLOBAL_WINDOW = 150  # samples analysed before the cut-off when there is no stretch to look at (the first pass analysed the whole history: its B4 prompts overflowed the 8192-token context in 14 of 24 evidence pairs)
PACK = DomainPack("reactor", DEFAULT_VOCABULARY, {"temperature": {"max": ThresholdSpec(ALARM, "K", "declared alarm level of the plant (design convention, no source)")}}, forbidden_claims=())
CAUSAL = re.compile(r"\b(because|caused?|causing|due to|leads? to|led to|as a result|results? in|resulted in|responsible for|explains?|triggered)\b", re.IGNORECASE)


NEGATED = re.compile(r"\b(not|no|nor|never)\s+(a\s+|an\s+|the\s+)?(cause|causes|caused|causal)\b|\b(no es|no son|no una)\s+(una\s+)?causa\b", re.IGNORECASE)


def frame_of(simulator, record, observed, cut):
    return MultivariateFrame(tuple(record["time"][:cut]), {n: tuple(observed[n][:cut]) for n in TARGETS}, simulator.catalogue(), {n: "SYNTHETIC" for n in TARGETS}, {})


def facts_over(frame, scale, bounds, events=()):
    """Facts of the analysis of ``frame[start:stop]`` with windows in the frame's own indexing."""
    start, stop = bounds
    window = frame.window(start, stop)
    enricher = SemanticEnricher(PACK, scale.sample_hours, "SYNTHETIC")
    analyses = analyze_frame(window, TARGETS, AnalyzerConfig.for_time_scale(scale))
    local_events = [{**e, "index": e["index"] - start} for e in events]
    facts = [*enricher.quality(window.quality())]
    for name in TARGETS:
        unit = window.catalogue.variables[name].unit
        facts += [*enricher.changes(analyses[name], unit, local_events, tolerance=scale.tolerance), *enricher.trends(analyses[name], unit), *(enricher.exceedances(name, window.series[name], unit) if name == "temperature" else [])]
    return ordered([replace(f, window=(f.window[0] + start, f.window[1] + start)) if f.window else f for f in facts])


def forecast_facts(simulator, record, observed, scale, cut, widen):
    """The forecast fact of the temperature at ``cut`` on the observed series (a noiseless series gives a band of zero width); ``widen`` scales the band around the median (a synthetic change of the forecaster's confidence)."""
    full = MultivariateFrame(tuple(record["time"]), {n: tuple(v) for n, v in observed.items()}, simulator.catalogue(), {}, {})
    view = full.forecast_view(cut, 60)
    response = LaggedRegressionBackend().forecast(request_from_view(view, 60, quantiles=(0.1, 0.5, 0.9)))
    median = response.median["temperature"]
    quantiles = {"temperature": {q: tuple(m + widen * (v - m) for m, v in zip(median, values)) for q, values in response.quantiles["temperature"].items()}}
    wrapped = SimpleNamespace(median=response.median, quantiles=quantiles, model=response.model, content_hash=f"{response.content_hash}:{widen}")
    return SemanticEnricher(PACK, scale.sample_hours, "SYNTHETIC").forecast("temperature", wrapped, "K", start=cut)


def build_pairs():
    simulator = PlcReactor()
    scale, design, catalogue = time_scale_of(simulator), BenchmarkDesign(), simulator.catalogue()
    pairs = []

    def situation(kind, unit, season, expected, facts_a, facts_b, affected=None, note="", found=True):
        # found False: the local analysis found no stretch where the two observed series differ, so the rule layer reports no difference (the facts of the two noisy histories are still given to B4)
        diff = fact_difference(facts_a, facts_b, window_tolerance=scale.tolerance) if found else FactDifference((), (), ())
        pairs.append({"id": f"{kind}|{unit}|{season}", "kind": kind, "expected": expected, "facts_a": facts_a, "facts_b": facts_b, "diff": diff, "both": ordered([*facts_a, *facts_b]), "affected": affected, "note": note})

    def observed_pair(pair, level):
        records = [run_scenario(simulator, s, catalogue) for s in (pair.base, pair.variant)]
        seen = [observation(r, design, level)["series"] for r in records]
        frames = [frame_of(simulator, r, o, pair.horizon) for r, o in zip(records, seen)]
        exact = [{n: r["series"][n][:pair.horizon] for n in TARGETS} for r in records]
        return frames, seen, exact

    def facts_pair(frames, seen, horizon):
        stretch = differing_stretch({n: seen[0][n][:horizon] for n in TARGETS}, {n: seen[1][n][:horizon] for n in TARGETS}, TARGETS)
        bounds = (max(0, horizon - GLOBAL_WINDOW), horizon) if stretch is None else (max(0, stretch[0] - LOCAL_CONTEXT), min(horizon, stretch[1] + 1 + LOCAL_CONTEXT))
        return [facts_over(f, scale, bounds) for f in frames], stretch is not None

    for unit in UNITS:
        for season in SEASONS:
            base = ScenarioSpec(f"{unit}-{season}", ScenarioDescriptor({"unit": unit}, season, START, LENGTH, {}), (PLAN,), (), "none", f"unit={unit}|season={season}", "dev")
            for pair in hidden_setting_pairs(simulator, base, "trip", TRIP_A, TRIP_B, design):
                frames, seen, exact = observed_pair(pair, NOISE)
                (fa, fb), found = facts_pair(frames, seen, pair.horizon)
                situation(pair.kind, unit, season, "abstain" if pair.kind == "hidden_setting" else "distinguish", fa, fb, divergences(exact[0], exact[1], TARGETS), found=found)
            empty = ScenarioSpec(f"{unit}-{season}-t", ScenarioDescriptor({"unit": unit}, season, START, LENGTH, {}), (), (), "none", f"unit={unit}|season={season}", "dev")
            pair = threshold_pair(simulator, empty, "SETPOINT", "temperature", ALARM, 375.0, 365.0, 300, 120, design=design)
            if pair is not None:
                frames, seen, exact = observed_pair(pair, NOISE)
                (fa, fb), found = facts_pair(frames, seen, pair.horizon)
                situation("threshold", unit, season, "distinguish", fa, fb, divergences(exact[0], exact[1], TARGETS), found=found)
            # evidence and uncertainty: one plant, noiseless; the two situations share the data and differ in what is declared or in the forecaster's band
            record = run_scenario(simulator, base, catalogue)
            exact_series = {n: record["series"][n] for n in TARGETS}
            frame = frame_of(simulator, record, exact_series, 360)
            events = [{"index": PLAN.start + 1, "kind": "SETPOINT", "source": "operator"}]
            situation("evidence", unit, season, "distinguish", facts_over(frame, scale, (360 - GLOBAL_WINDOW, 360), events), facts_over(frame, scale, (360 - GLOBAL_WINDOW, 360)), None, "an operator event declared in A and not in B")
            noisy = observation(record, design, NOISE)["series"]  # one noisy history shared by the two situations, so the forecaster's band has a width
            base_facts = facts_over(frame_of(simulator, record, noisy, 300), scale, (300 - GLOBAL_WINDOW, 300))
            situation("uncertainty", unit, season, "distinguish", ordered([*base_facts, *forecast_facts(simulator, record, noisy, scale, 300, 1.0)]), ordered([*base_facts, *forecast_facts(simulator, record, noisy, scale, 300, 3.0)]), None,
                      "forecast band 3 times wider in B")
    return pairs


def judge(system, answer, pair, report=None):
    diff, both = pair["diff"], pair["both"]
    score = score_answer(answer, diff, pair["expected"], both)
    text = NEGATED.sub("", " ".join(c.text for c in answer.explanation.claims))  # the claims only, and without "not a cause" (the facts' own wording says it): the first counts took the negation for an assertion and were meaningless
    row = {"pair": pair["id"], "kind": pair["kind"], "expected": pair["expected"], "claims": len(answer.explanation.claims), "differences_available": len(diff.only_a) + len(diff.only_b) + len(diff.changed),
           "causal_words": len(CAUSAL.findall(text)), **score, "system": system}  # the full system name (with the model) comes last: score_answer carries the bare design name
    if pair["affected"] is not None:
        row.update(relevance_score(answer, both, pair["affected"]))
    if report is not None:
        row["verifier_violations"] = len(report.violations)
        row["violation_rules"] = dict(Counter(v.rule for v in report.violations))
    return row


def run(replay: bool) -> dict:
    pairs = build_pairs()
    rows, runs = [], []
    for pair in pairs:  # the two systems without a model
        for system, realise in (("B0", b0_list), ("B1", b1_template)):
            answer = realise(pair["diff"], PACK, "en", MAX_CLAIMS)
            rows.append(judge(system, answer, pair, verify(answer.explanation, pair["both"], PACK, "en")))
    RECORDS.mkdir(parents=True, exist_ok=True)
    for key, (port, model_id) in MODELS.items():
        path = RECORDS / f"{key}.json"
        recording = None if replay else RecordingLanguageModel(OpenAILanguageModel(f"http://{HOST}:{port}", model_id, timeout=3600.0, server_config=SERVER_CONFIG))
        model = recording or RecordedLanguageModel.load(path)
        jobs = [(pair, design) for pair in pairs for design in ("B2", "B4")]
        def ask(job):
            try:
                return contrast_explain(job[1], job[0]["facts_a"], job[0]["facts_b"], job[0]["diff"], PACK, model, "en", max_tokens=MAX_TOKENS, max_claims=MAX_CLAIMS)
            except (ServiceError, PortError) as error:  # a prompt that does not fit the context window (max_model_len 8192) is a result, not a crash; in a replay, the same prompt has no record
                return str(error)[:160]

        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            results = list(pool.map(ask, jobs))
        if recording is not None:
            recording.recorded().save(path)
        for (pair, design), result in zip(jobs, results):
            if isinstance(result, str):
                runs.append({"model": key, "pair": pair["id"], "system": design, "status": "SERVICE_ERROR", "error": result})
                rows.append({"pair": pair["id"], "kind": pair["kind"], "system": f"{design}:{key}", "expected": pair["expected"], "unparseable": True, "correct": False, "service_error": True})
                if design == "B2":
                    rows.append({"pair": pair["id"], "kind": pair["kind"], "system": f"B3:{key}", "expected": pair["expected"], "unparseable": True, "correct": False, "service_error": True})
                continue
            variants = [(design, result)] + ([("B3", to_b3(result, pair["diff"], PACK, "en", MAX_CLAIMS))] if design == "B2" else [])
            for system, item in variants:
                info = {"model": key, "attempts": result.attempts, "status": result.status, "fallback": item.fallback, "prompt_hash": result.prompt_hash, "response_hash": result.response_hash}
                runs.append({**info, "pair": pair["id"], "system": system})
                if item.answer is None:
                    rows.append({"pair": pair["id"], "kind": pair["kind"], "system": f"{system}:{key}", "expected": pair["expected"], "unparseable": True, "correct": False})
                    continue
                rows.append({**judge(f"{system}:{key}", item.answer, pair, item.report), "fallback": item.fallback})
    summary: dict[str, Counter] = {}
    for row in rows:
        c = summary.setdefault(f"{row['kind']}|{row['system']}", Counter())
        c["answers"] += 1
        for field in ("correct", "abstained", "invented_contrast", "fallback", "unparseable", "scope_stated", "service_error"):
            c[field] += bool(row.get(field))
        for field in ("causal_words", "verifier_violations", "cited_relevant", "cited_irrelevant", "claims"):
            c[field] += row.get(field, 0)
        for rule, count in row.get("violation_rules", {}).items():
            c[f"rule:{rule}"] += count
    report = {"status": "MEASURED", "llm": "REAL (Spark, vLLM, temperature 0, seed 0)", "models": {k: v[1] for k, v in MODELS.items()}, "pairs": len(pairs), "pairs_by_kind": dict(Counter(p["kind"] for p in pairs)),
              "summary": {k: dict(v) for k, v in sorted(summary.items())}, "rows": rows, "runs": runs,
              "statement": "first run of contrastive explanation with real models: constructed pairs of a synthetic teaching plant, 8 related plants, counts and not rates with an interval, no human judgement; the causal-word count is a crude pattern"}
    report["report_hash"] = content_hash({k: v for k, v in report.items() if k != "statement"})
    return report


def main() -> int:
    replay = "--replay" in sys.argv
    report = run(replay)
    REPORT.write_text(json.dumps(report, indent=1, sort_keys=True, allow_nan=False), encoding="utf-8")
    print(json.dumps({"pairs": report["pairs_by_kind"], "report_hash": report["report_hash"]}))
    cols = ("answers", "correct", "abstained", "invented_contrast", "fallback", "unparseable", "service_error", "scope_stated", "causal_words", "verifier_violations", "cited_relevant", "cited_irrelevant")
    print(f"{'kind|system':42s}" + "".join(f"{c[:9]:>10s}" for c in cols))
    for key, c in report["summary"].items():
        print(f"{key:42s}" + "".join(f"{c.get(col, 0):10d}" for col in cols))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
