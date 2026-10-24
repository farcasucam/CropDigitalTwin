"""Phase 6.2b verification: detection power against effect size, a precision-recall sweep, alternative detectors, and detection on what the known forcing does not explain.

    python -u manual_phase6_2b_adjusted_analysis_test.py     # reads data/xai/gctsb_dev_pilot/ (run manual_phase6_2_analyzer_test.py first); writes data/xai/rq1b_pilot_report.json

Development partition only. A pilot: intervals are wide and nothing here is the preregistered evaluation. Truth is the truth of the SIMULATED twin; the data are synthetic.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from tsxai.analysis import AnalyzerConfig  # noqa: E402
from tsxai.analysis.study import evaluate_adjusted, penalty_sweep, power_curve  # noqa: E402
from tsxai.bench import read_scenario  # noqa: E402
from tsxai.core import content_hash  # noqa: E402

from agri_twin.interfaces.xai_adapter import benchmark_design  # noqa: E402

COVARIATES = ["outdoor_temperature_c", "outdoor_radiation_w_m2", "outdoor_relative_humidity_pct", "outdoor_wind_speed_m_s", "outdoor_rain_rate_mm_h"]
CONFIGS = {"stl_pelt": AnalyzerConfig(holt_winters=False), "stl_pelt_white_noise": AnalyzerConfig(holt_winters=False, noise_model="white"), "stl_binseg": AnalyzerConfig(method="stl_binseg", holt_winters=False),
           "stl_cusum": AnalyzerConfig(method="stl_cusum", holt_winters=False), "zscore": AnalyzerConfig(method="zscore", holt_winters=False), "raw_pelt": AnalyzerConfig(method="raw_pelt", holt_winters=False)}
SHORT, LONG = (0, 1, 2, 3, 6), (0, 1, 2, 3, 6, 12, 24)


def main() -> int:
    design = benchmark_design()
    root = ROOT / "data" / "xai" / "gctsb_dev_pilot"
    records = [read_scenario(p) for p in sorted((root / "scenarios").glob("*.json.gz"))]
    assert records and all(r["spec"]["split"] == "dev" for r in records), "only the development partition may be scored"
    report = {"status": "PASS", "scenarios": len(records), "partition": "dev", "configs": {k: v.content_hash for k, v in CONFIGS.items()}, "power": {}, "sweep": {}, "adjusted": {}}
    for level in ("none", "medium"):
        report["power"][level] = power_curve(records, design, CONFIGS, level)
        report["sweep"][level] = penalty_sweep(records, design, CONFIGS["stl_pelt"], (0.5, 1, 2, 4, 8, 16, 32, 64), level)
        for name, lags in (("short_lags", SHORT), ("long_lags", LONG)):
            report["adjusted"][f"{level}/{name}"] = evaluate_adjusted(records, design, COVARIATES, CONFIGS["stl_pelt"], level, lags=lags)
    report["statement"] = "development pilot: wide intervals, not the preregistered evaluation; synthetic data; truth of the simulated twin"
    report["report_hash"] = content_hash({k: v for k, v in report.items() if k != "statement"})
    (ROOT / "data" / "xai" / "rq1b_pilot_report.json").write_text(json.dumps(report, indent=1, sort_keys=True, allow_nan=True), encoding="utf-8")
    print("minimum detectable effect bin (power >= 0.8, level none):", {m: c["minimum_detectable_effect_bin"] for m, c in report["power"]["none"]["methods"].items()})
    print("power by bin (none):", json.dumps({m: {b: round(v["power"], 2) for b, v in c["bins"].items()} for m, c in report["power"]["none"]["methods"].items()}))
    print("precision-recall sweep (none):", [(p["penalty_k"], round(p["precision"], 3), round(p["recall"], 3)) for p in report["sweep"]["none"]["points"]], "AUPRC", round(report["sweep"]["none"]["area_under_precision_recall"], 3))
    for key, r in report["adjusted"].items():
        print("adjusted", key, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items() if k not in ("level", "tolerance", "material_fraction", "lags")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
