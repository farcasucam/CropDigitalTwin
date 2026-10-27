"""Analysis of the human audit of 52 real claims against the verifier (old and corrected) and the assistant's first pass.

    python -u manual_phase6_6_audit_analysis.py        # offline; reads data/xai/audit/*.csv, writes data/xai/audit/audit_analysis.json

Human verdict: OK, or an error code (NUMBER, UNIT, OVERCLAIM, UNSUPPORTED, OTHER); every error code counts as "error" in the binary comparison. One auditor, so there is NO inter-annotator agreement yet. The sample was drawn with the OLD verifier
(all its 26 flags plus 26 random unflagged claims), so recall can be extrapolated only for the old verifier, and only roughly; the corrected verifier is compared on the same 52 claims, which is a biased frame for it.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

AUDIT = Path(__file__).resolve().parent / "data" / "xai" / "audit"


def rows(name: str, encoding: str) -> dict[str, dict[str, str]]:
    with (AUDIT / name).open(encoding=encoding, newline="") as handle:
        return {r["row_id"]: r for r in csv.DictReader(handle)}


def confusion(ids, predicted, truth) -> dict[str, float]:
    tp = sum(1 for i in ids if predicted[i] and truth[i])
    fp = sum(1 for i in ids if predicted[i] and not truth[i])
    fn = sum(1 for i in ids if not predicted[i] and truth[i])
    tn = sum(1 for i in ids if not predicted[i] and not truth[i])
    return {"TP": tp, "FP": fp, "FN": fn, "TN": tn, "precision": round(tp / max(1, tp + fp), 3), "recall_in_sample": round(tp / max(1, tp + fn), 3)}


def kappa(a: dict[str, bool], b: dict[str, bool]) -> dict[str, float]:
    n = len(a)
    observed = sum(a[i] == b[i] for i in a) / n
    pa, pb = sum(a.values()) / n, sum(b.values()) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    return {"agreement": round(observed, 3), "kappa": round((observed - expected) / (1 - expected), 3)}


def main() -> int:
    human = rows("audit_blind_annotated.csv", "utf-8-sig")
    old = rows("audit_key.csv", "utf-8-sig")
    new = rows("audit_key_corrected_verifier.csv", "utf-8")
    first = rows("audit_assistant_firstpass.csv", "utf-8")
    ids = sorted(human)
    assert len(ids) == 52 and set(ids) == set(old) == set(new) == set(first), "the annotated sheet must have the 52 rows of the sample"
    truth = {i: human[i]["verdict"].strip().upper() != "OK" for i in ids}
    assert all(human[i]["verdict"].strip().upper() in {"OK", "NUMBER", "UNIT", "OVERCLAIM", "UNSUPPORTED", "OTHER"} for i in ids), "unknown verdict code"
    old_flag = {i: old[i]["flagged"] == "True" for i in ids}
    new_flag = {i: new[i]["now_flagged"] == "True" for i in ids}
    assistant = {i: first[i]["assistant_category"] not in ("OK", "FP_ARTIFACT") for i in ids}
    unflagged_old = sum(1 for i in ids if not old_flag[i])
    missed_old = sum(1 for i in ids if truth[i] and not old_flag[i])
    caught_old = sum(1 for i in ids if truth[i] and old_flag[i])
    # all 26 old flags were audited; the 26 unflagged are a random sample of 78 unflagged claims in the 22 evaluable runs
    scale = 78 / unflagged_old
    report = {
        "claims_audited": len(ids), "human_verdicts": dict(Counter(human[i]["verdict"].strip().upper() for i in ids)),
        "human_errors": sum(truth.values()),
        "old_verifier_as_sampled": confusion(ids, old_flag, truth),
        "corrected_verifier_same_claims": confusion(ids, new_flag, truth),
        "assistant_first_pass": confusion(ids, assistant, truth),
        "human_vs_assistant": kappa(truth, assistant),
        "old_verifier_recall_extrapolated": {"caught_in_all_flags": caught_old, "missed_in_sample": missed_old, "missed_extrapolated_to_78_unflagged": round(missed_old * scale, 1),
                                             "recall": round(caught_old / (caught_old + missed_old * scale), 2), "note": "26 unflagged sampled of 78; very wide uncertainty"},
        "errors_missed_by_corrected_verifier": {i: human[i]["verdict"].strip().upper() for i in ids if truth[i] and not new_flag[i]},
        "flags_of_corrected_verifier_judged_ok": {i: new[i]["now_rules"] for i in ids if new_flag[i] and not truth[i]},
        "human_error_types_vs_corrected_rules": {i: [human[i]["verdict"].strip().upper(), new[i]["now_rules"] or "-"] for i in ids if truth[i]},
        "limits": "one auditor: no inter-annotator agreement; sample drawn with the old verifier; the assistant that wrote the verifier also made the first pass; 52 claims; not a model error rate",
    }
    report["report_hash"] = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()
    (AUDIT / "audit_analysis.json").write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("human_verdicts", "old_verifier_as_sampled", "corrected_verifier_same_claims", "human_vs_assistant", "old_verifier_recall_extrapolated", "flags_of_corrected_verifier_judged_ok", "errors_missed_by_corrected_verifier")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
