"""PT-7a: fertilisation as a player (amount against timing, and its interaction with a heat wave), by re-simulation and by a data-based method that is told the applied dose.

    python -u manual_phase7_pt7a_fertilisation_player.py

The nutrient line, level 0, made the reduced nutrient model reachable (event FERTILIZATION: a total dose over an interval, added to the pool). The declared graph 0.3 covers its series (19 of 19 consistent on three dev
episodes). Here the question "what did the doses and the heat wave each do, and does WHEN the same dose is given matter?" is asked of the twin. The model is the reduced single-pool one, UNCALIBRATED: the results
are properties of that structure, not agronomic findings.

SETTING. Tomato, OUTDOOR (no controller), window of 336 h from hour 1500, DEV seasons 34, 35, 37, 38. Players: heat_wave (+6 degC, window hours 48-144), fert_early (24 kg/ha in total over 24 h from hour 20),
fert_late (the same 24 kg/ha over 24 h from hour 280). Reference = the unfertilised, unperturbed run. Outcomes: total biomass at the end of the window and the mean nutrient status (pool over reserve) over the window
(minimums 1 g/m2 and 0.01). Truth: re-simulation, exact Shapley over 8 coalitions.

DATA METHOD (as PT-6b, told what a manager observes): the PT-5a surrogate on the outdoor forcing (temperature, radiation, relative humidity), the applied dose per step and its running sum, plus the window-start stocks
(total biomass, nutrient pool) and the hour index; targets: the hourly increment of the total biomass and the nutrient status. Trained on the 24 PT-5a dev seasons, one run each with 0-3 natural random events (heat
wave, high radiation, fertilisation of 5 to 60 kg/ha over 12-72 h), no re-simulation. Occlusion: a player in the coalition keeps its factual channels over ITS SEGMENT, the exact steps where its single-player run
differs from the reference in those channels (given to the method); the rest comes from a baseline: ORACLE (the reference run's forcing, no fertilisation) or CLIMATOLOGY (the mean training forcing, no fertilisation).

READING RULES, fixed before the run (counts and ranges, four held-out seasons, no inference):
* MATERIAL cell: the truth's |total effect| reaches the minimum.
* For material cells: top player agrees (ties inside 1 percent of the minimum); sign right among the players with a true |share| of at least 5 percent of the sum of absolute true shares; normalised error = max |data
  share - true share| / sum |true shares|; explained fraction = data total / true total; the truth's interaction gap relative to the sum of absolute shares.
* TIMING: in the truth, the ratio |share of fert_early| / |share of fert_late| (the doses are equal, so a ratio different from 1 is purely timing); in the data method, whether it also ranks the early dose above the
  late one, reported as a count over the material cells.
Limits: one crop, one generator, one window, one dose, segments given, a simple surrogate, uncalibrated nutrient model, no leaching, no fertiliser type. Development.
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

REPORT = ROOT / "data" / "xai" / "effects_pt7a_fertilisation_player.json"
CROP, START, HOURS = "tomato", 1500, 336
LABELS = {"crop": CROP, "environment": "outdoor", "control": "off"}
RAW = ("temperature_c", "radiation_w_m2", "relative_humidity_pct", "nutrient_applied_kg_ha")
APPLIED = RAW.index("nutrient_applied_kg_ha")
MINIMUM = {"biomass_total_end": 1.0, "nutrient_status_mean": 0.01}
PLAYERS = (Player("heat_wave", (Intervention("HEAT_WAVE", 48, 96, 6.0),)),
           Player("fert_early", (Intervention("FERTILIZATION", 20, 24, 24.0),)),
           Player("fert_late", (Intervention("FERTILIZATION", 280, 24, 24.0),)))
PLAYER_CHANNELS = {"heat_wave": ("temperature_c", "relative_humidity_pct"), "fert_early": ("nutrient_applied_kg_ha",), "fert_late": ("nutrient_applied_kg_ha",)}
NATURAL = {"HEAT_WAVE": (3.0, 12.0), "HIGH_RADIATION": (1.1, 1.5), "FERTILIZATION": (5.0, 60.0)}
OUTCOMES = (Outcome("biomass_total_end", "biomass_total_g_m2", "max", "g/m2"), Outcome("nutrient_status_mean", "nutrient_status", "mean", "fraction"))
SIGN_SHARE = 0.05
TOL = 1e-9


def natural_events(season: int) -> tuple[Intervention, ...]:
    rng = random.Random(4000 + season)
    events = []
    for _ in range(rng.randint(0, 3)):
        factor = rng.choice(sorted(NATURAL))
        low, high = NATURAL[factor]
        events.append(Intervention(factor, rng.randint(0, HOURS - 73), rng.randint(12, 72), round(rng.uniform(low, high), 3)))
    return tuple(events)


def descriptor(simulator: TwinSimulator, season: int) -> ScenarioDescriptor:
    return ScenarioDescriptor(LABELS, season, START, HOURS, simulator.scenario_options(LABELS, season))


def raw_of(series: dict) -> np.ndarray:
    return np.array([np.array(series[c], dtype=float) for c in RAW])


def stocks_of(series: dict) -> tuple[float, float]:
    return float(series["biomass_total_g_m2"][0]), float(series["nutrient_available_kg_ha"][0])


def full(raw: np.ndarray, stocks: tuple[float, float]) -> np.ndarray:
    """Observed channels, the running sum of the applied dose, the window-start stocks (constant) and the hour index."""
    return np.concatenate([raw, np.cumsum(raw[APPLIED])[None, :], np.full((2, HOURS), 0.0) + np.array(stocks)[:, None], np.arange(HOURS, dtype=float)[None, :]])


def targets_of(series: dict) -> dict[str, np.ndarray]:
    total = np.array(series["biomass_total_g_m2"], dtype=float)
    return {"total": np.diff(total, prepend=total[0]), "status": np.array(series["nutrient_status"], dtype=float)}


def outcome_value(name: str, start_total: float, predicted: dict[str, np.ndarray]) -> float:
    if name == "biomass_total_end":
        return start_total + float(np.sum(predicted["total"][1:]))
    return float(np.mean(np.clip(predicted["status"], 0.0, 1.0)))


def main() -> int:
    simulator = TwinSimulator()
    fulls, targets = [], {"total": [], "status": []}
    raws = []
    for season in pt5a.TRAIN_SEASONS:
        run = simulator.run(descriptor(simulator, season), natural_events(season))
        raws.append(raw_of(run.series))
        fulls.append(full(raws[-1], stocks_of(run.series)))
        for k, v in targets_of(run.series).items():
            targets[k].append(v)
    model = pt5a.Surrogate().fit(fulls, targets)
    climatology = np.mean(np.stack(raws), axis=0)
    climatology[APPLIED] = 0.0  # the default plan applies nothing
    names = [p.name for p in PLAYERS]
    everything = tuple(i for p in PLAYERS for i in p.interventions)
    coalitions = [frozenset(c) for size in range(len(names) + 1) for c in itertools.combinations(names, size)]
    seasons, quality = {}, {"end_biomass_error_over_window_growth": [], "increment_rmse_over_std": [], "status_rmse": []}
    for season in pt5a.EVAL_SEASONS:
        desc = descriptor(simulator, season)
        truth = ResimulationEngine(simulator).evaluate(EffectQuery(desc, OUTCOMES, PLAYERS, policy=Policy("reactive")))
        factual_run, reference_run = simulator.run(desc, everything), simulator.run(desc, ())
        factual, oracle = raw_of(factual_run.series), raw_of(reference_run.series)
        stocks = stocks_of(factual_run.series)
        pred_factual, actual = model.predict(full(factual, stocks)), targets_of(factual_run.series)  # a diagnostic added after the first run (the reading rules above are unchanged)
        grown = float(factual_run.series["biomass_total_g_m2"][-1]) - stocks[0]
        quality["end_biomass_error_over_window_growth"].append(abs(outcome_value("biomass_total_end", stocks[0], pred_factual) - float(factual_run.series["biomass_total_g_m2"][-1])) / grown)
        quality["increment_rmse_over_std"].append(float(np.sqrt(np.mean((pred_factual["total"][1:] - actual["total"][1:]) ** 2))) / (float(np.std(actual["total"][1:])) + 1e-9))
        quality["status_rmse"].append(float(np.sqrt(np.mean((np.clip(pred_factual["status"], 0, 1) - actual["status"]) ** 2))))
        masks = {}
        for p in PLAYERS:
            single = raw_of(simulator.run(desc, p.interventions).series)
            masks[p.name] = {c: np.abs(single[RAW.index(c)] - oracle[RAW.index(c)]) > TOL for c in PLAYER_CHANNELS[p.name]}

        def occluded(baseline: np.ndarray, coalition: frozenset) -> np.ndarray:
            out = baseline.copy()
            for p in PLAYERS:
                if p.name in coalition:
                    for channel, mask in masks[p.name].items():
                        k = RAW.index(channel)
                        out[k, mask] = factual[k, mask]
            return out

        cells = {}
        for variant, baseline in (("oracle_baseline", oracle), ("climatology_baseline", climatology)):
            predicted = {c: model.predict(full(occluded(baseline, c), stocks)) for c in coalitions}
            for out in OUTCOMES:
                values = {c: outcome_value(out.name, stocks[0], predicted[c]) for c in coalitions}
                shares = shapley_exact(names, values)
                data_total = values[frozenset(names)] - values[frozenset()]
                t = truth["outcomes"][out.name]
                total, minimum = t["total_effect"], MINIMUM[out.name]
                scale_sum = sum(abs(v) for v in t["shapley"].values())
                row = {"truth_total": total, "data_total": data_total, "truth_shapley": t["shapley"], "data_shapley": shares, "material": abs(total) >= minimum,
                       "interaction_relative_to_sum_abs_shares": abs(t["interaction_gap"]) / scale_sum if scale_sum else 0.0,
                       "truth_early_over_late": abs(t["shapley"]["fert_early"]) / abs(t["shapley"]["fert_late"]) if t["shapley"]["fert_late"] else None}
                if row["material"]:
                    tol = 0.01 * minimum
                    big = [p for p in names if abs(t["shapley"][p]) >= SIGN_SHARE * scale_sum]
                    row.update({"top_agrees": top_player(shares, tol) == top_player(t["shapley"], tol), "sign_right": sum(1 for p in big if shares[p] * t["shapley"][p] > 0), "sign_of": len(big),
                                "normalised_error": max(abs(shares[p] - t["shapley"][p]) for p in names) / scale_sum, "explained_fraction": data_total / total,
                                "kendall_tau_b": kendall_tau_b(t["shapley"], shares, tol), "data_ranks_early_above_late": abs(shares["fert_early"]) > abs(shares["fert_late"])})
                else:
                    row["false_effect"] = abs(data_total) >= minimum
                cells.setdefault(variant, {})[out.name] = row
        seasons[str(season)] = cells
        print(season, {o: (round(r["truth_total"], 3), round(r["data_total"], 3), {k: round(v, 3) for k, v in r["truth_shapley"].items()}) for o, r in cells["climatology_baseline"].items()}, flush=True)
    summary = {}
    for variant in ("oracle_baseline", "climatology_baseline"):
        for out in MINIMUM:
            rows = [seasons[str(s)][variant][out] for s in pt5a.EVAL_SEASONS]
            material = [r for r in rows if r["material"]]
            rng = lambda key: [round(min(r[key] for r in material), 3), round(max(r[key] for r in material), 3)] if material else None  # noqa: E731
            summary[f"{variant}/{out}"] = {"material_cells": len(material), "of": len(rows), "top_agrees": sum(r["top_agrees"] for r in material),
                                           "sign_right": f"{sum(r['sign_right'] for r in material)}/{sum(r['sign_of'] for r in material)}", "normalised_error_range": rng("normalised_error"),
                                           "explained_fraction_range": rng("explained_fraction"), "interaction_range": rng("interaction_relative_to_sum_abs_shares"),
                                           "truth_early_over_late_range": rng("truth_early_over_late"), "data_ranks_early_above_late": f"{sum(r['data_ranks_early_above_late'] for r in material)}/{len(material)}",
                                           "false_effects": f"{sum(1 for r in rows if not r['material'] and r['false_effect'])}/{sum(1 for r in rows if not r['material'])}"}
    out = {"status": "DEVELOPMENT: tomato outdoor, four held-out DEV seasons, two equal doses at different times plus a heat wave, uncalibrated reduced nutrient model, a simple surrogate told the applied dose; counts and ranges only",
           "surrogate_quality": {k: [round(min(v), 3), round(max(v), 3)] for k, v in quality.items()}, "seasons": seasons, "summary": summary}
    out["report_hash"] = content_hash(out)
    REPORT.write_text(json.dumps(out, indent=1, sort_keys=True, default=float) + "\n", encoding="utf-8")
    print("surrogate quality:", out["surrogate_quality"])
    for key, row in summary.items():
        print("  ", key, row, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
