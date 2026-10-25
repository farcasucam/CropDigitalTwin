"""Phase 6.5r, step 4: RQ4b with more interventions, targets, seasons and windows, to test whether "k of n variants" carries any information about the direction of a what-if.

    python -u manual_phase6_5r_rq4b_wide.py [--seasons 4] [--workers 3]      # needs EnergyPlus 26.1; writes data/xai/rq4b_wide_report.json

The first experiment (4 seasons, a cold wave and a heat wave, two energy targets) had every variant agree in every case, so the "not confirmed" branch of the evidence rule was never exercised. Here:
* 7 interventions (heat wave, cold wave, low and high radiation, wind, vent opening, shade screen) at the benchmark's probe levels, two windows (spring and late May), 4 seasons, tomato greenhouse with the controller;
* 5 targets: heating and cooling energy, indoor temperature, relative humidity and vapour deficit (each as the sum of the effect over 48 h: kWh or unit-hours);
* truth: EnergyPlus (lock-step); working twin: the simplified model at mismatch levels 0, small and large (``src/xai_double_twin.json``, D19), seven variants each.
A pair (case, target) is MATERIAL when the truth's effect is at least 1 % of the sum of the baseline's magnitude over the horizon (floor 1 kWh or 1 unit-hour); smaller effects are 'no effect' and a variant that
still claims a direction there is a spurious claim. Reading rule, stated before the numbers: the evidence rule is informative only if (a) some claims fail the quorum and (b) a confirmed claim is right more often than an
unconfirmed one. If every claim is confirmed and correct, the rule certifies robustness and nothing more. Intervals are Wilson 95 % over pairs and ignore the clustering of pairs inside a (window, season) group: read
them as optimistic. Synthetic data; exploratory; both twins uncalibrated; no quality claim.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

WINDOWS = (480, 2400)
WINDOW, START, DURATION, HORIZON = 240, 100, 24, 48
INTERVENTIONS = ("HEAT_WAVE", "COLD_WAVE", "LOW_RADIATION", "HIGH_RADIATION", "WIND", "VENTILATION", "SHADING")
TARGETS = ("greenhouse_heating_kw", "greenhouse_cooling_kw", "temperature_c", "relative_humidity_pct", "vpd_kpa")
FLOORS = {"greenhouse_heating_kw": 1.0, "greenhouse_cooling_kw": 1.0, "temperature_c": 1.0, "relative_humidity_pct": 1.0, "vpd_kpa": 0.1}
MATERIAL_FRACTION = 0.01
LABELS = {"crop": "tomato", "environment": "greenhouse", "control": "on"}


def sums(pair, cut):
    """Per target: (sum of the effect over the horizon, sum of the baseline's magnitude over it)."""
    out = {}
    for target in TARGETS:
        effect = pair.effect(target)[cut:cut + HORIZON]
        base = pair.baseline.series[target][cut:cut + HORIZON]
        out[target] = (sum(v for v in effect if v is not None), sum(abs(v) for v in base if v is not None))
    return out


def one_case(job):
    window_start, season, factor = job
    from tsxai.core import Intervention, ScenarioDescriptor, paired_frames

    from agri_twin.interfaces.xai_adapter import TwinSimulator, twin_series_source
    from agri_twin.interfaces.xai_double_twin import load_design, truth_scenario, variants, working_scenario

    design = load_design()
    simulator = TwinSimulator()
    source = twin_series_source(simulator)
    level = simulator.factors()[factor].probe_level
    base = ScenarioDescriptor(LABELS, season, window_start, WINDOW, simulator.scenario_options(LABELS, season))
    item = Intervention(factor, START, DURATION, level)

    def run(scene):
        pair = paired_frames(source, scene, [item])
        return sums(pair, pair.first_changed_sample)

    truth = run(truth_scenario(base))
    levels = {name: [run(working_scenario(base, p)) for p in variants(name, design)] for name in design["levels"]}
    return {"window_start": window_start, "season": season, "factor": factor, "level": level, "truth": truth, "variants": levels}


def wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(centre - half, 3), round(centre + half, 3)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", type=int, default=4)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    from tsxai.core import content_hash
    from tsxai.semantics import DomainPack, SemanticEnricher
    from tsxai.semantics.vocabulary import DEFAULT_VOCABULARY

    from agri_twin.infrastructure.energyplus_timeline import find_energyplus
    from agri_twin.interfaces.xai_double_twin import load_design

    install = find_energyplus()
    if install is None or not install.version.startswith("26.1"):
        print("EnergyPlus 26.1 is not installed: nothing to measure")
        return 1
    design = load_design()
    conventions = json.loads((ROOT / "src" / "xai_semantics.json").read_text(encoding="utf-8"))["conventions"]
    enricher = SemanticEnricher(DomainPack("agri-twin", DEFAULT_VOCABULARY, conventions=conventions), 1.0, "SYNTHETIC")
    jobs = [(w, s, f) for w in WINDOWS for s in range(args.seasons) for f in INTERVENTIONS]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        cases = []
        for number, case in enumerate(pool.map(one_case, jobs), 1):
            cases.append(case)
            print(f"case {number}/{len(jobs)}", flush=True)
    claims = []
    for case in cases:
        for target in TARGETS:
            truth, scale = case["truth"][target]
            material_floor = max(MATERIAL_FRACTION * scale, FLOORS[target])
            truth_material = abs(truth) >= material_floor
            for level, runs in case["variants"].items():
                effects = [r[target][0] if abs(r[target][0]) >= material_floor else 0.0 for r in runs]
                median = statistics.median(effects)
                if len(effects) >= 3 and all(e == 0.0 for e in effects):
                    continue  # the working twin claims no effect at all: nothing to confirm
                fact = enricher.counterfactual(target, case["factor"].lower(), (0, HORIZON - 1), "", twin_effects=effects)[0]
                correct = truth_material and median != 0 and (median > 0) == (truth > 0)
                claims.append({"window_start": case["window_start"], "season": case["season"], "factor": case["factor"], "target": target, "level": level, "truth_material": truth_material,
                               "truth": truth, "median": median, "support": list(fact.support) if fact.support else None, "evidence_key": fact.key, "confirmed": fact.evidence_level == "TWIN_CONFIRMED",
                               "direction_correct": correct, "spurious": not truth_material, "truth_inside_range": min(effects) <= truth <= max(effects), "ratio": (median / truth) if truth_material else None})
    summary = {}
    for level in design["levels"]:
        mine = [c for c in claims if c["level"] == level and c["support"] is not None and c["support"][1] >= 3]
        confirmed, unconfirmed = [c for c in mine if c["confirmed"]], [c for c in mine if not c["confirmed"]]
        material = [c for c in mine if c["truth_material"]]
        by_support = {}
        for c in mine:
            share = c["support"][0] / c["support"][1]
            band = "all agree" if share == 1.0 else "quorum, not all" if c["confirmed"] else "below quorum"
            cell = by_support.setdefault(band, {"claims": 0, "correct": 0, "spurious": 0})
            cell["claims"] += 1
            cell["correct"] += c["direction_correct"]
            cell["spurious"] += c["spurious"]
        ratios = sorted(c["ratio"] for c in material if c["ratio"] is not None and c["ratio"] > 0)
        by_target = {t: {"claims": sum(1 for c in mine if c["target"] == t), "material": sum(1 for c in material if c["target"] == t), "correct": sum(c["direction_correct"] for c in material if c["target"] == t)} for t in TARGETS}
        summary[level] = {"claims": len(mine), "material_claims": len(material), "spurious_claims": sum(c["spurious"] for c in mine),
                          "confirmed": len(confirmed), "confirmed_correct": sum(c["direction_correct"] for c in confirmed), "confirmed_spurious": sum(c["spurious"] for c in confirmed),
                          "unconfirmed": len(unconfirmed), "unconfirmed_correct": sum(c["direction_correct"] for c in unconfirmed), "unconfirmed_spurious": sum(c["spurious"] for c in unconfirmed),
                          "direction_correct_among_material": sum(c["direction_correct"] for c in material), "direction_correct_among_material_wilson95": wilson(sum(c["direction_correct"] for c in material), len(material)),
                          "confirmed_precision_wilson95": wilson(sum(c["direction_correct"] for c in confirmed), len(confirmed)), "by_support": by_support, "by_target": by_target,
                          "truth_inside_range": sum(c["truth_inside_range"] for c in material), "ratio_median_over_truth": {"n": len(ratios), "p10": ratios[int(0.1 * (len(ratios) - 1))] if ratios else None,
                          "median": statistics.median(ratios) if ratios else None, "p90": ratios[int(0.9 * (len(ratios) - 1))] if ratios else None}}
    report = {"status": "PASS", "partition": "dev (synthetic)", "energyplus_version": install.version, "scenario": LABELS, "windows": list(WINDOWS), "seasons": args.seasons, "interventions": list(INTERVENTIONS), "targets": list(TARGETS),
              "material_fraction": MATERIAL_FRACTION, "floors": FLOORS, "cases": len(cases), "design_hash": content_hash(design), "summary": summary, "claims": claims,
              "statement": "exploratory; Wilson intervals ignore clustering inside (window, season) groups; synthetic data; both twins uncalibrated; mismatch widths are declared design choices (D19); no quality claim"}
    report["report_hash"] = content_hash({k: v for k, v in report.items() if k != "statement"})
    out = ROOT / "data" / "xai" / "rq4b_wide_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, sort_keys=True, allow_nan=False), encoding="utf-8")
    print(json.dumps({"report_hash": report["report_hash"], "summary": {k: {kk: vv for kk, vv in v.items() if kk not in ("by_target",)} for k, v in summary.items()}}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
