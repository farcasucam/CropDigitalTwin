"""Phase 5.44 verification: the simplified (lumped) greenhouse against the EnergyPlus greenhouse of the same layout.

Compares, over a winter window (synthetic weather) and a summer window (local real weather, if downloaded), the indoor climate, the radiation reaching the crop,
the heating energy and the answer to the interventions of both models, and asserts the stated tolerances. EnergyPlus must be installed.

    python -u manual_phase5_44_greenhouse_consistency.py        # writes data/audit/greenhouse_consistency.json

This is consistency between two models with PROVISIONAL envelope values, not validation against a real greenhouse.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from agri_twin.application.interactive_simulation import InteractiveSimulationService  # noqa: E402
from agri_twin.application.weather_datasets import dataset_info  # noqa: E402
from agri_twin.infrastructure.energyplus_timeline import find_energyplus  # noqa: E402

OPTIONS = {"include_trajectory": True, "compute_trajectory_hash": False}
WINDOWS = {
    "winter_synthetic": {"crop": "tomato", "end_time": "2026-03-17T00:00:00+00:00"},
    "summer_real_weather": {"crop": "tomato", "weather": {"source": "LOCAL_ARCHIVE", "campaign_start": "2022-06-01T00:00:00+00:00"}, "end_time": "2022-06-30T00:00:00+00:00"},
}
TOLERANCES = {"hourly_indoor_rmse_k": 3.0, "midday_gap_k": 2.5, "radiation_ratio_error": 0.08, "winter_heating_energy_error": 0.35, "intervention_gap_k": 1.5}
INTERVENTIONS = (("SHADING", 0.6), ("VENTILATION", 1.0), ("LOW_RADIATION", 0.5), ("HIGH_RADIATION", 1.5))
service = InteractiveSimulationService()
mean = statistics.mean


def run(document: dict, backend: str, events=()) -> dict:
    request = {**document, "environment": "greenhouse", "greenhouse": {"backend": backend}, "options": OPTIONS}
    if events:
        request["runtime_events"] = list(events)
    response = service.run_simulation(request)
    assert response.execution_status.value == "COMPLETED", response.errors
    return response.result.trajectory


def summary(tr: dict, hours: list[int]) -> dict:
    gap = [i - o for i, o in zip(tr["temperature_c"], tr["outdoor_temperature_c"])]
    return {"radiation_w_m2": round(mean(tr["radiation_w_m2"]), 1), "indoor_minus_outdoor_midday_k": round(mean(g for g, h in zip(gap, hours) if 10 <= h <= 16), 2),
            "indoor_minus_outdoor_night_k": round(mean(g for g, h in zip(gap, hours) if h <= 5), 2), "indoor_min_c": round(min(tr["temperature_c"]), 1),
            "indoor_max_c": round(max(tr["temperature_c"]), 1), "indoor_rh_pct": round(mean(tr["relative_humidity_pct"]), 1),
            "heating_kwh": round(sum(tr["greenhouse_heating_kw"])), "vent_opening_mean": round(mean(tr["greenhouse_ventilation_fraction"]), 2)}


def main() -> int:
    if find_energyplus() is None:
        print("EnergyPlus is not installed: nothing to compare")
        return 1
    report: dict = {"tolerances": TOLERANCES, "windows": {}, "interventions": {}, "scientific_status": "consistency between two models with provisional envelope values; not validation"}
    failures: list[str] = []
    for label, document in WINDOWS.items():
        if "weather" in document and dataset_info(document["crop"]) is None:
            report["windows"][label] = {"skipped": "no local weather downloaded"}
            continue
        lumped, detailed = run(document, "SIMPLIFIED"), run(document, "ENERGYPLUS")
        hours = [int(stamp[11:13]) for stamp in lumped["time"]]
        a, b = summary(lumped, hours), summary(detailed, hours)
        rmse = mean((x - y) ** 2 for x, y in zip(lumped["temperature_c"], detailed["temperature_c"])) ** 0.5
        row = {"lumped": a, "energyplus": b, "hourly_indoor_rmse_k": round(rmse, 2)}
        report["windows"][label] = row
        checks = [("hourly_indoor_rmse_k", rmse < TOLERANCES["hourly_indoor_rmse_k"]),
                  ("midday_gap_k", abs(a["indoor_minus_outdoor_midday_k"] - b["indoor_minus_outdoor_midday_k"]) < TOLERANCES["midday_gap_k"]),
                  ("radiation_ratio_error", abs(a["radiation_w_m2"] / b["radiation_w_m2"] - 1) < TOLERANCES["radiation_ratio_error"])]
        if b["heating_kwh"] > 0:
            checks.append(("winter_heating_energy_error", abs(a["heating_kwh"] / b["heating_kwh"] - 1) < TOLERANCES["winter_heating_energy_error"]))
        failures += [f"{label}: {name}" for name, ok in checks if not ok]
        print(label, json.dumps(row))
    winter = WINDOWS["winter_synthetic"]
    start = "2026-02-27T00:00:00+00:00"
    base_l, base_e = run(winter, "SIMPLIFIED"), run(winter, "ENERGYPLUS")
    first = next(i for i, stamp in enumerate(base_l["time"]) if stamp >= start)
    for kind, intensity in INTERVENTIONS:
        event = [{"event_type": kind, "intensity": intensity, "start_simulation_time": start, "duration_hours": 72}]
        change = {}
        for name, base, backend in (("lumped", base_l, "SIMPLIFIED"), ("energyplus", base_e, "ENERGYPLUS")):
            tr = run(winter, backend, event)
            change[name] = round(mean(y - x for x, y in zip(base["temperature_c"][first:first + 72], tr["temperature_c"][first:first + 72])), 2)
            change[f"{name}_heating_kw"] = round(mean(y - x for x, y in zip(base["greenhouse_heating_kw"][first:first + 72], tr["greenhouse_heating_kw"][first:first + 72])), 1)
        report["interventions"][f"{kind} {intensity}"] = change
        if abs(change["lumped"] - change["energyplus"]) >= TOLERANCES["intervention_gap_k"]:
            failures.append(f"{kind}: indoor change differs by {abs(change['lumped'] - change['energyplus']):.2f} K")
        print(kind, intensity, change)
    report["status"] = "PASS" if not failures else "FAIL"
    report["failures"] = failures
    destination = ROOT / "data" / "audit"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "greenhouse_consistency.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(report["status"], failures)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
