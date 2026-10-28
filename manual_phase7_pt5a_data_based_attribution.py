"""PT-5a: a data-based attribution of the perturbations (surrogate model + occlusion Shapley) against the re-simulation truth, in two capacity regimes.

    python -u manual_phase7_pt5a_data_based_attribution.py

QUESTION. A method that has only data (no simulator to re-run) learns how the greenhouse responds to the outdoor forcing from observational episodes and explains an episode by occluding each perturbation. Does it
recover what re-simulation says (reactive policy), and does it invent effects where the controller masks the perturbation (headroom regime, PT-3a)?

SETTING (tomato, greenhouse, controller on, window of 336 h from hour 960, the four PT-2 perturbations as candidate players; DEV seasons only: the benchmark's split `gctsb-1`, never its test partition).
* Training: 24 dev seasons [1 2 4 6 7 8 9 10 11 12 13 14 16 17 18 19 21 23 24 25 26 27 28 30], each ONE run with 0 to 3 natural random events (factors and ranges of the benchmark design), no re-simulation. Held-out
  evaluation: dev seasons 34, 35, 37, 38. Two capacity regimes, each with its own training set: cooling capacity scale 1.0 (headroom) and 0.3 (saturation, PT-3a).
* Surrogate (numpy only): per target (greenhouse_cooling_kw, greenhouse_heating_kw, temperature_c) a ridge on the four outdoor channels (temperature, radiation, humidity, wind) at lags 0..3, hour of day, and 300
  fixed random ReLU features (seeded), lambda 1.0 on standardised inputs. The model is never given the controller's commands, the indoor state or any perturbation label.
* Occlusion: the coalition S of players keeps the factual forcing over its segment (the player's declared window; the heat and cold waves also carry the outdoor humidity, an edge of the declared graph v0.2) and
  the baseline elsewhere; the outcome is computed on the surrogate's predicted series; exact Shapley over the four players. Two baselines: ORACLE (the unperturbed run's own forcing: isolates the model's error) and
  CLIMATOLOGY (mean forcing per hour of the window over the training seasons: what a method without the reference run could use). The candidate segments are GIVEN to the method (detecting them is a later question).
* Truth: re-simulation, reactive policy, exact Shapley (the PT-2 engine), same outcomes (cooling and heating energy, hours above the stage's maximum temperature, peak temperature), minimums 1 kWh, 1 h, 0.05 K.

READING RULES, fixed before the run (provisional conventions; counts and ranges, no inference, four held-out seasons per regime):
* A cell (season, outcome) is MATERIAL when the truth's |total effect| reaches the minimum. For material cells: does the top player agree; of the players whose true |share| is at least 5 percent of the sum of absolute
  true shares, how many have the right sign; the normalised error = max over players |data share - true share| / sum |true shares| (a normaliser that does not cancel when players oppose); the relative error of the total.
* FALSE EFFECT: a cell where the truth is below the minimum (masked or null) but the method's |total effect| reaches it. Counted per regime and baseline: it is the test of whether a data-based method invents an effect.
* The surrogate's quality is reported first (held-out RMSE of each target over the factual series, with the series' own standard deviation), since an attribution from a bad model says nothing about the method.
Limits: one crop, one generator, the segments given, a linear-plus-random-features surrogate (not a tuned or modern forecaster); a negative result for this surrogate is not a statement about all data-based methods.
"""

from __future__ import annotations

import json
import random
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import manual_phase7_pt2_effects_family as pt2  # noqa: E402
import manual_phase7_pt3_capacity_sweep as pt3  # noqa: E402
from tsxai.core import Intervention, ScenarioDescriptor, content_hash  # noqa: E402
from tsxai.effects import EffectQuery, Policy, ResimulationEngine, kendall_tau_b, relative_gap, shapley_exact, top_player  # noqa: E402

from agri_twin.application.seasonal_synthetic_campaign import campaign_cycle  # noqa: E402
from agri_twin.interfaces.xai_adapter import TwinSimulator  # noqa: E402

REPORT = ROOT / "data" / "xai" / "effects_pt5a_data_based.json"
CROP, START, HOURS = "tomato", 960, 336
TRAIN_SEASONS = [1, 2, 4, 6, 7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 18, 19, 21, 23, 24, 25, 26, 27, 28, 30]
EVAL_SEASONS = [34, 35, 37, 38]
SCALES = (1.0, 0.3)
CHANNELS = ("outdoor_temperature_c", "outdoor_radiation_w_m2", "outdoor_relative_humidity_pct", "outdoor_wind_speed_m_s")
TARGETS = ("greenhouse_cooling_kw", "greenhouse_heating_kw", "temperature_c")
OUTCOME_TARGET = {"cooling_energy": "greenhouse_cooling_kw", "heating_energy": "greenhouse_heating_kw", "hours_temperature_above_stage_max": "temperature_c", "temperature_peak": "temperature_c"}
PLAYER_CHANNELS = {"heat_wave": ("outdoor_temperature_c", "outdoor_relative_humidity_pct"), "cold_wave": ("outdoor_temperature_c", "outdoor_relative_humidity_pct"), "high_radiation": ("outdoor_radiation_w_m2",), "wind": ("outdoor_wind_speed_m_s",)}
LAGS, N_RANDOM, LAMBDA = 3, 300, 1.0
NATURAL = {"HEAT_WAVE": (3.0, 12.0), "COLD_WAVE": (3.0, 12.0), "LOW_RADIATION": (0.3, 0.8), "HIGH_RADIATION": (1.1, 1.5), "WIND": (1.5, 4.0)}  # ranges of the benchmark design
SIGN_SHARE = 0.05


def natural_events(season: int) -> tuple[Intervention, ...]:
    rng = random.Random(1000 + season)
    events = []
    for _ in range(rng.randint(0, 3)):
        factor = rng.choice(sorted(NATURAL))
        low, high = NATURAL[factor]
        events.append(Intervention(factor, rng.randint(0, HOURS - 73), rng.randint(12, 72), round(rng.uniform(low, high), 3)))
    return tuple(events)


class Surrogate:
    """Ridge on lagged outdoor forcing, hour of day and fixed random ReLU features; one coefficient vector per target."""

    def __init__(self) -> None:
        self.mean = self.std = self.w = self.b = None
        self.coef: dict[str, np.ndarray] = {}

    @staticmethod
    def raw(forcing: np.ndarray) -> np.ndarray:  # forcing: channels x hours -> hours x features
        padded = np.concatenate([np.repeat(forcing[:, :1], LAGS, axis=1), forcing], axis=1)
        cols = [padded[:, LAGS - lag: LAGS - lag + HOURS].T for lag in range(LAGS + 1)]
        hour = np.arange(HOURS) % 24
        return np.concatenate(cols + [np.sin(2 * np.pi * hour / 24)[:, None], np.cos(2 * np.pi * hour / 24)[:, None]], axis=1)

    def design(self, forcing: np.ndarray) -> np.ndarray:
        xs = (self.raw(forcing) - self.mean) / self.std
        return np.concatenate([np.ones((xs.shape[0], 1)), xs, np.maximum(0.0, xs @ self.w + self.b)], axis=1)

    def fit(self, forcings: list[np.ndarray], targets: dict[str, list[np.ndarray]]) -> "Surrogate":
        raw = np.concatenate([self.raw(f) for f in forcings])
        self.mean, self.std = raw.mean(axis=0), raw.std(axis=0) + 1e-9
        rng = np.random.RandomState(7)
        self.w, self.b = rng.randn(raw.shape[1], N_RANDOM) / np.sqrt(raw.shape[1]), rng.uniform(-1.0, 1.0, N_RANDOM)
        x = np.concatenate([self.design(f) for f in forcings])
        for name, series in targets.items():
            y = np.concatenate(series)
            self.coef[name] = np.linalg.solve(x.T @ x + LAMBDA * np.eye(x.shape[1]), x.T @ y)
        return self

    def predict(self, forcing: np.ndarray) -> dict[str, np.ndarray]:
        x = self.design(forcing)
        return {name: x @ c for name, c in self.coef.items()}


def forcing_of(series: dict) -> np.ndarray:
    return np.array([series[c] for c in CHANNELS], dtype=float)


def occluded(baseline: np.ndarray, factual: np.ndarray, players, coalition: frozenset) -> np.ndarray:
    out = baseline.copy()
    for p in players:
        if p.name not in coalition:
            continue
        iv = p.interventions[0]
        for channel in PLAYER_CHANNELS[p.name]:
            k = CHANNELS.index(channel)
            out[k, iv.start: iv.start + iv.duration] = factual[k, iv.start: iv.start + iv.duration]
    return out


def collect_training(simulator: TwinSimulator, scale: float) -> tuple[list[np.ndarray], dict[str, list[np.ndarray]]]:
    forcings, targets = [], {t: [] for t in TARGETS}
    for season in TRAIN_SEASONS:
        labels = {"crop": CROP, "environment": "greenhouse", "control": "on"}
        options = pt3.scaled_options(dict(simulator.scenario_options(labels, season)), scale)
        run = simulator.run(ScenarioDescriptor(labels, season, START, HOURS, options), natural_events(season))
        forcings.append(forcing_of(run.series))
        for t in TARGETS:
            targets[t].append(np.array(run.series[t], dtype=float))
    return forcings, targets


def evaluate_regime(simulator: TwinSimulator, scale: float) -> dict:
    forcings, targets = collect_training(simulator, scale)
    model = Surrogate().fit(forcings, targets)
    climatology = np.mean(np.stack(forcings), axis=0)
    labels = {"crop": CROP, "environment": "greenhouse", "control": "on"}
    players = pt2.base_players()
    names = [p.name for p in players]
    everything = tuple(i for p in players for i in p.interventions)
    result = {"scale": scale, "training_seasons": TRAIN_SEASONS, "seasons": {}}
    quality = {t: [] for t in TARGETS}
    for season in EVAL_SEASONS:
        options = pt3.scaled_options(dict(simulator.scenario_options(labels, season)), scale)
        desc = ScenarioDescriptor(labels, season, START, HOURS, options)
        outs = tuple(o for o in pt2.outcomes(CROP, (campaign_cycle(CROP)[1] + timedelta(hours=START)).month) if o.name in OUTCOME_TARGET)
        truth = ResimulationEngine(simulator).evaluate(EffectQuery(desc, outs, players, policy=Policy("reactive")))
        factual_run, reference_run = simulator.run(desc, everything), simulator.run(desc, ())
        factual, oracle = forcing_of(factual_run.series), forcing_of(reference_run.series)
        pred = model.predict(factual)
        for t in TARGETS:
            quality[t].append(float(np.sqrt(np.mean((pred[t] - np.array(factual_run.series[t])) ** 2))) / (float(np.std(factual_run.series[t])) + 1e-9))
        cells = {}
        for variant, baseline in (("oracle_baseline", oracle), ("climatology_baseline", climatology)):
            coalitions = [frozenset(c) for size in range(len(names) + 1) for c in __import__("itertools").combinations(names, size)]
            predicted = {c: model.predict(occluded(baseline, factual, players, c)) for c in coalitions}
            for out in outs:
                values = {c: out.evaluate(list(predicted[c][OUTCOME_TARGET[out.name]])) for c in coalitions}
                shares = shapley_exact(names, values)
                data_total = values[frozenset(names)] - values[frozenset()]
                t = truth["outcomes"][out.name]
                total, minimum = t["total_effect"], pt2.MINIMUM[out.name]
                row = {"truth_total": total, "data_total": data_total, "truth_shapley": t["shapley"], "data_shapley": shares, "material": abs(total) >= minimum}
                if row["material"]:
                    tol = pt2.TIE_FRACTION * minimum
                    scale_sum = sum(abs(v) for v in t["shapley"].values())
                    big = [p for p in names if abs(t["shapley"][p]) >= SIGN_SHARE * scale_sum]
                    row.update({"top_agrees": top_player(shares, tol) == top_player(t["shapley"], tol), "sign_right": sum(1 for p in big if shares[p] * t["shapley"][p] > 0), "sign_of": len(big),
                                "normalised_error": max(abs(shares[p] - t["shapley"][p]) for p in names) / scale_sum, "total_relative_error": abs(data_total - total) / abs(total),
                                "kendall_tau_b": kendall_tau_b(t["shapley"], shares, tol)})
                else:
                    row["false_effect"] = abs(data_total) >= minimum
                cells.setdefault(variant, {}).setdefault(out.name, {})[str(season)] = row
        result["seasons"][str(season)] = {"cells": cells}
    result["surrogate_relative_rmse_over_series_std"] = {t: {"min": min(v), "max": max(v)} for t, v in quality.items()}
    return result


def summarise(regime: dict) -> dict:
    out = {}
    for variant in ("oracle_baseline", "climatology_baseline"):
        for outcome in OUTCOME_TARGET:
            rows = [s["cells"][variant][outcome][str(season)] for season, s in zip(EVAL_SEASONS, (regime["seasons"][str(x)] for x in EVAL_SEASONS))]
            material = [r for r in rows if r["material"]]
            key = f"{variant}/{outcome}"
            out[key] = {"material_cells": len(material), "of": len(rows), "top_agrees": sum(r["top_agrees"] for r in material),
                        "sign_right": f"{sum(r['sign_right'] for r in material)}/{sum(r['sign_of'] for r in material)}",
                        "normalised_error_range": [round(min(r["normalised_error"] for r in material), 3), round(max(r["normalised_error"] for r in material), 3)] if material else None,
                        "total_relative_error_range": [round(min(r["total_relative_error"] for r in material), 3), round(max(r["total_relative_error"] for r in material), 3)] if material else None,
                        "false_effects": f"{sum(1 for r in rows if not r['material'] and r['false_effect'])}/{sum(1 for r in rows if not r['material'])}"}
    return out


def main() -> int:
    simulator = TwinSimulator()
    regimes = []
    for scale in SCALES:
        regime = evaluate_regime(simulator, scale)
        regime["summary"] = summarise(regime)
        regimes.append(regime)
        print(f"== capacity scale {scale}; surrogate relative RMSE (min-max over held-out seasons):", {k: [round(v['min'], 3), round(v['max'], 3)] for k, v in regime["surrogate_relative_rmse_over_series_std"].items()})
        for key, row in regime["summary"].items():
            print("  ", key, row, flush=True)
    out = {"status": "DEVELOPMENT: tomato, four held-out DEV seasons per regime, candidate segments given, a simple surrogate; counts and ranges only", "regimes": regimes}
    out["report_hash"] = content_hash(out)
    REPORT.write_text(json.dumps(out, indent=1, sort_keys=True, default=float) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
