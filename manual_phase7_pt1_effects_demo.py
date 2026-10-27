"""Work package PT-1 of the re-planning (D25 draft): one complete, hand-inspectable episode of the greenhouse with its climate controller, explained by re-simulation.

    python -u manual_phase7_pt1_effects_demo.py     # writes data/xai/effects_pt1_report.json; no language model, no network

One episode (tomato, greenhouse, controller on, 14-day window), four exogenous perturbations as players (a heat wave, a cold wave, a high-radiation spell that overlaps the heat wave, and a wind spell), five outcomes
computed on the same runs, under two policies:

* REACTIVE: the rule-based controller answers each perturbation ("effect with reactive policy").
* REPLAYED: the commands the controller issued WITHOUT any perturbation are imposed step by step ("effect with replayed actuation"). Their difference is reported as the difference between two contrasts, not as
  a direct or an indirect effect.

For each outcome the report carries, separately: the contrast factual minus reference, the leave-one-out effects, their gap to the contrast, and the exact Shapley division (16 coalitions) under the stated valuation.
Checked here: the division reconstructs the contrast (efficiency), replaying the reference's own commands reproduces the reference run, the reference is the same run under both policies, and a second build gives the
same report hash. These checks are about arithmetic and plumbing: nothing here validates the twin against a real greenhouse (its crop model is uncalibrated), and one episode is no sample.

An outcome that is a function of the controller's commands (the heating and cooling energy) cannot change when the commands are replayed: its replayed contrast is zero by construction, and the whole effect on it is the
controller's reaction. That is a consequence of the definition, not a finding about the greenhouse.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from tsxai.core import Intervention, ScenarioDescriptor, content_hash  # noqa: E402
from tsxai.effects import EffectQuery, Outcome, Player, Policy, ResimulationEngine  # noqa: E402

from agri_twin.application.seasonal_synthetic_campaign import campaign_cycle  # noqa: E402
from agri_twin.interfaces.xai_adapter import TwinSimulator, semantic_pack  # noqa: E402

REPORT = ROOT / "data" / "xai" / "effects_pt1_report.json"
LABELS = {"crop": "tomato", "environment": "greenhouse", "control": "on"}
SEASON, WINDOW_START, WINDOW_HOURS = 0, 24 * 40, 24 * 14
PLAYERS = (  # window sample index at which each starts, duration in hours, level (the levels are those of the benchmark's probes, not agronomic values)
    Player("heat_wave", (Intervention("HEAT_WAVE", 48, 48, 8.0),)),
    Player("cold_wave", (Intervention("COLD_WAVE", 200, 48, 6.0),)),
    Player("high_radiation", (Intervention("HIGH_RADIATION", 72, 48, 1.3),)),  # overlaps the heat wave on purpose: a pair that can interact
    Player("wind", (Intervention("WIND", 150, 36, 3.0),)),
)
TOLERANCE = 1e-6


def scenario(simulator: TwinSimulator) -> ScenarioDescriptor:
    return ScenarioDescriptor(LABELS, SEASON, WINDOW_START, WINDOW_HOURS, simulator.scenario_options(LABELS, SEASON))


def outcomes(month: int) -> tuple[Outcome, ...]:
    """Five outcomes. The thresholds are the crop catalogue's own for the stage of the window's month (read with their path), never invented."""
    pack = semantic_pack(LABELS["crop"], month)
    t_max, vpd_max = pack.thresholds["temperature_c"]["max"], pack.thresholds["vpd_kpa"]["max"]
    return (
        Outcome("heating_energy", "greenhouse_heating_kw", "integral", "kWh (thermal)"),
        Outcome("cooling_energy", "greenhouse_cooling_kw", "integral", "kWh (thermal)"),
        Outcome("hours_temperature_above_stage_max", "temperature_c", "hours_above", "h", threshold=t_max.value),
        Outcome("hours_vpd_above_stage_max", "vpd_kpa", "hours_above", "h", threshold=vpd_max.value),
        Outcome("temperature_peak", "temperature_c", "max", "degC"),
    )


def table(report: dict) -> list[str]:
    lines = []
    for name, o in report["outcomes"].items():
        lines.append(f"  {name} [{o['unit']}]  factual {o['factual']:.2f}  reference {o['reference']:.2f}  contrast {o['total_effect']:+.2f}  interaction gap {o['interaction_gap']:+.2f}")
        for player in report["query"]["players"]:
            n = player["name"]
            lines.append(f"      {n:15s} leave-one-out {o['leave_one_out'][n]:+9.2f}   shapley {o['shapley'][n]:+9.2f}")
    return lines


def main() -> int:
    simulator = TwinSimulator()
    desc = scenario(simulator)
    _, origin, _ = campaign_cycle(LABELS["crop"])
    month = (origin.replace(microsecond=0) + __import__("datetime").timedelta(hours=WINDOW_START)).month
    outs = outcomes(month)
    started = time.perf_counter()
    engine = ResimulationEngine(simulator)
    reactive = engine.evaluate(EffectQuery(desc, outs, PLAYERS, policy=Policy("reactive")))
    t_reactive = time.perf_counter() - started
    replayed = engine.evaluate(EffectQuery(desc, outs, PLAYERS, policy=Policy("replayed")))
    t_total = time.perf_counter() - started
    second = ResimulationEngine(simulator).evaluate(EffectQuery(desc, outs, PLAYERS, policy=Policy("reactive")))

    row = lambda r, players: next(c for c in r["coalitions"] if c["players"] == sorted(players))
    checks = {
        "efficiency_reactive_max_abs_residual": max(abs(o["efficiency_residual"]) for o in reactive["outcomes"].values()),
        "efficiency_replayed_max_abs_residual": max(abs(o["efficiency_residual"]) for o in replayed["outcomes"].values()),
        "replay_of_the_references_own_commands_reproduces_the_reference_run": replayed["policy_check"]["reproduces_source_run"],
        "reference_is_the_same_run_under_both_policies": row(reactive, [])["run_hash"] == row(replayed, [])["run_hash"],
        "second_build_gives_the_same_reactive_report_hash": second["report_hash"] == reactive["report_hash"],
        "all_coalitions_completed": all(c["status"] == "ok" for r in (reactive, replayed) for c in r["coalitions"]),
        "commands_replayed": replayed["policy_check"]["trace_actuators"],
    }
    contrasts = {name: {"reactive": reactive["outcomes"][name]["total_effect"], "replayed": replayed["outcomes"][name]["total_effect"],
                        "difference_between_contrasts": reactive["outcomes"][name]["total_effect"] - replayed["outcomes"][name]["total_effect"]} for name in reactive["outcomes"]}
    report = {
        "phase": "7.PT-1 (D25 draft, development)", "status": "DEVELOPMENT: one episode; arithmetic and replay plumbing checked; no physical validation, no sample, no confirmatory claim",
        "episode": {"labels": LABELS, "season": SEASON, "window_start_hour": WINDOW_START, "window_hours": WINDOW_HOURS, "month_of_window": month},
        "thresholds_source": {o.name: {"threshold": o.threshold, "source": "crop_config.json via semantic_pack, stage of the window's month"} for o in outs if o.threshold is not None},
        "reactive": reactive, "replayed": replayed, "difference_between_contrasts": contrasts, "checks": checks,
        "reading": ("Commands that the controller determines (heating and cooling energy) are replayed, so their replayed contrast is zero by construction. The physical outcomes (temperature, VPD) show what the "
                    "perturbations do when the controller does not answer them. Shapley shares depend on the stated valuation (outcome with exactly the players of the coalition ON, the rest at the reference), "
                    "on the reference (no perturbation) and on the grouping of the four players."),
    }
    report["report_hash"] = content_hash({k: v for k, v in report.items() if k != "report_hash"})
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"episode: {LABELS}, season {SEASON}, hours {WINDOW_START}..{WINDOW_START + WINDOW_HOURS} (month {month})")
    print("REACTIVE policy (the controller answers):"), [print(line) for line in table(reactive)]
    print("REPLAYED actuation (the reference's commands imposed):"), [print(line) for line in table(replayed)]
    print("difference between contrasts (reactive - replayed):", {k: round(v["difference_between_contrasts"], 2) for k, v in contrasts.items()})
    print("checks:", json.dumps(checks))
    print(f"runs executed {engine.runs}, cache hits {engine.cache_hits}; wall time {t_reactive:.0f} s reactive, {t_total:.0f} s both (a measurement of this machine, not part of the report)")
    assert checks["efficiency_reactive_max_abs_residual"] < TOLERANCE and checks["efficiency_replayed_max_abs_residual"] < TOLERANCE
    assert checks["replay_of_the_references_own_commands_reproduces_the_reference_run"] and checks["reference_is_the_same_run_under_both_policies"]
    assert checks["second_build_gives_the_same_reactive_report_hash"] and checks["all_coalitions_completed"]
    print(f"report: {REPORT.relative_to(ROOT)} (hash {report['report_hash'][:8]}...)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
