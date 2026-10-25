"""Phase 6.3c: the latent-threshold (thermostat) hypothesis and the measures for an intermittent demand, on the development bank of the main context (decisions D8-D11).

    python -u manual_phase6_3c_thermostat_intermittency.py [--workers 6] [--threshold 0.0] [--min-pairs 10] [--service name=url ...]      # needs data/xai/gctsb_c_dev/; writes data/xai/forecast_c_strata_report.json

Exploratory analysis of the DEVELOPMENT partition (never the test one); it does not prove a mechanism and a negative reading is as publishable as a positive one.
* Stratification of the counterfactual pairs of the controller's demand (heating, cooling) by what the forecaster had seen of that demand: ACTIVE when the demand summed over the context window BEFORE the cut-off is above zero,
  FLAT when it is identically zero. Nothing of the horizon is used. Cells under ``--min-pairs`` pairs are declared not estimable; intervals resample whole crop-seasons.
  Reading rule, stated before the numbers: a forecaster that fails in the FLAT stratum and works in the ACTIVE one fails for lack of prior excitation (the response to a threshold that was never crossed cannot be learned);
  one that fails in both fails for a reason that excitation does not explain (for example a linear model against a threshold nonlinearity).
* Measures that do not need a scale of the context: onset matching within the host's tolerance (F1 of pooled counts), dual conditional MAE (instants with demand and instants without) and the integral over the horizon
  (kWh at an hourly sample). The integral of the effect is the main volume criterion of the counterfactual (a decision derived from development, recorded in docs/xai/PREREGISTRATION.md).
Truth is the truth of the SIMULATED twin; synthetic data; no quality claim.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from tsxai.adapters import HttpForecastBackend  # noqa: E402
from tsxai.bench import ScenarioSpec, read_scenario  # noqa: E402
from tsxai.core import content_hash, time_scale_of  # noqa: E402
from tsxai.forecast import HoltWintersBackend, LaggedRegressionBackend, SeasonalNaiveBackend, backtest, counterfactual_gate, f1_of_counts, stratified_summary  # noqa: E402

from agri_twin.interfaces.xai_adapter import TwinSimulator, intervention_plan_variables, twin_series_source  # noqa: E402
from manual_phase6_3b_context_c_analysis import BANK, CONTEXT, CONTROLLER, HORIZON, ORIGINS, CachedTwin, Memo, _prefetch, clean  # noqa: E402


def mean_of(rows, key):
    finite = [r[key] for r in rows if r[key] == r[key]]
    return statistics.fmean(finite) if finite else None


def quantile(values, q):
    ordered = sorted(values)
    return ordered[int(q * (len(ordered) - 1))] if ordered else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--threshold", type=float, default=0.0, help="demand above this is 'on' (kW)")
    parser.add_argument("--min-pairs", type=int, default=10)
    parser.add_argument("--backtest-only", action="store_true", help="only the backtest measures (a sensitivity run for another --threshold); the gate is not run")
    parser.add_argument("--service", action="append", default=[])
    args = parser.parse_args()
    scale = time_scale_of(TwinSimulator())
    records = [read_scenario(p) for p in sorted((BANK / "scenarios").glob("*.json.gz"))]
    assert records and all(r["spec"]["split"] == "dev" for r in records), "only the development partition may be scored"
    specs = [ScenarioSpec.from_dict(r["spec"]) for r in records]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(_prefetch, [s.to_dict() for s in specs]))
    backends = {"seasonal_naive": SeasonalNaiveBackend(24), "holt_winters": HoltWintersBackend(24), "lagged_ridge": LaggedRegressionBackend()}
    service: dict = {"used": False}
    for item in args.service:
        label, url = item.split("=", 1)
        client = HttpForecastBackend(url, name=label)
        service = {"used": True, **service, label: {"url": url, "health": client.health()}}
        backends[label] = Memo(client)
    source = twin_series_source(CachedTwin())
    report: dict = {"status": "PASS", "partition": "dev", "bank_manifest": json.loads((BANK / "manifest.json").read_text(encoding="utf-8"))["manifest_hash"], "scenarios": len(specs), "service": service,
                    "backends": sorted(backends), "context": CONTEXT, "horizon": HORIZON, "time_scale": scale.to_dict(), "onset_tolerance_samples": scale.onset_tolerance, "activation_threshold_kw": args.threshold,
                    "min_pairs_per_cell": args.min_pairs, "backtest": {}, "gate": {}}
    rows = []
    for number, spec in enumerate(specs, 1):
        frame = source.frame(spec.scenario)
        origins = [o for o in ORIGINS if o >= CONTEXT and o + 24 <= len(frame)]
        if origins:
            rows += [{**r, "scenario": spec.scenario_id, "group": spec.group} for r in backtest(frame, backends, CONTEXT, 24, origins, time_scale=scale, activation_threshold=args.threshold)["rows"] if r["target"] in CONTROLLER]
        if number % 20 == 0:
            print(f"backtest {number}/{len(specs)}", flush=True)
    for label in backends:
        report["backtest"][label] = {}
        for target in (*CONTROLLER, "both"):
            mine = [r for r in rows if r["backend"] == label and (target == "both" or r["target"] == target)]
            tp, fp, fn = (sum(r[f"onset_{k}"] for r in mine) for k in ("tp", "fp", "fn"))
            report["backtest"][label][target] = {
                "rows": len(mine), "rows_with_demand": sum(1 for r in mine if r["active_steps"] > 0), "undefined_mase_rows": sum(1 for r in mine if r["mase"] != r["mase"]),
                "onsets": {"true": tp + fn, "detected_within_tolerance": tp, "false_alarms": fp, "f1": f1_of_counts(tp, fp, fn)},
                "mean_mae_active": mean_of(mine, "mae_active"), "mean_mae_inactive": mean_of(mine, "mae_inactive"),
                "forecast_integral_kwh": {"median": quantile([r["integral_forecast"] for r in mine], 0.5), "p90": quantile([r["integral_forecast"] for r in mine], 0.9), "p99": quantile([r["integral_forecast"] for r in mine], 0.99), "max": max((r["integral_forecast"] for r in mine), default=None)},
                "integral": {"mean_true_kwh": mean_of(mine, "integral_true"), "mean_forecast_kwh": mean_of(mine, "integral_forecast"), "mean_error_kwh": mean_of(mine, "integral_error"),
                             "median_relative_error": (statistics.median([r["integral_relative_error"] for r in mine if r["integral_relative_error"] == r["integral_relative_error"]] or [float("nan")]))}}
    if args.backtest_only:
        report = clean({k: v for k, v in report.items() if k != "gate"})
        report["report_hash"] = content_hash(report)
        (ROOT / "data" / "xai" / f"forecast_c_intermittency_threshold_{args.threshold:g}kw.json").write_text(json.dumps(report, indent=1, sort_keys=True, allow_nan=False), encoding="utf-8")
        for label, block in report["backtest"].items():
            b = block["both"]
            print("backtest", label, {"onsets": b["onsets"], "mae_active": b["mean_mae_active"], "mae_inactive": b["mean_mae_inactive"]})
        return 0
    cases = [(spec.scenario, item) for spec in specs for item in spec.interventions]
    case_groups = [spec.group for spec in specs for _ in spec.interventions]
    gate = counterfactual_gate(source, cases, backends, CONTEXT, HORIZON, plan_variables=intervention_plan_variables, targets=set(CONTROLLER), groups=case_groups, time_scale=scale)
    report["gate"] = {"cases": gate["cases"], "cases_used": gate["cases_used"], "skipped": gate["skipped"], "summary": gate["summary"], "strata": {}}
    activity = lambda r: "active" if r["context_total"] > 0 else "flat"  # noqa: E731  (the context window only: nothing of the horizon)
    for label, backend_rows in gate["rows"].items():
        scored = [r for r in backend_rows if r["expressible"]]
        report["gate"]["strata"][label] = {"pooled_by_activity": stratified_summary(scored, activity, args.min_pairs),
                                           "by_target_and_activity": stratified_summary(scored, lambda r: f"{r['target']}|{activity(r)}", args.min_pairs),
                                           "by_target": stratified_summary(scored, lambda r: r["target"], args.min_pairs)}
    report["statement"] = "exploratory analysis of the development partition; synthetic data; truth of the simulated twin; not the preregistered evaluation; no quality claim"
    report = clean(report)
    report["report_hash"] = content_hash({k: v for k, v in report.items() if k != "statement"})
    (ROOT / "data" / "xai" / "forecast_c_strata_report.json").write_text(json.dumps(report, indent=1, sort_keys=True, allow_nan=False), encoding="utf-8")
    print("pairs per backend:", {k: v["pairs"] for k, v in gate["summary"].items()}, "cases used", gate["cases_used"], "skipped", gate["skipped"])
    for label, strata in report["gate"]["strata"].items():
        print(label)
        for block in ("pooled_by_activity", "by_target_and_activity"):
            for name, cell in strata[block].items():
                if not cell["estimable"]:
                    print(f"  {block[:6]} {name}: pairs {cell['pairs']} groups {cell['groups']} NOT ESTIMABLE")
                    continue
                iv = cell["intervals_95"]
                span = lambda k: f"[{iv[k]['low']:.2f}, {iv[k]['high']:.2f}]" if iv[k]["low"] is not None else "[n/a]"  # noqa: E731
                print(f"  {block[:6]} {name}: pairs {cell['pairs']} groups {cell['groups']} sign {cell['sign_agreement']:.2f} {span('sign_agreement')} spearman {cell['spearman_peaks']} {span('spearman_peaks')} | integral sign {cell['integral_sign_agreement']:.2f} {span('integral_sign_agreement')}")
    for label, block in report["backtest"].items():
        b = block["both"]
        print("backtest", label, {"rows": b["rows"], "with_demand": b["rows_with_demand"], "onsets": b["onsets"], "mae_active": b["mean_mae_active"], "mae_inactive": b["mean_mae_inactive"], "integral": b["integral"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
