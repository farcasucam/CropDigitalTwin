"""Phase 6.2c verification: detection scored against a truth that includes the natural changes of the system (G1b), next to the intervention-only truth of G1.

    python -u manual_phase6_2c_full_truth_test.py     # reads data/xai/gctsb_dev_pilot/; writes data/xai/rq1c_pilot_report.json

Development partition only. A pilot: nothing here is the preregistered evaluation. Truth is the truth of the SIMULATED twin; the data are synthetic.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from tsxai.analysis import AnalyzerConfig  # noqa: E402
from tsxai.analysis.natural import evaluate_full_truth, full_truth  # noqa: E402
from tsxai.bench import read_scenario  # noqa: E402
from tsxai.core import content_hash  # noqa: E402

from agri_twin.interfaces.xai_adapter import benchmark_design  # noqa: E402

COVARIATES = ["outdoor_temperature_c", "outdoor_radiation_w_m2", "outdoor_relative_humidity_pct", "outdoor_wind_speed_m_s", "outdoor_rain_rate_mm_h"]
CONFIGS = {"stl_pelt": AnalyzerConfig(holt_winters=False), "stl_binseg": AnalyzerConfig(method="stl_binseg", holt_winters=False), "zscore": AnalyzerConfig(method="zscore", holt_winters=False),
           "raw_pelt": AnalyzerConfig(method="raw_pelt", holt_winters=False)}
THRESHOLDS = (0.25, 0.5, 1.0)


def main() -> int:
    design = benchmark_design()
    root = ROOT / "data" / "xai" / "gctsb_dev_pilot"
    records = [read_scenario(p) for p in sorted((root / "scenarios").glob("*.json.gz"))]
    assert records and all(r["spec"]["split"] == "dev" for r in records), "only the development partition may be scored"
    report = {"status": "PASS", "scenarios": len(records), "partition": "dev", "configs": {k: v.content_hash for k, v in CONFIGS.items()}, "evaluation": {}, "truth_composition": {}}
    for level in ("none", "medium"):
        report["evaluation"][level] = evaluate_full_truth(records, design, CONFIGS, COVARIATES, level, thresholds=THRESHOLDS)
    for threshold in THRESHOLDS:
        counts = {"INTERVENTION": 0, "FORCING": 0, "NATURAL": 0}
        series = 0
        for record in records:
            for name in sorted(record["reference_series"]):
                if name in COVARIATES:
                    continue
                series += 1
                for row in full_truth(record, name, COVARIATES, threshold):
                    counts[row["cause"]] += 1
        report["truth_composition"][f"{threshold:g}"] = {"series": series, **counts}
    report["statement"] = "development pilot: not the preregistered evaluation; synthetic data; truth of the simulated twin"
    report["report_hash"] = content_hash({k: v for k, v in report.items() if k != "statement"})
    (ROOT / "data" / "xai" / "rq1c_pilot_report.json").write_text(json.dumps(report, indent=1, sort_keys=True, allow_nan=True), encoding="utf-8")
    print("truth composition:", json.dumps(report["truth_composition"]))
    for level, block in report["evaluation"].items():
        for method, cells in block["methods"].items():
            for threshold, c in cells.items():
                rc = {k: round(v["recall"], 2) for k, v in c["recall_by_cause"].items()}
                print(level, method, "thr", threshold, "P", round(c["precision"], 3), "R", round(c["recall"], 3), "F1", round(c["f1"], 3), "chance P/R", round(c["chance"]["precision"], 3), round(c["chance"]["recall"], 3), "P(interventions only)", round(c["precision_against_interventions_only"], 3),
                      "recall by cause", rc, "truth/series", round(c["true_changes_per_series"], 1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
