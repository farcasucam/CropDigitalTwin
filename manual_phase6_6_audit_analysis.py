"""Analysis of the human annotations of the 52 audited claims against the verifier (old and corrected) and the assistant's first pass.

    python -u manual_phase6_6_audit_analysis.py        # offline; reads data/xai/audit/*.csv, writes data/xai/audit/audit_analysis.json

Annotation: OK, or an error code (NUMBER, UNIT, OVERCLAIM, UNSUPPORTED, OTHER); every error code counts as "error" in the binary comparison. Two annotation files are read (`audit_blind_annotated.csv`, `audit_blind_annotated2.csv`);
who made the second one and whether it was blind to the first has not been stated, so the agreement figures are between two annotations, not yet certified as two independent auditors. The sample was drawn with the OLD verifier
(all its 26 flags plus 26 random unflagged claims), so recall can be extrapolated only for the old verifier, and only roughly; the corrected verifier is compared on the same 52 claims, which is a biased frame for it.
Verifier precision and recall are given for four readings of the truth (annotation 1, annotation 2, error in both, error in either), because the annotations disagree on a few claims. No annotation is edited.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

AUDIT = Path(__file__).resolve().parent / "data" / "xai" / "audit"
CODES = {"OK", "NUMBER", "UNIT", "OVERCLAIM", "UNSUPPORTED", "OTHER"}


def rows(name: str, encoding: str) -> dict[str, dict[str, str]]:
    with (AUDIT / name).open(encoding=encoding, newline="") as handle:
        return {r["row_id"]: r for r in csv.DictReader(handle)}


def confusion(ids, predicted, truth) -> dict[str, float]:
    tp = sum(1 for i in ids if predicted[i] and truth[i])
    fp = sum(1 for i in ids if predicted[i] and not truth[i])
    fn = sum(1 for i in ids if not predicted[i] and truth[i])
    tn = sum(1 for i in ids if not predicted[i] and not truth[i])
    return {"TP": tp, "FP": fp, "FN": fn, "TN": tn, "precision": round(tp / max(1, tp + fp), 3), "recall_in_sample": round(tp / max(1, tp + fn), 3)}


def kappa(a: dict[str, object], b: dict[str, object]) -> dict[str, float]:
    n = len(a)
    observed = sum(a[i] == b[i] for i in a) / n
    expected = sum((sum(1 for i in a if a[i] == c) / n) * (sum(1 for i in b if b[i] == c) / n) for c in set(a.values()) | set(b.values()))
    return {"agreement": round(observed, 3), "kappa": round((observed - expected) / (1 - expected), 3) if expected < 1 else 1.0}


def main() -> int:
    annotations = {"annotation_1": rows("audit_blind_annotated.csv", "utf-8-sig"), "annotation_2": rows("audit_blind_annotated2.csv", "utf-8-sig")}
    old = rows("audit_key.csv", "utf-8-sig")
    new = rows("audit_key_corrected_verifier.csv", "utf-8")
    first = rows("audit_assistant_firstpass.csv", "utf-8")
    ids = sorted(old)
    assert len(ids) == 52 and all(set(a) == set(ids) for a in annotations.values()) and set(new) == set(first) == set(ids), "every annotation must have the 52 rows of the sample"
    for name, a in annotations.items():
        assert all(a[i]["verdict"].strip().upper() in CODES for i in ids), f"unknown verdict code in {name}"
        assert all(a[i]["text"] == annotations["annotation_1"][i]["text"] and a[i]["cited_facts"] == annotations["annotation_1"][i]["cited_facts"] for i in ids), f"{name}: the blind columns were modified"
    code = {n: {i: a[i]["verdict"].strip().upper() for i in ids} for n, a in annotations.items()}
    error = {n: {i: c != "OK" for i, c in codes.items()} for n, codes in code.items()}
    truths = {"annotation_1": error["annotation_1"], "annotation_2": error["annotation_2"],
              "error_in_both": {i: error["annotation_1"][i] and error["annotation_2"][i] for i in ids}, "error_in_either": {i: error["annotation_1"][i] or error["annotation_2"][i] for i in ids}}
    old_flag = {i: old[i]["flagged"] == "True" for i in ids}
    new_flag = {i: new[i]["now_flagged"] == "True" for i in ids}
    assistant = {i: first[i]["assistant_category"] not in ("OK", "FP_ARTIFACT") for i in ids}
    disagreements = {i: {"annotation_1": code["annotation_1"][i], "annotation_2": code["annotation_2"][i], "old_flag": old_flag[i], "corrected_flag": new_flag[i], "assistant": first[i]["assistant_category"]}
                     for i in ids if code["annotation_1"][i] != code["annotation_2"][i]}
    # old-verifier recall, extrapolated: all 26 flags audited, 26 unflagged sampled out of 78
    recall = {}
    for name, truth in truths.items():
        caught = sum(1 for i in ids if truth[i] and old_flag[i])
        missed = sum(1 for i in ids if truth[i] and not old_flag[i])
        scale = 78 / sum(1 for i in ids if not old_flag[i])
        recall[name] = {"caught": caught, "missed_in_sample": missed, "missed_extrapolated": round(missed * scale, 1), "recall": round(caught / (caught + missed * scale), 2)}
    report = {
        "claims_audited": len(ids), "verdicts": {n: dict(Counter(c.values())) for n, c in code.items()}, "errors": {n: sum(t.values()) for n, t in truths.items()},
        "agreement_between_annotations": {"binary_ok_vs_error": kappa(error["annotation_1"], error["annotation_2"]), "six_codes": kappa(code["annotation_1"], code["annotation_2"]),
                                          "claims_with_different_code": len(disagreements), "claims_where_one_says_ok_and_the_other_error": sum(1 for i in disagreements if error["annotation_1"][i] != error["annotation_2"][i])},
        "disagreements": disagreements,
        "old_verifier_as_sampled": {n: confusion(ids, old_flag, t) for n, t in truths.items()},
        "corrected_verifier_same_claims": {n: confusion(ids, new_flag, t) for n, t in truths.items()},
        "assistant_first_pass": {n: confusion(ids, assistant, t) for n, t in truths.items()},
        "old_verifier_recall_extrapolated": {"by_truth": recall, "note": "26 unflagged sampled of 78; very wide uncertainty"},
        "errors_in_both_missed_by_corrected_verifier": {i: [code["annotation_1"][i], code["annotation_2"][i]] for i in ids if truths["error_in_both"][i] and not new_flag[i]},
        "corrected_flags_judged_ok_by_both": {i: new[i]["now_rules"] for i in ids if new_flag[i] and not truths["error_in_either"][i]},
        "limits": "who made annotation 2 and whether it was blind to annotation 1 is not stated; sample drawn with the old verifier; the assistant that wrote the verifier also made the first pass; 52 claims; not a model error rate",
    }
    report["report_hash"] = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()
    (AUDIT / "audit_analysis.json").write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    keys = ("verdicts", "errors", "agreement_between_annotations", "disagreements", "old_verifier_as_sampled", "corrected_verifier_same_claims", "old_verifier_recall_extrapolated", "errors_in_both_missed_by_corrected_verifier", "corrected_flags_judged_ok_by_both")
    print(json.dumps({k: report[k] for k in keys}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
