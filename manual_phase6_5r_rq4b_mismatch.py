"""Phase 6.5r, step 3: RQ4b on the development partition: how much worse is the twin's what-if when the explainer's twin is not the exact one?

    python -u manual_phase6_5r_rq4b_mismatch.py [--seasons 4]      # needs EnergyPlus 26.1; writes data/xai/rq4b_mismatch_report.json

Truth twin: EnergyPlus (lock-step, controller on), benchmark parameters. Working twin: the simplified model at three levels of mismatch (``src/xai_double_twin.json``, decision D19): 0 (nominal parameters: a ceiling,
structure alone already separates the twins), small and large (seven Latin-hypercube variants each). For each case (season x intervention) and level:
* the exact effect of the intervention on the controller's energy over 48 h (kWh, integral) and on the indoor-air peak, from the truth twin, against the same effect in each variant;
* direction agreement (sign), ratio working/truth, and whether the truth lies within the variants' range;
* the evidence level the semantic layer (6.4) would give the working twin's claim ("direction confirmed in k of n variants"), and whether a CONFIRMED claim is right about the direction of the truth.
Reading rule, stated before the numbers: a confirmed direction that is often wrong would make 'k of n' misleading; the magnitude is reported as a range. Cases are few (seasons x 2 interventions), so intervals are not
computed and nothing here is a rate with a claim of precision. Synthetic data; exploratory; no quality claim; the twins are uncalibrated and EnergyPlus is not the real greenhouse.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from tsxai.core import Intervention, ScenarioDescriptor, content_hash, paired_frames  # noqa: E402
from tsxai.semantics import DomainPack, SemanticEnricher  # noqa: E402
from tsxai.semantics.vocabulary import DEFAULT_VOCABULARY  # noqa: E402

from agri_twin.infrastructure.energyplus_timeline import find_energyplus  # noqa: E402
from agri_twin.interfaces.xai_adapter import TwinSimulator, twin_series_source  # noqa: E402
from agri_twin.interfaces.xai_double_twin import load_design, truth_scenario, variants, working_scenario  # noqa: E402

LABELS = {"crop": "tomato", "environment": "greenhouse", "control": "on"}
WINDOW_START, WINDOW, START, DURATION, HORIZON = 480, 240, 100, 24, 48
CASES = (("COLD_WAVE", "greenhouse_heating_kw"), ("HEAT_WAVE", "greenhouse_cooling_kw"))


def effect(source, scene, item, target):
    pair = paired_frames(source, scene, [item])
    cut = pair.first_changed_sample
    energy = sum(v for v in pair.effect(target)[cut:cut + HORIZON] if v is not None)
    peak = max(pair.effect("temperature_c")[cut:cut + HORIZON], key=abs)
    return energy, peak, cut


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", type=int, default=4)
    args = parser.parse_args()
    install = find_energyplus()
    if install is None or not install.version.startswith("26.1"):
        print("EnergyPlus 26.1 is not installed: nothing to measure")
        return 1
    design = load_design()
    simulator = TwinSimulator()
    source = twin_series_source(simulator)
    factors = simulator.factors()
    enricher = SemanticEnricher(DomainPack("agri-twin", DEFAULT_VOCABULARY, conventions=json.loads((ROOT / "src" / "xai_semantics.json").read_text(encoding="utf-8"))["conventions"]), 1.0, "SYNTHETIC")
    levels = list(design["levels"])
    rows = []
    for season in range(args.seasons):
        base = ScenarioDescriptor(LABELS, season, WINDOW_START, WINDOW, simulator.scenario_options(LABELS, season))
        for factor, target in CASES:
            item = Intervention(factor, START, DURATION, factors[factor].probe_level)
            truth_energy, truth_peak, cut = effect(source, truth_scenario(base), item, target)
            row = {"season": season, "factor": factor, "target": target, "truth_energy_kwh": truth_energy, "truth_peak_c": truth_peak, "levels": {}}
            for level in levels:
                energies, peaks = [], []
                for parameters in variants(level, design):
                    energy, peak, _ = effect(source, working_scenario(base, parameters), item, target)
                    energies.append(energy)
                    peaks.append(peak)
                claim = enricher.counterfactual(target, factor.lower(), (cut, cut + HORIZON - 1), "kWh", twin_effects=energies)[0]
                median = statistics.median(energies)
                row["levels"][level] = {
                    "variants": len(energies), "energy_kwh": {"min": min(energies), "median": median, "max": max(energies)},
                    "variant_direction_correct": sum(1 for e in energies if e != 0 and truth_energy != 0 and (e > 0) == (truth_energy > 0)), "ratio_median_over_truth": median / truth_energy if truth_energy else None,
                    "truth_inside_range": min(energies) <= truth_energy <= max(energies), "peak_direction_correct": sum(1 for p in peaks if p != 0 and truth_peak != 0 and (p > 0) == (truth_peak > 0)),
                    "evidence_level": claim.evidence_level, "evidence_key": claim.key, "support": list(claim.support) if claim.support else None,
                    "median_direction_correct": median != 0 and truth_energy != 0 and (median > 0) == (truth_energy > 0)}
            rows.append(row)
            print(season, factor, "truth", round(truth_energy, 1), {lv: (round(row["levels"][lv]["energy_kwh"]["median"], 1), row["levels"][lv]["evidence_key"], row["levels"][lv]["support"]) for lv in levels}, flush=True)
    summary = {}
    for level in levels:
        cells = [r["levels"][level] for r in rows]
        pairs = sum(c["variants"] for c in cells)
        confirmed = [c for c in cells if c["evidence_level"] == "TWIN_CONFIRMED"]
        ratios = sorted(c["ratio_median_over_truth"] for c in cells if c["ratio_median_over_truth"] is not None)
        summary[level] = {"cases": len(cells), "variant_runs": pairs, "variant_direction_agreement": sum(c["variant_direction_correct"] for c in cells) / pairs,
                          "median_direction_correct_cases": sum(c["median_direction_correct"] for c in cells), "confirmed_claims": len(confirmed), "confirmed_and_correct": sum(1 for c in confirmed if c["median_direction_correct"]),
                          "truth_inside_range_cases": sum(c["truth_inside_range"] for c in cells), "ratio_median_over_truth": {"min": ratios[0], "median": statistics.median(ratios), "max": ratios[-1]},
                          "evidence_keys": {k: sum(1 for c in cells if c["evidence_key"] == k) for k in sorted({c["evidence_key"] for c in cells})}}
    report = {"status": "PASS", "partition": "dev (synthetic)", "energyplus_version": install.version, "scenario": LABELS, "window": [WINDOW_START, WINDOW], "design": design, "design_hash": content_hash(design), "cases": rows, "summary": summary,
              "statement": "exploratory; few cases, no intervals; synthetic data; both twins uncalibrated; widths of the mismatch levels are declared design choices (D19), not scientific uncertainty; no quality claim"}
    report["report_hash"] = content_hash({k: v for k, v in report.items() if k != "statement"})
    out = ROOT / "data" / "xai" / "rq4b_mismatch_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, sort_keys=True, allow_nan=False), encoding="utf-8")
    print(json.dumps({"report_hash": report["report_hash"], "summary": summary}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
