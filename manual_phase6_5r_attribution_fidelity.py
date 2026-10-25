"""Phase 6.5r, step 5: RQ3 (level L2) on the development partition: does the forecaster rank the factors the way the simulated system does?

    python -u manual_phase6_5r_attribution_fidelity.py [--seasons 8]      # writes data/xai/attribution_fidelity_report.json

Each scenario (tomato greenhouse, without and with the climate controller, one season each) gets EVERY probe factor as a separate 24-hour intervention at the same cut-off. For each factor the system's exact effect on
each target (paired runs of the simplified twin: the truth of the benchmark) is compared with the forecaster's effect (its forecast under the intervened plan minus under the baseline plan, same past). Then, inside each
(scenario, target) cell, the factors are ranked by the magnitude of the integral of the effect, on both sides: Spearman of the rankings, whether the forecaster's first factor is the system's first (chance: one over the
number of factors), and sign agreement. Intervals resample whole scenarios.
Reading rule, stated before the numbers (H3a, provisional): the ranking is expected to be good for smooth factors and to fail for threshold actuators and slow variables. A mean Spearman near zero, or a first-factor hit rate
near its chance level, means the forecaster's sensitivities carry no information about which cause matters most, whatever their size. With the controller on the decision variables are the controller's outputs, so those factors
are inexpressible for the forecaster (counted, not scored). Synthetic data; truth of the simulated twin; no quality claim; the TimesFM service was not run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from tsxai.core import Intervention, ScenarioDescriptor, content_hash, time_scale_of  # noqa: E402
from tsxai.forecast import LaggedRegressionBackend, SeasonalNaiveBackend, counterfactual_gate, ranking_fidelity  # noqa: E402

from agri_twin.interfaces.xai_adapter import TwinSimulator, intervention_plan_variables, twin_series_source  # noqa: E402

CONTEXT, HORIZON, START, DURATION, WINDOW_START, WINDOW = 120, 48, 130, 24, 480, 240
FACTORS = ("HEAT_WAVE", "COLD_WAVE", "LOW_RADIATION", "HIGH_RADIATION", "WIND", "VENTILATION", "SHADING", "IRRIGATION")
VARIANTS = {"control_off": {"crop": "tomato", "environment": "greenhouse", "control": "off"}, "control_on": {"crop": "tomato", "environment": "greenhouse", "control": "on"}}


def clean(value):
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", type=int, default=8)
    args = parser.parse_args()
    simulator = TwinSimulator()
    source = twin_series_source(simulator)
    scale = time_scale_of(simulator)
    factors = simulator.factors()
    cases, groups = [], []
    for variant, labels in VARIANTS.items():
        for season in range(args.seasons):
            scenario = ScenarioDescriptor(labels, season, WINDOW_START, WINDOW, simulator.scenario_options(labels, season))
            for factor in FACTORS:
                cases.append((scenario, Intervention(factor, START, DURATION, factors[factor].probe_level)))
                groups.append(f"{variant}|{season}")
    backends = {"lagged_ridge": LaggedRegressionBackend(), "seasonal_naive": SeasonalNaiveBackend(24)}
    gate = counterfactual_gate(source, cases, backends, CONTEXT, HORIZON, plan_variables=intervention_plan_variables, groups=groups, time_scale=scale)
    report: dict = {"status": "PASS", "partition": "dev (synthetic)", "seasons": args.seasons, "variants": sorted(VARIANTS), "factors": list(FACTORS), "context": CONTEXT, "horizon": HORIZON, "cases": gate["cases"],
                    "cases_used": gate["cases_used"], "skipped": gate["skipped"], "backends": {}}
    for label, rows in gate["rows"].items():
        block = {"gate_summary": {k: v for k, v in gate["summary"][label].items() if k != "intervals_95"}, "ranking": {}}
        for variant in ("all", *VARIANTS):
            mine = [r for r in rows if variant == "all" or r["group"].startswith(variant + "|")]
            result = ranking_fidelity(mine)
            block["ranking"][variant] = {k: v for k, v in result.items() if k != "cells"}
        by_factor = {}
        for factor in FACTORS:
            mine = [r for r in rows if r["factor"] == factor]
            scored = [r for r in mine if r["expressible"]]
            by_factor[factor] = {"pairs": len(mine), "expressible": len(scored), "sign_agreement": (sum(r["integral_sign_agrees"] for r in scored) / len(scored)) if scored else None}
        block["by_factor"] = by_factor
        report["backends"][label] = block
    report["statement"] = "exploratory; development partition; synthetic data; truth of the simulated twin; TimesFM not run; no quality claim"
    report = clean(report)
    report["report_hash"] = content_hash({k: v for k, v in report.items() if k != "statement"})
    out = ROOT / "data" / "xai" / "attribution_fidelity_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, sort_keys=True, allow_nan=False), encoding="utf-8")
    for label, block in report["backends"].items():
        print(label, "pairs", block["gate_summary"]["pairs"], "expressible", block["gate_summary"]["expressible_pairs"])
        for variant, r in block["ranking"].items():
            o = r["overall"]
            print(f"  {variant}: cells {r['cells_total']} scored {r['cells_scored']} inexpressible {r['cells_inexpressible']} | mean rho {o['mean_rho']} top1 {o['top1_rate']} (chance {o['top1_chance']}) sign {o['sign_agreement']}")
        print("  by factor", block["by_factor"])
    print("report_hash", report["report_hash"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
