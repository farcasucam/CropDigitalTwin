"""Manual acceptance test for the Phase 3 physical-environment MVP."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from agri_twin.application import OpenFieldPhysicalModel, WeatherEngine
from agri_twin.application.providers import ScenarioWeatherProvider
from agri_twin.domain import SoilState, WeatherConfiguration, WeatherState
from agri_twin.infrastructure import CsvWeatherProvider

ROOT = Path(__file__).resolve().parent


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def weather(**changes: float) -> WeatherState:
    values = dict(
        temperature_c=25.0,
        relative_humidity_pct=50.0,
        solar_radiation_w_m2=600.0,
        wind_speed_m_s=2.0,
        wind_direction_deg=180.0,
        rain_rate_mm_h=0.0,
        pressure_hpa=1012.0,
    )
    values.update(changes)
    return WeatherState(**values)


def soil() -> SoilState:
    return SoilState(0.25, 20.0, 0.35, 0.10, 0.0, 0.25)


def run_check(name: str, function, results: list[tuple[str, str, str]]) -> None:
    try:
        results.append((name, "PASS", str(function() or "verified")))
    except Exception as exc:
        results.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))


def physics_check() -> str:
    result = OpenFieldPhysicalModel().evaluate(weather(), soil(), 3600)
    require(result.environment.vpd_kpa > 0, "VPD was not derived")
    require(result.environment.vapor_pressure < result.environment.saturation_vapor_pressure, "vapour pressures invalid")
    require(0.10 <= result.soil.vwc_m3_m3 <= 0.35, "VWC invariant failed")
    return f"VPD={result.environment.vpd_kpa:.3f} kPa, VWC={result.soil.vwc_m3_m3:.3f}"


def causal_water_check() -> str:
    model = OpenFieldPhysicalModel()
    baseline = model.evaluate(weather(), soil(), 3600)
    wet = model.evaluate(weather(rain_rate_mm_h=20), soil(), 3600, irrigation_mm=10)
    require(wet.soil.vwc_m3_m3 > baseline.soil.vwc_m3_m3, "rain/irrigation did not increase VWC")
    return "rain and irrigation affect soil state through balance"


def reproducibility_check() -> str:
    model = OpenFieldPhysicalModel()
    require(model.evaluate(weather(), soil(), 3600) == model.evaluate(weather(), soil(), 3600), "physical result is not reproducible")
    return "same weather, soil and timestep produce equal results"


def offline_chain_check() -> str:
    csv_path = ROOT / "data" / "weather" / "manual_forecast.csv"
    provider = CsvWeatherProvider(csv_path)
    engine = WeatherEngine(WeatherConfiguration(), provider=provider)
    timestamp = provider.timestamps[0]
    state = engine.generate(timestamp)
    physical = OpenFieldPhysicalModel().evaluate(state, soil(), 3600)
    require(isinstance(state, WeatherState) and physical.environment.vpd_kpa >= 0, "offline chain failed")
    scenario = ScenarioWeatherProvider(provider)
    require(scenario.get(timestamp) == state, "scenario changed unperturbed state")
    return "CSV -> provider -> WeatherEngine -> physical model, offline"


def isolation_check() -> str:
    allowed = ROOT / "src" / "agri_twin" / "infrastructure" / "open_meteo.py"
    forbidden = ("requests", "httpx", "aiohttp", "urllib.request", "http.client", "urlopen")
    offenders = []
    for path in (ROOT / "src" / "agri_twin").rglob("*.py"):
        if path == allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        text = path.read_text(encoding="utf-8")
        if any(item in text for item in forbidden):
            offenders.append(str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)) and any(item in ast.unparse(node) for item in forbidden):
                offenders.append(str(path))
    require(not offenders, f"HTTP references outside Open-Meteo: {offenders}")
    return "physical model contains no HTTP dependency"


def regression_check() -> str:
    completed = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    require(completed.returncode == 0, completed.stdout[-500:] or completed.stderr[-500:])
    return completed.stdout.strip().splitlines()[-1]


def main() -> int:
    results: list[tuple[str, str, str]] = []
    run_check("Physical environment derivation", physics_check, results)
    run_check("Causal soil-water balance", causal_water_check, results)
    run_check("Reproducibility", reproducibility_check, results)
    run_check("Offline Weather -> Physics chain", offline_chain_check, results)
    run_check("HTTP isolation", isolation_check, results)
    run_check("Regression suite", regression_check, results)
    print("=" * 60)
    print(" CROP DIGITAL TWIN - PHASE 3 MANUAL AUDIT")
    print("=" * 60)
    for index, (name, status, detail) in enumerate(results, 1):
        print(f"[{index:02d}] {name:.<39} {status}  {detail}")
    passed = sum(status == "PASS" for _, status, _ in results)
    failed = sum(status == "FAIL" for _, status, _ in results)
    skipped = sum(status == "SKIP" for _, status, _ in results)
    print("\n" + "=" * 60)
    print(f"PASS: {passed}\nFAIL: {failed}\nSKIP: {skipped}")
    print("PHASE 3 STATUS: " + ("ACCEPTED" if failed == 0 and skipped == 0 else "NOT READY"))
    return 0 if failed == 0 and skipped == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
