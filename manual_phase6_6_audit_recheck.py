"""Re-run the corrected verifier on the 52 audited claims and cross it with the assistant's first-pass categories.

    python -u manual_phase6_6_audit_recheck.py        # offline; writes data/xai/audit/audit_key_corrected_verifier.csv

The audit sheet and its sample are NOT redrawn: the claims are the ones drawn with the previous verifier. The corrected verifier was written after reading these very claims, so this is a regression check of the fix on the cases that
motivated it, not an independent measurement of the new verifier.
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.argv += ["--design", "v2", "--server", "agritwin", "--replay"] if "--design" not in sys.argv else []

from tsxai.llm import RecordedLanguageModel  # noqa: E402
from tsxai.report import explain  # noqa: E402

from manual_phase6_6_real_llm_test import DESIGN, MAX_TOKENS, MODELS, RECORDS, scenarios  # noqa: E402

AUDIT = ROOT / "data" / "xai" / "audit"


def main() -> int:
    now = {}
    for key in MODELS:
        model = RecordedLanguageModel.load(RECORDS / f"{key}.json")
        for case, facts, pack in scenarios():
            for language in ("en", "es"):
                bundle = explain(facts, pack, model, language, max_tokens=MAX_TOKENS, design=DESIGN)
                if bundle.status != "OK":
                    continue
                by_claim = {}
                for v in bundle.report.violations:
                    by_claim.setdefault(v.claim_id, []).append(v)
                for claim in bundle.raw.claims:
                    now[(key, case, language, claim.claim_id)] = by_claim.get(claim.claim_id, [])
    first_pass = {r["row_id"]: r["assistant_category"] for r in csv.DictReader((AUDIT / "audit_assistant_firstpass.csv").open(encoding="utf-8"))}
    rows, table = [], Counter()
    for r in csv.DictReader((AUDIT / "audit_key.csv").open(encoding="utf-8-sig")):
        found = now[(r["model"], r["case"], r["language"], r["claim_id"])]
        rows.append({"row_id": r["row_id"], "was_flagged": r["flagged"], "now_flagged": bool(found), "now_rules": ",".join(sorted({v.rule for v in found})), "assistant_category": first_pass[r["row_id"]]})
        table[(first_pass[r["row_id"]], r["flagged"] == "True", bool(found))] += 1
    with (AUDIT / "audit_key_corrected_verifier.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print("category, flagged before, flagged now: count")
    for (category, before, after), count in sorted(table.items()):
        print(f"  {category:18s} {str(before):5s} {str(after):5s} {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
