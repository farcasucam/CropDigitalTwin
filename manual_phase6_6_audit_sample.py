"""Phase 6.6 audit sample: the claims written by the three real models (design v2, own containers), prepared for a manual check of what the verifier flags and what it lets through.

    python -u manual_phase6_6_audit_sample.py        # offline: replays the recorded answers; writes data/xai/audit/

Sample: EVERY claim the verifier flagged plus an equal-size random sample (fixed seed) of the claims it did not flag, from the evaluable runs of the three models. The sheet for the auditor (`audit_blind.csv`) is shuffled and does
NOT show the verifier's verdict; the key (`audit_key.csv`) maps each row to it. Verdict codes for the auditor: OK (consistent with the cited facts), NUMBER (a number not in the cited facts), UNIT (wrong unit), OVERCLAIM (stronger than
the evidence level of the cited facts: a cause or a confirmation the facts do not give), UNSUPPORTED (says something the cited facts do not say), OTHER (describe in the note). Only claims are audited, not summaries, caveats or recommendations.
"""

from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.argv += ["--design", "v2", "--server", "agritwin", "--replay"] if "--design" not in sys.argv else []

from tsxai.llm import RecordedLanguageModel  # noqa: E402
from tsxai.report import explain  # noqa: E402
from tsxai.semantics.formatter import render_fact  # noqa: E402

from manual_phase6_6_real_llm_test import DESIGN, MAX_TOKENS, RECORDS, MODELS, scenarios  # noqa: E402

SEED = 20261026
OUT = ROOT / "data" / "xai" / "audit"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    cases = list(scenarios())
    rows = []
    for key in MODELS:
        model = RecordedLanguageModel.load(RECORDS / f"{key}.json")
        for case, facts, pack in cases:
            for language in ("en", "es"):
                bundle = explain(facts, pack, model, language, max_tokens=MAX_TOKENS, design=DESIGN)
                if bundle.status != "OK":
                    continue
                by_id = {f.fact_id: f for f in bundle.facts}
                violations = {}
                for v in bundle.report.violations:
                    violations.setdefault(v.claim_id, []).append(v)
                for claim in bundle.raw.claims:
                    cited = [render_fact(by_id[f], pack, language) if f in by_id else f"(unknown fact id {f})" for f in claim.fact_ids]
                    flagged = violations.get(claim.claim_id, [])
                    rows.append({"model": key, "case": case, "language": language, "claim_id": claim.claim_id, "text": claim.text, "cited_facts": " || ".join(cited),
                                 "declared_numbers": "; ".join(f"{n.value} {n.unit} ({n.fact_id})" for n in claim.numeric_values), "confidence": claim.confidence,
                                 "flagged": bool(flagged), "rules": ",".join(sorted({v.rule for v in flagged})), "details": " | ".join(v.detail for v in flagged)})
    flagged_rows = [r for r in rows if r["flagged"]]
    clean_rows = [r for r in rows if not r["flagged"]]
    rng = random.Random(SEED)
    sample = flagged_rows + rng.sample(clean_rows, min(len(flagged_rows), len(clean_rows)))
    rng.shuffle(sample)
    for index, row in enumerate(sample, 1):
        row["row_id"] = f"A{index:03d}"
    blind = ["row_id", "model", "case", "language", "claim_id", "text", "cited_facts", "declared_numbers", "confidence"]
    with (OUT / "audit_blind.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[*blind, "verdict", "note"])
        writer.writeheader()
        writer.writerows({k: r[k] for k in blind} for r in sample)
    with (OUT / "audit_key.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["row_id", "model", "case", "language", "claim_id", "flagged", "rules", "details"])
        writer.writeheader()
        writer.writerows({k: r[k] for k in ("row_id", "model", "case", "language", "claim_id", "flagged", "rules", "details")} for r in sorted(sample, key=lambda r: r["row_id"]))
    print(json.dumps({"claims_in_evaluable_runs": len(rows), "flagged": len(flagged_rows), "unflagged": len(clean_rows), "sample": len(sample), "seed": SEED}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
