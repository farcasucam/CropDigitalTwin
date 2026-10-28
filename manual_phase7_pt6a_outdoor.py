"""PT-6a: a short outdoor test. The same explanation by re-simulation, without a climate controller, on crop outcomes; and what a data-only method recovers there.

    python -u manual_phase7_pt6a_outdoor.py

SETTING. Tomato, OUTDOOR (no greenhouse, no controller: nothing masks a perturbation and there is no reactive-vs-replayed distinction), window of 336 h from hour 1500 (vegetative growth, fruit starting), DEV seasons
only (benchmark split `gctsb-1`). Players: a heat wave (+8 degC, window hours 48-96), a low-radiation spell (x0.6, 100-148) and a cold wave (-6 degC, 200-248). Outcomes: total biomass and fruit biomass at the end of the
window (the series are cumulative, so the aggregate `max` is the final value). Exploration before the design (one season, no inference): irrigation x2 and rain x4 over 24-48 h change the end biomass by 0.2 and 0.1 g/m2
(water is not limiting in this window, the root zone stays at 150 mm), so they are not made players here; DRYNESS takes no intensity.
* Truth: re-simulation, exact Shapley over 8 coalitions, reference = the unperturbed run (evaluation seasons 34, 35, 37, 38).
* Data method: the PT-5a surrogate (ridge on lagged inputs, hour of day, 300 fixed random ReLU features) on the outdoor forcing (temperature, radiation, relative humidity) plus two per-episode constants (biomass and fruit biomass
  at the window start) and the hour index, predicting the HOURLY INCREMENT of total and of fruit biomass; the end biomass is the start value plus the cumulated increments. Trained on the 24 PT-5a dev seasons, each ONE run
  with 0-3 natural random events (heat, cold, low and high radiation), no re-simulation. Occlusion as in PT-5a (the waves carry temperature and humidity; segments given), oracle and climatology baselines.

READING RULES, fixed before the run (counts and ranges, four held-out seasons, no inference):
* MATERIAL cell: the truth's |total effect| reaches the minimum (1 g/m2 for total biomass, 0.1 g/m2 for fruit biomass).
* For material cells: does the data method's top player agree with the truth's (ties inside 1 percent of the minimum); of the players with a true |share| of at least 5 percent of the sum of absolute true shares, how many have
  the right sign; normalised error = max over players |data share - true share| / sum |true shares|; explained fraction = data total / true total; the truth's interaction gap relative to the sum of absolute shares.
* FALSE EFFECT: truth below the minimum but the method's |total| at or above it.
* Surrogate quality first: held-out relative RMSE of the cumulative end value (|predicted end - actual end| / actual increment over the window) and of the hourly increment over its standard deviation.
Limits: one crop, one generator, one window, segments given, a simple surrogate, no irrigation or fertilisation player (water is not limiting; the nutrient model is not exposed to the XAI layer). Development.
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

REPORT = ROOT / "data" / "xai" / "effects_pt6a_outdoor.json"
CROP, START, HOURS = "tomato", 1500, 336
LABELS = {"crop": CROP, "environment": "outdoor", "control": "off"}
FORCING = ("temperature_c", "radiation_w_m2", "relative_humidity_pct")
STOCKS = {"total": "biomass_total_g_m2", "fruit": "biomass_fruit_g_m2"}
MINIMUM = {"biomass_total_end": 1.0, "biomass_fruit_end": 0.1}
OUTCOME_STOCK = {"biomass_total_end": "total", "biomass_fruit_end": "fruit"}
PLAYERS = (Player("heat_wave", (Intervention("HEAT_WAVE", 48, 48, 8.0),)),
           Player("low_radiation", (Intervention("LOW_RADIATION", 100, 48, 0.6),)),
           Player("cold_wave", (Intervention("COLD_WAVE", 200, 48, 6.0),)))
PLAYER_CHANNELS = {"heat_wave": ("temperature_c", "relative_humidity_pct"), "cold_wave": ("temperature_c", "relative_humidity_pct"), "low_radiation": ("radiation_w_m2",)}
NATURAL = {k: v for k, v in pt5a.NATURAL.items() if k != "WIND"}
OUTCOMES = (Outcome("biomass_total_end", "biomass_total_g_m2", "max", "g/m2"), Outcome("biomass_fruit_end", "biomass_fruit_g_m2", "max", "g/m2"))
SIGN_SHARE = 0.05


def natural_events(season: int) -> tuple[Intervention, ...]:
    rng = random.Random(2000 + season)
    events = []
    for _ in range(rng.randint(0, 3)):
        factor = rng.choice(sorted(NATURAL))
        low, high = NATURAL[factor]
        events.append(Intervention(factor, rng.randint(0, HOURS - 73), rng.randint(12, 72), round(rng.uniform(low, high), 3)))
    return tuple(events)


def descriptor(simulator: TwinSimulator, season: int) -> ScenarioDescriptor:
    return ScenarioDescriptor(LABELS, season, START, HOURS, simulator.scenario_options(LABELS, season))


def features(series: dict) -> np.ndarray:
    """Forcing channels, then the window-start stocks (constant) and the hour index."""
    rows = [np.array(series[c], dtype=float) for c in FORCING]
    rows += [np.full(HOURS, float(series[s][0])) for s in STOCKS.values()] + [np.arange(HOURS, dtype=float)]
    return np.array(rows)


def increments(series: dict) -> dict[str, np.ndarray]:
    out = {}
    for key, name in STOCKS.items():
        values = np.array(series[name], dtype=float)
        out[key] = np.diff(values, prepend=values[0])
    return out


def end_value(start: float, predicted_increments: np.ndarray) -> float:
    return start + float(np.sum(predicted_increments[1:]))


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
    forcings, targets = [], {k: [] for k in STOCKS}
    for season in pt5a.TRAIN_SEASONS:
        run = simulator.run(descriptor(simulator, season), natural_events(season))
        forcings.append(features(run.series))
        for k, v in increments(run.series).items():
            targets[k].append(v)
    model = pt5a.Surrogate().fit(forcings, targets)
    climatology = np.mean(np.stack(forcings), axis=0)
    names = [p.name for p in PLAYERS]
    everything = tuple(i for p in PLAYERS for i in p.interventions)
    coalitions = [frozenset(c) for size in range(len(names) + 1) for c in itertools.combinations(names, size)]
    quality = {"end_error_over_window_increment": [], "increment_rmse_over_std": []}
    seasons = {}
    for season in pt5a.EVAL_SEASONS:
        desc = descriptor(simulator, season)
        truth = ResimulationEngine(simulator).evaluate(EffectQuery(desc, OUTCOMES, PLAYERS, policy=Policy("reactive")))
        factual_run, reference_run = simulator.run(desc, everything), simulator.run(desc, ())
        factual, oracle = features(factual_run.series), features(reference_run.series)
        climate = climatology.copy()
        climate[3:] = factual[3:]  # the window-start stocks and the hour index are the episode's own
        pred = model.predict(factual)
        actual = increments(factual_run.series)
        quality["end_error_over_window_increment"].append(abs(end_value(factual[3, 0], pred["total"]) - float(factual_run.series[STOCKS["total"]][-1])) / (float(factual_run.series[STOCKS["total"]][-1]) - float(factual_run.series[STOCKS["total"]][0])))
        quality["increment_rmse_over_std"].append(float(np.sqrt(np.mean((pred["total"][1:] - actual["total"][1:]) ** 2))) / (float(np.std(actual["total"][1:])) + 1e-9))
        cells = {}
        for variant, baseline in (("oracle_baseline", oracle), ("climatology_baseline", climate)):
            predicted = {c: model.predict(occluded(baseline, factual, c)) for c in coalitions}
            for out in OUTCOMES:
                key = OUTCOME_STOCK[out.name]
                start = factual[3 if key == "total" else 4, 0]
                values = {c: end_value(start, predicted[c][key]) for c in coalitions}
                shares = shapley_exact(names, values)
                data_total = values[frozenset(names)] - values[frozenset()]
                t = truth["outcomes"][out.name]
                total, minimum = t["total_effect"], MINIMUM[out.name]
                row = {"truth_total": total, "data_total": data_total, "truth_shapley": t["shapley"], "data_shapley": shares, "material": abs(total) >= minimum, "truth_leave_one_out": t["leave_one_out"]}
                scale_sum = sum(abs(v) for v in t["shapley"].values())
                row["interaction_relative_to_sum_abs_shares"] = abs(t["interaction_gap"]) / scale_sum if scale_sum else 0.0
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
                "material_cells": len(material), "of": len(rows), "top_agrees": sum(r["top_agrees"] for r in material),
                "sign_right": f"{sum(r['sign_right'] for r in material)}/{sum(r['sign_of'] for r in material)}",
                "normalised_error_range": [round(min(r["normalised_error"] for r in material), 3), round(max(r["normalised_error"] for r in material), 3)] if material else None,
                "explained_fraction_range": [round(min(r["explained_fraction"] for r in material), 3), round(max(r["explained_fraction"] for r in material), 3)] if material else None,
                "interaction_range": [round(min(r["interaction_relative_to_sum_abs_shares"] for r in material), 3), round(max(r["interaction_relative_to_sum_abs_shares"] for r in material), 3)] if material else None,
                "false_effects": f"{sum(1 for r in rows if not r['material'] and r['false_effect'])}/{sum(1 for r in rows if not r['material'])}"}
    out = {"status": "DEVELOPMENT: tomato outdoor, four held-out DEV seasons, three weather players, a simple surrogate; counts and ranges only",
           "surrogate_quality": {k: [round(min(v), 3), round(max(v), 3)] for k, v in quality.items()}, "seasons": seasons, "summary": summary}
    out["report_hash"] = content_hash(out)
    REPORT.write_text(json.dumps(out, indent=1, sort_keys=True, default=float) + "\n", encoding="utf-8")
    print("surrogate quality:", out["surrogate_quality"])
    for key, row in summary.items():
        print("  ", key, row, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
