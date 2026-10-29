"""PT-8a: level 1 of the nutrient line, fertigation. Does irrigation leach the dose away, and what does the explanation say about a dose, a heat wave and an irrigation together?

    python -u manual_phase7_pt8a_fertigation.py

The optional NITROGEN_DEMAND model (src/agri_twin/domain/nitrogen_demand.py) adds what the reduced pool lacks: uptake driven by demand, a nitrogen nutrition index (NNI) as the growth factor and leaching that follows the
drainage of the water balance. EVERY PARAMETER IS AN UNSOURCED PLACEHOLDER: the results are properties of the structure (sign, order, compensation, interaction), not agronomic values. The data-based comparison is NOT
part of this package (the surrogate of PT-7a was weak for the biomass with 24 episodes); the question here is what the twin's truth says.

SETTING. Tomato, OUTDOOR (no controller), model option nutrient_model = NITROGEN_DEMAND with the default initial soil pool (the pool the state starts with, 200 kg/ha; by the window the soil is largely depleted: the
crop is nitrogen-limited), 336 h from hour 1500, DEV seasons 34, 35, 37, 38. Players: heat_wave (+6 degC, window hours 48-144), fertiliser (40 kg/ha in total over 24 h from hour 20) and extra_irrigation (IRRIGATION 0.6 mm
per step over hours 48-200; the event REPLACES the outdoor plan of 0.38 mm per step, PT-6b, so it adds 0.22 mm per step). Reference: no dose, no heat wave, the plan irrigation. Outcomes: total biomass at the end,
mean nitrogen nutrition index (the status) over the window, and the nitrogen leached over the window (sum, kg/ha; minimum 0.1). Minimums: 1 g/m2, 0.01, 0.1 kg/ha.
Truth: re-simulation, exact Shapley over 8 coalitions, plus the PAIRWISE interaction of the dose and the irrigation: v(F+I) - v(F) - v(I) + v(none), read from the four coalitions without the heat wave.

READING RULES, fixed before the run (counts and ranges, four seasons, no inference):
* MATERIAL cell: the truth's |total effect| reaches the minimum.
* For material cells: the Shapley shares and the sum of absolute shares; the interaction gap relative to that sum; for the dose and the irrigation, the sign and the size of the pairwise interaction relative to the sum of
  absolute shares of the cell.
* The question "does the irrigation leach the dose away": in how many seasons the extra irrigation raises the leached nitrogen (its share positive) and the pairwise dose-irrigation interaction on the biomass is negative
  (the irrigation reduces the benefit of the dose).
Limits: one crop, one generator, one window, placeholder parameters, no data-based method, no other crops. Development.
"""

from __future__ import annotations

import itertools
import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from tsxai.core import Intervention, ScenarioDescriptor, content_hash  # noqa: E402
from tsxai.effects import EffectQuery, Outcome, Player, Policy, ResimulationEngine  # noqa: E402

from agri_twin.interfaces.xai_adapter import TwinSimulator  # noqa: E402

REPORT = ROOT / "data" / "xai" / "effects_pt8a_fertigation.json"
CROP, START, HOURS = "tomato", 1500, 336
LABELS = {"crop": CROP, "environment": "outdoor", "control": "off"}
EVAL_SEASONS = [34, 35, 37, 38]
PLAYERS = (Player("heat_wave", (Intervention("HEAT_WAVE", 48, 96, 6.0),)),
           Player("fertiliser", (Intervention("FERTILIZATION", 20, 24, 40.0),)),
           Player("extra_irrigation", (Intervention("IRRIGATION", 48, 152, 0.6),)))
OUTCOMES = (Outcome("biomass_total_end", "biomass_total_g_m2", "max", "g/m2"), Outcome("nitrogen_status_mean", "nutrient_status", "mean", "fraction"),
            Outcome("nitrogen_leached", "nutrient_leached_kg_ha", "sum", "kg/ha"))
MINIMUM = {"biomass_total_end": 1.0, "nitrogen_status_mean": 0.01, "nitrogen_leached": 0.1}


def main() -> int:
    simulator = TwinSimulator()
    seasons = {}
    for season in EVAL_SEASONS:
        options = {**simulator.scenario_options(LABELS, season), "model_options": {"nutrient_model": "NITROGEN_DEMAND"}}
        desc = ScenarioDescriptor(LABELS, season, START, HOURS, options)
        truth = ResimulationEngine(simulator).evaluate(EffectQuery(desc, OUTCOMES, PLAYERS, policy=Policy("reactive")))
        coalitions = {frozenset(c): simulator.run(desc, tuple(i for p in PLAYERS if p.name in c for i in p.interventions)) for size in range(3) for c in itertools.combinations(("fertiliser", "extra_irrigation"), size)}
        coalitions[frozenset(("fertiliser", "extra_irrigation"))] = simulator.run(desc, tuple(i for p in PLAYERS if p.name != "heat_wave" for i in p.interventions))
        cells = {}
        for out in OUTCOMES:
            t = truth["outcomes"][out.name]
            scale_sum = sum(abs(v) for v in t["shapley"].values())
            value = {c: out.evaluate(list(run.series[out.variable])) for c, run in coalitions.items()}
            pair = value[frozenset(("fertiliser", "extra_irrigation"))] - value[frozenset(("fertiliser",))] - value[frozenset(("extra_irrigation",))] + value[frozenset()]
            cells[out.name] = {"total_effect": t["total_effect"], "shapley": t["shapley"], "leave_one_out": t["leave_one_out"], "material": abs(t["total_effect"]) >= MINIMUM[out.name],
                               "interaction_relative_to_sum_abs_shares": abs(t["interaction_gap"]) / scale_sum if scale_sum else 0.0,
                               "pairwise_dose_irrigation": pair, "pairwise_relative_to_sum_abs_shares": pair / scale_sum if scale_sum else 0.0}
        seasons[str(season)] = cells
        print(season, {o: (round(c["total_effect"], 3), {k: round(v, 3) for k, v in c["shapley"].items()}, round(c["pairwise_dose_irrigation"], 3)) for o, c in cells.items()}, flush=True)
    summary = {}
    for name in MINIMUM:
        rows = [seasons[str(s)][name] for s in EVAL_SEASONS]
        material = [r for r in rows if r["material"]]
        rng = lambda f: [round(min(f(r) for r in material), 3), round(max(f(r) for r in material), 3)] if material else None  # noqa: E731
        summary[name] = {"material_cells": len(material), "of": len(rows), "total_effect_range": rng(lambda r: r["total_effect"]),
                         "shapley_range": {p.name: rng(lambda r, n=p.name: r["shapley"][n]) for p in PLAYERS}, "interaction_range": rng(lambda r: r["interaction_relative_to_sum_abs_shares"]),
                         "pairwise_dose_irrigation_relative_range": rng(lambda r: r["pairwise_relative_to_sum_abs_shares"])}
    leaches = sum(1 for s in EVAL_SEASONS if seasons[str(s)]["nitrogen_leached"]["shapley"]["extra_irrigation"] > 0)
    reduces = sum(1 for s in EVAL_SEASONS if seasons[str(s)]["biomass_total_end"]["pairwise_dose_irrigation"] < 0)
    out = {"status": "DEVELOPMENT: tomato outdoor, four DEV seasons, NITROGEN_DEMAND with unsourced placeholder parameters; counts and ranges only", "seasons": seasons, "summary": summary,
           "irrigation_leaches_the_dose": {"seasons_where_the_extra_irrigation_raises_the_leached_nitrogen": f"{leaches}/{len(EVAL_SEASONS)}", "seasons_where_the_dose_irrigation_interaction_on_the_biomass_is_negative": f"{reduces}/{len(EVAL_SEASONS)}"}}
    out["report_hash"] = content_hash(out)
    REPORT.write_text(json.dumps(out, indent=1, sort_keys=True, default=float) + "\n", encoding="utf-8")
    print(json.dumps({"summary": summary, "irrigation_leaches_the_dose": out["irrigation_leaches_the_dose"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
