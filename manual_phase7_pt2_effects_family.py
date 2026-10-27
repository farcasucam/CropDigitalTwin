"""Work package PT-2 (D25): a small family of greenhouse episodes explained by re-simulation, and how much the division depends on the choices that define it.

    python -u manual_phase7_pt2_effects_family.py                  # all 9 episodes, resumable (a finished episode is not recomputed)
    python -u manual_phase7_pt2_effects_family.py --only tomato:0  # one episode
    python -u manual_phase7_pt2_effects_family.py --summarize      # only rebuild data/xai/effects_pt2_summary.json from the episode files

Family: 3 crops (tomato, pepper, lettuce) x 3 seeds (each seed is a different synthetic weather), greenhouse, climate controller on, a 14-day window; the same four exogenous perturbations as PT-1 (conventions of
the benchmark's probes). DEVELOPMENT: nine cells of one synthetic generator are not an independent sample of anything, there is no inferential test and no confirmatory claim. The twin's crop model is uncalibrated.

For each episode, under the REACTIVE policy and under REPLAYED actuation (the reference's commands imposed), the report keeps the contrast, the leave-one-out effects, the exact Shapley shares and the gap between
the leave-one-out effects and the contrast. On top of that, four sensitivity analyses, each a different choice that defines a share:

* S1 interaction-free score: ``v({i}) - v(empty)`` per player, the approximation of one-intervention-at-a-time analyses (Weilbach et al. 2024 drop interactions by design), against the exact share.
* S2 grouping: the heat wave and the high-radiation spell merged into one player ("weather_spell"), and the heat wave split into two adjacent 24-hour halves (the union is physically the same event: checked).
* S3 level: every perturbation at 0.5x and 1.5x of its level (additive offsets scaled; multipliers scaled in their excess over 1).
* S4 reference: the same players against a reference that already contains a dull period (LOW_RADIATION x0.8 over the whole window) instead of the unperturbed run. Events compose in the twin (temperature offsets add,
  radiation multipliers multiply), so this reference is well defined.

READING RULES, fixed before any episode was run (provisional design conventions, not scientific thresholds):

* A cell (episode, policy, outcome) is MATERIAL when the absolute total effect is at least the outcome's declared minimum: 1 kWh for the energies, 1 h for the hour counts, 0.05 K for the peak. Ratios are reported only
  for material cells; a ratio to a negligible total says nothing. Two scores are tied when they differ by less than 1 percent of that minimum.
* R1 masking (peak temperature, per episode): |reactive contrast| / |replayed contrast| < 0.05 is "masked", from 0.05 to 0.5 "partly masked", above 0.5 "not masked". Only where the replayed contrast is material.
* R2 interaction: |sum of leave-one-out effects - contrast| / |contrast| above 0.10 is a "material interaction".
* R3 S1: report whether the interaction-free top player equals the exact top player, Kendall tau-b between the two scorings, and the largest |interaction-free - exact| / |contrast|.
* R4 S2: |coarse share - sum of fine shares| / |contrast| above 0.10 is a "material grouping effect".
* R5 S3 and S4: report whether the top player is the same as in the base case, and Kendall tau-b against the base shares. No threshold: the distribution is the result.
* Results are shown as counts and ranges (minimum, median, maximum) over material cells. Nothing is averaged into a single figure of merit, and nothing is concluded about greenhouses in general.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from tsxai.core import Intervention, ScenarioDescriptor, content_hash  # noqa: E402
from tsxai.effects import (EffectQuery, Outcome, Player, Policy, ResimulationEngine, grouping_discrepancy, kendall_tau_b, relative_gap, singleton_effects, top_player)  # noqa: E402

from agri_twin.application.seasonal_synthetic_campaign import campaign_cycle  # noqa: E402
from agri_twin.interfaces.xai_adapter import TwinSimulator, semantic_pack  # noqa: E402

OUT_DIR = ROOT / "data" / "xai" / "effects_pt2"
SUMMARY = ROOT / "data" / "xai" / "effects_pt2_summary.json"
CROPS = ("tomato", "pepper", "lettuce")
SEASONS = (0, 1, 2)
WINDOW_START = {"tomato": 24 * 40, "pepper": 24 * 40, "lettuce": 24 * 14}  # lettuce's campaign is 42 days long
WINDOW_HOURS = 24 * 14
MINIMUM = {"heating_energy": 1.0, "cooling_energy": 1.0, "hours_temperature_above_stage_max": 1.0, "hours_vpd_above_stage_max": 1.0, "temperature_peak": 0.05}
TIE_FRACTION = 0.01
LEVELS = (0.5, 1.5)
ADDITIVE = {"HEAT_WAVE", "COLD_WAVE"}  # a level scaled as an offset; the others are multipliers scaled in their excess over 1


def base_players(scale: float = 1.0) -> tuple[Player, ...]:
    """Order matters: the heat wave and the radiation spell are adjacent so that the merged player's coalitions are the base coalitions (same runs, from the cache)."""
    def level(factor: str, value: float) -> float:
        return value * scale if factor in ADDITIVE else 1.0 + (value - 1.0) * scale
    return (Player("heat_wave", (Intervention("HEAT_WAVE", 48, 48, level("HEAT_WAVE", 8.0)),)),
            Player("high_radiation", (Intervention("HIGH_RADIATION", 72, 48, level("HIGH_RADIATION", 1.3)),)),
            Player("cold_wave", (Intervention("COLD_WAVE", 200, 48, level("COLD_WAVE", 6.0)),)),
            Player("wind", (Intervention("WIND", 150, 36, level("WIND", 3.0)),)))


def merged_players() -> tuple[Player, ...]:
    p = base_players()
    return (Player("weather_spell", p[0].interventions + p[1].interventions), p[2], p[3])


def split_players() -> tuple[Player, ...]:
    p = base_players()
    return (Player("heat_wave_a", (Intervention("HEAT_WAVE", 48, 24, 8.0),)), Player("heat_wave_b", (Intervention("HEAT_WAVE", 72, 24, 8.0),)), p[1], p[2], p[3])


def dull_reference() -> tuple[Intervention, ...]:
    return (Intervention("LOW_RADIATION", 0, WINDOW_HOURS - 1, 0.8),)


def outcomes(crop: str, month: int) -> tuple[Outcome, ...]:
    thresholds = semantic_pack(crop, month).thresholds
    outs = [Outcome("heating_energy", "greenhouse_heating_kw", "integral", "kWh (thermal)"), Outcome("cooling_energy", "greenhouse_cooling_kw", "integral", "kWh (thermal)")]
    if "max" in thresholds.get("temperature_c", {}):
        outs.append(Outcome("hours_temperature_above_stage_max", "temperature_c", "hours_above", "h", threshold=thresholds["temperature_c"]["max"].value))
    if "max" in thresholds.get("vpd_kpa", {}):
        outs.append(Outcome("hours_vpd_above_stage_max", "vpd_kpa", "hours_above", "h", threshold=thresholds["vpd_kpa"]["max"].value))
    outs.append(Outcome("temperature_peak", "temperature_c", "max", "degC"))
    return tuple(outs)


def digest(report: dict) -> dict:
    """What is kept of a full report: per outcome the numbers of the division and the interaction-free scores, plus the report hash for audit."""
    out = {}
    for name, o in report["outcomes"].items():
        out[name] = {"unit": o["unit"], "factual": o["factual"], "reference": o["reference"], "total_effect": o["total_effect"], "leave_one_out": o["leave_one_out"], "interaction_gap": o["interaction_gap"],
                     "shapley": o["shapley"], "efficiency_residual": o["efficiency_residual"], "singleton": singleton_effects(report, name)}
    return {"report_hash": report["report_hash"], "outcomes": out, "policy_check": report["policy_check"]}


def run_episode(crop: str, season: int) -> dict:
    simulator = TwinSimulator()
    labels = {"crop": crop, "environment": "greenhouse", "control": "on"}
    start = WINDOW_START[crop]
    desc = ScenarioDescriptor(labels, season, start, WINDOW_HOURS, simulator.scenario_options(labels, season))
    month = (campaign_cycle(crop)[1] + timedelta(hours=start)).month
    outs = outcomes(crop, month)
    engine = ResimulationEngine(simulator)
    policies = {"reactive": Policy("reactive"), "replayed": Policy("replayed")}

    def explain(players, policy, base=()):
        return engine.evaluate(EffectQuery(desc, outs, players, base_interventions=base, policy=policy))

    result: dict = {"episode": {"crop": crop, "season": season, "window_start_hour": start, "window_hours": WINDOW_HOURS, "month_of_window": month,
                                "thresholds": {o.name: o.threshold for o in outs if o.threshold is not None}},
                    "base": {}, "merged": {}, "split": {}, "levels": {}, "reference": {}}
    reports = {}
    for label, policy in policies.items():
        reports[label] = explain(base_players(), policy)
        result["base"][label] = digest(reports[label])
        result["merged"][label] = digest(explain(merged_players(), policy))
        result["split"][label] = digest(explain(split_players(), policy))
        result["reference"][label] = digest(explain(base_players(), policy, dull_reference()))
        for s in LEVELS:
            result["levels"].setdefault(str(s), {})[label] = digest(explain(base_players(s), policy))
    # checks: arithmetic, replay plumbing, and that splitting the heat wave in two halves is a pure regrouping (all players on is the same physical scenario)
    checks = {
        "max_abs_efficiency_residual": max(abs(o["efficiency_residual"]) for part in ("base", "merged", "split", "reference") for label in policies for o in result[part][label]["outcomes"].values()),
        "replay_reproduces_source_run_everywhere": all(result[part]["replayed"]["policy_check"]["reproduces_source_run"] for part in ("base", "merged", "split", "reference")),
        "levels_replay_reproduces": all(result["levels"][str(s)]["replayed"]["policy_check"]["reproduces_source_run"] for s in LEVELS),
        "split_factual_equals_base_factual_max_abs_difference": max(abs(result["split"][label]["outcomes"][name]["factual"] - result["base"][label]["outcomes"][name]["factual"])
                                                                    for label in policies for name in result["base"][label]["outcomes"]),
    }
    result["checks"] = checks
    result["engine_runs"] = {"executed": engine.runs, "cache_hits": engine.cache_hits}
    result["episode_hash"] = content_hash({k: v for k, v in result.items() if k != "engine_runs"})
    assert checks["max_abs_efficiency_residual"] < 1e-6, checks
    assert checks["replay_reproduces_source_run_everywhere"] and checks["levels_replay_reproduces"], checks
    assert checks["split_factual_equals_base_factual_max_abs_difference"] < 1e-9, checks
    return result


# -- reading the stored episodes (a pure function of the files) ------------------------------------------------------------------------------------
def spread(values: list[float]) -> dict:
    return {"n": len(values), "min": min(values), "median": statistics.median(values), "max": max(values)} if values else {"n": 0}


def summarize(episodes: list[dict]) -> dict:
    cells: dict[str, list] = {k: [] for k in ("interaction_relative_gap", "s1_top_agrees", "s1_tau", "s1_max_relative_error", "s2_merge_relative", "s2_split_relative", "s3_top_same", "s3_tau", "s4_top_same", "s4_tau")}
    masking, material_cells, rows = [], 0, []
    for ep in episodes:
        tag = f"{ep['episode']['crop']}:{ep['episode']['season']}"
        for label in ("reactive", "replayed"):
            for name, o in ep["base"][label]["outcomes"].items():
                minimum, total = MINIMUM[name], o["total_effect"]
                if abs(total) < minimum:
                    continue
                material_cells += 1
                tol = TIE_FRACTION * minimum
                shap = o["shapley"]
                rel = relative_gap(o["interaction_gap"], total, minimum)
                cells["interaction_relative_gap"].append(rel)
                single = o["singleton"]
                tp_e, tp_s = top_player(shap, tol), top_player(single, tol)
                cells["s1_top_agrees"].append(tp_e == tp_s)
                tau = kendall_tau_b(shap, single, tol)
                if tau is not None:
                    cells["s1_tau"].append(tau)
                cells["s1_max_relative_error"].append(max(abs(single[p] - shap[p]) for p in shap) / abs(total))
                merged = ep["merged"][label]["outcomes"][name]["shapley"]
                gm = grouping_discrepancy(merged, shap, {"weather_spell": ("heat_wave", "high_radiation")})
                cells["s2_merge_relative"].append(abs(gm["weather_spell"]) / abs(total))
                fine = ep["split"][label]["outcomes"][name]["shapley"]
                gs = grouping_discrepancy(shap, fine, {"heat_wave": ("heat_wave_a", "heat_wave_b")})
                cells["s2_split_relative"].append(abs(gs["heat_wave"]) / abs(total))
                for s in LEVELS:
                    scaled = ep["levels"][str(s)][label]["outcomes"][name]
                    cells["s3_top_same"].append(top_player(scaled["shapley"], tol) == tp_e)
                    t = kendall_tau_b(shap, scaled["shapley"], tol)
                    if t is not None:
                        cells["s3_tau"].append(t)
                ref = ep["reference"][label]["outcomes"][name]
                cells["s4_top_same"].append(top_player(ref["shapley"], tol) == tp_e)
                t = kendall_tau_b(shap, ref["shapley"], tol)
                if t is not None:
                    cells["s4_tau"].append(t)
                rows.append({"episode": tag, "policy": label, "outcome": name, "total_effect": total, "interaction_relative_gap": rel, "s1_top_agrees": tp_e == tp_s, "top_player": tp_e})
        reactive, replayed = ep["base"]["reactive"]["outcomes"]["temperature_peak"], ep["base"]["replayed"]["outcomes"]["temperature_peak"]
        if abs(replayed["total_effect"]) >= MINIMUM["temperature_peak"]:
            ratio = abs(reactive["total_effect"]) / abs(replayed["total_effect"])
            masking.append({"episode": tag, "ratio": ratio, "class": "masked" if ratio < 0.05 else "partly masked" if ratio <= 0.5 else "not masked"})
    flag = lambda xs, test: sum(1 for x in xs if x is not None and test(x))
    return {
        "status": "DEVELOPMENT: nine cells of one synthetic generator, no inferential test, no confirmatory claim; thresholds are provisional conventions fixed before the runs (see the script's docstring)",
        "episodes": len(episodes), "material_cells": material_cells,
        "R1_masking_of_peak_temperature": {"episodes_with_material_replayed_contrast": len(masking), "by_class": {c: sum(1 for m in masking if m["class"] == c) for c in ("masked", "partly masked", "not masked")}, "ratios": spread([m["ratio"] for m in masking]), "per_episode": masking},
        "R2_interaction": {"relative_gap": spread([x for x in cells["interaction_relative_gap"] if x is not None]), "material_interactions_above_10_percent": flag(cells["interaction_relative_gap"], lambda x: x > 0.10), "of": len([x for x in cells["interaction_relative_gap"] if x is not None])},
        "R3_S1_interaction_free_score": {"top_player_agrees": {"yes": sum(cells["s1_top_agrees"]), "of": len(cells["s1_top_agrees"])}, "kendall_tau_b": spread(cells["s1_tau"]), "max_relative_error": spread(cells["s1_max_relative_error"])},
        "R4_S2_grouping": {"merge_heat_wave_and_radiation_relative_discrepancy": spread(cells["s2_merge_relative"]), "material_above_10_percent": flag(cells["s2_merge_relative"], lambda x: x > 0.10),
                           "split_heat_wave_relative_discrepancy": spread(cells["s2_split_relative"]), "split_material_above_10_percent": flag(cells["s2_split_relative"], lambda x: x > 0.10)},
        "R5_S3_levels": {"top_player_same": {"yes": sum(cells["s3_top_same"]), "of": len(cells["s3_top_same"])}, "kendall_tau_b": spread(cells["s3_tau"])},
        "R5_S4_reference": {"top_player_same": {"yes": sum(cells["s4_top_same"]), "of": len(cells["s4_top_same"])}, "kendall_tau_b": spread(cells["s4_tau"])},
        "cells": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only")
    parser.add_argument("--summarize", action="store_true")
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    wanted = [(c, s) for c in CROPS for s in SEASONS if not args.only or args.only == f"{c}:{s}"]
    if not args.summarize:
        for crop, season in wanted:
            path = OUT_DIR / f"{crop}_s{season}.json"
            if path.exists():
                print(f"{crop}:{season} already done")
                continue
            started = time.perf_counter()
            episode = run_episode(crop, season)
            path.write_text(json.dumps(episode, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"{crop}:{season} done in {time.perf_counter() - started:.0f} s (a measurement of this machine, not part of the report); runs {episode['engine_runs']}; checks {episode['checks']}", flush=True)
    episodes = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(OUT_DIR.glob("*_s*.json"))]
    if not episodes:
        return 1
    summary = summarize(episodes)
    summary["episode_hashes"] = {f"{e['episode']['crop']}:{e['episode']['season']}": e["episode_hash"] for e in episodes}
    summary["summary_hash"] = content_hash({k: v for k, v in summary.items() if k != "summary_hash"})
    SUMMARY.write_text(json.dumps(summary, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("cells",)}, indent=1, ensure_ascii=False)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
