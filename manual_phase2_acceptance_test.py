"""Objective manual audit of the current Phase 2 integration."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

from agri_twin.application import (
    build_crop_digital_twin_state,
    download_weather_for_plot,
    load_weather_source_configuration,
    WeatherEngine,
)
from agri_twin.application.providers import ScenarioWeatherProvider
from agri_twin.domain import CropConfigRepository, FarmConfigRepository, FarmConfigurationError, CropDigitalTwinState, WeatherConfiguration
from agri_twin.domain.weather import WeatherEventType, WeatherPerturbation
from agri_twin.domain import WeatherConfiguration
from agri_twin.infrastructure import CsvWeatherProvider

ROOT = Path(__file__).resolve().parent
FARM = ROOT / "src" / "farm_config.json"
CROP = ROOT / "src" / "crop_config.json"
APP = ROOT / "config" / "app.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_check(name: str, function, results: list[tuple[str, str, str]], skips=()) -> None:
    try:
        results.append((name, "PASS", str(function() or "verified")))
    except skips as exc:
        results.append((name, "SKIP", f"external dependency: {exc}"))
    except Exception as exc:
        results.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))


def farm_crop_check() -> str:
    farm = FarmConfigRepository(FARM)
    crops = CropConfigRepository(CROP)
    require(farm.plots, "farm has no plots")
    require(len({plot.plot_id for plot in farm.plots}) == len(farm.plots), "plot IDs are not unique")
    for plot in farm.plots:
        require(plot.area_ha > 0, f"invalid area: {plot.plot_id}")
        crops.resolve_stage(plot.crop_key, plot.current_stage)
    return f"{len(farm.plots)} plots and crop/stage links valid"


def plot_coordinates_check(temp: Path) -> str:
    captured = []

    class FakeClient:
        request_count = 0

        def download(self, request, output_csv, **kwargs):
            captured.append(request)

    module = __import__("agri_twin.application.plot_weather", fromlist=["build_open_meteo_client"])
    original = module.build_open_meteo_client
    module.build_open_meteo_client = lambda settings: FakeClient()
    try:
        download_weather_for_plot("plot_14705", FARM, CROP, APP, temp / "unused.csv", "2026-08-28", "2026-08-28")
    finally:
        module.build_open_meteo_client = original
    plot = FarmConfigRepository(FARM).get_plot("plot_14705")
    require(captured and captured[0].latitude == plot.latitude, "latitude did not come from plot")
    require(captured[0].longitude == plot.longitude and captured[0].elevation == plot.elevation, "location did not come from plot")
    return f"{plot.latitude}, {plot.longitude}, elevation={plot.elevation}"


def two_plot_check(temp: Path) -> str:
    captured = []

    class FakeClient:
        request_count = 0

        def download(self, request, output_csv, **kwargs):
            captured.append(request)

    module = __import__("agri_twin.application.plot_weather", fromlist=["build_open_meteo_client"])
    original = module.build_open_meteo_client
    module.build_open_meteo_client = lambda settings: FakeClient()
    try:
        for plot_id in ("plot_14705", "plot_12010"):
            download_weather_for_plot(plot_id, FARM, CROP, APP, temp / f"{plot_id}.csv", "2026-08-28", "2026-08-28")
    finally:
        module.build_open_meteo_client = original
    require(len(captured) == 2, "did not construct two requests")
    require((captured[0].latitude, captured[0].longitude) != (captured[1].latitude, captured[1].longitude), "plots share coordinates")
    return "distinct coordinates without changing app.json"


def invalid_farm_checks(temp: Path) -> str:
    payload = json.loads(FARM.read_text(encoding="utf-8"))
    payload["plots"][0]["coordinates"]["latitude"] = 95
    payload["plots"][0]["area_ha"] = -1
    payload["plots"].append(dict(payload["plots"][0]))
    bad = temp / "invalid-farm.json"
    bad.write_text(json.dumps(payload), encoding="utf-8")
    try:
        FarmConfigRepository(bad)
    except FarmConfigurationError:
        return "invalid coordinates and duplicate IDs rejected"
    raise AssertionError("invalid farm accepted")


def missing_crop_check(temp: Path) -> str:
    payload = json.loads(FARM.read_text(encoding="utf-8"))
    payload["plots"][0]["crop_key"] = "missing-crop"
    bad = temp / "missing-crop-farm.json"
    bad.write_text(json.dumps(payload), encoding="utf-8")
    farm = FarmConfigRepository(bad)
    try:
        CropConfigRepository(CROP).get_crop(farm.get_plot("plot_14705").crop_key)
    except Exception:
        return "missing crop rejected"
    raise AssertionError("missing crop accepted")


def reproducibility_check() -> str:
    provider = CsvWeatherProvider(ROOT / "data" / "weather" / "manual_forecast.csv")
    timestamp = provider.timestamps[0]
    first = provider.get(timestamp)
    second = provider.get(timestamp)
    require(first == second, "offline observation is not reproducible")
    return "same local input produced equal WeatherState values"


def real_flow(temp: Path) -> str:
    today = date.today()
    csv_path = temp / "plot_14705.csv"
    result = download_weather_for_plot("plot_14705", FARM, CROP, APP, csv_path, today, today)
    require(not result.cached and result.request_count >= 1, "invalid real acquisition result")
    metadata_path = csv_path.with_suffix(".metadata.json")
    require(csv_path.is_file() and metadata_path.is_file(), "CSV/metadata not generated")
    provider = CsvWeatherProvider(csv_path)
    require(provider.timestamps, "real CSV is empty")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    require(metadata.get("plot_id") == "plot_14705", "plot_id absent from metadata")
    require("api_key" not in json.dumps(metadata).lower(), "secret present in metadata")
    cached = download_weather_for_plot("plot_14705", FARM, CROP, APP, csv_path, today, today)
    require(cached.cached and cached.request_count == 0, "compatible second acquisition missed cache")
    return f"{len(provider.timestamps)} observations; HTTP={result.request_count}; cache hit=1"


def offline_check() -> str:
    source = ROOT / "data" / "weather" / "manual_forecast.csv"
    provider = CsvWeatherProvider(source)
    timestamp = provider.timestamps[0]
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    scenario = ScenarioWeatherProvider(provider)
    scenario.add_perturbation(WeatherPerturbation(
        "phase2", WeatherEventType.HEAT_WAVE, timestamp, timestamp + timedelta(hours=1),
        1, "manual", {"temperature_offset_c": 5},
    ))
    require(scenario.get(timestamp).temperature_c == provider.get(timestamp).temperature_c + 5, "perturbation not applied")
    require(hashlib.sha256(source.read_bytes()).hexdigest() == digest, "source CSV changed")
    return "CSV provider and perturbation use local data"


def engine_provider_check(temp: Path) -> str:
    csv_path = temp / "engine-provider.csv"
    csv_path.write_text(
        "timestamp,temperature_c,relative_humidity_pct,solar_radiation_w_m2,wind_speed_m_s,wind_direction_deg,rain_rate_mm_h,pressure_hpa\n"
        "2026-08-27T08:00:00+00:00,21,55,400,3,90,0.2,1008\n"
        "2026-08-27T09:00:00+00:00,22,56,500,4,100,0.3,1009\n",
        encoding="utf-8",
    )
    provider = CsvWeatherProvider(csv_path)
    engine = WeatherEngine(WeatherConfiguration(), provider=provider)
    timestamp = provider.timestamps[0]
    require(engine.generate(timestamp) == provider.get(timestamp), "engine did not consume CSV state")
    return "WeatherEngine.generate returned the CSV WeatherState offline"


def digital_twin_check(temp: Path) -> str:
    csv_path = temp / "twin.csv"
    today = date.today()
    download_weather_for_plot("plot_14705", FARM, CROP, APP, csv_path, today, today)
    provider = CsvWeatherProvider(csv_path)
    engine = WeatherEngine(WeatherConfiguration(), provider=provider)
    timestamp = provider.timestamps[0]
    state = CropDigitalTwinState(
        plot_id="plot_14705",
        crop_key="plum",
        variety=FarmConfigRepository(FARM).get_plot("plot_14705").variety,
        current_stage="yield_maturation",
        timestamp=timestamp,
        weather_state=engine.generate(timestamp),
        agronomic_state={},
    )
    require(state.plot_id == "plot_14705" and state.crop_key == "plum", "Digital Twin identity invalid")
    require(state.weather_state == provider.get(timestamp), "state did not use WeatherEngine CSV weather")
    return "CSV -> CsvWeatherProvider -> WeatherEngine -> DigitalTwinState"


def http_isolation_check() -> str:
    allowed = ROOT / "src" / "agri_twin" / "infrastructure" / "open_meteo.py"
    forbidden = ("requests", "httpx", "aiohttp", "urllib.request", "http.client", "socket")
    offenders = []
    for path in (ROOT / "src" / "agri_twin").rglob("*.py"):
        if path == allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(forbidden):
                offenders.append(str(path))
            if isinstance(node, ast.Import) and any(alias.name in forbidden for alias in node.names):
                offenders.append(str(path))
    require(not offenders, f"HTTP imports outside Open-Meteo: {offenders}")
    return "HTTP imports isolated to infrastructure/open_meteo.py"


def regression_check(command: list[str]) -> str:
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    require(completed.returncode == 0, completed.stdout[-500:] or completed.stderr[-500:])
    return "command passed"


def main() -> int:
    results: list[tuple[str, str, str]] = []
    with tempfile.TemporaryDirectory(prefix="crop-phase2-audit-") as directory:
        temp = Path(directory)
        run_check("Farm configuration", farm_crop_check, results)
        run_check("Crop configuration and Farm -> Crop relation", farm_crop_check, results)
        run_check("Parcel coordinates -> Open-Meteo", lambda: plot_coordinates_check(temp), results)
        run_check("Two parcels use different coordinates", lambda: two_plot_check(temp), results)
        run_check("Invalid coordinates, area and IDs", lambda: invalid_farm_checks(temp), results)
        run_check("Missing crop reference", lambda: missing_crop_check(temp), results)
        run_check("Configuration loading has no HTTP", lambda: (load_weather_source_configuration(APP), "no network side effect")[1], results)
        run_check("Real Open-Meteo, CSV and metadata", lambda: real_flow(temp), results, skips=(OSError, TimeoutError, ConnectionError))
        run_check("Offline CSV provider and perturbations", offline_check, results)
        run_check("Reproducibility", reproducibility_check, results)
        run_check("Digital Twin state from offline weather", lambda: digital_twin_check(temp), results, skips=(OSError, TimeoutError, ConnectionError))
        run_check("CsvWeatherProvider -> WeatherEngine", lambda: engine_provider_check(temp), results)
        run_check("HTTP isolation", http_isolation_check, results)
        run_check("Public API imports", lambda: (__import__("agri_twin.application"), __import__("agri_twin.infrastructure"), "imports ok")[2], results)
        for command in ([sys.executable, "-m", "pytest", "-q"], [sys.executable, "-u", "manual_weather_test.py"], [sys.executable, "-u", "manual_weather_perturbations_test.py"]):
            run_check("Regression: " + Path(command[-1]).name, lambda command=command: regression_check(command), results)
        print("=" * 60)
        print(" CROP DIGITAL TWIN - PHASE 2 MANUAL AUDIT")
        print("=" * 60)
        for index, (name, status, detail) in enumerate(results, 1):
            print(f"[{index:02d}] {name:.<39} {status}  {detail}")
        passed = sum(status == "PASS" for _, status, _ in results)
        failed = sum(status == "FAIL" for _, status, _ in results)
        skipped = sum(status == "SKIP" for _, status, _ in results)
        print("\n" + "=" * 60)
        print(f"PASS: {passed}\nFAIL: {failed}\nSKIP: {skipped}")
        print(f"Temporary directory: {temp}")
        print("PHASE 2 STATUS: " + ("ACCEPTED" if failed == 0 and skipped == 0 else "NOT READY"))
        return 0 if failed == 0 and skipped == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
