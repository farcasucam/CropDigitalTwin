"""F1 pilot of the confirmatory protocol D25, first slice: TimesFM as a data-based estimator of the effects of three weather players, against the re-simulation truth, on DEVELOPMENT seasons only.

    python -u manual_phase7_f1_pilot.py [--url http://127.0.0.1:8088] [--seasons 34 35 37 38] [--windows 2]

PURPOSE. Find faults in the pipeline and fix the open parameters of `src/xai_protocol_d25.json` (`pilot_fixed`), never to produce results: the test partition is not touched (seasons come from the development
partition of `gctsb-1` and the script refuses a season that is a test season).

SETTING. Tomato; strata S1 (outdoor, no controller), S2 (greenhouse, controller off), S3 (greenhouse, controller on, truth reactive and replayed). Context 336 h of history before the window, window 240 h (the service
of TimesFM 2.5 returns at most 256 steps). Per episode three players drawn without replacement, by a generator seeded from (season, window), from the design's weather factors with intensities inside its ranges.
Truth: exact Shapley over 8 coalitions by re-simulation (tsxai.effects), both policies in S3.

ESTIMATE. The forecast of the outcome path from the context with the weather covariates over context and horizon (known future): for a coalition S the covariates are the baseline (reference run) weather with the
factual weather inside the segments of the players in S; the effect of S is the outcome of its forecast minus the outcome of the forecast of the empty coalition; the Shapley shares are the occlusion over the 8
coalitions. S1 forecasts the increments of total biomass (a cumulative stock cannot be forecast with a linear covariate fit) and rebuilds the end value; S2 and S3 forecast the indoor temperature. The controller
is not told anything (no controller covariate): its reading is against the replayed truth (the declared object of a forecaster that does not know the controller's reaction); the reactive truth is reported too.
Service: whatever answers at --url; its model and licence are written in the report. The protocol's primary comparator is TimesFM 3.0; with a 2.5 service this is the variant TF25 (XReg) and the report says so.
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import freeze_protocol_d25 as freeze  # noqa: E402
from tsxai.adapters.http_forecast import HttpForecastBackend  # noqa: E402
from tsxai.core import ForecastRequest, Intervention, ScenarioDescriptor, content_hash  # noqa: E402
from tsxai.effects import EffectQuery, Outcome, Player, Policy, ResimulationEngine, shapley_exact  # noqa: E402

from agri_twin.interfaces.xai_adapter import TwinSimulator  # noqa: E402

REPORT = ROOT / "data" / "xai" / "f1_pilot_timesfm.json"
CROP, CONTEXT, HOURS, START = "tomato", 336, 240, 1500
POOL = {"HEAT_WAVE": (3.0, 12.0), "COLD_WAVE": (3.0, 12.0), "LOW_RADIATION": (0.3, 0.8), "HIGH_RADIATION": (1.1, 1.5)}  # ranges of the benchmark design (wind is not a covariate of the forecast)
CHANNELS = {"outdoor": ("temperature_c", "radiation_w_m2", "relative_humidity_pct"), "greenhouse": ("outdoor_temperature_c", "outdoor_radiation_w_m2", "outdoor_relative_humidity_pct")}
FACTOR_CHANNELS = {"HEAT_WAVE": (0, 2), "COLD_WAVE": (0, 2), "LOW_RADIATION": (1,), "HIGH_RADIATION": (1,)}
STRATA = {"S1": {"environment": "outdoor", "control": "off", "truth": ("reactive",)}, "S2": {"environment": "greenhouse", "control": "off", "truth": ("reactive",)},
          "S3": {"environment": "greenhouse", "control": "on", "truth": ("reactive", "replayed_all")}}
MATERIALITY = {"biomass_total_end": 1.0, "temperature_mean": 0.1, "temperature_peak": 0.5}  # starting values of the protocol, to be fixed by this pilot
SIGN_SHARE = 0.05


def outcomes_of(stratum: str) -> tuple[Outcome, ...]:
    if stratum == "S1":
        return (Outcome("biomass_total_end", "biomass_total_g_m2", "max", "g/m2"),)
    return (Outcome("temperature_mean", "temperature_c", "mean", "degC"), Outcome("temperature_peak", "temperature_c", "max", "degC"))


def draw_players(season: int, window: int) -> tuple[Player, ...]:
    rng = random.Random(7000 + 10 * season + window)
    factors = rng.sample(sorted(POOL), 3)
    starts = sorted(rng.sample(range(0, HOURS - 73, 12), 3))
    players = []
    for factor, start in zip(factors, starts):
        low, high = POOL[factor]
        players.append(Player(factor.lower(), (Intervention(factor, start, rng.randint(12, 72), round(rng.uniform(low, high), 3)),)))
    return tuple(players)


def shifted(players, factual: bool = True):
    return tuple(Intervention(i.factor, i.start + CONTEXT, i.duration, i.level) for p in players for i in p.interventions) if factual else ()


def forcing(series: dict, environment: str) -> np.ndarray:
    return np.array([series[c] for c in CHANNELS[environment]], dtype=float)


def occluded(baseline: np.ndarray, factual: np.ndarray, players, coalition: frozenset) -> np.ndarray:
    out = baseline.copy()
    for p in players:
        if p.name in coalition:
            iv = p.interventions[0]
            for k in FACTOR_CHANNELS[iv.factor]:
                out[k, iv.start + CONTEXT: iv.start + CONTEXT + iv.duration] = factual[k, iv.start + CONTEXT: iv.start + CONTEXT + iv.duration]
    return out


def estimate(backend, stratum: str, players, ref_series: dict, fact_series: dict, outs, names) -> dict:
    """The forecast of every coalition and the occlusion division per outcome; the history is the factual one (identical to the reference before the first intervention)."""
    environment = STRATA[stratum]["environment"]
    base_f, fact_f = forcing(ref_series, environment), forcing(fact_series, environment)
    stock = stratum == "S1"
    target = np.array(ref_series["biomass_total_g_m2" if stock else "temperature_c"], dtype=float)
    history = np.diff(target[:CONTEXT + 1]) if stock else target[:CONTEXT]
    start_value = float(target[CONTEXT - 1]) if stock else 0.0
    coalitions = [frozenset(c) for n in range(len(names) + 1) for c in itertools.combinations(names, n)]
    paths = {}
    for c in coalitions:
        cov = occluded(base_f, fact_f, players, c)
        names_cov = {f"cov{k}": tuple(float(x) for x in cov[k, : CONTEXT + HOURS]) for k in range(cov.shape[0])}
        request = ForecastRequest(targets={"y": tuple(float(x) for x in history)}, horizon=HOURS, known_future=names_cov)
        median = backend.forecast(request).median["y"]
        paths[c] = list(np.cumsum(median) + start_value) if stock else list(median)
    result = {}
    for out in outs:
        if stock:
            values = {c: out.evaluate([0.0] * 0 + paths[c]) for c in coalitions}
        else:
            values = {c: out.evaluate(paths[c]) for c in coalitions}
        result[out.name] = {"total": values[frozenset(names)] - values[frozenset()], "shapley": shapley_exact(names, values)}
    return result


def spearman(a: dict, b: dict) -> float | None:
    keys = sorted(a)
    ra, rb = np.argsort(np.argsort([a[k] for k in keys])), np.argsort(np.argsort([b[k] for k in keys]))
    if np.std(ra) == 0 or np.std(rb) == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def episode(simulator, backend, stratum: str, season: int, window: int) -> dict:
    spec = STRATA[stratum]
    labels = {"crop": CROP, "environment": spec["environment"], "control": spec["control"]}
    options = dict(simulator.scenario_options(labels, season))
    players = draw_players(season, window)
    names = [p.name for p in players]
    outs = outcomes_of(stratum)
    desc = ScenarioDescriptor(labels, season, START + window * HOURS, HOURS, options)
    truth = {}
    for policy in spec["truth"]:
        truth[policy] = ResimulationEngine(simulator).evaluate(EffectQuery(desc, outs, players, policy=Policy("replayed" if policy == "replayed_all" else "reactive")))
    wide = ScenarioDescriptor(labels, season, START + window * HOURS - CONTEXT, CONTEXT + HOURS, options)
    fact_series = simulator.run(wide, shifted(players)).series
    ref_series = simulator.run(wide, ()).series
    est = estimate(backend, stratum, players, ref_series, fact_series, outs, names)
    cells = {}
    for out in outs:
        row = {"players": {p.name: [{"factor": i.factor, "start": i.start, "duration": i.duration, "value": i.level} for i in p.interventions] for p in players}, "estimate_total": est[out.name]["total"],
               "estimate_shapley": est[out.name]["shapley"], "truth": {}}
        for policy, report in truth.items():
            t = report["outcomes"][out.name]
            total, minimum = t["total_effect"], MATERIALITY[out.name]
            scale = sum(abs(v) for v in t["shapley"].values())
            row["truth"][policy] = {"total": total, "shapley": t["shapley"], "material": abs(total) >= minimum, "sign_agrees": (est[out.name]["total"] * total > 0) if abs(total) >= minimum else None,
                                    "relative_error": abs(est[out.name]["total"] - total) / max(abs(total), minimum), "spearman": spearman(est[out.name]["shapley"], t["shapley"]),
                                    "net_understates_largest": bool(scale > 0 and abs(total) < max(abs(v) for v in t["shapley"].values()) and any(v > 0 for v in t["shapley"].values()) and any(v < 0 for v in t["shapley"].values()))}
        cells[out.name] = row
    return {"stratum": stratum, "season": season, "window": window, "cells": cells}


def summarise(episodes: list[dict]) -> dict:
    out = {}
    for stratum in STRATA:
        for outcome in {o for e in episodes if e["stratum"] == stratum for o in e["cells"]}:
            for policy in STRATA[stratum]["truth"]:
                rows = [e["cells"][outcome]["truth"][policy] for e in episodes if e["stratum"] == stratum]
                material = [r for r in rows if r["material"]]
                rho = [r["spearman"] for r in material if r["spearman"] is not None]
                out[f"{stratum}/{outcome}/{policy}"] = {"episodes": len(rows), "material": len(material), "sign_agrees": sum(1 for r in material if r["sign_agrees"]),
                                                       "median_relative_error": float(np.median([r["relative_error"] for r in material])) if material else None,
                                                       "median_spearman": float(np.median(rho)) if rho else None, "net_understates_largest": sum(r["net_understates_largest"] for r in rows)}
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8088")
    parser.add_argument("--seasons", type=int, nargs="*", default=[34, 35, 37, 38])
    parser.add_argument("--windows", type=int, default=2)
    parser.add_argument("--strata", nargs="*", default=list(STRATA))
    args = parser.parse_args()
    protocol = json.loads(freeze.PROTOCOL.read_text(encoding="utf-8"))
    test = set(freeze.partitions(protocol)["agri"][CROP])
    if test & set(args.seasons):
        raise SystemExit(f"refused: seasons {sorted(test & set(args.seasons))} belong to the test partition")
    backend = HttpForecastBackend(args.url)
    service = backend.health()
    simulator = TwinSimulator()
    episodes = []
    for stratum in args.strata:
        for season in args.seasons:
            for window in range(args.windows):
                episodes.append(episode(simulator, backend, stratum, season, window))
                print(stratum, season, window, flush=True)
    report = {"status": "DEVELOPMENT PILOT F1 (first slice): development seasons only, not confirmatory", "service": service, "crop": CROP, "context_hours": CONTEXT, "horizon_hours": HOURS, "materiality_used": MATERIALITY,
              "seasons": args.seasons, "episodes": episodes, "summary": summarise(episodes)}
    report["report_hash"] = content_hash(report)
    REPORT.write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps(report["summary"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
