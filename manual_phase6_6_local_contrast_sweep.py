"""Phase 6.6, sensitivity of the local analysis of the contrast to its three conventions (k robust standard deviations, minimum run, samples of context), on the reactor pairs of manual_phase6_6_local_contrast_test.py.

    python -u manual_phase6_6_local_contrast_sweep.py     # writes data/xai/local_contrast_sweep.json

Same plants, noise levels and oracle as that script; only the three conventions change. One convention varies at a time around the default (k=4, min_run=3, context=60), so the table shows what each one does on its own.
For each setting: how many of the 8 hidden pairs B1 abstains on at low and medium noise (right: 8), how many of the 8 visible pairs the stretch is found in, and the share of B1's cited facts on an affected variable and window.
Synthetic teaching model, 8 related plants, no language model.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from tsxai.core import content_hash  # noqa: E402

from manual_phase6_6_local_contrast_test import run  # noqa: E402

SETTINGS = [{"k": 4.0, "min_run": 3, "context": 60}] + [{"k": k, "min_run": 3, "context": 60} for k in (2.0, 3.0, 6.0, 8.0)] + [{"k": 4.0, "min_run": m, "context": 60} for m in (1, 2, 5, 8)] \
    + [{"k": 4.0, "min_run": 3, "context": c} for c in (0, 20, 120)]


def digest(report: dict, level: str) -> dict:
    cell = report["summary"]
    hidden, visible = cell[f"hidden_setting|{level}|local|B1"], cell[f"visible_setting|{level}|local|B1"]
    cited = visible["cited_relevant"] + visible["cited_irrelevant"]
    return {"hidden_abstained": hidden["abstained"], "visible_stretch_found": visible["stretch_found"], "visible_relevant_share": None if not cited else round(visible["cited_relevant"] / cited, 3), "visible_cited": cited}


def main() -> int:
    table = []
    for setting in SETTINGS:
        report = run(**setting)
        row = {**setting, **{level: digest(report, level) for level in ("low", "medium")}}
        table.append(row)
        print(row, flush=True)
    out = {"status": "MEASURED", "settings": table, "statement": "sensitivity of a detector's conventions on 8 related synthetic plants; not a rate with an interval"}
    out["sweep_hash"] = content_hash(out["settings"])
    (ROOT / "data" / "xai" / "local_contrast_sweep.json").write_text(json.dumps(out, indent=1, sort_keys=True, allow_nan=False), encoding="utf-8")
    print(out["sweep_hash"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
