import json
from datetime import date, datetime, timedelta, timezone

import pytest

from agri_twin.application import (
    build_crop_digital_twin_state,
    download_weather_for_plot,
    WeatherEngine,
)
from agri_twin.domain import (
    CropConfigRepository,
    CropConfigurationError,
    CropDigitalTwinState,
    FarmConfigRepository,
    FarmConfigurationError,
    WeatherConfiguration,
)
from agri_twin.infrastructure import OpenMeteoClient


FARM_PATH = "src/farm_config.json"
CROP_PATH = "src/crop_config.json"
VARIABLES = (
    "temperature_2m", "relative_humidity_2m", "shortwave_radiation",
    "wind_speed_10m", "wind_direction_10m", "rain", "surface_pressure",
)


def response(start, end):
    current = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    limit = datetime.fromisoformat(end).replace(tzinfo=timezone.utc) + timedelta(hours=23)
    times = []
    while current <= limit:
        times.append(current.strftime("%Y-%m-%dT%H:%M"))
        current += timedelta(hours=1)
    return json.dumps({"model": "gfs", "elevation": 650, "hourly": {
        "time": times, "temperature_2m": [20] * len(times),
        "relative_humidity_2m": [50] * len(times), "shortwave_radiation": [100] * len(times),
        "wind_speed_10m": [2] * len(times), "wind_direction_10m": [180] * len(times),
        "rain": [0] * len(times), "surface_pressure": [1012] * len(times),
    }}).encode()


class Transport:
    def __init__(self):
        self.calls = []

    def get(self, url, params):
        self.calls.append((url, dict(params)))
        return response(params["start_date"], params["end_date"])


def app_config(tmp_path):
    path = tmp_path / "app.json"
    path.write_text(json.dumps({
        "weather": {"provider": "open_meteo"},
        "open_meteo": {
            "enabled": True, "api": "historical",
            "endpoint": "https://archive-api.open-meteo.com/v1/archive",
            "cache": {"enabled": True}, "acquisition": {"chunk_days": 1},
        },
    }), encoding="utf-8")
    return path


def test_repositories_resolve_plot_crop_and_stage():
    plot = FarmConfigRepository(FARM_PATH).get_plot("plot_14705")
    crop = CropConfigRepository(CROP_PATH).get_crop(plot.crop_key)
    stage = crop.resolve_stage(plot.current_stage)

    assert plot.latitude == pytest.approx(38.25130770201682)
    assert plot.longitude == pytest.approx(-1.4368665045230333)
    assert crop.crop_key == "plum"
    assert stage.stage_key == "yield_maturation"
    assert "stress_thresholds" in stage.parameters


def test_repositories_reject_missing_plot_crop_and_stage():
    farm = FarmConfigRepository(FARM_PATH)
    crops = CropConfigRepository(CROP_PATH)
    with pytest.raises(FarmConfigurationError):
        farm.get_plot("missing")
    with pytest.raises(CropConfigurationError):
        crops.get_crop("missing")
    with pytest.raises(CropConfigurationError):
        crops.resolve_stage("plum", "missing")


def test_plot_weather_uses_plot_coordinates_and_cache_identity(tmp_path, monkeypatch):
    transport = Transport()
    monkeypatch.setattr(
        "agri_twin.application.plot_weather.build_open_meteo_client",
        lambda settings: OpenMeteoClient(transport=transport),
    )
    config = app_config(tmp_path)
    first = download_weather_for_plot("plot_14705", FARM_PATH, CROP_PATH, config, tmp_path / "a.csv", date(2026, 8, 28), date(2026, 8, 28))
    second = download_weather_for_plot("plot_14705", FARM_PATH, CROP_PATH, config, tmp_path / "a.csv", date(2026, 8, 28), date(2026, 8, 28))
    other = download_weather_for_plot("plot_12010", FARM_PATH, CROP_PATH, config, tmp_path / "b.csv", date(2026, 8, 28), date(2026, 8, 28))

    assert first.cached is False and first.request_count == 1
    assert second.cached is True and second.request_count == 0
    assert other.cached is False and other.request_count == 1
    assert len(transport.calls) == 2
    assert transport.calls[0][1]["latitude"] != transport.calls[1][1]["latitude"]
    metadata = json.loads((tmp_path / "a.metadata.json").read_text(encoding="utf-8"))
    assert metadata["plot_id"] == "plot_14705"
    assert metadata["crop_key"] == "plum"


def test_digital_twin_state_uses_local_csv(tmp_path, monkeypatch):
    transport = Transport()
    monkeypatch.setattr(
        "agri_twin.application.plot_weather.build_open_meteo_client",
        lambda settings: OpenMeteoClient(transport=transport),
    )
    config = app_config(tmp_path)
    csv_path = tmp_path / "plot.csv"
    download_weather_for_plot("plot_14705", FARM_PATH, CROP_PATH, config, csv_path, date(2026, 8, 28), date(2026, 8, 28))
    state = build_crop_digital_twin_state(
        "plot_14705", FARM_PATH, CROP_PATH, csv_path,
        datetime(2026, 8, 28, tzinfo=timezone.utc),
    )

    assert state.plot_id == "plot_14705"
    assert state.crop_key == "plum"
    assert state.current_stage == "yield_maturation"
    assert state.weather_state.temperature_c == 20
    assert len(transport.calls) == 1


def test_digital_twin_state_can_use_weather_engine_provider(tmp_path, monkeypatch):
    transport = Transport()
    monkeypatch.setattr(
        "agri_twin.application.plot_weather.build_open_meteo_client",
        lambda settings: OpenMeteoClient(transport=transport),
    )
    config = app_config(tmp_path)
    csv_path = tmp_path / "plot.csv"
    download_weather_for_plot("plot_14705", FARM_PATH, CROP_PATH, config, csv_path, date(2026, 8, 28), date(2026, 8, 28))
    provider = __import__("agri_twin.infrastructure", fromlist=["CsvWeatherProvider"]).CsvWeatherProvider(csv_path)
    timestamp = provider.timestamps[0]
    weather_engine = WeatherEngine(WeatherConfiguration(), provider=provider)
    state = CropDigitalTwinState("plot_14705", "plum", "Suplum 26", "yield_maturation", timestamp, weather_engine.generate(timestamp), {})

    assert state.weather_state == provider.get(timestamp)
    assert len(transport.calls) == 1
