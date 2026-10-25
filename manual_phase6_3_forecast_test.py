"""Phase 6.3 / 6.3a verification: rolling-origin backtest and the counterfactual feasibility gate of the forecasters on the twin's development pilot.

    python -u manual_phase6_3_forecast_test.py                          # baselines only
    python -u manual_phase6_3_forecast_test.py --service timesfm25=http://127.0.0.1:8088 --service timesfm3=http://127.0.0.1:8089   # adds running TimesFM services (through SSH tunnels)

Development partition only. A pilot: nothing here is the preregistered evaluation, and no quality claim follows. Truth is that of the SIMULATED twin; the data are synthetic. Without ``--timesfm`` the report
says the service was not used; there is no hidden fallback.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from tsxai.adapters import HttpForecastBackend  # noqa: E402
from tsxai.bench import ScenarioSpec, read_scenario  # noqa: E402
from tsxai.core import content_hash  # noqa: E402
from tsxai.forecast import HoltWintersBackend, LaggedRegressionBackend, SeasonalNaiveBackend, backtest, counterfactual_gate  # noqa: E402

from agri_twin.interfaces.xai_adapter import intervention_plan_variables, twin_series_source  # noqa: E402

CONTEXT, HORIZON, ORIGINS = 168, 24, (200, 260, 320, 380)


def clean(value):
    """NaN (an undefined measure) becomes null so the report hashes and serialises canonically."""
    if isinstance(value, float) and value != value:
        return None
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", action="append", default=[], help="name=base URL of a running forecast service (repeatable)")
    args = parser.parse_args()
    backends = {"seasonal_naive": SeasonalNaiveBackend(24), "holt_winters": HoltWintersBackend(24), "lagged_ridge": LaggedRegressionBackend()}
    service: dict = {"used": False}
    for item in args.service:
        label, url = item.split("=", 1)
        client = HttpForecastBackend(url, name=label)
        service = {"used": True, **service, label: {"url": url, "health": client.health()}}
        backends[label] = client
    root = ROOT / "data" / "xai" / "gctsb_dev_pilot"
    records = [read_scenario(p) for p in sorted((root / "scenarios").glob("*.json.gz"))]
    assert records and all(r["spec"]["split"] == "dev" for r in records), "only the development partition may be scored"
    specs = [ScenarioSpec.from_dict(r["spec"]) for r in records]
    source = twin_series_source()
    report = {"status": "PASS", "partition": "dev", "scenarios": len(specs), "service": service, "backends": sorted(backends), "context": CONTEXT, "horizon": HORIZON, "backtest": {}, "gate": None}
    rows = []
    for spec in specs:
        frame = source.frame(spec.scenario)
        origins = [o for o in ORIGINS if o + HORIZON <= len(frame)]
        if not origins:
            continue
        result = backtest(frame, backends, CONTEXT, HORIZON, origins)
        rows += [{**r, "scenario": spec.scenario_id, "group": spec.group} for r in result["rows"]]
        print("backtest", spec.scenario_id, {k: round(v["mase"], 2) for k, v in result["summary"].items()}, flush=True)
    report["backtest_rows"] = rows
    for label in backends:
        mine = [r for r in rows if r["backend"] == label]
        finite = lambda k: [r[k] for r in mine if r[k] == r[k]]  # noqa: E731
        report["backtest"][label] = {**{k: statistics.fmean(finite(k)) for k in ("mase", "rmsse", "nrmse", "smape", "pinball", "coverage80")}, **{f"median_{k}": statistics.median(finite(k)) for k in ("mase", "rmsse", "nrmse", "smape", "pinball")}, "undefined_scale_rows": sum(1 for r in mine if r["mase"] != r["mase"]), "rows": len(mine)}
    cases = [(spec.scenario, i) for spec in specs for i in spec.interventions]
    gate = counterfactual_gate(source, cases, backends, CONTEXT, HORIZON, plan_variables=intervention_plan_variables)
    gate.pop("rows")
    report["gate"] = gate
    report["statement"] = "development pilot: not the preregistered evaluation; synthetic data; truth of the simulated twin; no quality claim"
    report = clean(report)
    report["report_hash"] = content_hash({k: v for k, v in report.items() if k != "statement"})
    (ROOT / "data" / "xai" / "forecast_pilot_report.json").write_text(json.dumps(report, indent=1, sort_keys=True, allow_nan=False), encoding="utf-8")
    print("backtest (mean, then median of the rows):", {k: {m: round(v[m], 3) for m in ("median_mase", "median_rmsse", "median_nrmse", "median_smape", "median_pinball", "coverage80", "undefined_scale_rows") if v.get(m) is not None} for k, v in report["backtest"].items()})
    print("gate: cases", gate["cases"], "used", gate["cases_used"], "skipped", gate["skipped"])
    for label, s in gate["summary"].items():
        print(" ", label, {k: (round(v, 2) if isinstance(v, float) else v) for k, v in s.items() if k != "by_factor"}, {f: round(x["sign_agreement"], 2) for f, x in s["by_factor"].items() if x["sign_agreement"] is not None})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
