"""Audit of how the interventions (runtime events) act on every output, outdoors and in the greenhouse, with and without EnergyPlus.

Offline (EnergyPlus runs only if it is installed). For each mode and each event it runs the same simulation with and without the event and reports, per output,
the mean change inside the event window, the largest change inside it and the largest change after it. It also checks when an event acts, how the humidity is
treated in a heat wave, and how the indoor climate of both greenhouse models compares with the outdoor one.

    python -u manual_audit_intervention_effects.py            # writes data/audit/intervention_effects.json

Findings and their interpretation: docs/auditoria_modelos_prediccion.md. Synthetic forcing only: nothing here validates a model against real data.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from agri_twin.application.interactive_simulation import InteractiveSimulationService, SimulationApiError  # noqa: E402
from agri_twin.infrastructure.energyplus_timeline import find_energyplus  # noqa: E402

MODES = {
    "outdoor": {"environment": "outdoor"},
    "gh_simplified": {"environment": "greenhouse"},
    "gh_energyplus": {"environment": "greenhouse", "greenhouse": {"backend": "ENERGYPLUS"}},
}
START = "2026-02-27T00:00:00+00:00"  # day 12 of the tomato cycle
HOURS = 72
EVENTS = {
    "HEAT_WAVE +8": {"event_type": "HEAT_WAVE", "intensity": 8},
    "COLD_WAVE -8": {"event_type": "COLD_WAVE", "intensity": 8},
    "DRYNESS": {"event_type": "DRYNESS"},
    "RAIN 5 mm/h": {"event_type": "RAIN", "intensity": 5},
    "HIGH_RADIATION x1.5": {"event_type": "HIGH_RADIATION", "intensity": 1.5},
    "LOW_RADIATION x0.5": {"event_type": "LOW_RADIATION", "intensity": 0.5},
    "WIND x3": {"event_type": "WIND", "intensity": 3},
    "IRRIGATION 2 mm": {"event_type": "IRRIGATION", "intensity": 2},
    "VENTILATION 1.0": {"event_type": "VENTILATION", "intensity": 1.0},
    "SHADING 0.6": {"event_type": "SHADING", "intensity": 0.6},
    "CO2 0.8": {"event_type": "CO2", "intensity": 0.8},
}
BASE = {"crop": "tomato", "end_time": "2026-03-12T00:00:00+00:00", "scenario": "BASE_SEASON", "options": {"include_trajectory": True, "compute_trajectory_hash": False}}
service = InteractiveSimulationService()


def run(mode: str, events=()):
    request = {**BASE, **MODES[mode]}
    if events:
        request["runtime_events"] = [{**event, "start_simulation_time": START, "duration_hours": HOURS} for event in events]
    return service.run_simulation(request)


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def effects(base: dict, other: dict, w0: int, w1: int) -> dict:
    changed = {}
    for name, series in other.items():
        if name == "time" or name not in base or not (base[name] and is_number(base[name][0])):
            continue
        deltas = [(y - x) if is_number(x) and is_number(y) else 0.0 for x, y in zip(base[name], series)]
        if max((abs(d) for d in deltas), default=0.0) <= 1e-9:
            continue
        window, after = deltas[w0:w1], deltas[w1:]
        changed[name] = {"window_mean": round(statistics.mean(window), 4), "window_max_abs": round(max(abs(d) for d in window), 4),
                         "after_max_abs": round(max((abs(d) for d in after), default=0.0), 4), "baseline_window_mean": round(statistics.mean(v for v in base[name][w0:w1] if is_number(v)), 4)}
    return changed


def matrix() -> dict:
    results = {}
    for mode in MODES:
        if mode == "gh_energyplus" and find_energyplus() is None:
            results[mode] = {"skipped": "EnergyPlus is not installed"}
            continue
        started = time.time()
        baseline = run(mode).result.trajectory
        w0 = next(i for i, stamp in enumerate(baseline["time"]) if stamp >= START)
        results[mode] = {}
        for label, event in EVENTS.items():
            try:
                response = run(mode, [event])
            except SimulationApiError as exc:
                results[mode][label] = {"rejected": exc.to_dict()["errors"][0]["message"][:140]}
                continue
            results[mode][label] = effects(baseline, response.result.trajectory, w0, w0 + HOURS)
        print(f"{mode}: {time.time() - started:.0f} s", flush=True)
    return results


def saturation_kpa(temperature: float) -> float:
    return 0.6108 * math.exp(17.27 * temperature / (temperature + 237.3))


def extra_checks() -> dict:
    out = {}
    heat = {"event_type": "HEAT_WAVE", "intensity": 8}
    base, hot = run("outdoor").result.trajectory, run("outdoor", [heat]).result.trajectory
    hit = [i for i, (x, y) in enumerate(zip(base["temperature_c"], hot["temperature_c"])) if abs(y - x) > 1e-9]
    out["event_timing"] = {"event_hours": HOURS, "samples_affected": len(hit), "first": base["time"][hit[0]], "last": base["time"][hit[-1]]}
    temperature, humidity = base["temperature_c"][hit[0]:hit[-1] + 1], base["relative_humidity_pct"][hit[0]:hit[-1] + 1]
    mean = statistics.mean
    out["heat_wave_humidity"] = {
        "vpd_baseline_kpa": round(mean(saturation_kpa(t) * (1 - r / 100) for t, r in zip(temperature, humidity)), 3),
        "vpd_model_constant_relative_humidity_kpa": round(mean(saturation_kpa(t + 8) * (1 - r / 100) for t, r in zip(temperature, humidity)), 3),
        "vpd_if_vapour_pressure_were_kept_kpa": round(mean(saturation_kpa(t + 8) - saturation_kpa(t) * r / 100 for t, r in zip(temperature, humidity)), 3),
        "vapour_pressure_growth_under_constant_rh": round(mean(saturation_kpa(t + 8) / saturation_kpa(t) for t in temperature), 3)}
    greenhouses = {}
    for label, mode in (("simplified", "gh_simplified"), ("energyplus", "gh_energyplus")):
        if mode == "gh_energyplus" and find_energyplus() is None:
            continue
        tr = run(mode).result.trajectory
        hours = [int(stamp[11:13]) for stamp in tr["time"]]
        inside, outside = tr["temperature_c"], tr["outdoor_temperature_c"]
        greenhouses[label] = {"indoor_minus_outdoor_mean_k": round(mean(i - o for i, o in zip(inside, outside)), 2),
                              "midday_k": round(mean(i - o for i, o, h in zip(inside, outside, hours) if 10 <= h <= 16), 2),
                              "night_k": round(mean(i - o for i, o, h in zip(inside, outside, hours) if h <= 5), 2),
                              "indoor_min_c": round(min(inside), 1), "indoor_max_c": round(max(inside), 1), "indoor_rh_mean_pct": round(mean(tr["relative_humidity_pct"]), 1),
                              "heating_mean_kw": round(mean(tr["greenhouse_heating_kw"]), 2), "ventilation_fraction_mean": round(mean(tr["greenhouse_ventilation_fraction"]), 3)}
    out["greenhouse_baselines"] = greenhouses
    return out


if __name__ == "__main__":
    report = {"window": {"start": START, "hours": HOURS}, "effects": matrix(), **extra_checks(),
              "scientific_status": "synthetic forcing; differences between two simulated scenarios, not validated against real data"}
    destination = ROOT / "data" / "audit"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "intervention_effects.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("event_timing", "heat_wave_humidity", "greenhouse_baselines")}, indent=1))
    print("written data/audit/intervention_effects.json")
