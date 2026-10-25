"""Phase 6.3e: does the latent-threshold mechanism of 6.3c generalise? The counterfactual gate on the PLC reactor (``tsxai.examples.PlcReactor``), development seasons only (decision D14).

    python -u manual_phase6_3e_reactor_generality.py [--seasons 6] [--min-pairs 10]      # writes data/xai/reactor_gate_report.json

Hypothesis (6.3c): a forecaster fails to anticipate the effect of a decision when that effect passes through a threshold it never saw crossed in its context. The reactor's latched high-temperature
interlock plays the role of the thermostat: it is a regime switch that is not a smooth function of the state.
Reading rule, stated before the numbers: pairs are stratified by what the forecaster SAW (the context window before the cut-off): TRIPPED-SEEN when the interlock was tripped at some sample of the context,
NEVER-TRIPPED otherwise. A forecaster that fails only in NEVER-TRIPPED fails for lack of prior excitation, as in 6.3c; one that fails in both fails for a reason excitation does not explain.
A second, descriptive stratum uses the truth (whether the intervention changed the interlock state within the compared horizon): it labels the mechanism of the cases, it is never an input of a forecaster.
Cells under ``--min-pairs`` pairs are declared not estimable; intervals resample whole (unit, season) groups. Synthetic teaching model, no quality claim, not the preregistered evaluation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from tsxai.core import Intervention, ScenarioDescriptor, SimulatorSeriesSource, content_hash, paired_frames, time_scale_of  # noqa: E402
from tsxai.examples import PlcReactor  # noqa: E402
from tsxai.forecast import LaggedRegressionBackend, SeasonalNaiveBackend, counterfactual_gate, stratified_summary  # noqa: E402

CONTEXT, HORIZON, TAIL = 240, 120, 24
STARTS = (300, 450, 600, 750, 900, 1050)
DURATION = 60
PLANS = (("SETPOINT", 340.0), ("SETPOINT", 360.0), ("SETPOINT", 375.0), ("FEED_CONC", 1.0), ("FEED_CONC", 2.0), ("COOLANT_TEMP", 15.0), ("COOLANT_TEMP", 30.0))
EXCITATION = (("SETPOINT", 375.0), ("COOLANT_TEMP", 30.0), ("FEED_CONC", 2.0))  # the severe combination that reaches the interlock (see tests/test_examples.py of tsxai)
EXCITATION_DURATION = 60
PLAN_VARIABLE ={"FEED_CONC": "feed_concentration", "COOLANT_TEMP": "coolant_supply_temperature", "SETPOINT": "setpoint"}


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
    parser.add_argument("--seasons", type=int, default=6)
    parser.add_argument("--min-pairs", type=int, default=10)
    args = parser.parse_args()
    reactor = PlcReactor()
    scale = time_scale_of(reactor)
    source = SimulatorSeriesSource(reactor)
    units = sorted(context.labels["unit"] for context in reactor.contexts())
    cases, groups, facts = [], [], []
    for unit in units:
        for season in range(args.seasons):
            for factor, level in PLANS:
                for start in STARTS:
                    for excited in (False, True):
                        # an excited case has a trip burst in the plant's past (shared by both runs), so that the interlock is crossed inside the context; the others do not reach it before the cut-off
                        history = [{"factor": f, "start": start - 200, "duration": EXCITATION_DURATION, "level": v} for f, v in EXCITATION] if excited else []
                        scenario = ScenarioDescriptor({"unit": unit}, season, 0, 24 * 60, {"history": history})
                        item = Intervention(factor, start, DURATION, level)
                        paired = paired_frames(source, scenario, [item])
                        cut = paired.first_changed_sample
                        if cut is None or cut < CONTEXT:
                            continue
                        steps = min(HORIZON, DURATION + TAIL, len(paired.baseline) - cut)
                        seen = any(v == "tripped" for v in paired.baseline.series["trip"][cut - CONTEXT:cut])
                        changes_interlock = paired.baseline.series["trip"][cut:cut + steps] != paired.intervened.series["trip"][cut:cut + steps]
                        cases.append((scenario, item))
                        groups.append(f"{unit}|{season}")
                        facts.append({"trip_seen_in_context": seen, "intervention_changes_interlock": changes_interlock, "tripped_at_cut": paired.baseline.series["trip"][cut - 1] == "tripped"})
    backends = {"persistence": SeasonalNaiveBackend(1), "lagged_ridge": LaggedRegressionBackend(), "lagged_ridge_unclipped": LaggedRegressionBackend(clip_factor=None)}
    gate = counterfactual_gate(source, cases, backends, CONTEXT, HORIZON, tail=TAIL, plan_variables=lambda i: {PLAN_VARIABLE[i.factor]}, groups=groups, time_scale=scale)
    seen = lambda r: "tripped_seen" if facts[r["case"]]["trip_seen_in_context"] else "never_tripped"  # noqa: E731  (the context window only)
    mechanism = lambda r: "changes_interlock" if facts[r["case"]]["intervention_changes_interlock"] else "interlock_unchanged"  # noqa: E731  (truth: descriptive)
    report: dict = {"status": "PASS", "partition": "dev (synthetic teaching model; no bank partition applies)", "simulator": reactor.name, "units": units, "seasons": args.seasons, "context": CONTEXT, "horizon": HORIZON,
                    "time_scale": scale.to_dict(), "cases": gate["cases"], "cases_used": gate["cases_used"], "skipped": gate["skipped"], "min_pairs_per_cell": args.min_pairs, "summary": gate["summary"],
                    "case_mechanism_counts": {"trip_seen_in_context": sum(f["trip_seen_in_context"] for f in facts), "intervention_changes_interlock": sum(f["intervention_changes_interlock"] for f in facts), "tripped_at_cut": sum(f["tripped_at_cut"] for f in facts), "cases": len(facts)}, "strata": {}}
    for label, rows in gate["rows"].items():
        scored = [r for r in rows if r["expressible"]]
        report["strata"][label] = {"by_context_state": stratified_summary(scored, seen, args.min_pairs), "by_mechanism_truth": stratified_summary(scored, mechanism, args.min_pairs),
                                   "by_context_state_and_target": stratified_summary(scored, lambda r: f"{r['target']}|{seen(r)}", args.min_pairs), "by_factor": stratified_summary(scored, lambda r: r["factor"], args.min_pairs)}
    report["statement"] = "exploratory analysis of a synthetic teaching model; truth of the simulator; not the preregistered evaluation; no quality claim"
    report = clean(report)
    report["report_hash"] = content_hash({k: v for k, v in report.items() if k != "statement"})
    out = ROOT / "data" / "xai" / "reactor_gate_report.json"
    out.write_text(json.dumps(report, indent=1, sort_keys=True, allow_nan=False), encoding="utf-8")
    print("cases", gate["cases"], "used", gate["cases_used"], "skipped", gate["skipped"], "mechanism", report["case_mechanism_counts"])
    for label, block in gate["summary"].items():
        print(label, {k: block[k] for k in ("pairs", "expressible_pairs", "sign_agreement", "spearman_peaks", "integral_sign_agreement", "clipped_steps", "forecast_steps")})
        for name in ("by_context_state", "by_mechanism_truth"):
            for stratum, cell in report["strata"][label][name].items():
                print("  ", name, stratum, {k: cell.get(k) for k in ("pairs", "groups", "estimable", "sign_agreement", "spearman_peaks")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
