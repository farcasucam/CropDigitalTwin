"""Phase 6.2 verification: the deterministic analyzer against the known changes of a DEVELOPMENT pilot of the benchmark (RQ1 smoke evaluation, not the preregistered evaluation).

    python -u manual_phase6_2_analyzer_test.py [N]    # N scenarios (default 24); writes data/xai/gctsb_dev_pilot/ and data/xai/rq1_pilot_report.json

Only scenarios of the development partition are scored; the test partition is never opened here. A pilot of a few dozen scenarios gives wide intervals: it checks that the pipeline works and shows the
direction of the effects, nothing more. Truth is the truth of the SIMULATED twin; the data are synthetic; nothing here is a validation or a calibration.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from tsxai.analysis import AnalyzerConfig  # noqa: E402
from tsxai.analysis.evaluate import evaluate_rq1, reference_alarm_rate  # noqa: E402
from tsxai.bench import generate, leakage_report, read_scenario, sample_scenarios, verify  # noqa: E402
from tsxai.core import content_hash  # noqa: E402

from agri_twin.interfaces.xai_adapter import TwinSimulator, benchmark_design  # noqa: E402

LEVELS = ("none", "low", "medium", "high")
CONFIGS = {"stl_pelt": AnalyzerConfig(holt_winters=False), "stl_pelt_white_noise": AnalyzerConfig(holt_winters=False, noise_model="white"),
           "stl_residual_pelt": AnalyzerConfig(method="stl_residual_pelt", holt_winters=False), "raw_pelt": AnalyzerConfig(method="raw_pelt", holt_winters=False),
           "zscore": AnalyzerConfig(method="zscore", holt_winters=False)}


def main() -> int:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    sim, design = TwinSimulator(), benchmark_design()
    out = ROOT / "data" / "xai" / "gctsb_dev_pilot"
    specs = sample_scenarios(sim, count, 20261024, design)
    dev = [s for s in specs if s.split == "dev"]
    manifest_file = out / "manifest.json"
    reuse = manifest_file.exists() and json.loads(manifest_file.read_text(encoding="utf-8")).get("count") == len(dev)
    started = time.perf_counter()
    if not reuse:
        manifest = generate(sim, dev, out, design, baseline_label="dev-pilot")
    else:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    seconds = time.perf_counter() - started
    assert verify(out) == [] and leakage_report(manifest)["status"] == "PASS"
    records = [read_scenario(out / "scenarios" / f"{s.scenario_id}.json.gz") for s in dev]
    assert records and all(r["spec"]["split"] == "dev" for r in records), "only the development partition may be scored"
    results = evaluate_rq1(records, design, CONFIGS, LEVELS, tolerance=3, material_fraction=0.25, resamples=500)
    assert evaluate_rq1(records, design, {"stl_pelt": CONFIGS["stl_pelt"]}, ("none",), tolerance=3, material_fraction=0.25, resamples=500)["methods"]["stl_pelt"]["none"] == results["methods"]["stl_pelt"]["none"]
    sensitivity = {f"materiality={fraction},tolerance={tol}": evaluate_rq1(records, design, {"stl_pelt": CONFIGS["stl_pelt"]}, ("none", "medium"), tolerance=tol, material_fraction=fraction, resamples=200)["methods"]["stl_pelt"]
                   for fraction, tol in ((0.1, 3), (0.5, 3), (0.25, 2), (0.25, 6))}
    alarms = reference_alarm_rate(records, CONFIGS)
    report = {"status": "PASS", "scenarios_scored": len(records), "partition": "dev", "manifest_hash": manifest["manifest_hash"], "configs": {k: v.content_hash for k, v in CONFIGS.items()},
              "results": results, "sensitivity_stl_pelt": sensitivity, "reference_series_alarms": alarms,
              "statement": "development pilot, wide intervals: smoke evaluation of the pipeline, not the preregistered RQ1 evaluation; synthetic data; truth of the simulated twin"}
    report["report_hash"] = content_hash(report)
    (ROOT / "data" / "xai" / "rq1_pilot_report.json").write_text(json.dumps(report, indent=1, sort_keys=True, allow_nan=True), encoding="utf-8")
    summary = {method: {level: {k: (round(v, 3) if isinstance(v, float) else v) for k, v in cell.items() if k in ("tp", "fp", "fn", "precision", "recall", "f1", "median_abs_error")}
                        for level, cell in cells.items() if level in ("none", "high")} for method, cells in results["methods"].items()}
    print(json.dumps({"status": "PASS", "scored": len(records), "seconds_generating": round(seconds, 1), "summary": summary, "reference_alarms": alarms}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
