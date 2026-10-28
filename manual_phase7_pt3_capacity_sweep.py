"""PT-3a: where does the masking of the perturbation by the climate controller break when the cooling capacity is reduced?

    python -u manual_phase7_pt3_capacity_sweep.py

PT-2 found the peak air temperature identical to the crop's upper set-point under the REACTIVE controller in all nine episodes, also at 1.5x perturbations, because the illustrative cooling capacity (0.45 kW per m2
of floor) never saturates. That is a property of the equipment convention. Here the cooling capacity is scaled down (all other equipment, the weather, the window and the perturbations stay as in PT-2) and, for each
crop (seed 0) and scale, the four PT-2 perturbations are applied TOGETHER as one player (the all-on coalition against the unperturbed reference), under both policies: 3 runs per scale.

READING RULES, fixed before the runs (provisional conventions, not scientific thresholds):

* R1 (same as PT-2): masking ratio = |reactive contrast of the peak temperature| / |replayed contrast|, only where the replayed contrast is at least 0.05 K; below 0.05 "masked", 0.05 to 0.5 "partly masked",
  above 0.5 "not masked".
* R6 the BREAK of the masking for a crop is the largest capacity scale (of the declared grid) at which the class is not "masked"; if every scale is masked, the break is below the grid and is reported as such, not extrapolated.
* R7 saturation: hours in which the cooling power is at least 0.99 of the capacity in the all-on run under the reactive policy (and in the reference run). Reported as counts; it is the mechanism, not a threshold.
* R8 cooling energy that the controller spends in the all-on run against the reference (reactive contrast): reported for every scale. When the capacity saturates, this contrast stops growing with the perturbation:
  the cost of holding the set-point is capped and the temperature starts to show the perturbation.
* The grid is declared in advance. If the break is not inside it, the grid is extended in a later, labelled run (never silently).
Development: one seed per crop, no inferential test, no claim about greenhouses in general. The equipment is illustrative and the crop model is uncalibrated.
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import manual_phase7_pt2_effects_family as pt2  # noqa: E402
from tsxai.core import ScenarioDescriptor, content_hash  # noqa: E402
from tsxai.effects import EffectQuery, Outcome, Player, Policy, ResimulationEngine  # noqa: E402

from agri_twin.application.seasonal_synthetic_campaign import campaign_cycle  # noqa: E402
from agri_twin.interfaces.xai_adapter import TwinSimulator  # noqa: E402

REPORT = ROOT / "data" / "xai" / "effects_pt3_capacity_sweep.json"
GRID = (1.0, 0.5, 0.3, 0.2, 0.15, 0.1, 0.07, 0.05, 0.03)
SATURATED_FRACTION = 0.99


def scaled_options(options: dict, scale: float) -> dict:
    control = options["control"]
    return {**options, "control": {**control, "equipment": {**control["equipment"], "cooling_capacity_kw": round(control["equipment"]["cooling_capacity_kw"] * scale, 6)}}}


def classify(ratio: float) -> str:
    return "masked" if ratio < 0.05 else "partly masked" if ratio <= 0.5 else "not masked"


def run_cell(crop: str, scale: float) -> dict:
    simulator = TwinSimulator()
    labels = {"crop": crop, "environment": "greenhouse", "control": "on"}
    start = pt2.WINDOW_START[crop]
    options = scaled_options(dict(simulator.scenario_options(labels, 0)), scale)
    desc = ScenarioDescriptor(labels, 0, start, pt2.WINDOW_HOURS, options)
    capacity = options["control"]["equipment"]["cooling_capacity_kw"]
    outs = pt2.outcomes(crop, (campaign_cycle(crop)[1] + timedelta(hours=start)).month)
    keep = [o for o in outs if o.name in ("cooling_energy", "hours_temperature_above_stage_max", "temperature_peak")]
    keep.append(Outcome("hours_cooling_saturated", "greenhouse_cooling_kw", "hours_above", "h", threshold=SATURATED_FRACTION * capacity))
    everything = Player("all_four", tuple(i for p in pt2.base_players() for i in p.interventions))
    engine = ResimulationEngine(simulator)
    cell = {"crop": crop, "scale": scale, "cooling_capacity_kw": capacity, "policies": {}}
    for label in ("reactive", "replayed"):
        report = engine.evaluate(EffectQuery(desc, tuple(keep), (everything,), policy=Policy(label)))
        cell["policies"][label] = {name: {"factual": o["factual"], "reference": o["reference"], "total_effect": o["total_effect"]} for name, o in report["outcomes"].items()}
        if report["policy_check"] is not None:
            cell["policies"][label]["reproduces_source_run"] = report["policy_check"]["reproduces_source_run"]
    peak_r, peak_p = cell["policies"]["reactive"]["temperature_peak"]["total_effect"], cell["policies"]["replayed"]["temperature_peak"]["total_effect"]
    cell["masking_ratio"] = abs(peak_r) / abs(peak_p) if abs(peak_p) >= 0.05 else None
    cell["masking_class"] = classify(cell["masking_ratio"]) if cell["masking_ratio"] is not None else "replayed contrast not material"
    cell["saturated_hours_all_on_reactive"] = cell["policies"]["reactive"]["hours_cooling_saturated"]["factual"]
    cell["saturated_hours_reference_reactive"] = cell["policies"]["reactive"]["hours_cooling_saturated"]["reference"]
    return cell


def main() -> int:
    cells = []
    for crop in pt2.CROPS:
        for scale in GRID:
            c = run_cell(crop, scale)
            cells.append(c)
            print(crop, f"scale {scale:<5}", c["masking_class"], None if c["masking_ratio"] is None else round(c["masking_ratio"], 4),
                  "| reactive peak contrast", round(c["policies"]["reactive"]["temperature_peak"]["total_effect"], 3), "replayed", round(c["policies"]["replayed"]["temperature_peak"]["total_effect"], 3),
                  "| saturated h", c["saturated_hours_all_on_reactive"], "(ref", c["saturated_hours_reference_reactive"], ") | cooling energy contrast", round(c["policies"]["reactive"]["cooling_energy"]["total_effect"], 1), flush=True)
    breaks = {}
    for crop in pt2.CROPS:
        not_masked = [c["scale"] for c in cells if c["crop"] == crop and c["masking_class"] in ("partly masked", "not masked")]
        breaks[crop] = max(not_masked) if not_masked else "below the grid"
    out = {"status": "DEVELOPMENT: one seed per crop, the four PT-2 perturbations applied together, only the cooling capacity varies; the equipment is illustrative", "grid": list(GRID), "cells": cells, "break_of_masking_largest_scale_not_masked": breaks}
    out["report_hash"] = content_hash(out)
    REPORT.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print("break:", breaks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
