"""Analysis of the human annotations of the 52 audited claims against the verifier (old and corrected) and the assistant's first pass.

    python -u manual_phase6_6_audit_analysis.py        # offline; reads data/xai/audit/*.csv, writes data/xai/audit/audit_analysis.json

Every file `audit_blind_annotated*.csv` is one annotator's version of the blind sheet (each made without seeing the others or the verifier's output). A verdict is OK or an error code (NUMBER, UNIT, OVERCLAIM, UNSUPPORTED, OTHER); every
error code counts as "error" in the binary comparison. The sample was drawn with the OLD verifier (all its 26 flags plus 26 random unflagged claims), so recall can be extrapolated only for the old verifier, and only roughly; the corrected
verifier is compared on the same 52 claims, which is a biased frame for it. Verifier precision and recall are given against several readings of the truth (each annotator, majority, unanimity, at least one), because annotators disagree on
a few claims. No annotation is edited.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from itertools import combinations
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


def cohen(a: dict[str, object], b: dict[str, object]) -> float:
    n = len(a)
    observed = sum(a[i] == b[i] for i in a) / n
    expected = sum((sum(1 for i in a if a[i] == c) / n) * (sum(1 for i in b if b[i] == c) / n) for c in set(a.values()) | set(b.values()))
    return round((observed - expected) / (1 - expected), 3) if expected < 1 else 1.0


def fleiss(labels: list[dict[str, object]]) -> float:
    """Fleiss' kappa for a fixed number of annotators over the same items."""
    items, raters = list(labels[0]), len(labels)
    categories = sorted({v for a in labels for v in a.values()}, key=str)
    counts = [[sum(1 for a in labels if a[i] == c) for c in categories] for i in items]
    p_i = [(sum(n * n for n in row) - raters) / (raters * (raters - 1)) for row in counts]
    p_j = [sum(row[k] for row in counts) / (len(items) * raters) for k in range(len(categories))]
    observed, expected = sum(p_i) / len(items), sum(p * p for p in p_j)
    return round((observed - expected) / (1 - expected), 3) if expected < 1 else 1.0


def main() -> int:
    files = sorted(p.name for p in AUDIT.glob("audit_blind_annotated*.csv"))
    names = [f"annotation_{n + 1}" for n in range(len(files))]
    annotations = {name: rows(f, "utf-8-sig") for name, f in zip(names, files)}
    old = rows("audit_key.csv", "utf-8-sig")
    new = rows("audit_key_corrected_verifier.csv", "utf-8")
    first = rows("audit_assistant_firstpass.csv", "utf-8")
    ids = sorted(old)
    assert len(ids) == 52 and len(names) >= 2 and all(set(a) == set(ids) for a in annotations.values()) and set(new) == set(first) == set(ids), "every annotation must have the 52 rows of the sample"
    reference = rows("audit_blind.csv", "utf-8-sig")  # the sheet as it was sent
    for name, a in annotations.items():
        assert all(a[i]["verdict"].strip().upper() in CODES for i in ids), f"unknown or empty verdict code in {name}"
        if "text" in a[ids[0]]:  # a sheet may carry only row_id, verdict and note; when it carries the claim, the claim must be the one that was sent
            assert all(a[i]["text"] == reference[i]["text"] and a[i]["cited_facts"] == reference[i]["cited_facts"] for i in ids), f"{name}: the blind columns were modified"
    code = {n: {i: a[i]["verdict"].strip().upper() for i in ids} for n, a in annotations.items()}
    error = {n: {i: c != "OK" for i, c in codes.items()} for n, codes in code.items()}
    votes = {i: sum(error[n][i] for n in names) for i in ids}
    k = len(names)
    truths = {**error, "majority_error": {i: votes[i] * 2 > k for i in ids}, "unanimous_error": {i: votes[i] == k for i in ids}, "at_least_one_error": {i: votes[i] >= 1 for i in ids}}
    old_flag = {i: old[i]["flagged"] == "True" for i in ids}
    new_flag = {i: new[i]["now_flagged"] == "True" for i in ids}
    assistant = {i: first[i]["assistant_category"] not in ("OK", "FP_ARTIFACT") for i in ids}
    recall = {}
    for name, truth in truths.items():
        caught = sum(1 for i in ids if truth[i] and old_flag[i])
        missed = sum(1 for i in ids if truth[i] and not old_flag[i])
        scale = 78 / sum(1 for i in ids if not old_flag[i])  # all 26 old flags audited, 26 unflagged sampled out of 78
        recall[name] = {"caught": caught, "missed_in_sample": missed, "missed_extrapolated": round(missed * scale, 1), "recall": round(caught / (caught + missed * scale), 2) if caught + missed else None}
    split = {i: {"errors_of_%d" % k: votes[i], **{n: code[n][i] for n in names}, "old_flag": old_flag[i], "corrected_flag": new_flag[i], "assistant": first[i]["assistant_category"]} for i in ids if 0 < votes[i] < k}
    report = {
        "claims_audited": len(ids), "annotators": k, "files": files,
        "verdicts": {n: dict(Counter(c.values())) for n, c in code.items()}, "errors_per_annotator": {n: sum(error[n].values()) for n in names},
        "claims_by_number_of_annotators_saying_error": dict(sorted(Counter(votes.values()).items())),
        "agreement": {"fleiss_kappa_binary_ok_vs_error": fleiss([error[n] for n in names]), "fleiss_kappa_six_codes": fleiss([code[n] for n in names]),
                      "cohen_kappa_binary_by_pair": {f"{a}-{b}": cohen(error[a], error[b]) for a, b in combinations(names, 2)},
                      "cohen_kappa_six_codes_by_pair": {f"{a}-{b}": cohen(code[a], code[b]) for a, b in combinations(names, 2)},
                      "claims_all_annotators_agree_on_ok_vs_error": sum(1 for i in ids if votes[i] in (0, k)), "claims_with_split_votes": len(split)},
        "split_votes": split,
        "old_verifier_as_sampled": {n: confusion(ids, old_flag, t) for n, t in truths.items()},
        "corrected_verifier_same_claims": {n: confusion(ids, new_flag, t) for n, t in truths.items()},
        "assistant_first_pass": {n: confusion(ids, assistant, t) for n, t in truths.items()},
        "old_verifier_recall_extrapolated": {"by_truth": recall, "note": "26 unflagged sampled of 78; very wide uncertainty"},
        "unanimous_errors_missed_by_corrected_verifier": {i: [code[n][i] for n in names] for i in ids if truths["unanimous_error"][i] and not new_flag[i]},
        "corrected_flags_judged_ok_by_all": {i: new[i]["now_rules"] for i in ids if new_flag[i] and votes[i] == 0},
        "limits": "52 claims; sample drawn with the old verifier; the assistant that wrote the verifier also made the first pass; annotator identities and expertise are not recorded here; not a model error rate",
    }
    report["report_hash"] = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()
    (AUDIT / "audit_analysis.json").write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    keys = ("verdicts", "errors_per_annotator", "claims_by_number_of_annotators_saying_error", "agreement", "split_votes", "old_verifier_as_sampled", "corrected_verifier_same_claims", "old_verifier_recall_extrapolated",
            "unanimous_errors_missed_by_corrected_verifier", "corrected_flags_judged_ok_by_all")
    print(json.dumps({key: report[key] for key in keys}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
