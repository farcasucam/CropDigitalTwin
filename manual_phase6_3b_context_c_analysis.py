"""Phase 6.3b: forecasters and the counterfactual gate on the development bank of the main context (greenhouse with the climate controller on), decisions D8-D11.

    python -u manual_phase6_3b_context_c_analysis.py [--workers 6] [--service name=url ...]      # needs data/xai/gctsb_c_dev/ (manual_phase6_3b_context_c_bank.py); writes data/xai/forecast_c_report.json

The explained object is the controller's demand (``greenhouse_heating_kw``, ``greenhouse_cooling_kw``) under the exterior forcing; the indoor climate is reported separately as the consequence. The controller's own
outputs are past-only covariates (never a plan). Runs of the twin are cached on disk (``data/xai/_cache_c/``, ignored by git) and prefetched in worker processes: a pair of runs costs seconds, not minutes.
DEVELOPMENT partition only; a pilot with intervals, not the preregistered evaluation; no quality claim. Truth is the truth of the SIMULATED twin.
"""

from __future__ import annotations

import argparse
import gzip
import json
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from tsxai.adapters import HttpForecastBackend  # noqa: E402
from tsxai.bench import ScenarioSpec, read_scenario  # noqa: E402
from tsxai.core import RunResult, content_hash  # noqa: E402
from tsxai.forecast import HoltWintersBackend, LaggedRegressionBackend, SeasonalNaiveBackend, backtest, counterfactual_gate  # noqa: E402

from agri_twin.interfaces.xai_adapter import TwinSimulator, intervention_plan_variables, twin_series_source  # noqa: E402

BANK = ROOT / "data" / "xai" / "gctsb_c_dev"
CACHE = ROOT / "data" / "xai" / "_cache_c"
CONTEXT, HORIZON, ORIGINS = 168, 96, (200, 260, 320, 380, 440)
CONTROLLER = ("greenhouse_heating_kw", "greenhouse_cooling_kw")
CONSEQUENCE = ("temperature_c", "relative_humidity_pct", "vpd_kpa")


class CachedTwin:
    """The twin as a simulator whose runs are cached on disk by the hash of the scenario and the interventions (a run is a pure function of them)."""

    def __init__(self) -> None:
        self._twin = TwinSimulator()
        self.name = self._twin.name

    def catalogue(self):
        return self._twin.catalogue()

    def run(self, scenario, interventions=()):
        key = content_hash({"scenario": {"labels": dict(scenario.labels), "season": scenario.season, "window": [scenario.window_start, scenario.window_hours], "options": dict(scenario.options)},
                            "interventions": [i.to_dict() for i in interventions], "twin": self.name})
        path = CACHE / f"{key[:32]}.json.gz"
        if path.exists():
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                document = json.load(handle)
            return RunResult(document["series"], document["time"], document["run_hash"])
        result = self._twin.run(scenario, interventions)
        CACHE.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        with gzip.open(temporary, "wt", encoding="utf-8") as handle:
            json.dump({"series": {k: list(v) for k, v in result.series.items()}, "time": list(result.time), "run_hash": result.run_hash}, handle)
        temporary.replace(path)
        return result


def _prefetch(spec_document: dict) -> int:
    sim = CachedTwin()
    spec = ScenarioSpec.from_dict(spec_document)
    sim.run(spec.scenario, ())
    for item in spec.interventions:
        sim.run(spec.scenario, [item])
    return 1 + len(spec.interventions)


class Memo:
    """Remembers the answers of a deterministic backend by request hash (the gate asks the same request again for the second group of targets)."""

    def __init__(self, backend) -> None:
        self._backend, self._seen, self.name = backend, {}, backend.name

    def forecast(self, request):
        key = request.content_hash
        if key not in self._seen:
            self._seen[key] = self._backend.forecast(request)
        return self._seen[key]


def clean(value):
    if isinstance(value, float) and value != value:
        return None
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--service", action="append", default=[])
    args = parser.parse_args()
    records = [read_scenario(p) for p in sorted((BANK / "scenarios").glob("*.json.gz"))]
    assert records and all(r["spec"]["split"] == "dev" for r in records), "only the development partition may be scored"
    specs = [ScenarioSpec.from_dict(r["spec"]) for r in records]
    runs = 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for done, n in enumerate(pool.map(_prefetch, [s.to_dict() for s in specs]), 1):
            runs += n
            if done % 20 == 0:
                print(f"prefetched {done}/{len(specs)} scenarios", flush=True)
    backends = {"seasonal_naive": SeasonalNaiveBackend(24), "holt_winters": HoltWintersBackend(24), "lagged_ridge": LaggedRegressionBackend()}
    service: dict = {"used": False}
    for item in args.service:
        label, url = item.split("=", 1)
        client = HttpForecastBackend(url, name=label)
        service = {"used": True, **service, label: {"url": url, "health": client.health()}}
        backends[label] = Memo(client)
    source = twin_series_source(CachedTwin())
    report: dict = {"status": "PASS", "partition": "dev", "bank_manifest": json.loads((BANK / "manifest.json").read_text(encoding="utf-8"))["manifest_hash"], "scenarios": len(specs), "runs_cached": runs,
                    "service": service, "backends": sorted(backends), "context": CONTEXT, "horizon": HORIZON, "backtest": {}, "gate": {}}
    rows = []
    for number, spec in enumerate(specs, 1):
        frame = source.frame(spec.scenario)
        origins = [o for o in ORIGINS if o >= CONTEXT and o + 24 <= len(frame)]
        if origins:
            rows += [{**r, "scenario": spec.scenario_id, "group": spec.group, "crop": spec.scenario.labels["crop"], "feedback": spec.scenario.labels.get("feedback", "off")} for r in backtest(frame, backends, CONTEXT, 24, origins)["rows"]]
        if number % 20 == 0:
            print(f"backtest {number}/{len(specs)}", flush=True)
    report["backtest_rows"] = len(rows)
    for label in backends:
        report["backtest"][label] = {}
        for name, targets in (("controller", CONTROLLER), ("consequence", CONSEQUENCE)):
            mine = [r for r in rows if r["backend"] == label and r["target"] in targets]
            finite = lambda k: [r[k] for r in mine if r[k] == r[k]]  # noqa: E731
            report["backtest"][label][name] = {"rows": len(mine), "undefined_mase_rows": sum(1 for r in mine if r["mase"] != r["mase"]), **{f"median_{k}": (statistics.median(finite(k)) if finite(k) else None) for k in ("mase", "rmsse", "nrmse", "smape", "pinball")},
                                               "coverage80": statistics.fmean(finite("coverage80")) if finite("coverage80") else None}
    cases = [(spec.scenario, item) for spec in specs for item in spec.interventions]
    case_groups = [spec.group for spec in specs for _ in spec.interventions]
    for name, targets in (("controller", CONTROLLER), ("consequence", CONSEQUENCE)):
        gate = counterfactual_gate(source, cases, backends, CONTEXT, HORIZON, plan_variables=intervention_plan_variables, targets=set(targets), groups=case_groups)
        first = next(iter(gate["rows"].values()))
        by_factor: dict = {}
        for r in first:
            cell = by_factor.setdefault(r["factor"], {"pairs": 0, "expressible": 0})
            cell["pairs"] += 1
            cell["expressible"] += r["expressible"]
        gate["expressibility_by_factor"] = by_factor
        per_backend_factor = {}
        for label, backend_rows in gate["rows"].items():
            cells: dict = {}
            for r in backend_rows:
                if r["expressible"]:
                    c = cells.setdefault(r["factor"], {"pairs": 0, "sign_agrees": 0})
                    c["pairs"] += 1
                    c["sign_agrees"] += r["sign_agrees"]
            per_backend_factor[label] = {f: {"pairs": c["pairs"], "sign_agreement": c["sign_agrees"] / c["pairs"]} for f, c in sorted(cells.items())}
        gate["sign_by_factor"] = per_backend_factor
        gate.pop("rows")
        report["gate"][name] = gate
    report["statement"] = "development pilot on the main context: not the preregistered evaluation; synthetic data; truth of the simulated twin; no quality claim"
    report = clean(report)
    report["report_hash"] = content_hash({k: v for k, v in report.items() if k != "statement"})
    (ROOT / "data" / "xai" / "forecast_c_report.json").write_text(json.dumps(report, indent=1, sort_keys=True, allow_nan=False), encoding="utf-8")
    for name in ("controller", "consequence"):
        g = report["gate"][name]
        print(f"gate [{name}]: cases {g['cases']} used {g['cases_used']} skipped {g['skipped']}")
        for label, s in g["summary"].items():
            iv = s.get("intervals_95", {})
            span = lambda k: (f"[{iv[k]['low']:.2f}, {iv[k]['high']:.2f}]" if iv.get(k) and iv[k]["low"] is not None else "")  # noqa: E731
            print(f"  {label}: pairs {s['pairs']} expressible {s['expressible_pairs']} sign {s['sign_agreement']} {span('sign_agreement')} spearman {s['spearman_peaks']} {span('spearman_peaks')} rel.err {s['median_relative_error']} {span('median_relative_error')}")
        print("  expressibility by factor:", g["expressibility_by_factor"])
    for label, block in report["backtest"].items():
        print("backtest", label, {k: {m: (round(v, 3) if isinstance(v, float) else v) for m, v in cell.items()} for k, cell in block.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
