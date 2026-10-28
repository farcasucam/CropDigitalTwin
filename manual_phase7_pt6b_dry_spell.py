"""PT-6b: an outdoor dry spell, where water is limiting and irrigation is a player (an intervention of the farmer).

    python -u manual_phase7_pt6b_dry_spell.py

PT-6a found that in the cool window of hour 1500 water is not limiting, so irrigation did nothing. The synthetic weather has no rain at all, and the outdoor run irrigates by a fixed plan of 0.38 mm per hour (127.7 mm per 336 h);
in a hot window the evaporative demand exceeds it. A first run (kept as data/xai/effects_pt6b_dry_spell_v0_hour2300_irrigation_0p3.json) used hour 2300 and an irrigation of 0.3 and was flawed in two ways, found by
exploration (season 34, tomato, no inference) before this design: (1) the IRRIGATION event REPLACES the plan's irrigation during its interval with the stated amount times about 0.95, so 0.3 REDUCED the irrigation (200 to 257 h of
water stress instead of 142 at hour 2300) and the "remedy" worked as a deficit; a remedy needs an amount above the plan, 0.6 here; (2) at hour 2300 the crop no longer grows (growth factor 0, biomass flat), so every biomass effect
was exactly zero. Windows where water is limiting and where the crop grows barely overlap: at hours 1700 and 1850 (growing) there is almost no water stress; at 2000 (growth tapering, 22.8 g/m2 per window) a heat wave plus a
radiation spell gives 247 h of stress, extra irrigation removes all of them and adds only 0.08 g/m2; from hour 2150 growth is over. So the window is tomato, OUTDOOR, 336 h from hour 2000, DEV seasons only, and the players are:
* heat_wave (+6 degC, window hours 48-144): raises the demand, the crop's heat stress and the water use;
* high_radiation (x1.25, 48-144): the same through ET0 and the energy;
* extra_irrigation (IRRIGATION 0.6 mm in every step of hours 48-200, i.e. above the plan of 0.38): the farmer's remedy.
Truth: re-simulation, exact Shapley over 8 coalitions, reference = the plan with no perturbation and no extra irrigation (evaluation seasons 34, 35, 37, 38). Outcomes: total and fruit biomass at the end, hours with water stress above 0.05.

Data method (as PT-6a, plus what a manager would observe): the PT-5a surrogate on the channels temperature, radiation, relative humidity AND applied irrigation (irrigation is an observed actuation, so the method is told it), plus
the window-start stocks (total biomass, fruit biomass, root-zone water) and the hour index; targets: hourly increments of total and fruit biomass and the water-stress level. Trained on the 24 PT-5a dev seasons, one run each with 0-3
natural random events (heat wave, high radiation, irrigation 0.1-1.0 mm), no re-simulation. Occlusion with the segments given, oracle and climatology baselines; the irrigation player carries the irrigation channel.

READING RULES, fixed before the run (counts and ranges, four held-out seasons, no inference):
* MATERIAL cell: the truth's |total effect| reaches the minimum (1 g/m2, 0.1 g/m2, 1 h). Only material cells enter the comparison; the others are reported as counts.
* Truth structure: the interaction gap relative to the sum of absolute true shares, and whether the extra irrigation is a player with a material share (|share| at least 5 percent of the sum of absolute shares).
* For material cells: top player agreement (ties inside 1 percent of the minimum), sign right among players with a true share of at least 5 percent, normalised error = max |data share - true share| / sum |true shares|,
  explained fraction = data total / true total. FALSE EFFECT: the truth below the minimum and the method's |total| at or above it.
Limits: one crop, one generator, one window, segments given, a simple surrogate, no fertilisation player. Development.
"""

from __future__ import annotations

import itertools
import json
import random
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import manual_phase7_pt5a_data_based_attribution as pt5a  # noqa: E402
from tsxai.core import Intervention, ScenarioDescriptor, content_hash  # noqa: E402
from tsxai.effects import EffectQuery, Outcome, Player, Policy, ResimulationEngine, kendall_tau_b, shapley_exact, top_player  # noqa: E402

from agri_twin.interfaces.xai_adapter import TwinSimulator  # noqa: E402

REPORT = ROOT / "data" / "xai" / "effects_pt6b_dry_spell.json"
CROP, START, HOURS = "tomato", 2000, 336
LABELS = {"crop": CROP, "environment": "outdoor", "control": "off"}
FORCING = ("temperature_c", "radiation_w_m2", "relative_humidity_pct", "irrigation_mm")
STOCK_SERIES = ("biomass_total_g_m2", "biomass_fruit_g_m2", "root_zone_water_mm")
N_FORCING = len(FORCING)
MINIMUM = {"biomass_total_end": 1.0, "biomass_fruit_end": 0.1, "hours_water_stress": 1.0}
WATER_STRESS_THRESHOLD = 0.05
PLAYERS = (Player("heat_wave", (Intervention("HEAT_WAVE", 48, 96, 6.0),)),
           Player("high_radiation", (Intervention("HIGH_RADIATION", 48, 96, 1.25),)),
           Player("extra_irrigation", (Intervention("IRRIGATION", 48, 152, 0.6),)))
PLAYER_CHANNELS = {"heat_wave": ("temperature_c", "relative_humidity_pct"), "high_radiation": ("radiation_w_m2",), "extra_irrigation": ("irrigation_mm",)}
NATURAL = {"HEAT_WAVE": (3.0, 12.0), "HIGH_RADIATION": (1.1, 1.5), "IRRIGATION": (0.1, 1.0)}
OUTCOMES = (Outcome("biomass_total_end", "biomass_total_g_m2", "max", "g/m2"), Outcome("biomass_fruit_end", "biomass_fruit_g_m2", "max", "g/m2"),
            Outcome("hours_water_stress", "water_stress", "hours_above", "h", threshold=WATER_STRESS_THRESHOLD))
SIGN_SHARE = 0.05


def natural_events(season: int) -> tuple[Intervention, ...]:
    rng = random.Random(3000 + season)
    events = []
    for _ in range(rng.randint(0, 3)):
        factor = rng.choice(sorted(NATURAL))
        low, high = NATURAL[factor]
        events.append(Intervention(factor, rng.randint(0, HOURS - 73), rng.randint(12, 72), round(rng.uniform(low, high), 3)))
    return tuple(events)


def descriptor(simulator: TwinSimulator, season: int) -> ScenarioDescriptor:
    return ScenarioDescriptor(LABELS, season, START, HOURS, simulator.scenario_options(LABELS, season))


def features(series: dict) -> np.ndarray:
    """Forcing and applied irrigation, then the window-start stocks (constant) and the hour index."""
    rows = [np.array(series[c], dtype=float) for c in FORCING]
    rows += [np.full(HOURS, float(series[s][0])) for s in STOCK_SERIES] + [np.arange(HOURS, dtype=float)]
    return np.array(rows)


def targets_of(series: dict) -> dict[str, np.ndarray]:
    total, fruit = np.array(series["biomass_total_g_m2"], dtype=float), np.array(series["biomass_fruit_g_m2"], dtype=float)
    return {"total": np.diff(total, prepend=total[0]), "fruit": np.diff(fruit, prepend=fruit[0]), "stress": np.array(series["water_stress"], dtype=float)}


def outcome_value(name: str, start_total: float, start_fruit: float, predicted: dict[str, np.ndarray]) -> float:
    if name == "biomass_total_end":
        return start_total + float(np.sum(predicted["total"][1:]))
    if name == "biomass_fruit_end":
        return start_fruit + float(np.sum(predicted["fruit"][1:]))
    return float(np.sum(predicted["stress"] > WATER_STRESS_THRESHOLD))


def occluded(baseline: np.ndarray, factual: np.ndarray, coalition: frozenset) -> np.ndarray:
    out = baseline.copy()
    for p in PLAYERS:
        if p.name not in coalition:
            continue
        iv = p.interventions[0]
        for channel in PLAYER_CHANNELS[p.name]:
            k = FORCING.index(channel)
            out[k, iv.start: iv.start + iv.duration] = factual[k, iv.start: iv.start + iv.duration]
    return out


def main() -> int:
    simulator = TwinSimulator()
    forcings, targets = [], {k: [] for k in ("total", "fruit", "stress")}
    for season in pt5a.TRAIN_SEASONS:
        run = simulator.run(descriptor(simulator, season), natural_events(season))
        forcings.append(features(run.series))
        for k, v in targets_of(run.series).items():
            targets[k].append(v)
    model = pt5a.Surrogate().fit(forcings, targets)
    climatology = np.mean(np.stack(forcings), axis=0)
    names = [p.name for p in PLAYERS]
    everything = tuple(i for p in PLAYERS for i in p.interventions)
    coalitions = [frozenset(c) for size in range(len(names) + 1) for c in itertools.combinations(names, size)]
    seasons = {}
    for season in pt5a.EVAL_SEASONS:
        desc = descriptor(simulator, season)
        truth = ResimulationEngine(simulator).evaluate(EffectQuery(desc, OUTCOMES, PLAYERS, policy=Policy("reactive")))
        factual_run, reference_run = simulator.run(desc, everything), simulator.run(desc, ())
        factual, oracle = features(factual_run.series), features(reference_run.series)
        climate = climatology.copy()
        climate[N_FORCING:] = factual[N_FORCING:]  # the stocks at the window start and the hour index are the episode's own
        start_total, start_fruit = float(factual[N_FORCING, 0]), float(factual[N_FORCING + 1, 0])
        cells = {}
        for variant, baseline in (("oracle_baseline", oracle), ("climatology_baseline", climate)):
            predicted = {c: model.predict(occluded(baseline, factual, c)) for c in coalitions}
            for out in OUTCOMES:
                values = {c: outcome_value(out.name, start_total, start_fruit, predicted[c]) for c in coalitions}
                shares = shapley_exact(names, values)
                data_total = values[frozenset(names)] - values[frozenset()]
                t = truth["outcomes"][out.name]
                total, minimum = t["total_effect"], MINIMUM[out.name]
                scale_sum = sum(abs(v) for v in t["shapley"].values())
                row = {"truth_total": total, "data_total": data_total, "truth_shapley": t["shapley"], "data_shapley": shares, "truth_leave_one_out": t["leave_one_out"], "material": abs(total) >= minimum,
                       "interaction_relative_to_sum_abs_shares": abs(t["interaction_gap"]) / scale_sum if scale_sum else 0.0,
                       "irrigation_share": abs(t["shapley"]["extra_irrigation"]) / scale_sum if scale_sum else 0.0}
                if row["material"]:
                    tol = 0.01 * minimum
                    big = [p for p in names if abs(t["shapley"][p]) >= SIGN_SHARE * scale_sum]
                    row.update({"top_agrees": top_player(shares, tol) == top_player(t["shapley"], tol), "sign_right": sum(1 for p in big if shares[p] * t["shapley"][p] > 0), "sign_of": len(big),
                                "normalised_error": max(abs(shares[p] - t["shapley"][p]) for p in names) / scale_sum, "explained_fraction": data_total / total,
                                "kendall_tau_b": kendall_tau_b(t["shapley"], shares, tol)})
                else:
                    row["false_effect"] = abs(data_total) >= minimum
                cells.setdefault(variant, {})[out.name] = row
        seasons[str(season)] = cells
        print(season, {o: (round(r["truth_total"], 2), round(r["data_total"], 2), {k: round(v, 2) for k, v in r["truth_shapley"].items()}) for o, r in cells["climatology_baseline"].items()}, flush=True)
    summary = {}
    for variant in ("oracle_baseline", "climatology_baseline"):
        for out in MINIMUM:
            rows = [seasons[str(s)][variant][out] for s in pt5a.EVAL_SEASONS]
            material = [r for r in rows if r["material"]]
            summary[f"{variant}/{out}"] = {
                "material_cells": len(material), "of": len(rows),
                "top_agrees": sum(r["top_agrees"] for r in material),
                "sign_right": f"{sum(r['sign_right'] for r in material)}/{sum(r['sign_of'] for r in material)}",
                "normalised_error_range": [round(min(r["normalised_error"] for r in material), 3), round(max(r["normalised_error"] for r in material), 3)] if material else None,
                "explained_fraction_range": [round(min(r["explained_fraction"] for r in material), 3), round(max(r["explained_fraction"] for r in material), 3)] if material else None,
                "interaction_range": [round(min(r["interaction_relative_to_sum_abs_shares"] for r in material), 3), round(max(r["interaction_relative_to_sum_abs_shares"] for r in material), 3)] if material else None,
                "true_irrigation_share_range": [round(min(r["irrigation_share"] for r in material), 3), round(max(r["irrigation_share"] for r in material), 3)] if material else None,
                "false_effects": f"{sum(1 for r in rows if not r['material'] and r['false_effect'])}/{sum(1 for r in rows if not r['material'])}"}
    out = {"status": "DEVELOPMENT: tomato outdoor hot window, four held-out DEV seasons, three players with irrigation as a farmer intervention, a simple surrogate told the applied irrigation; counts and ranges only", "seasons": seasons, "summary": summary}
    out["report_hash"] = content_hash(out)
    REPORT.write_text(json.dumps(out, indent=1, sort_keys=True, default=float) + "\n", encoding="utf-8")
    for key, row in summary.items():
        print("  ", key, row, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
