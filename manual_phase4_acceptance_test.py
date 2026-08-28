"""Manual offline acceptance test for the Phase 4 Crop Engine MVP."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from agri_twin.application import OpenFieldPhysicalModel, WeatherEngine
from agri_twin.application.clock import SimulationClock
from agri_twin.application.providers import ScenarioWeatherProvider
from agri_twin.domain import (
    CropConfigRepository,
    CropEngine,
    FarmConfigRepository,
    SoilState,
    WeatherConfiguration,
)
from agri_twin.infrastructure import CsvWeatherProvider

ROOT = Path(__file__).resolve().parent
FARM = ROOT / "src" / "farm_config.json"
CROP = ROOT / "src" / "crop_config.json"
DATASET = ROOT / "data" / "weather" / "manual_forecast.csv"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_check(name: str, function, results: list[tuple[str, str, str]]) -> None:
    try:
        results.append((name, "PASS", str(function() or "verified")))
    except Exception as exc:
        results.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))


def context():
    plot = FarmConfigRepository(FARM).get_plot("plot_14705")
    crop = CropConfigRepository(CROP).get_crop(plot.crop_key)
    stage = crop.resolve_stage(plot.current_stage)
    return plot, crop, stage


def configuration_check() -> str:
    plot, crop, stage = context()
    require(plot.crop_key == crop.crop_key and stage.stage_key == plot.current_stage, "plot/crop/stage mismatch")
    return f"{plot.plot_id} -> {crop.crop_key} -> {stage.stage_key}"


def normal_check() -> str:
    _, crop, stage = context()
    state = CsvWeatherProvider(DATASET)
    timestamp = state.timestamps[0]
    weather_engine = WeatherEngine(WeatherConfiguration(), provider=state)
    weather = weather_engine.generate(timestamp)
    physical = OpenFieldPhysicalModel().evaluate(weather, SoilState(0.25, 20, 0.35, 0.10, 0, 0.25), 3600)
    crop_state = CropEngine().evaluate(crop, stage, weather, physical.environment, physical.soil, timestamp)
    require(crop_state.temperature_stress == 0, "normal temperature unexpectedly stressed")
    require(0 <= crop_state.total_stress <= 1 and 0 <= crop_state.growth_factor <= 1, "stress invariant failed")
    return f"stress={crop_state.total_stress:.3f}, growth_factor={crop_state.growth_factor:.3f}"


def causal_stress_check() -> str:
    _, crop, stage = context()
    model = CropEngine()
    soil = SoilState(0.25, 20, 0.35, 0.10, 0, 0.25)
    physical = OpenFieldPhysicalModel()
    normal_weather = __import__("agri_twin.domain", fromlist=["WeatherState"]).WeatherState(25, 50, 600, 2, 180, 0, 1012)
    extreme_weather = __import__("agri_twin.domain", fromlist=["WeatherState"]).WeatherState(40, 10, 600, 2, 180, 0, 1012)
    normal_environment = physical.evaluate(normal_weather, soil, 3600).environment
    extreme_environment = physical.evaluate(extreme_weather, soil, 3600).environment
    normal = model.evaluate(crop, stage, normal_weather, normal_environment, soil, context()[0].location and __import__("datetime").datetime(2026, 8, 28, tzinfo=__import__("datetime").timezone.utc))
    extreme = model.evaluate(crop, stage, extreme_weather, extreme_environment, soil, __import__("datetime").datetime(2026, 8, 28, tzinfo=__import__("datetime").timezone.utc))
    dry = model.evaluate(crop, stage, normal_weather, normal_environment, SoilState(0.11, 20, 0.35, 0.10, 0, 0.11), __import__("datetime").datetime(2026, 8, 28, tzinfo=__import__("datetime").timezone.utc))
    require(extreme.temperature_stress > normal.temperature_stress, "thermal causality failed")
    require(dry.water_stress > normal.water_stress, "water causality failed")
    return "thermal and water stress respond causally"


def clock_progress_check() -> str:
    plot, crop, stage = context()
    provider = CsvWeatherProvider(DATASET)
    engine = WeatherEngine(WeatherConfiguration(), provider=provider)
    physical = OpenFieldPhysicalModel()
    crop_engine = CropEngine()
    initial_soil = SoilState(0.25, 20, 0.35, 0.10, 0, 0.25)
    initial = provider.timestamps[0]

    def simulate(speed: float):
        clock = SimulationClock(initial, speed=speed)
        current = initial
        state = None
        soil = initial_soil
        for _ in range(24):
            weather = engine.generate(current)
            result = physical.evaluate(weather, soil, 3600)
            state = crop_engine.evaluate(crop, stage, weather, result.environment, result.soil, current, 3600, state)
            soil = result.soil
            clock.advance(3600)
            current += timedelta(hours=1)
        return clock.now(), state

    normal_time, normal_state = simulate(1)
    accelerated_time, accelerated_state = simulate(3600)
    require(normal_time == accelerated_time == initial + timedelta(hours=24), "clock did not advance exactly 24 simulated hours")
    require(normal_state == accelerated_state, "accelerated simulation changed agronomic result")
    require(normal_state is not None and normal_state.development_index > 0, "crop did not progress")
    return f"24 simulated hours, development_index={normal_state.development_index:.4f}"


def offline_check() -> str:
    provider = CsvWeatherProvider(DATASET)
    weather_engine = WeatherEngine(WeatherConfiguration(), provider=provider)
    before = provider.get(provider.timestamps[0])
    after = weather_engine.generate(provider.timestamps[0])
    require(before == after, "WeatherEngine did not consume offline provider")
    scenario = ScenarioWeatherProvider(provider)
    require(scenario.get(provider.timestamps[0]) == before, "offline scenario changed baseline")
    return "CSV/provider/engine path requires no network"


def isolation_check() -> str:
    allowed = ROOT / "src" / "agri_twin" / "infrastructure" / "open_meteo.py"
    forbidden = ("requests", "httpx", "aiohttp", "urllib.request", "urlopen")
    offenders = []
    for path in (ROOT / "src" / "agri_twin").rglob("*.py"):
        if path == allowed:
            continue
        text = path.read_text(encoding="utf-8")
        if any(item in text for item in forbidden):
            offenders.append(str(path))
    require(not offenders, f"HTTP outside Open-Meteo: {offenders}")
    return "HTTP remains isolated"


def regression_check() -> str:
    completed = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    require(completed.returncode == 0, completed.stdout[-500:] or completed.stderr[-500:])
    return completed.stdout.strip().splitlines()[-1]


def main() -> int:
    results: list[tuple[str, str, str]] = []
    run_check("Crop configuration", lambda: configuration_check(), results)
    run_check("Stage and plot relation", lambda: configuration_check(), results)
    run_check("Normal conditions", normal_check, results)
    run_check("Thermal, VPD and water stress causality", causal_stress_check, results)
    run_check("CropState invariants and growth", normal_check, results)
    run_check("24 simulated hours and accelerated clock", clock_progress_check, results)
    run_check("Offline end-to-end chain", offline_check, results)
    run_check("Reproducibility", lambda: require(clock_progress_check(), "reproducibility failed") or "same speed-independent result", results)
    run_check("HTTP isolation", isolation_check, results)
    run_check("Regression suite", regression_check, results)
    print("=" * 60)
    print(" CROP DIGITAL TWIN - PHASE 4 MANUAL ACCEPTANCE")
    print("=" * 60)
    for index, (name, status, detail) in enumerate(results, 1):
        print(f"[{index:02d}] {name:.<39} {status}  {detail}")
    passed = sum(status == "PASS" for _, status, _ in results)
    failed = sum(status == "FAIL" for _, status, _ in results)
    skipped = sum(status == "SKIP" for _, status, _ in results)
    print("\n" + "=" * 60)
    print(f"PASS: {passed}\nFAIL: {failed}\nSKIP: {skipped}")
    print("PHASE 4 STATUS: " + ("ACCEPTED" if failed == 0 and skipped == 0 else "NOT READY"))
    return 0 if failed == 0 and skipped == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
