"""Phase 6.3d: the ridge's safety net and the device-declared ON threshold, on the development bank of the main context (decisions D12 and D13).

    python -u manual_phase6_3d_ridge_net_device_threshold.py [--workers 6] [--clip-factor 5] [--sweep 0 1 5]      # needs data/xai/gctsb_c_dev/; writes data/xai/forecast_c_ridge_net_report.json

1. Safety net. The recursive linear forecaster can diverge; its steps are bounded to the context range widened by ``clip-factor`` times that range on each side (a last resort, not an analytical fix), and the
   steps in which the net acted are counted (``clipped_steps``). The counterfactual gate is run WITH and WITHOUT the net; the median (the primary summary) and the preregistered verdict are compared, so that a
   conclusion that does not change shows the framework is robust to the baseline's outliers.
2. ON threshold. It is a property of the device, not a tuning knob: a fraction of the rated thermal power of the scenario's equipment, read from the twin's variable catalogue (``VariableCatalogue.activation_thresholds``).
   The fixed thresholds of the earlier sweep (0, 1, 5 kW) are kept as a complementary robustness report: how the onset F1 changes with the analyst's tolerance.
DEVELOPMENT partition only; synthetic data; truth of the simulated twin; exploratory, not the preregistered evaluation; no quality claim.
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

from tsxai.bench import ScenarioSpec, read_scenario  # noqa: E402
from tsxai.core import content_hash, time_scale_of  # noqa: E402
from tsxai.forecast import HoltWintersBackend, LaggedRegressionBackend, SeasonalNaiveBackend, backtest, counterfactual_gate, f1_of_counts  # noqa: E402

from agri_twin.interfaces.xai_adapter import TwinSimulator, intervention_plan_variables, twin_series_source  # noqa: E402
from manual_phase6_3b_context_c_analysis import BANK, CONTEXT, CONTROLLER, HORIZON, ORIGINS, CachedTwin, _prefetch, clean  # noqa: E402

GATE_SIGN, GATE_SPEARMAN = 0.8, 0.6  # the preregistered feasibility gate (6.3a)


def quantile(values, q):
    ordered = sorted(values)
    return ordered[int(q * (len(ordered) - 1))] if ordered else None


def mean_of(rows, key):
    values = [r[key] for r in rows if r[key] == r[key]]
    return statistics.fmean(values) if values else None


def backtest_summary(rows, label):
    """Pooled measures of one backend over the controller targets (onsets pooled as counts, then one F1)."""
    mine = [r for r in rows if r["backend"] == label]
    tp, fp, fn = (sum(r[f"onset_{k}"] for r in mine) for k in ("tp", "fp", "fn"))
    clipped, steps = sum(r["clipped_steps"] for r in mine), sum(r["forecast_steps"] for r in mine)
    relative = [r["integral_relative_error"] for r in mine if r["integral_relative_error"] == r["integral_relative_error"]]
    return {"rows": len(mine), "onsets": {"true": tp + fn, "detected_within_tolerance": tp, "false_alarms": fp, "f1": f1_of_counts(tp, fp, fn)}, "mean_mae_active": mean_of(mine, "mae_active"), "mean_mae_inactive": mean_of(mine, "mae_inactive"),
            "integral_median_relative_error": statistics.median(relative) if relative else None, "integral_mean_error_kwh": mean_of(mine, "integral_error"),
            "forecast_integral_kwh": {"median": quantile([r["integral_forecast"] for r in mine], 0.5), "p99": quantile([r["integral_forecast"] for r in mine], 0.99), "max": max((r["integral_forecast"] for r in mine), default=None)},
            "clipped_steps": clipped, "forecast_steps": steps, "clipped_share": (clipped / steps) if steps else None}


def passes(block):
    return bool(block["sign_agreement"] >= GATE_SIGN and block["spearman_peaks"] >= GATE_SPEARMAN)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--clip-factor", type=float, default=5.0)
    parser.add_argument("--sweep", type=float, nargs="*", default=[0.0, 1.0, 5.0], help="fixed ON thresholds (kW) kept as the complementary robustness report")
    args = parser.parse_args()
    twin = TwinSimulator()
    scale = time_scale_of(twin)
    records = [read_scenario(p) for p in sorted((BANK / "scenarios").glob("*.json.gz"))]
    assert records and all(r["spec"]["split"] == "dev" for r in records), "only the development partition may be scored"
    specs = [ScenarioSpec.from_dict(r["spec"]) for r in records]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(_prefetch, [s.to_dict() for s in specs]))
    backends = {"seasonal_naive": SeasonalNaiveBackend(24), "holt_winters": HoltWintersBackend(24), "lagged_ridge": LaggedRegressionBackend(clip_factor=args.clip_factor),
                "lagged_ridge_unclipped": LaggedRegressionBackend(clip_factor=None)}
    source = twin_series_source(CachedTwin())
    thresholds = {spec.scenario_id: twin.catalogue_for(spec.scenario).activation_thresholds() for spec in specs}
    assert all(set(CONTROLLER) <= set(t) for t in thresholds.values()), "every scenario of the main context runs with the controller: its devices must declare a threshold"
    report: dict = {"status": "PASS", "partition": "dev", "bank_manifest": json.loads((BANK / "manifest.json").read_text(encoding="utf-8"))["manifest_hash"], "scenarios": len(specs), "backends": sorted(backends),
                    "context": CONTEXT, "horizon": HORIZON, "time_scale": scale.to_dict(), "clip_factor": args.clip_factor, "gate_rule": {"sign_agreement_min": GATE_SIGN, "spearman_peaks_min": GATE_SPEARMAN},
                    "device_thresholds_kw": {name: sorted({round(t[name], 6) for t in thresholds.values()}) for name in CONTROLLER},
                    "threshold_basis": {name: twin._roles["variables"][name]["activation"] for name in CONTROLLER}}
    frames = [(spec, source.frame(spec.scenario)) for spec in specs]
    modes = {"device_catalogue": None, **{f"fixed_{kw:g}kw": kw for kw in args.sweep}}
    report["backtest"] = {}
    for mode, fixed in modes.items():
        rows = []
        for number, (spec, frame) in enumerate(frames, 1):
            origins = [o for o in ORIGINS if o >= CONTEXT and o + 24 <= len(frame)]
            if origins:
                level = thresholds[spec.scenario_id] if fixed is None else fixed
                rows += [{**r, "scenario": spec.scenario_id} for r in backtest(frame, backends, CONTEXT, 24, origins, time_scale=scale, activation_threshold=level)["rows"] if r["target"] in CONTROLLER]
            if number % 40 == 0:
                print(f"backtest[{mode}] {number}/{len(frames)}", flush=True)
        report["backtest"][mode] = {label: backtest_summary(rows, label) for label in backends}
    cases = [(spec.scenario, item) for spec in specs for item in spec.interventions]
    gate = counterfactual_gate(source, cases, backends, CONTEXT, HORIZON, plan_variables=intervention_plan_variables, targets=set(CONTROLLER), groups=[spec.group for spec in specs for _ in spec.interventions], time_scale=scale)
    report["gate"] = {"cases": gate["cases"], "cases_used": gate["cases_used"], "skipped": gate["skipped"], "summary": gate["summary"]}
    clipped, free = gate["summary"]["lagged_ridge"], gate["summary"]["lagged_ridge_unclipped"]
    keys = ("sign_agreement", "median_relative_error", "spearman_peaks", "integral_sign_agreement", "integral_median_relative_error", "integral_spearman", "effect_coverage")
    report["net_isolation"] = {"clipped_steps": clipped["clipped_steps"], "forecast_steps": clipped["forecast_steps"], "clipped_share": (clipped["clipped_steps"] / clipped["forecast_steps"]) if clipped["forecast_steps"] else None,
                               "with_net": {k: clipped[k] for k in keys}, "without_net": {k: free[k] for k in keys}, "difference": {k: clipped[k] - free[k] for k in keys},
                               "gate_verdict_with_net": passes(clipped), "gate_verdict_without_net": passes(free), "verdict_unchanged": passes(clipped) == passes(free),
                               "primary_median_unchanged": clipped["integral_median_relative_error"] == free["integral_median_relative_error"]}
    report["statement"] = "exploratory analysis of the development partition; synthetic data; truth of the simulated twin; the net is a safety measure, not a model improvement; no quality claim"
    report = clean(report)
    report["report_hash"] = content_hash({k: v for k, v in report.items() if k != "statement"})
    (ROOT / "data" / "xai" / "forecast_c_ridge_net_report.json").write_text(json.dumps(report, indent=1, sort_keys=True, allow_nan=False), encoding="utf-8")
    iso = report["net_isolation"]
    print("net acted in", iso["clipped_steps"], "of", iso["forecast_steps"], "gate forecast steps;", "verdict unchanged:", iso["verdict_unchanged"], "primary median unchanged:", iso["primary_median_unchanged"])
    print("with", iso["with_net"])
    print("without", iso["without_net"])
    for mode, block in report["backtest"].items():
        print(mode, {label: (b["onsets"]["f1"], b["clipped_share"]) for label, b in block.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
