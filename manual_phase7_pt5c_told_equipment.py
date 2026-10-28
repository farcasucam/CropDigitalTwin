"""PT-5c: a data-based method that is TOLD the installation state and trained on episodes where it varied. Does it attribute the equipment player that PT-5b's method could not see?

    python -u manual_phase7_pt5c_told_equipment.py

PT-5b showed that a surrogate which only observes the outdoor channels and was trained at the nominal capacity accounts for 13 to 32 percent of the +2 to +3 K peak caused by (heat wave + degraded cooling plant) and for none
of the hours above the maximum. That is true by construction (the method never saw the installation change). The fair question is the other one: give the surrogate the cooling-capacity scale as an input, train it on episodes in
which the capacity varied (as a plant with maintenance records would have), and occlude the capacity player like the weather players. Does it then recover the re-simulation truth?

SETTING. As PT-5b: tomato, greenhouse, controller on, window 336 h from hour 960, players heat_wave (+8, hours 48-96), high_radiation (x1.3, 72-120), cooling_degradation (capacity x0.3, whole run), truth = re-simulation,
reactive policy, exact Shapley over 8 coalitions, DEV seasons only (evaluation 34, 35, 37, 38; the 24 PT-5a training seasons). Outcomes: cooling energy, hours above the stage maximum, peak temperature.
* Surrogate: PT-5a's (ridge on lagged inputs, hour of day, 300 fixed random ReLU features) with a fifth input channel, the capacity scale (constant over the window). Trained on 48 episodes (each training season twice, with two
  different capacity scales, plus the season's natural random events, no re-simulation, no perturbation labels).
* Two training grids of capacity scales: SEEN (1.0, 0.7, 0.5, 0.3, 0.15: the evaluated fault level is in the grid) and UNSEEN (1.0, 0.7, 0.5, 0.15, 0.1: 0.3 is between grid points, an interpolation).
* Occlusion: weather players as in PT-5a/5b; the capacity player sets the capacity channel to the factual 0.3 when in the coalition and to 1.0 (nominal) when not. Two baselines: ORACLE (unperturbed forcing) and
  CLIMATOLOGY (mean forcing of the training episodes), capacity 1.0 in both. Candidate segments given, as before.

READING RULES, fixed before the run (counts and ranges, four seasons):
* MATERIAL cell: the truth's |total effect| reaches the minimum (1 kWh, 1 h, 0.05 K).
* EXPLAINED FRACTION = data total effect / true total effect. For this test a method RECOVERS the effect of an outcome when the fraction is in [0.7, 1.3] in at least 3 of the material cells.
* CAPACITY SHARE assigned by the data method = |its share of the capacity player| / sum of its absolute shares, against the true one (PT-5b: 0.40-0.50 for the peak). Reported as ranges; its sign is compared with the truth's.
* The comparison method of PT-5b (not told, trained at nominal) is quoted from its report, not recomputed.
Limits: one fault level, one crop and generator, a simple surrogate (not a tuned forecaster), segments given, 48 training episodes. A positive result says that a method with the state and varied training data can attribute;
it does not say that real plants have such data. Development.
"""

from __future__ import annotations

import itertools
import json
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import manual_phase7_pt2_effects_family as pt2  # noqa: E402
import manual_phase7_pt3_capacity_sweep as pt3  # noqa: E402
import manual_phase7_pt5a_data_based_attribution as pt5a  # noqa: E402
import manual_phase7_pt5b_equipment_player as pt5b  # noqa: E402
from tsxai.core import ScenarioDescriptor, content_hash  # noqa: E402
from tsxai.effects import EffectQuery, Policy, ResimulationEngine, shapley_exact  # noqa: E402

from agri_twin.application.seasonal_synthetic_campaign import campaign_cycle  # noqa: E402
from agri_twin.interfaces.xai_adapter import TwinSimulator  # noqa: E402

REPORT = ROOT / "data" / "xai" / "effects_pt5c_told_equipment.json"
GRIDS = {"seen": (1.0, 0.7, 0.5, 0.3, 0.15), "unseen": (1.0, 0.7, 0.5, 0.15, 0.1)}
KEEP = pt5b.KEEP
PLAYERS, WEATHER, EQUIPMENT, CAPACITY_SCALE = pt5b.PLAYERS, pt5b.WEATHER, pt5b.EQUIPMENT, pt5b.CAPACITY_SCALE
RECOVER = (0.7, 1.3)


def with_capacity(forcing: np.ndarray, scale: float) -> np.ndarray:
    return np.concatenate([forcing, np.full((1, forcing.shape[1]), scale)], axis=0)


def collect(simulator: TwinSimulator, grid: tuple[float, ...]) -> tuple[list[np.ndarray], dict[str, list[np.ndarray]]]:
    forcings, targets = [], {t: [] for t in pt5a.TARGETS}
    labels = {"crop": pt5a.CROP, "environment": "greenhouse", "control": "on"}
    for index, season in enumerate(pt5a.TRAIN_SEASONS):
        for k in (0, 1):
            scale = grid[(2 * index + k) % len(grid)]
            options = pt3.scaled_options(dict(simulator.scenario_options(labels, season)), scale)
            run = simulator.run(ScenarioDescriptor(labels, season, pt5a.START, pt5a.HOURS, options), pt5a.natural_events(season))
            forcings.append(with_capacity(pt5a.forcing_of(run.series), scale))
            for t in pt5a.TARGETS:
                targets[t].append(np.array(run.series[t], dtype=float))
    return forcings, targets


def occluded(baseline: np.ndarray, factual: np.ndarray, coalition: frozenset) -> np.ndarray:
    out = baseline.copy()
    for p in WEATHER:
        if p.name not in coalition:
            continue
        iv = p.interventions[0]
        for channel in pt5a.PLAYER_CHANNELS[p.name]:
            k = pt5a.CHANNELS.index(channel)
            out[k, iv.start: iv.start + iv.duration] = factual[k, iv.start: iv.start + iv.duration]
    if EQUIPMENT.name in coalition:
        out[-1, :] = factual[-1, :]
    return out


def main() -> int:
    simulator = TwinSimulator()
    labels = {"crop": pt5a.CROP, "environment": "greenhouse", "control": "on"}
    names = [p.name for p in PLAYERS]
    everything = tuple(i for p in PLAYERS for i in p.interventions)
    coalitions = [frozenset(c) for size in range(len(names) + 1) for c in itertools.combinations(names, size)]
    truths = {}
    for season in pt5a.EVAL_SEASONS:
        desc = ScenarioDescriptor(labels, season, pt5a.START, pt5a.HOURS, simulator.scenario_options(labels, season))
        outs = tuple(o for o in pt2.outcomes(pt5a.CROP, (campaign_cycle(pt5a.CROP)[1] + timedelta(hours=pt5a.START)).month) if o.name in KEEP)
        truth = ResimulationEngine(simulator).evaluate(EffectQuery(desc, outs, PLAYERS, policy=Policy("reactive")))
        factual = with_capacity(pt5a.forcing_of(simulator.run(desc, everything).series), CAPACITY_SCALE)
        oracle = with_capacity(pt5a.forcing_of(simulator.run(desc, ()).series), 1.0)
        truths[season] = (outs, truth, factual, oracle)
    grids = {}
    for grid_name, grid in GRIDS.items():
        forcings, targets = collect(simulator, grid)
        model = pt5a.Surrogate().fit(forcings, targets)
        climatology = np.mean(np.stack(forcings), axis=0)
        climatology[-1, :] = 1.0
        quality = {t: [] for t in pt5a.TARGETS}
        seasons = {}
        for season, (outs, truth, factual, oracle) in truths.items():
            pred = model.predict(factual)
            actual = simulator.run(ScenarioDescriptor(labels, season, pt5a.START, pt5a.HOURS, simulator.scenario_options(labels, season)), everything)
            for t in pt5a.TARGETS:
                quality[t].append(float(np.sqrt(np.mean((pred[t] - np.array(actual.series[t])) ** 2))) / (float(np.std(actual.series[t])) + 1e-9))
            cells = {}
            for variant, baseline in (("oracle_baseline", oracle), ("climatology_baseline", climatology)):
                predicted = {c: model.predict(occluded(baseline, factual, c)) for c in coalitions}
                for out in outs:
                    values = {c: out.evaluate(list(predicted[c][pt5a.OUTCOME_TARGET[out.name]])) for c in coalitions}
                    shares = shapley_exact(names, values)
                    data_total = values[frozenset(names)] - values[frozenset()]
                    t = truth["outcomes"][out.name]
                    total, minimum = t["total_effect"], pt2.MINIMUM[out.name]
                    row = {"truth_total": total, "data_total": data_total, "truth_shapley": t["shapley"], "data_shapley": shares, "material": abs(total) >= minimum}
                    if row["material"]:
                        true_sum, data_sum = sum(abs(v) for v in t["shapley"].values()), sum(abs(v) for v in shares.values())
                        row.update({"explained_fraction": data_total / total, "true_capacity_share": abs(t["shapley"][EQUIPMENT.name]) / true_sum,
                                    "data_capacity_share": abs(shares[EQUIPMENT.name]) / data_sum if data_sum else 0.0,
                                    "capacity_sign_agrees": shares[EQUIPMENT.name] * t["shapley"][EQUIPMENT.name] > 0})
                    cells.setdefault(variant, {})[out.name] = row
            seasons[str(season)] = cells
            print(grid_name, season, {o: (round(r["truth_total"], 2), round(r["data_total"], 2)) for o, r in cells["climatology_baseline"].items()}, flush=True)
        summary = {}
        for variant in ("oracle_baseline", "climatology_baseline"):
            for out in KEEP:
                material = [seasons[str(s)][variant][out] for s in pt5a.EVAL_SEASONS if seasons[str(s)][variant][out]["material"]]
                fractions = [r["explained_fraction"] for r in material]
                summary[f"{variant}/{out}"] = {
                    "material_cells": len(material), "of": len(pt5a.EVAL_SEASONS),
                    "explained_fraction_range": [round(min(fractions), 3), round(max(fractions), 3)] if material else None,
                    "recovered_cells": f"{sum(1 for f in fractions if RECOVER[0] <= f <= RECOVER[1])}/{len(material)}",
                    "true_capacity_share_range": [round(min(r["true_capacity_share"] for r in material), 3), round(max(r["true_capacity_share"] for r in material), 3)] if material else None,
                    "data_capacity_share_range": [round(min(r["data_capacity_share"] for r in material), 3), round(max(r["data_capacity_share"] for r in material), 3)] if material else None,
                    "capacity_sign_agrees": f"{sum(r['capacity_sign_agrees'] for r in material)}/{len(material)}"}
        grids[grid_name] = {"grid": list(grid), "training_episodes": len(forcings), "surrogate_relative_rmse_over_series_std": {t: [round(min(v), 3), round(max(v), 3)] for t, v in quality.items()},
                            "seasons": seasons, "summary": summary}
        print("==", grid_name, "surrogate relative RMSE:", grids[grid_name]["surrogate_relative_rmse_over_series_std"])
        for key, row in summary.items():
            print("  ", key, row, flush=True)
    out = {"status": "DEVELOPMENT: tomato, four held-out DEV seasons, one fault level, a surrogate told the capacity and trained on varied-capacity episodes; counts and ranges only", "capacity_scale": CAPACITY_SCALE, "grids": grids}
    out["report_hash"] = content_hash(out)
    REPORT.write_text(json.dumps(out, indent=1, sort_keys=True, default=float) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
