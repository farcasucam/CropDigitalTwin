"""PT-5b: an installation fault as a player. What a data-only method can and cannot attribute when one cause is the equipment, not the weather.

    python -u manual_phase7_pt5b_equipment_player.py

PT-5a gave a data-based surrogate (trained on observational episodes at the nominal installation) the weather perturbations and found it close to the re-simulation truth for energy. Here one of the three players is
an INTERVENTION ON THE INSTALLATION: the cooling capacity multiplied by 0.3 for the whole run (a degradation or an undersized plant; factor COOLING_CAPACITY of the twin adapter), beside a heat wave (+8 degC, window hours
48-96) and a high-radiation spell (x1.3, hours 72-120). The question for the episode is "why did the air get this hot / this much cooling energy?"

* Truth: re-simulation, reactive policy, exact Shapley over the three players (8 coalitions), reference = the nominal installation with no perturbation. Reactive only (the comparable policy).
* Data method (same as PT-5a, same 24 DEV training seasons, trained at the NOMINAL capacity; it never saw a reduced installation): occlusion Shapley over the players whose effect appears as a change of an observed
  outdoor channel (heat wave, radiation); the capacity player changes no observed channel, so the method has nothing to occlude: its value function does not depend on it. Baselines oracle and climatology as in PT-5a.
* Episode: tomato, window 336 h from hour 960, DEV seasons 34, 35, 37, 38. Outcomes: cooling energy, hours above the stage maximum, peak temperature (minimums 1 kWh, 1 h, 0.05 K).

READING RULES, fixed before the run (counts and ranges, four seasons, no inference):
* A cell is MATERIAL when the truth's |total effect| reaches the minimum.
* EQUIPMENT SHARE: for material cells, |true Shapley share of the cooling-capacity player| / sum of the absolute true shares (what the data method cannot assign: it assigns 0).
* EXPLAINED FRACTION: data total effect / true total effect (1 would be a data method that accounts for the whole effect; 0 one that sees none of it). Reported with its sign; a negative or tiny value means the method
  explains the episode by something other than what happened.
* The weather players' shares are compared with the truth's as in PT-5a, but the truth's shares now include the interaction with the equipment: a heat wave costs more on a smaller plant.
Limits: one installation fault level (x0.3), one crop and generator, a simple surrogate, a method that is never told the installation changed (a method that could observe the capacity could use it; real data rarely
has it). Development.
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

import manual_phase7_pt2_effects_family as pt2  # noqa: E402
import manual_phase7_pt5a_data_based_attribution as pt5a  # noqa: E402
from tsxai.core import Intervention, ScenarioDescriptor, content_hash  # noqa: E402
from tsxai.effects import EffectQuery, Player, Policy, ResimulationEngine, shapley_exact  # noqa: E402

from agri_twin.application.seasonal_synthetic_campaign import campaign_cycle  # noqa: E402
from agri_twin.interfaces.xai_adapter import TwinSimulator  # noqa: E402

REPORT = ROOT / "data" / "xai" / "effects_pt5b_equipment_player.json"
CAPACITY_SCALE = 0.3
KEEP = ("cooling_energy", "hours_temperature_above_stage_max", "temperature_peak")
WEATHER = (Player("heat_wave", (Intervention("HEAT_WAVE", 48, 48, 8.0),)), Player("high_radiation", (Intervention("HIGH_RADIATION", 72, 48, 1.3),)))
EQUIPMENT = Player("cooling_degradation", (Intervention("COOLING_CAPACITY", 0, pt5a.HOURS, CAPACITY_SCALE),))
PLAYERS = WEATHER + (EQUIPMENT,)


def main() -> int:
    simulator = TwinSimulator()
    forcings, targets = pt5a.collect_training(simulator, 1.0)
    model = pt5a.Surrogate().fit(forcings, targets)
    climatology = pt5a.np.mean(pt5a.np.stack(forcings), axis=0)
    labels = {"crop": pt5a.CROP, "environment": "greenhouse", "control": "on"}
    names = [p.name for p in PLAYERS]
    weather_names = [p.name for p in WEATHER]
    seasons = {}
    for season in pt5a.EVAL_SEASONS:
        desc = ScenarioDescriptor(labels, season, pt5a.START, pt5a.HOURS, simulator.scenario_options(labels, season))
        outs = tuple(o for o in pt2.outcomes(pt5a.CROP, (campaign_cycle(pt5a.CROP)[1] + timedelta(hours=pt5a.START)).month) if o.name in KEEP)
        truth = ResimulationEngine(simulator).evaluate(EffectQuery(desc, outs, PLAYERS, policy=Policy("reactive")))
        everything = tuple(i for p in PLAYERS for i in p.interventions)
        factual = pt5a.forcing_of(simulator.run(desc, everything).series)  # forcing seen by a method that only observes the outdoor channels
        oracle = pt5a.forcing_of(simulator.run(desc, ()).series)
        cells = {}
        for variant, baseline in (("oracle_baseline", oracle), ("climatology_baseline", climatology)):
            coalitions = [frozenset(c) for size in range(len(weather_names) + 1) for c in itertools.combinations(weather_names, size)]
            predicted = {c: model.predict(pt5a.occluded(baseline, factual, WEATHER, c)) for c in coalitions}
            for out in outs:
                values = {c: out.evaluate(list(predicted[c][pt5a.OUTCOME_TARGET[out.name]])) for c in coalitions}
                shares = shapley_exact(weather_names, values)
                data_total = values[frozenset(weather_names)] - values[frozenset()]
                t = truth["outcomes"][out.name]
                total, minimum = t["total_effect"], pt2.MINIMUM[out.name]
                row = {"truth_total": total, "data_total": data_total, "truth_shapley": t["shapley"], "data_shapley": shares, "material": abs(total) >= minimum}
                if row["material"]:
                    scale_sum = sum(abs(v) for v in t["shapley"].values())
                    row.update({"equipment_share": abs(t["shapley"][EQUIPMENT.name]) / scale_sum, "explained_fraction": data_total / total, "interaction_relative_to_sum_abs_shares": abs(t["interaction_gap"]) / scale_sum})
                cells.setdefault(variant, {})[out.name] = row
        seasons[str(season)] = cells
        print(season, {v: {o: (round(r["truth_total"], 2), round(r["data_total"], 2), None if not r["material"] else round(r["equipment_share"], 2)) for o, r in cs.items()} for v, cs in cells.items() if v == "climatology_baseline"}, flush=True)
    summary = {}
    for variant in ("oracle_baseline", "climatology_baseline"):
        for out in KEEP:
            rows = [seasons[str(s)][variant][out] for s in pt5a.EVAL_SEASONS]
            material = [r for r in rows if r["material"]]
            summary[f"{variant}/{out}"] = {"material_cells": len(material), "of": len(rows),
                                           "equipment_share_range": [round(min(r["equipment_share"] for r in material), 3), round(max(r["equipment_share"] for r in material), 3)] if material else None,
                                           "explained_fraction_range": [round(min(r["explained_fraction"] for r in material), 3), round(max(r["explained_fraction"] for r in material), 3)] if material else None}
    out = {"status": "DEVELOPMENT: tomato, four held-out DEV seasons, one installation fault level; counts and ranges only", "capacity_scale": CAPACITY_SCALE, "seasons": seasons, "summary": summary}
    out["report_hash"] = content_hash(out)
    REPORT.write_text(json.dumps(out, indent=1, sort_keys=True, default=float) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
