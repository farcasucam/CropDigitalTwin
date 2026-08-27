import json
from datetime import date, datetime, timedelta, timezone

import pytest

from agri_twin.infrastructure import (
    OpenMeteoApi,
    OpenMeteoClient,
    OpenMeteoRequest,
    OpenMeteoResponseError,
    WeatherRangeNotAvailable,
    WeatherCache,
    OpenMeteoRequestError,
    WeatherModelNotAvailable,
    OpenMeteoAuthConfig,
)


class FakeTransport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, params):
        self.calls.append((url, dict(params)))
        return json.dumps(self.response).encode()


class ChunkTransport(FakeTransport):
    def get(self, url, params):
        self.calls.append((url, dict(params)))
        start = datetime.fromisoformat(params["start_date"]).replace(tzinfo=timezone.utc)
        end = datetime.fromisoformat(params["end_date"]).replace(tzinfo=timezone.utc)
        times = []
        current = start
        while current <= end + timedelta(hours=23):
            times.append(current.strftime("%Y-%m-%dT%H:%M"))
            current += timedelta(hours=1)
        result = response()
        result["hourly"] = {
            "time": times,
            "temperature_2m": [20] * len(times),
            "relative_humidity_2m": [50] * len(times),
            "shortwave_radiation": [100] * len(times),
            "wind_speed_10m": [2] * len(times),
            "wind_direction_10m": [180] * len(times),
            "rain": [0] * len(times),
            "surface_pressure": [1012] * len(times),
        }
        return json.dumps(result).encode()


def request(api=OpenMeteoApi.HISTORICAL):
    return OpenMeteoRequest(
        latitude=40.0,
        longitude=-3.0,
        start_date=date(2026, 8, 27),
        end_date=date(2026, 8, 28),
        variables=("temperature_2m", "relative_humidity_2m", "shortwave_radiation", "wind_speed_10m", "wind_direction_10m", "rain", "surface_pressure"),
        api=api,
    )


def response():
    return {
        "latitude": 40,
        "longitude": -3,
        "elevation": 650,
        "timezone": "UTC",
        "model": "gfs",
        "hourly": {
            "time": ["2026-08-27T12:00"],
            "temperature_2m": [31],
            "relative_humidity_2m": [42],
            "shortwave_radiation": [820],
            "wind_speed_10m": [2.5],
            "wind_direction_10m": [180],
            "rain": [0],
            "surface_pressure": [1012],
        },
    }


def test_open_meteo_download_normalizes_csv_and_metadata_without_http_in_provider(tmp_path):
    transport = FakeTransport(response())
    client = OpenMeteoClient(transport=transport)
    output = tmp_path / "weather.csv"
    client.download(request(), output)

    assert len(transport.calls) == 1
    assert "timezone" in transport.calls[0][1]
    assert transport.calls[0][1]["timezone"] == "UTC"
    assert transport.calls[0][1]["wind_speed_unit"] == "ms"
    assert "apikey" not in transport.calls[0][1]
    assert output.read_text(encoding="utf-8").splitlines()[1].split(",")[1] == "31"
    metadata = json.loads(output.with_suffix(".metadata.json").read_text(encoding="utf-8"))
    assert "api_key" not in json.dumps(metadata).lower()
    assert metadata["model_returned"] == "gfs"


def test_public_and_customer_authentication_are_explicit(monkeypatch, tmp_path):
    public_transport = FakeTransport(response())
    forecast_request = request(api=OpenMeteoApi.FORECAST)
    OpenMeteoClient(transport=public_transport).download(forecast_request, tmp_path / "public.csv")
    assert "apikey" not in public_transport.calls[0][1]

    monkeypatch.setenv("TEST_OPEN_METEO_KEY", "TEST_SECRET_123")
    customer_transport = FakeTransport(response())
    client = OpenMeteoClient(
        transport=customer_transport,
        auth=OpenMeteoAuthConfig(mode="customer", key_env="TEST_OPEN_METEO_KEY"),
    )
    client.download(forecast_request, tmp_path / "customer.csv")
    assert customer_transport.calls[0][0] == "https://customer-api.open-meteo.com/v1/forecast"
    assert customer_transport.calls[0][1]["apikey"] == "TEST_SECRET_123"


def test_open_meteo_rejects_malformed_response_and_forecast_horizon(tmp_path):
    client = OpenMeteoClient(transport=FakeTransport({"hourly": {"time": []}}))
    with pytest.raises(OpenMeteoResponseError):
        client.download(request(), tmp_path / "weather.csv")
    future = OpenMeteoRequest(
        latitude=40, longitude=-3, start_date=date(2099, 1, 1), end_date=date(2099, 1, 20),
        variables=request().variables, api=OpenMeteoApi.FORECAST,
    )
    with pytest.raises(WeatherRangeNotAvailable):
        OpenMeteoClient(transport=FakeTransport(response())).download(future, tmp_path / "future.csv")


def test_open_meteo_rejects_model_errors_without_fallback(tmp_path):
    client = OpenMeteoClient(transport=FakeTransport({"error": True, "reason": "invalid model"}))
    with pytest.raises(WeatherModelNotAvailable):
        client.download(request(), tmp_path / "weather.csv")
    archived = OpenMeteoRequest(
        latitude=40, longitude=-3, start_date=date(2026, 8, 27), end_date=date(2026, 8, 27),
        variables=request().variables, api=OpenMeteoApi.HISTORICAL_FORECAST,
    )
    with pytest.raises(WeatherRangeNotAvailable):
        client.download(archived, tmp_path / "archived.csv")


def test_open_meteo_request_errors_are_sanitized():
    class FailingTransport:
        def get(self, url, params):
            raise OpenMeteoRequestError("network failed")

    with pytest.raises(OpenMeteoRequestError, match="network failed"):
        OpenMeteoClient(transport=FailingTransport()).download(request(), "weather.csv")


def test_open_meteo_rejects_invalid_chunk_size(tmp_path):
    invalid = OpenMeteoRequest(
        latitude=40, longitude=-3, start_date=date(2026, 8, 27), end_date=date(2026, 8, 27),
        variables=request().variables, chunk_days=0,
    )
    with pytest.raises(OpenMeteoResponseError):
        OpenMeteoClient(transport=FakeTransport(response())).download(invalid, tmp_path / "weather.csv")


def test_open_meteo_rejects_invalid_timeout():
    with pytest.raises(OpenMeteoRequestError):
        OpenMeteoClient(timeout_seconds=0)


def test_cache_compatibility_avoids_download(tmp_path):
    output = tmp_path / "weather.csv"
    output.write_text("data", encoding="utf-8")
    metadata = output.with_suffix(".metadata.json")
    metadata.write_text(json.dumps({
        "source": "open-meteo", "api": "historical", "model_requested": "auto",
        "latitude": 40.0, "longitude": -3.0, "elevation": None, "timezone": "UTC",
        "start_date": "2026-08-27", "end_date": "2026-08-28", "resolution": "hourly",
        "variables": list(request().variables), "wind_speed_unit": "ms",
        "temperature_unit": "celsius", "precipitation_unit": "mm",
        "endpoint": "https://archive-api.open-meteo.com/v1/archive",
        "units": {"wind_speed": "ms", "temperature": "celsius", "precipitation": "mm"},
    }), encoding="utf-8")
    assert WeatherCache(output).is_compatible(request())


def test_download_cache_hit_uses_zero_http_and_force_refresh_downloads(tmp_path):
    output = tmp_path / "weather.csv"
    transport = FakeTransport(response())
    client = OpenMeteoClient(transport=transport)

    client.download(request(), output)
    assert len(transport.calls) == 1

    offline_client = OpenMeteoClient(transport=FakeTransport({}))
    offline_client.download(request(), output, use_cache=True)
    assert len(offline_client._transport.calls) == 0

    client.download(request(), output, use_cache=True, force_refresh=True)
    assert len(transport.calls) == 2


def test_incompatible_cache_requires_explicit_refresh(tmp_path):
    output = tmp_path / "weather.csv"
    transport = FakeTransport(response())
    client = OpenMeteoClient(transport=transport)
    client.download(request(), output)

    incompatible = OpenMeteoRequest(
        latitude=41.0,
        longitude=-3.0,
        start_date=request().start_date,
        end_date=request().end_date,
        variables=request().variables,
    )
    with pytest.raises(WeatherRangeNotAvailable):
        client.download(incompatible, output, use_cache=True)


def test_long_range_can_be_partitioned_without_duplicates_or_gaps(tmp_path):
    transport = ChunkTransport(response())
    client = OpenMeteoClient(transport=transport)
    chunked = OpenMeteoRequest(
        latitude=40.0,
        longitude=-3.0,
        start_date=date(2026, 8, 27),
        end_date=date(2026, 8, 28),
        variables=request().variables,
        chunk_days=1,
    )

    output = tmp_path / "weather.csv"
    client.download(chunked, output)

    assert len(transport.calls) == 2
    assert len(output.read_text(encoding="utf-8").splitlines()) == 49
