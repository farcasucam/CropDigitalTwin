"""PT-9a: do the nutrient-line structures of PT-7a and PT-8a hold in the other crops? Pepper and lettuce, outdoors, truth only.

    python -u manual_phase7_pt9a_other_crops.py

Tomato showed, under the reduced single-pool model (PT-7a), a compensation between a heat wave and a dose and a large timing effect (the same dose early is worth about 6 times the late one), and, under the optional
NITROGEN_DEMAND model with placeholder parameters (PT-8a), that an extra irrigation leaches part of a dose (a product term). This package repeats the SAME designs on pepper and lettuce (outdoor, no controller,
DEV seasons only) to see whether the STRUCTURE is reproduced; sizes are not compared as agronomic quantities (uncalibrated models, one generator).

DESIGN (fixed before the run). Window of 336 h; pepper from hour 1500, lettuce from hour 336 (its campaign is 42 days long); DEV seasons: pepper 1, 2, 4, 6; lettuce 2, 4, 5, 6 (members of the `gctsb-1` dev partition).
* REDUCED model (default): players heat_wave (+6 degC, hours 48-144), fert_early (24 kg/ha in total over 24 h from hour 20), fert_late (the same from hour 280).
* NITROGEN_DEMAND model: players heat_wave, fertiliser (40 kg/ha over 24 h from hour 20), extra_irrigation (IRRIGATION 0.6 mm per step over hours 48-200, replacing the 0.38 plan).
Truth: re-simulation, exact Shapley over 8 coalitions, reference = no dose, no heat wave, the plan irrigation. Outcomes: total biomass at the end (minimum 1 g/m2) and the mean nutrient status (minimum 0.01); with
the nitrogen model also the nitrogen leached (sum, minimum 0.1 kg/ha).

READING RULES, fixed before the run (counts and ranges per crop and model, no inference, four seasons each):
* MATERIAL cell: |total effect| reaches the minimum.
* COMPENSATION (biomass): in how many material seasons the dose's share is positive and the heat wave's negative, and |net total| is smaller than the largest absolute share.
* TIMING (reduced model): in how many material seasons |share of fert_early| > |share of fert_late|, with the range of their ratio.
* FERTIGATION (nitrogen model): in how many seasons the extra irrigation's share of the leached nitrogen is positive, and the pairwise dose-irrigation interaction on the leached nitrogen is positive.
* Interaction gap relative to the sum of absolute shares, as a range.
Limits: three crops of one generator and two uncalibrated models; a crop in which a structure fails to appear is reported as it is. Development.
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from tsxai.core import Intervention, ScenarioDescriptor, content_hash  # noqa: E402
from tsxai.effects import EffectQuery, Outcome, Player, Policy, ResimulationEngine  # noqa: E402

from agri_twin.interfaces.xai_adapter import TwinSimulator  # noqa: E402

REPORT = ROOT / "data" / "xai" / "effects_pt9a_other_crops.json"
HOURS = 336
CROPS = {"pepper": (1500, [1, 2, 4, 6]), "lettuce": (336, [2, 4, 5, 6])}
HEAT = Player("heat_wave", (Intervention("HEAT_WAVE", 48, 96, 6.0),))
REDUCED_PLAYERS = (HEAT, Player("fert_early", (Intervention("FERTILIZATION", 20, 24, 24.0),)), Player("fert_late", (Intervention("FERTILIZATION", 280, 24, 24.0),)))
NITROGEN_PLAYERS = (HEAT, Player("fertiliser", (Intervention("FERTILIZATION", 20, 24, 40.0),)), Player("extra_irrigation", (Intervention("IRRIGATION", 48, 152, 0.6),)))
BIOMASS = Outcome("biomass_total_end", "biomass_total_g_m2", "max", "g/m2")
STATUS = Outcome("nutrient_status_mean", "nutrient_status", "mean", "fraction")
LEACHED = Outcome("nitrogen_leached", "nutrient_leached_kg_ha", "sum", "kg/ha")
MINIMUM = {"biomass_total_end": 1.0, "nutrient_status_mean": 0.01, "nitrogen_leached": 0.1}


def explain(simulator: TwinSimulator, crop: str, start: int, season: int, players, outcomes, model_options) -> dict:
    labels = {"crop": crop, "environment": "outdoor", "control": "off"}
    options = {**simulator.scenario_options(labels, season), **({"model_options": model_options} if model_options else {})}
    desc = ScenarioDescriptor(labels, season, start, HOURS, options)
    truth = ResimulationEngine(simulator).evaluate(EffectQuery(desc, outcomes, players, policy=Policy("reactive")))
    cells = {}
    for out in outcomes:
        t = truth["outcomes"][out.name]
        scale_sum = sum(abs(v) for v in t["shapley"].values())
        cells[out.name] = {"total_effect": t["total_effect"], "shapley": t["shapley"], "material": abs(t["total_effect"]) >= MINIMUM[out.name],
                           "interaction_relative_to_sum_abs_shares": abs(t["interaction_gap"]) / scale_sum if scale_sum else 0.0}
    if model_options:  # the pairwise dose-irrigation interaction on the leached nitrogen
        runs = {c: simulator.run(desc, tuple(i for p in players if p.name in c for i in p.interventions)) for size in range(3) for c in map(frozenset, itertools.combinations(("fertiliser", "extra_irrigation"), size))}
        v = {c: LEACHED.evaluate(list(r.series[LEACHED.variable])) for c, r in runs.items()}
        cells["nitrogen_leached"]["pairwise_dose_irrigation"] = v[frozenset(("fertiliser", "extra_irrigation"))] - v[frozenset(("fertiliser",))] - v[frozenset(("extra_irrigation",))] + v[frozenset()]
    return cells


def main() -> int:
    simulator = TwinSimulator()
    report = {}
    for crop, (start, seasons) in CROPS.items():
        reduced = {str(s): explain(simulator, crop, start, s, REDUCED_PLAYERS, (BIOMASS, STATUS), None) for s in seasons}
        nitrogen = {str(s): explain(simulator, crop, start, s, NITROGEN_PLAYERS, (BIOMASS, STATUS, LEACHED), {"nutrient_model": "NITROGEN_DEMAND"}) for s in seasons}
        material = [reduced[str(s)]["biomass_total_end"] for s in seasons if reduced[str(s)]["biomass_total_end"]["material"]]
        ratios = [abs(r["shapley"]["fert_early"]) / abs(r["shapley"]["fert_late"]) for r in material if r["shapley"]["fert_late"]]
        material_n = [nitrogen[str(s)]["biomass_total_end"] for s in seasons if nitrogen[str(s)]["biomass_total_end"]["material"]]
        leach = [nitrogen[str(s)]["nitrogen_leached"] for s in seasons if nitrogen[str(s)]["nitrogen_leached"]["material"]]
        rng = lambda xs: [round(min(xs), 3), round(max(xs), 3)] if xs else None  # noqa: E731
        summary = {
            "reduced_model": {"material_biomass_cells": f"{len(material)}/{len(seasons)}", "total_effect_range": rng([r["total_effect"] for r in material]),
                              "compensation": f"{sum(1 for r in material if r['shapley']['fert_early'] > 0 and r['shapley']['heat_wave'] < 0 and abs(r['total_effect']) < max(abs(v) for v in r['shapley'].values()))}/{len(material)}",
                              "early_above_late": f"{sum(1 for r in material if abs(r['shapley']['fert_early']) > abs(r['shapley']['fert_late']))}/{len(material)}", "early_over_late_ratio_range": rng(ratios),
                              "interaction_range": rng([r["interaction_relative_to_sum_abs_shares"] for r in material]), "shapley_ranges": {p.name: rng([r["shapley"][p.name] for r in material]) for p in REDUCED_PLAYERS}},
            "nitrogen_model": {"material_biomass_cells": f"{len(material_n)}/{len(seasons)}", "total_effect_range": rng([r["total_effect"] for r in material_n]),
                               "compensation": f"{sum(1 for r in material_n if r['shapley']['fertiliser'] > 0 and r['shapley']['heat_wave'] < 0 and abs(r['total_effect']) < max(abs(v) for v in r['shapley'].values()))}/{len(material_n)}",
                               "biomass_shapley_ranges": {p.name: rng([r["shapley"][p.name] for r in material_n]) for p in NITROGEN_PLAYERS},
                               "material_leaching_cells": f"{len(leach)}/{len(seasons)}", "irrigation_leaches": f"{sum(1 for r in leach if r['shapley']['extra_irrigation'] > 0)}/{len(leach)}",
                               "pairwise_dose_irrigation_positive": f"{sum(1 for r in leach if r['pairwise_dose_irrigation'] > 0)}/{len(leach)}",
                               "leaching_interaction_range": rng([r["interaction_relative_to_sum_abs_shares"] for r in leach])}}
        report[crop] = {"window_start_hour": start, "seasons": seasons, "reduced": reduced, "nitrogen": nitrogen, "summary": summary}
        print(crop, json.dumps(summary, default=float), flush=True)
    out = {"status": "DEVELOPMENT: pepper and lettuce outdoors, four DEV seasons each, two uncalibrated nutrient models; counts and ranges only", "crops": report}
    out["report_hash"] = content_hash(out)
    REPORT.write_text(json.dumps(out, indent=1, sort_keys=True, default=float) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
