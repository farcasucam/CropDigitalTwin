"""Phase 6.5r, step 1: feasibility of the truth twin on EnergyPlus (decision D15) and a first look at the mismatch with the simplified twin.

    python -u manual_phase6_5r_energyplus_feasibility.py [--seasons 2]      # needs EnergyPlus 26.1; writes data/xai/energyplus_feasibility_report.json

What it checks, on the tomato greenhouse with the climate controller on (lock-step EnergyPlus, phase 5.46):
* the paired run (baseline and one intervention) completes on EnergyPlus, is deterministic (same trajectory hash twice) and costs how many seconds (wall time is reported, never used in any result);
* the effect of a cold wave on the heating energy and of a heat wave on the cooling energy and the indoor peak, in EnergyPlus (the truth twin) and in the simplified model (the working twin at mismatch level 0:
  same parameters, different structure), as direction, size and ratio. This is a measurement of the structural mismatch, not a validation of either twin.
Synthetic data; exploratory; no quality claim; the controller's equipment is illustrative.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from tsxai.core import Intervention, ScenarioDescriptor, content_hash, paired_frames  # noqa: E402

from agri_twin.infrastructure.energyplus_timeline import find_energyplus  # noqa: E402
from agri_twin.interfaces.xai_adapter import TwinSimulator, twin_series_source  # noqa: E402

LABELS = {"crop": "tomato", "environment": "greenhouse", "control": "on"}
WINDOW_START, WINDOW = 480, 240
CASES = (("COLD_WAVE", "greenhouse_heating_kw"), ("HEAT_WAVE", "greenhouse_cooling_kw"))


def scenario(simulator, season, backend):
    options = dict(simulator.scenario_options(LABELS, season))
    if backend == "ENERGYPLUS":
        options["greenhouse"] = {"backend": "ENERGYPLUS"}
    return ScenarioDescriptor(LABELS, season, WINDOW_START, WINDOW, options)


def integral(values):
    return float(sum(v for v in values if v is not None))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", type=int, default=2)
    args = parser.parse_args()
    install = find_energyplus()
    if install is None or not install.version.startswith("26.1"):
        print("EnergyPlus 26.1 is not installed: nothing to measure")
        return 1
    simulator = TwinSimulator()
    source = twin_series_source(simulator)
    factors = simulator.factors()
    rows, timings, determinism = [], [], []
    for season in range(args.seasons):
        for factor, target in CASES:
            item = Intervention(factor, 100, 24, factors[factor].probe_level)
            effects = {}
            for backend in ("SIMPLIFIED", "ENERGYPLUS"):
                scene = scenario(simulator, season, backend)
                started = time.perf_counter()
                pair = paired_frames(source, scene, [item])
                timings.append({"backend": backend, "season": season, "factor": factor, "paired_seconds": round(time.perf_counter() - started, 2)})
                if backend == "ENERGYPLUS":
                    determinism.append(pair.baseline.content_hash == source.frame(scene).content_hash)
                cut = pair.first_changed_sample
                effect_series = pair.effect(target)[cut:cut + 48]
                temperature = pair.effect("temperature_c")[cut:cut + 48]
                effects[backend] = {"effect_integral_kwh": integral(effect_series), "baseline_integral_kwh": integral(pair.baseline.series[target][cut:cut + 48]),
                                    "indoor_temperature_peak_effect": max(temperature, key=abs), "first_changed_sample": cut}
            truth, work = effects["ENERGYPLUS"]["effect_integral_kwh"], effects["SIMPLIFIED"]["effect_integral_kwh"]
            rows.append({"season": season, "factor": factor, "target": target, "level": item.level, "truth_energyplus": effects["ENERGYPLUS"], "working_simplified": effects["SIMPLIFIED"],
                         "same_direction": (truth > 0) == (work > 0) and truth != 0 and work != 0, "ratio_working_over_truth": (work / truth) if truth else None})
            print(season, factor, "truth", round(truth, 1), "working", round(work, 1), "kWh")
    seconds = [t["paired_seconds"] for t in timings if t["backend"] == "ENERGYPLUS"]
    report = {"status": "PASS" if all(determinism) else "FAIL", "energyplus_version": install.version, "window": [WINDOW_START, WINDOW], "scenario": LABELS, "cases": rows,
              "deterministic_energyplus_baseline": all(determinism), "paired_run_seconds_energyplus": {"min": min(seconds), "max": max(seconds), "mean": round(sum(seconds) / len(seconds), 2)},
              "timings_are_not_results": True, "statement": "feasibility and structural-mismatch measurement of the synthetic twin; no validation of either twin; no quality claim"}
    report["report_hash"] = content_hash({k: v for k, v in report.items() if k not in ("paired_run_seconds_energyplus", "statement")})
    out = ROOT / "data" / "xai" / "energyplus_feasibility_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, sort_keys=True, allow_nan=False), encoding="utf-8")
    print(json.dumps({"status": report["status"], "deterministic": report["deterministic_energyplus_baseline"], "seconds": report["paired_run_seconds_energyplus"], "report_hash": report["report_hash"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
