import json
from datetime import date, datetime, timezone

import pytest

from agri_twin.application import (
    WeatherConfigurationError,
    create_weather_provider_from_config,
)


def _config(path, provider):
    path.write_text(
        json.dumps({
            "weather": {"provider": provider},
            "open_meteo": {
                "enabled": True,
                "api": "forecast",
                "cache": {"enabled": False},
                "location": {"latitude": 40.0, "longitude": -3.0},
            },
        }),
        encoding="utf-8",
    )


def test_open_meteo_factory_downloads_then_returns_csv_provider(tmp_path, monkeypatch):
    config = tmp_path / "app.json"
    output = tmp_path / "forecast.csv"
    _config(config, "open_meteo")

    class FakeClient:
        request_count = 1

        def download(self, request, output_csv, metadata_path, use_cache, force_refresh):
            output_csv.write_text(
                "timestamp,temperature_c,relative_humidity_pct,solar_radiation_w_m2,wind_speed_m_s,wind_direction_deg,rain_rate_mm_h,pressure_hpa\n"
                "2026-08-27T00:00:00+00:00,20,50,0,2,180,0,1012\n",
                encoding="utf-8",
            )
            metadata_path.write_text(json.dumps({"request_count": 1}), encoding="utf-8")

    monkeypatch.setattr(
        "agri_twin.application.weather_configuration.build_open_meteo_client",
        lambda settings: FakeClient(),
    )

    provider = create_weather_provider_from_config(
        config,
        dataset_output_path=output,
        start_date=date(2026, 8, 27),
        end_date=date(2026, 8, 27),
    )
    assert provider.get(datetime(2026, 8, 27, tzinfo=timezone.utc)).temperature_c == 20


def test_open_meteo_factory_requires_output_path(tmp_path):
    config = tmp_path / "app.json"
    _config(config, "open_meteo")
    with pytest.raises(WeatherConfigurationError, match="dataset_output_path"):
        create_weather_provider_from_config(config, start_date="2026-08-27", end_date="2026-08-27")


def test_synthetic_factory_requires_existing_engine(tmp_path):
    config = tmp_path / "app.json"
    _config(config, "synthetic")
    with pytest.raises(WeatherConfigurationError, match="WeatherEngine"):
        create_weather_provider_from_config(config)
