import json
from datetime import datetime

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
        def download(self, request, output_csv, metadata_path, use_cache, force_refresh):
            output_csv.write_text("csv", encoding="utf-8")
            metadata_path.write_text(json.dumps({"request_count": 2}), encoding="utf-8")

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


def test_download_from_config_rejects_non_open_meteo_provider(tmp_path):
    path = tmp_path / "app.json"
    path.write_text(json.dumps({"weather": {"provider": "csv", "dataset": {"path": "x"}}}), encoding="utf-8")

    with pytest.raises(WeatherConfigurationError, match="open_meteo"):
        download_weather_dataset_from_config(path, tmp_path / "weather.csv", "2026-08-27", "2026-08-27")
