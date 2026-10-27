"""Phase 6.6 with REAL language models: the OpenAI-compatible client on the Spark's vLLM containers, the minimal pipeline and the verifier on the four scenarios of the twin, in Spanish and English.

    python -u manual_phase6_6_real_llm_test.py            # live: needs the Spark (SPARK_HOST, default 192.168.1.112); records the answers
    python -u manual_phase6_6_real_llm_test.py --replay   # offline: replays the recorded answers, same hashes

Each model answers every scenario once per language at temperature 0 with a fixed seed. Every (prompt, answer) pair is recorded under data/xai/llm_records/ so the report is reproducible without the service.
Assertions are about the infrastructure only (the answer is recorded, the replay gives the identical bundle hash, a failed parse is reported). What the verifier finds in the answers is REPORTED, not asserted: it is the first
measurement on real models, on four synthetic scenarios, with one run per cell. It is not a quality result of a model, not a rate with an interval, and not a human evaluation.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from tsxai.adapters import OpenAILanguageModel  # noqa: E402
from tsxai.core import content_hash  # noqa: E402
from tsxai.forecast import LaggedRegressionBackend  # noqa: E402
from tsxai.llm import RecordedLanguageModel, RecordingLanguageModel  # noqa: E402
from tsxai.report import RuleSelector, explain, rule_selection  # noqa: E402

from agri_twin.interfaces.xai_adapter import TwinSimulator, twin_series_source  # noqa: E402
from manual_phase6_4_semantics_test import CASES, build  # noqa: E402
from manual_phase6_7_verifier_double_test import twin_confirmation  # noqa: E402

HOST = os.environ.get("SPARK_HOST", "192.168.1.112")
def argument(name: str, default: str) -> str:
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


DESIGN = argument("--design", "v1")  # v1: one claim per fact (the first run); v2: short, bounded explanation (docs/phase6_6_real_llm.md section 5)
# fgkb: the containers of the Spark's owner (default server settings, free whitespace under constrained decoding); agritwin: this project's own containers, same images and flags plus xgrammar without free whitespace (section 6)
SERVER = argument("--server", "fgkb")
PORTS = {"fgkb": (8000, 8001, 8002), "agritwin": (8010, 8011, 8012)}[SERVER]
SERVER_CONFIG = {} if SERVER == "fgkb" else {"structured_outputs": "xgrammar, no free whitespace"}
NAMES = (("qwen2.5-7b", "Qwen/Qwen2.5-7B-Instruct"), ("llama-3.1-8b", "meta-llama/Llama-3.1-8B-Instruct"), ("olmo-3-7b", "allenai/Olmo-3-7B-Instruct"))
MODELS = {key: (port, model_id) for port, (key, model_id) in zip(PORTS, NAMES)}
SUFFIX = ("" if DESIGN == "v1" else f"_{DESIGN}") + ("" if SERVER == "fgkb" else f"_{SERVER}")
RECORDS = ROOT / "data" / "xai" / f"llm_records{SUFFIX}"
REPORT = ROOT / "data" / "xai" / f"real_llm_report{SUFFIX}.json"
# The prompt takes 1.6-3.1k tokens and the models write one claim per fact; the first run with 2048 truncated 26 of 39 answers (finish_reason=length), kept in llm_records_max2048/. max_model_len is 8192 and the longest prompt takes about 3.4k, so 4096 is the most that always fits.
MAX_TOKENS = 4096


def scenarios():
    simulator = TwinSimulator()
    source = twin_series_source(simulator)
    backend = LaggedRegressionBackend()
    for index, (crop, extra) in enumerate(CASES):
        _, _, facts, pack, _ = build(index, simulator, source, backend)
        if index == 1:
            facts, _ = twin_confirmation(simulator, source, facts, pack)
        yield f"{index}_{crop}_{'_'.join(extra.values())}", facts, pack


def label_usage(path: Path) -> tuple[int, int]:
    """How many fact ids the recorded answers cite, and how many carry the prompt's `[F:id]` label (normalized by the parser; the strict count is in real_llm_report_strict_ids.json)."""
    cited = labelled = 0
    for record in json.loads(path.read_text(encoding="utf-8"))["records"].values():
        try:
            claims = json.loads(record["text"])["claims"]
        except (ValueError, KeyError, TypeError):
            continue
        ids = [f for claim in claims for f in claim.get("fact_ids", [])]
        cited += len(ids)
        labelled += sum(str(f).strip().lstrip("[").startswith("F:") for f in ids)
    return cited, labelled


MAX_CLAIMS = 6


def selection_stats(facts, bundle) -> dict[str, int]:
    """Design v3 only. Overlap with the rule baseline (in thousandths of Jaccard) and coverage of the interpretive facts (evidence level above OBSERVED), capped at the number of slots, so a selector can reach 100%.
    The interpretive-facts criterion is a convention fixed here, exploratory until it is preregistered; it is not a claim of what an operator needs."""
    chosen = {c.fact_ids[0] for c in bundle.raw.claims} if bundle.raw else set()
    rule = set(rule_selection(facts, MAX_CLAIMS))
    key = [f.fact_id for f in facts if f.evidence_level != "OBSERVED"]
    union = chosen | rule
    return {"selection_runs": 1, "selected": len(chosen), "jaccard_with_rule_x1000": round(1000 * len(chosen & rule) / len(union)) if union else 1000,
            "interpretive_slots": min(len(key), MAX_CLAIMS), "interpretive_covered": len(chosen & set(key))}


def main(replay: bool) -> int:
    cases = list(scenarios())
    RECORDS.mkdir(parents=True, exist_ok=True)
    rows, summary = [], {}
    for key, (port, model_id) in MODELS.items():
        path = RECORDS / f"{key}.json"
        recording = None if replay else RecordingLanguageModel(OpenAILanguageModel(f"http://{HOST}:{port}", model_id, timeout=3600.0, server_config=SERVER_CONFIG))
        model = recording or RecordedLanguageModel.load(path)
        counts = Counter()
        jobs = [(case, facts, pack, language) for case, facts, pack in cases for language in ("en", "es")]
        # decoding is memory-bandwidth bound, so the server batches simultaneous requests at almost the cost of one: all of a model's runs go at once (each request is still temperature 0 with a fixed seed)
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            bundles = list(pool.map(lambda job: explain(job[1], job[2], model, job[3], max_tokens=MAX_TOKENS, design=DESIGN), jobs))
        for (case, facts, pack, language), bundle in zip(jobs, bundles):
            counts["runs"] += 1
            counts["truncated_last_attempt"] += bundle.model.get("finish_reason") == "length"
            counts["attempts"] += bundle.attempts
            counts["unparseable"] += bundle.status != "OK"
            # only violations on real claim ids (the first version of this counter also counted "recommendation:n" and "caveat:n", which inflated the share of flagged claims)
            counts["flagged_claims"] += len({v.claim_id for v in bundle.report.violations} & {c.claim_id for c in bundle.raw.claims}) if bundle.report else 0
            rules = Counter(v.rule for v in bundle.report.violations) if bundle.report else Counter()
            counts["runs_with_violations"] += bool(rules)
            counts["violations"] += sum(rules.values())
            counts["claims"] += len(bundle.raw.claims) if bundle.raw else 0
            counts["recommendations_final"] += len(bundle.final.recommendations) if bundle.final else 0
            if DESIGN == "v3" and bundle.raw:
                counts.update(selection_stats(facts, bundle))
            rows.append({"model": key, "case": case, "language": language, "status": bundle.status, "error": bundle.error, "attempts": bundle.attempts, "claims": len(bundle.raw.claims) if bundle.raw else 0,
                         "violations_by_rule": dict(sorted(rules.items())), "corrections": dict(Counter(c.action for c in bundle.report.corrections)) if bundle.report else {}, "bundle_hash": bundle.content_hash})
        if recording is not None:
            recording.recorded().save(path)
            # the replay of what was just recorded must give the identical bundles
            replayed = RecordedLanguageModel.load(path)
            for row, (case, facts, pack, language) in zip([r for r in rows if r["model"] == key], jobs):
                assert explain(facts, pack, replayed, language, max_tokens=MAX_TOKENS, design=DESIGN).content_hash == row["bundle_hash"], (key, case, language)
        counts["fact_ids_cited"], counts["fact_ids_with_label"] = label_usage(path)
        summary[key] = dict(counts)
    if DESIGN == "v3":  # the baseline without a language model: the fixed-priority selection, rendered and verified the same way
        counts = Counter()
        for case, facts, pack in cases:
            for language in ("en", "es"):
                bundle = explain(facts, pack, RuleSelector(facts, MAX_CLAIMS), language, design="v3", max_claims=MAX_CLAIMS)
                counts["runs"] += 1
                counts["violations"] += len(bundle.report.violations)
                counts["claims"] += len(bundle.raw.claims)
                counts.update(selection_stats(facts, bundle))
        summary["rule-selector (no model)"] = dict(counts)
    report = {"status": "MEASURED", "llm": "REAL (Spark, vLLM, temperature 0, seed 0)", "models": {k: v[1] for k, v in MODELS.items()}, "summary": summary, "rows": rows,
              "statement": "first measurement on real models: four synthetic scenarios, one run per model, language and scenario; what the verifier flags is reported, not a quality result, not a rate with an interval, no human evaluation"}
    report["report_hash"] = content_hash({k: v for k, v in report.items() if k != "statement"})
    report["design"], report["server"] = DESIGN, SERVER
    out = REPORT
    out.write_text(json.dumps(report, indent=1, sort_keys=True, allow_nan=False), encoding="utf-8")
    print(json.dumps({"summary": summary, "report_hash": report["report_hash"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--replay" in sys.argv))
