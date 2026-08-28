import json
from datetime import datetime, timedelta

import pytest

from agri_twin.application import (
    OpenMeteoSourceConfiguration,
    build_open_meteo_client,
    build_open_meteo_request,
    WeatherConfigurationError,
    WeatherSourceConfiguration,
    create_offline_weather_provider,
    load_weather_source_configuration,
    WeatherDatasetResult,
    download_weather_dataset_from_config,
)


def test_default_source_is_synthetic() -> None:
    configuration = WeatherSourceConfiguration()
    assert configuration.provider == "synthetic"


def test_csv_source_requires_dataset_and_loads_offline(tmp_path) -> None:
    with pytest.raises(WeatherConfigurationError):
        WeatherSourceConfiguration(provider="csv")
    dataset = tmp_path / "weather.csv"
    dataset.write_text(
        "timestamp,temperature_c,relative_humidity_pct,solar_radiation_w_m2,wind_speed_m_s,wind_direction_deg,rain_rate_mm_h,pressure_hpa\n"
        "2026-08-27T12:00:00+00:00,25,50,820,2.5,180,0,1012\n",
        encoding="utf-8",
    )
    provider = create_offline_weather_provider(
        WeatherSourceConfiguration(provider="csv", dataset_path=str(dataset))
    )
    assert provider.get(datetime.fromisoformat("2026-08-27T12:00:00+00:00")).temperature_c == 25


def test_configuration_loader_preserves_backward_compatible_default(tmp_path) -> None:
    path = tmp_path / "app.json"
    path.write_text(json.dumps({"schema_version": "1.0"}), encoding="utf-8")
    assert load_weather_source_configuration(path).provider == "synthetic"


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(WeatherConfigurationError):
        WeatherSourceConfiguration(provider="open_meteo")


def test_open_meteo_configuration_builds_without_downloading(tmp_path) -> None:
    path = tmp_path / "app.json"
    path.write_text(json.dumps({
        "weather": {"provider": "open_meteo"},
        "open_meteo": {
            "enabled": True,
            "api": "forecast",
            "location": {"latitude": 40, "longitude": -3},
            "authentication": {"mode": "public", "api_key_env": "OPEN_METEO_API_KEY"},
            "units": {"temperature": "celsius", "wind_speed": "ms", "precipitation": "mm"},
        },
    }), encoding="utf-8")
    configuration = load_weather_source_configuration(path)
    client = build_open_meteo_client(configuration.open_meteo)
    request = build_open_meteo_request(
        configuration.open_meteo, __import__("datetime").date(2026, 8, 27), __import__("datetime").date(2026, 8, 27)
    )

    assert configuration.provider == "open_meteo"
    assert client is not None
    assert request.latitude == 40


def test_open_meteo_configuration_rejects_duplicate_variables() -> None:
    with pytest.raises(WeatherConfigurationError):
        OpenMeteoSourceConfiguration(variables=("temperature_2m", "temperature_2m"))


def test_download_from_config_orchestrates_client_and_reports_result(tmp_path, monkeypatch):
    config_path = tmp_path / "app.json"
    output = tmp_path / "forecast.csv"
    config_path.write_text(json.dumps({
        "weather": {"provider": "open_meteo"},
        "open_meteo": {"enabled": True, "api": "forecast", "cache": {"enabled": False}},
    }), encoding="utf-8")

    class FakeClient:
        request_count = 2

        def download(self, request, output_csv, metadata_path, use_cache, force_refresh):
            output_csv.write_text("csv", encoding="utf-8")
            metadata_path.write_text(json.dumps({"request_count": 99}), encoding="utf-8")

    monkeypatch.setattr(
        "agri_twin.application.weather_configuration.build_open_meteo_client",
        lambda settings: FakeClient(),
    )
    result = download_weather_dataset_from_config(
        config_path, output, "2026-08-27", "2026-08-28"
    )

    assert isinstance(result, WeatherDatasetResult)
    assert result.csv_path == output
    assert result.metadata_path.exists()
    assert result.request_count == 2
    assert result.cached is False


def test_download_result_counts_current_http_requests_across_cache_and_refresh(tmp_path, monkeypatch):
    config_path = tmp_path / "app.json"
    output = tmp_path / "forecast.csv"
    config = {
        "weather": {"provider": "open_meteo"},
        "open_meteo": {
            "enabled": True,
            "api": "historical",
            "endpoint": "https://archive-api.open-meteo.com/v1/archive",
            "cache": {"enabled": True},
            "acquisition": {"chunk_days": 1},
        },
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")

    class ChunkTransport:
        def __init__(self):
            self.call_count = 0

        def get(self, url, params):
            self.call_count += 1
            start = datetime.fromisoformat(params["start_date"])
            end = datetime.fromisoformat(params["end_date"])
            times = []
            current = start
            while current <= end + timedelta(hours=23):
                times.append(current.strftime("%Y-%m-%dT%H:%M"))
                current += timedelta(hours=1)
            values = {
                "time": times,
                "temperature_2m": [20] * len(times),
                "relative_humidity_2m": [50] * len(times),
                "shortwave_radiation": [100] * len(times),
                "wind_speed_10m": [2] * len(times),
                "wind_direction_10m": [180] * len(times),
                "rain": [0] * len(times),
                "surface_pressure": [1012] * len(times),
            }
            return json.dumps({"model": "gfs", "hourly": values}).encode()

    from agri_twin.infrastructure import OpenMeteoClient

    transport = ChunkTransport()
    monkeypatch.setattr(
        "agri_twin.application.weather_configuration.build_open_meteo_client",
        lambda settings: OpenMeteoClient(transport=transport),
    )

    first = download_weather_dataset_from_config(
        config_path, output, "2026-08-27", "2026-08-28"
    )
    assert first.cached is False
    assert first.request_count == 2
    assert transport.call_count == 2

    second = download_weather_dataset_from_config(
        config_path, output, "2026-08-27", "2026-08-28"
    )
    assert second.cached is True
    assert second.request_count == 0
    assert transport.call_count == 2

    config["open_meteo"]["cache"]["force_refresh"] = True
    config_path.write_text(json.dumps(config), encoding="utf-8")
    refreshed = download_weather_dataset_from_config(
        config_path, output, "2026-08-27", "2026-08-28"
    )
    assert refreshed.cached is False
    assert refreshed.request_count == 2
    assert transport.call_count == 4


def test_download_from_config_rejects_non_open_meteo_provider(tmp_path):
    path = tmp_path / "app.json"
    path.write_text(json.dumps({"weather": {"provider": "csv", "dataset": {"path": "x"}}}), encoding="utf-8")

    with pytest.raises(WeatherConfigurationError, match="open_meteo"):
        download_weather_dataset_from_config(path, tmp_path / "weather.csv", "2026-08-27", "2026-08-27")
