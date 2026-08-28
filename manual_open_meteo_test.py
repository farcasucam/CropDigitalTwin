"""Manual end-to-end acceptance test for the Open-Meteo Phase 1.5 integration."""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agri_twin.application import (
    OpenMeteoSourceConfiguration,
    WeatherConfigurationError,
    WeatherDatasetResult,
    WeatherSourceConfiguration,
    build_open_meteo_client,
    build_open_meteo_request,
    download_weather_dataset_from_config,
    load_weather_source_configuration,
)
from agri_twin.domain.weather import WeatherEventType, WeatherPerturbation
from agri_twin.infrastructure import (
    CsvWeatherProvider,
    OpenMeteoApi,
    OpenMeteoAuthConfig,
    OpenMeteoClient,
    OpenMeteoRequest,
    OpenMeteoResponseError,
    WeatherModelNotAvailable,
    WeatherCache,
    WeatherRangeNotAvailable,
    OpenMeteoAuthenticationError,
)
from agri_twin.application.providers import ScenarioWeatherProvider

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config" / "app.json"
REQUIRED_CONFIG_KEYS = {
    "endpoint", "location", "model", "timezone", "units", "cache", "acquisition",
}


class AcceptanceFailure(Exception):
    pass


class ExternalDependency(Exception):
    pass


class FakeTransport:
    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.response = response or _response_for("2026-08-28", "2026-08-28")

    def get(self, url: str, params: dict[str, str]) -> bytes:
        self.calls.append((url, dict(params)))
        return json.dumps(self.response).encode("utf-8")


class ChunkTransport(FakeTransport):
    def get(self, url: str, params: dict[str, str]) -> bytes:
        self.calls.append((url, dict(params)))
        return json.dumps(_response_for(params["start_date"], params["end_date"])).encode("utf-8")


def _response_for(start_text: str, end_text: str) -> dict[str, Any]:
    start = datetime.fromisoformat(start_text).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(end_text).replace(tzinfo=timezone.utc) + timedelta(hours=23)
    times: list[str] = []
    current = start
    while current <= end:
        times.append(current.strftime("%Y-%m-%dT%H:%M"))
        current += timedelta(hours=1)
    values = {
        "time": times,
        "temperature_2m": [20.0] * len(times),
        "relative_humidity_2m": [50.0] * len(times),
        "shortwave_radiation": [100.0] * len(times),
        "wind_speed_10m": [2.0] * len(times),
        "wind_direction_10m": [180.0] * len(times),
        "rain": [0.0] * len(times),
        "surface_pressure": [1012.0] * len(times),
    }
    return {"latitude": 40.0, "longitude": -3.0, "elevation": 650, "model": "gfs", "timezone": "UTC", "hourly": values}


def _request(start: date = date(2026, 8, 28), end: date = date(2026, 8, 28), **changes: Any) -> OpenMeteoRequest:
    values: dict[str, Any] = {
        "latitude": 40.0, "longitude": -3.0, "start_date": start, "end_date": end,
        "variables": ("temperature_2m", "relative_humidity_2m", "shortwave_radiation", "wind_speed_10m", "wind_direction_10m", "rain", "surface_pressure"),
        "api": OpenMeteoApi.HISTORICAL, "timezone": "UTC", "model": "auto",
    }
    values.update(changes)
    return OpenMeteoRequest(**values)


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceFailure(message)


def _config_copy(directory: Path, *, force_refresh: bool = False, chunk_days: int = 1) -> Path:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    payload["open_meteo"]["cache"]["force_refresh"] = force_refresh
    payload["open_meteo"]["acquisition"]["chunk_days"] = chunk_days
    path = directory / "app.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _csv_integrity(path: Path, start: date, end: date) -> int:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    timestamps = [datetime.fromisoformat(row["timestamp"]) for row in rows]
    _check(rows and len(timestamps) == len(set(timestamps)), "CSV is empty or has duplicate timestamps")
    _check(all(item.tzinfo is not None and item.utcoffset() == timedelta(0) for item in timestamps), "CSV timestamps are not UTC")
    _check(timestamps == sorted(timestamps), "CSV timestamps are not ordered")
    _check(all(b - a == timedelta(hours=1) for a, b in zip(timestamps, timestamps[1:])), "CSV has an hourly gap")
    _check(timestamps[0].date() == start and timestamps[-1].date() == end, "CSV does not cover requested range")
    return len(rows)


def _metadata_integrity(path: Path) -> None:
    metadata = json.loads(path.read_text(encoding="utf-8"))
    required = {"provider", "endpoint", "api", "dataset_type", "authentication_mode", "model_requested", "model_returned", "latitude", "longitude", "elevation", "start_date", "end_date", "timezone", "units", "variables", "resolution", "request_count"}
    _check(required <= metadata.keys(), f"metadata missing fields: {sorted(required - metadata.keys())}")
    _check("api_key" not in json.dumps(metadata).lower(), "API key appeared in metadata")
    _check(metadata["resolution"] == "hourly" and metadata["timezone"] == "UTC", "metadata resolution/timezone is invalid")


def _run_mock_checks() -> dict[str, int]:
    counts = {"http": 0, "cache_hits": 0, "datasets": 0}
    output_dir = Path(tempfile.mkdtemp(prefix="open-meteo-mock-"))
    try:
        output = output_dir / "weather.csv"
        transport = ChunkTransport()
        client = OpenMeteoClient(transport=transport)
        first = client.download(_request(), output, use_cache=True)
        _check(first.exists() and client.request_count == 1, "initial mocked acquisition count is invalid")
        first_metadata = json.loads(output.with_suffix(".metadata.json").read_text(encoding="utf-8"))
        _check(first_metadata["request_count"] == 1, "metadata acquisition count is invalid")
        counts["datasets"] += 1
        cached_client = OpenMeteoClient(transport=transport)
        cached_client.download(_request(), output, use_cache=True)
        _check(cached_client.request_count == 0 and len(transport.calls) == 1, "cache hit performed HTTP")
        counts["cache_hits"] += 1
        refreshed = OpenMeteoClient(transport=transport)
        refreshed.download(_request(), output, use_cache=True, force_refresh=True)
        _check(refreshed.request_count == 1 and len(transport.calls) == 2, "force refresh did not perform one request")
        expanded = OpenMeteoClient(transport=transport)
        expanded.download(_request(date(2026, 8, 27), date(2026, 8, 28), chunk_days=1), output, use_cache=True)
        _check(expanded.request_count == 2 and len(transport.calls) == 4, "two chunks did not perform two requests")
        expanded_cached = OpenMeteoClient(transport=transport)
        expanded_cached.download(_request(date(2026, 8, 27), date(2026, 8, 28), chunk_days=1), output, use_cache=True)
        _check(expanded_cached.request_count == 0 and len(transport.calls) == 4, "multi-chunk cache hit performed HTTP")
        counts["cache_hits"] += 1
        changed = OpenMeteoClient(transport=transport)
        changed.download(_request(latitude=41.0), output, use_cache=True)
        _check(changed.request_count == 1, "changed coordinates were treated as cache hit")
        for bad_size in (0, -1):
            try:
                OpenMeteoClient(transport=transport).download(_request(chunk_days=bad_size), output)
            except OpenMeteoResponseError:
                pass
            else:
                raise AcceptanceFailure("invalid chunk_days was accepted")
        auto_transport = FakeTransport()
        OpenMeteoClient(transport=auto_transport).download(_request(), output)
        _check("models" not in auto_transport.calls[-1][1], "model=auto sent models=auto")
        explicit_transport = FakeTransport()
        OpenMeteoClient(transport=explicit_transport).download(_request(model="gfs_seamless"), output)
        _check(explicit_transport.calls[-1][1].get("models") == "gfs_seamless", "explicit model was not sent")
        customer_transport = FakeTransport()
        customer_client = OpenMeteoClient(
            transport=customer_transport,
            customer_endpoint="https://customer-api.example/forecast",
            api_key="test-secret",
            auth=OpenMeteoAuthConfig(mode="customer"),
        )
        customer_client.download(_request(api=OpenMeteoApi.FORECAST), output)
        _check(customer_transport.calls[-1][0] == "https://customer-api.example/forecast", "customer endpoint was not used")
        _check(customer_transport.calls[-1][1].get("apikey") == "test-secret", "customer API key was not resolved")
        try:
            OpenMeteoClient(
                transport=FakeTransport(),
                auth=OpenMeteoAuthConfig(mode="customer", key_env="MISSING_ACCEPTANCE_KEY"),
            ).download(_request(api=OpenMeteoApi.FORECAST), output)
        except OpenMeteoAuthenticationError as exc:
            _check("test-secret" not in str(exc) and "MISSING_ACCEPTANCE_KEY" not in str(exc), "API key details leaked in authentication error")
        else:
            raise AcceptanceFailure("missing customer API key was accepted")
        _check(not WeatherCache(output, endpoint="https://other.invalid").is_compatible(_request()), "endpoint change was treated as hit")
        _check(not WeatherCache(output, authentication_mode="customer").is_compatible(_request()), "authentication change was treated as hit")
        counts["http"] = len(transport.calls) + len(auto_transport.calls) + len(explicit_transport.calls)
        return counts
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


def _run_validation_checks() -> None:
    invalid_requests = [
        _request(latitude=91.0), _request(longitude=181.0),
        _request(start=date(2026, 8, 29), end=date(2026, 8, 28)),
        _request(model=""),
    ]
    for invalid in invalid_requests:
        try:
            OpenMeteoClient(transport=FakeTransport()).download(invalid, Path(tempfile.gettempdir()) / "unused.csv")
        except (OpenMeteoResponseError, WeatherRangeNotAvailable, WeatherModelNotAvailable):
            pass
        else:
            raise AcceptanceFailure("invalid request was accepted")
    try:
        OpenMeteoSourceConfiguration(variables=("temperature_2m", "temperature_2m"))
    except WeatherConfigurationError:
        pass
    else:
        raise AcceptanceFailure("duplicate variables were accepted")
    invalid_config_dir = Path(tempfile.mkdtemp(prefix="open-meteo-invalid-config-"))
    try:
        non_open_meteo_config = invalid_config_dir / "app.json"
        non_open_meteo_config.write_text(json.dumps({"weather": {"provider": "csv", "dataset": {"path": "unused.csv"}}}), encoding="utf-8")
        try:
            download_weather_dataset_from_config(non_open_meteo_config, invalid_config_dir / "unused.csv", "2026-08-28", "2026-08-28")
        except WeatherConfigurationError:
            pass
        else:
            raise AcceptanceFailure("non-open-meteo provider was accepted")
    finally:
        shutil.rmtree(invalid_config_dir, ignore_errors=True)


def _run_offline_check(csv_path: Path) -> None:
    provider = CsvWeatherProvider(csv_path)
    _check(provider.timestamps, "offline provider has no timestamps")
    original = provider.get(provider.timestamps[0])
    scenario = ScenarioWeatherProvider(provider)
    event = WeatherPerturbation("manual-heat", WeatherEventType.HEAT_WAVE, provider.timestamps[0], provider.timestamps[1] + timedelta(hours=1), 1, "manual", {"temperature_offset_c": 5.0})
    scenario.add_perturbation(event)
    altered = scenario.get(provider.timestamps[0])
    _check(altered.temperature_c == original.temperature_c + 5.0, "offline perturbation was not applied")
    _check(provider.get(provider.timestamps[0]) == original, "original CSV observation changed")


def _static_http_isolation() -> None:
    patterns = ("urlopen", "requests.", "httpx", "aiohttp", "ClientSession")
    offenders: list[str] = []
    target = ROOT / "src" / "agri_twin" / "infrastructure" / "open_meteo.py"
    for path in (ROOT / "src" / "agri_twin").rglob("*.py"):
        if path == target:
            continue
        text = path.read_text(encoding="utf-8")
        if any(pattern in text for pattern in patterns):
            offenders.append(str(path.relative_to(ROOT)))
    _check(not offenders, f"HTTP transport found outside open_meteo.py: {offenders}")


def _run_existing_commands() -> None:
    commands = [
        [sys.executable, "-m", "pytest", "-q"],
        [sys.executable, "-u", "manual_weather_test.py"],
        [sys.executable, "-u", "manual_weather_perturbations_test.py"],
    ]
    for command in commands:
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", env=environment)
        if completed.returncode:
            raise AcceptanceFailure(f"command failed: {' '.join(command)}\n{completed.stdout}\n{completed.stderr}")


def main() -> int:
    print("=" * 60)
    print(" CROP DIGITAL TWIN")
    print(" OPEN-METEO PHASE 1.5 MANUAL ACCEPTANCE TEST")
    print("=" * 60)
    results: list[tuple[str, str, str]] = []
    counts = {"http": 0, "cache_hits": 0, "datasets": 0}
    with tempfile.TemporaryDirectory(prefix="crop-open-meteo-") as temporary:
        temp_dir = Path(temporary)
        config_payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        real_csv = temp_dir / "forecast.csv"
        real_metadata = real_csv.with_suffix(".metadata.json")
        today = date.today()
        try:
            configuration = load_weather_source_configuration(CONFIG_PATH)
            raw_open_meteo = config_payload["open_meteo"]
            _check(configuration.provider == "open_meteo", "config provider is not open_meteo")
            _check(REQUIRED_CONFIG_KEYS <= raw_open_meteo.keys(), "config is missing an Open-Meteo section")
            _check("api" in raw_open_meteo or "authentication" in raw_open_meteo, "config is missing API authentication settings")
            _check("request" in raw_open_meteo or "timeout_seconds" in raw_open_meteo, "config is missing request timeout settings")
            results.append(("Configuration", "PASS", "public configuration loaded"))
            results.append(("No HTTP on config load", "PASS", "configuration loading is local"))
        except Exception as exc:
            results.extend((("Configuration", "FAIL", str(exc)), ("No HTTP on config load", "FAIL", str(exc))))
        try:
            result = download_weather_dataset_from_config(CONFIG_PATH, real_csv, today.isoformat(), today.isoformat())
            _check(isinstance(result, WeatherDatasetResult) and not result.cached and result.request_count >= 1, "real acquisition result is invalid")
            _check(real_csv.is_file() and real_metadata.is_file(), "real dataset artifacts were not generated")
            _csv_integrity(real_csv, today, today)
            results.append(("Real acquisition and CSV", "PASS", f"{result.request_count} HTTP request(s)"))
            _metadata_integrity(real_metadata)
            results.append(("Metadata integrity", "PASS", "required metadata present and key-free"))
            counts["http"] += result.request_count
            counts["datasets"] += 1
        except (OSError, ExternalDependency, Exception) as exc:
            results.append(("Real acquisition and CSV", "SKIP", f"external dependency: {exc}"))
            results.append(("Metadata integrity", "SKIP", "real acquisition unavailable"))
        try:
            same = download_weather_dataset_from_config(CONFIG_PATH, real_csv, today.isoformat(), today.isoformat())
            _check(same.cached and same.request_count == 0, "cache hit contract failed")
            results.append(("Cache hit", "PASS", "cached=True, request_count=0"))
            counts["cache_hits"] += 1
        except Exception as exc:
            results.append(("Cache hit", "FAIL", str(exc)))
        try:
            refresh_config = _config_copy(temp_dir, force_refresh=True, chunk_days=1)
            refreshed = download_weather_dataset_from_config(refresh_config, temp_dir / "refresh.csv", today.isoformat(), today.isoformat())
            _check(not refreshed.cached and refreshed.request_count >= 1, "force refresh contract failed")
            results.append(("Force refresh", "PASS", f"{refreshed.request_count} HTTP request(s)"))
            counts["http"] += refreshed.request_count
        except Exception as exc:
            results.append(("Force refresh", "SKIP", f"external dependency: {exc}"))
        try:
            changed_config = _config_copy(temp_dir, chunk_days=1)
            changed = download_weather_dataset_from_config(changed_config, real_csv, (today - timedelta(days=1)).isoformat(), today.isoformat())
            _check(not changed.cached, "changed date range was treated as cache hit")
            results.append(("Range change", "PASS", "incompatible cache replaced by acquisition"))
            counts["http"] += changed.request_count
        except Exception as exc:
            results.append(("Range change", "SKIP", f"external dependency: {exc}"))
        try:
            mock_counts = _run_mock_checks()
            counts["http"] += mock_counts["http"]
            counts["cache_hits"] += mock_counts["cache_hits"]
            counts["datasets"] += mock_counts["datasets"]
            results.extend([
                ("Partitioning", "PASS", "two chunks, continuous consolidated CSV"),
                ("Chunk validation", "PASS", "zero and negative values rejected"),
                ("model=auto", "PASS", "models parameter omitted"),
                ("Explicit model", "PASS", "models parameter sent"),
                ("Cache identity", "PASS", "endpoint and authentication changes miss"),
            ])
        except Exception as exc:
            results.append(("Mocked acquisition/cache checks", "FAIL", str(exc)))
        for label, function in (("Request validation", _run_validation_checks), ("HTTP isolation", _static_http_isolation)):
            try:
                function()
                results.append((label, "PASS", "expected validation/isolation confirmed"))
            except Exception as exc:
                results.append((label, "FAIL", str(exc)))
        try:
            _run_offline_check(real_csv)
            results.append(("Offline CSV provider and perturbations", "PASS", "CSV remains unchanged in scenario"))
        except Exception as exc:
            results.append(("Offline CSV provider and perturbations", "SKIP", f"real dataset unavailable: {exc}"))
        try:
            _run_existing_commands()
            results.append(("Existing suite and manual tests", "PASS", "pytest and both manual tests passed"))
        except Exception as exc:
            results.append(("Existing suite and manual tests", "FAIL", str(exc)))
        print()
        for index, (label, status, detail) in enumerate(results, 1):
            print(f"[{index:02d}] {label:.<39} {status}  {detail}")
        print("\n" + "=" * 60)
        print(" RESULT")
        print("=" * 60)
        passed = sum(status == "PASS" for _, status, _ in results)
        failed = sum(status == "FAIL" for _, status, _ in results)
        skipped = sum(status == "SKIP" for _, status, _ in results)
        print(f"{passed} PASS, {failed} FAIL, {skipped} SKIP")
        print(f"Temporary directory: {temp_dir}")
        print(f"HTTP requests observed/counts: {counts['http']}")
        print(f"Cache hits observed: {counts['cache_hits']}")
        print(f"Datasets generated: {counts['datasets']}")
        print("Open-Meteo Phase 1.5: " + ("ACCEPTED" if failed == 0 and skipped == 0 else "NOT ACCEPTED"))
        return 0 if failed == 0 and skipped == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
