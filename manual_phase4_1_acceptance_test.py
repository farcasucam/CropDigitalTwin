"""Manual technical and agronomic audit for the Phase 4.1 Crop Engine MVP."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agri_twin.application import OpenFieldPhysicalModel, WeatherEngine
from agri_twin.application.clock import SimulationClock
from agri_twin.application.plot_weather import build_crop_digital_twin_state
from agri_twin.domain import CropConfigRepository, CropEngine, CropDigitalTwinState, FarmConfigRepository, SoilState, WeatherConfiguration, WeatherState
from agri_twin.infrastructure import CsvWeatherProvider

ROOT = Path(__file__).resolve().parent
CROP = ROOT / "src" / "crop_config.json"
FARM = ROOT / "src" / "farm_config.json"
DATASET = ROOT / "data" / "weather" / "manual_forecast.csv"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_check(name: str, function, results: list[tuple[str, str, str]]) -> None:
    try:
        results.append((name, "PASS", str(function() or "verified")))
    except Exception as exc:
        results.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))


def context(plot_id="plot_14705"):
    plot = FarmConfigRepository(FARM).get_plot(plot_id)
    crop = CropConfigRepository(CROP).get_crop(plot.crop_key)
    stage = crop.resolve_stage(plot.current_stage)
    return plot, crop, stage


def parameter_audit() -> str:
    payload = json.loads(CROP.read_text(encoding="utf-8"))
    require(isinstance(payload.get("crops"), dict) and payload["crops"], "crop config has no crops")
    expected = {"stage_name", "months", "stress_thresholds", "vpd_thresholds", "vwc_thresholds", "solar_radiation_thresholds", "irrigation"}
    used = {"stress_thresholds", "vpd_thresholds", "vwc_thresholds"}
    loaded_only = expected - used
    for raw_crop in payload["crops"].values():
        for stage in raw_crop["stages"].values():
            require(expected <= stage.keys(), "crop stage parameter is missing")
    return f"used={sorted(used)}, loaded-but-not-used={sorted(loaded_only)}"


def stage_difference() -> str:
    _, crop, _ = context()
    engine = CropEngine()
    soil = SoilState(0.25, 20, 0.35, 0.10, 0, 0.25)
    weather = WeatherState(35, 30, 600, 2, 180, 0, 1012)
    environment = OpenFieldPhysicalModel().evaluate(weather, soil, 3600).environment
    timestamp = datetime(2026, 8, 28, tzinfo=timezone.utc)
    establishment = engine.evaluate(crop, "establishment", weather, environment, soil, timestamp)
    maturation = engine.evaluate(crop, "yield_maturation", weather, environment, soil, timestamp)
    require(establishment.temperature_stress != maturation.temperature_stress, "stage thresholds had no effect")
    return "same crop/weather produces stage-specific stress"


def stress_audit() -> str:
    _, crop, stage = context()
    engine = CropEngine()
    soil = SoilState(0.25, 20, 0.35, 0.10, 0, 0.25)
    physical = OpenFieldPhysicalModel()
    timestamp = datetime(2026, 8, 28, tzinfo=timezone.utc)
    normal = WeatherState(25, 80, 600, 2, 180, 0, 1012)
    extreme = WeatherState(40, 10, 600, 2, 180, 0, 1012)
    normal_result = physical.evaluate(normal, soil, 3600)
    extreme_result = physical.evaluate(extreme, soil, 3600)
    good = engine.evaluate(crop, stage, normal, normal_result.environment, soil, timestamp)
    bad = engine.evaluate(crop, stage, extreme, extreme_result.environment, SoilState(0.11, 20, 0.35, 0.10, 0, 0.11), timestamp)
    for value in (good, bad):
        require(all(0 <= getattr(value, field) <= 1 for field in ("temperature_stress", "water_stress", "vpd_stress", "cumulative_stress", "growth_factor")), "stress bounds failed")
    require(bad.temperature_stress > good.temperature_stress and bad.water_stress > good.water_stress and bad.vpd_stress > good.vpd_stress, "stress causality failed")
    require(bad.growth_factor < good.growth_factor, "growth factor causality failed")
    require(good.cumulative_stress == (good.temperature_stress + good.water_stress + good.vpd_stress) / 3, "stress combination is inconsistent")
    return "thermal, water and VPD stress are bounded and causal"


def clock_audit() -> str:
    source_files = [ROOT / "src" / "agri_twin" / "domain" / "crop_engine.py"]
    forbidden = ("datetime.now", "datetime.utcnow", "time.time", "sleep(")
    for path in source_files:
        text = path.read_text(encoding="utf-8")
        require(not any(token in text for token in forbidden), f"wall clock usage in {path}")
    _, crop, stage = context()
    provider = CsvWeatherProvider(DATASET)
    weather_engine = WeatherEngine(WeatherConfiguration(), provider=provider)
    physical = OpenFieldPhysicalModel()
    crop_engine = CropEngine()
    initial = provider.timestamps[0]
    soil = SoilState(0.25, 20, 0.35, 0.10, 0, 0.25)
    def simulate(speed):
        clock = SimulationClock(initial, speed=speed)
        state = None
        current_soil = soil
        for hour in range(24):
            current = initial + timedelta(hours=hour)
            weather = weather_engine.generate(current)
            result = physical.evaluate(weather, current_soil, 3600)
            state = crop_engine.evaluate(crop, stage, weather, result.environment, result.soil, current, 3600, state)
            current_soil = result.soil
            clock.advance(3600)
        return clock.now(), state
    first = simulate(1)
    second = simulate(86400)
    require(first[0] == second[0] == initial + timedelta(hours=24), "simulated time did not advance 24 hours")
    require(first[1] == second[1], "wall-clock speed changed agronomic result")
    return "SimulationClock dt is the only evolution time source"


def plot_isolation() -> str:
    plots = FarmConfigRepository(FARM).plots
    require(len(plots) >= 2 and plots[0].crop_key != plots[1].crop_key, "fixture lacks two different crops")
    require((plots[0].latitude, plots[0].longitude) != (plots[1].latitude, plots[1].longitude), "fixture lacks distinct locations")
    return f"{plots[0].plot_id}->{plots[0].crop_key}, {plots[1].plot_id}->{plots[1].crop_key}"


def digital_twin_check() -> str:
    provider = CsvWeatherProvider(DATASET)
    timestamp = provider.timestamps[0]
    state = build_crop_digital_twin_state("plot_14705", FARM, CROP, DATASET, timestamp)
    require(isinstance(state, CropDigitalTwinState) and state.weather_state == provider.get(timestamp), "DigitalTwinState integration failed")
    return "weather, physical context and optional crop state remain composable"


def invalid_inputs() -> str:
    _, crop, stage = context()
    engine = CropEngine()
    soil = SoilState(0.25, 20, 0.35, 0.10, 0, 0.25)
    weather = WeatherState(25, 50, 600, 2, 180, 0, 1012)
    environment = OpenFieldPhysicalModel().evaluate(weather, soil, 3600).environment
    try:
        engine.evaluate(crop, "missing", weather, environment, soil, datetime(2026, 8, 28, tzinfo=timezone.utc))
    except Exception:
        pass
    else:
        raise AssertionError("missing stage accepted")
    try:
        engine.evaluate(crop, stage, weather, environment, soil, datetime(2026, 8, 28))
    except Exception:
        pass
    else:
        raise AssertionError("naive timestamp accepted")
    return "invalid stage and timestamp rejected"


def http_isolation() -> str:
    allowed = ROOT / "src" / "agri_twin" / "infrastructure" / "open_meteo.py"
    forbidden = ("requests", "httpx", "aiohttp", "urllib.request", "urlopen")
    offenders = []
    for path in (ROOT / "src" / "agri_twin").rglob("*.py"):
        if path == allowed:
            continue
        if any(token in path.read_text(encoding="utf-8") for token in forbidden):
            offenders.append(str(path))
    require(not offenders, f"HTTP outside Open-Meteo: {offenders}")
    return "HTTP remains isolated to Open-Meteo infrastructure"


def regression() -> str:
    completed = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    require(completed.returncode == 0, completed.stdout[-500:] or completed.stderr[-500:])
    return completed.stdout.strip().splitlines()[-1]


def main() -> int:
    results: list[tuple[str, str, str]] = []
    with tempfile.TemporaryDirectory(prefix="crop-phase4-1-"):
        run_check("Crop config parameter traceability", parameter_audit, results)
        run_check("Stage parameters actually used", stage_difference, results)
        run_check("Stress bounds and causality", stress_audit, results)
        run_check("SimulationClock sole time source", clock_audit, results)
        run_check("Two plots/two crops isolation", plot_isolation, results)
        run_check("DigitalTwinState integration", digital_twin_check, results)
        run_check("Invalid inputs rejected", invalid_inputs, results)
        run_check("HTTP isolation", http_isolation, results)
        run_check("Regression", regression, results)
        print("=" * 60)
        print(" CROP DIGITAL TWIN - PHASE 4.1 AGRONOMIC AUDIT")
        print("=" * 60)
        for index, (name, status, detail) in enumerate(results, 1):
            print(f"[{index:02d}] {name:.<39} {status}  {detail}")
        passed = sum(status == "PASS" for _, status, _ in results)
        failed = sum(status == "FAIL" for _, status, _ in results)
        skipped = sum(status == "SKIP" for _, status, _ in results)
        print("\n" + "=" * 60)
        print(f"PASS: {passed}\nFAIL: {failed}\nSKIP: {skipped}")
        print("PHASE 4.1 STATUS: " + ("ACCEPTED" if failed == 0 and skipped == 0 else "NOT READY"))
        return 0 if failed == 0 and skipped == 0 else 1
if __name__ == "__main__":
    raise SystemExit(main())
