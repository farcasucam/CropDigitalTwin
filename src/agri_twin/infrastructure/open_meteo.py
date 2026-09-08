"""Explicit Open-Meteo acquisition, separated from simulation providers."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from agri_twin.domain.models import WeatherState
from agri_twin.domain.weather import WeatherEngineValueError, normalize_utc
from agri_twin.infrastructure.csv_weather import COLUMNS


class OpenMeteoRequestError(Exception):
    """Base error for acquisition failures."""


class OpenMeteoAuthenticationError(OpenMeteoRequestError):
    pass


class OpenMeteoRateLimitError(OpenMeteoRequestError):
    pass


class OpenMeteoResponseError(OpenMeteoRequestError):
    pass


class WeatherRangeNotAvailable(OpenMeteoRequestError):
    pass


class WeatherModelNotAvailable(OpenMeteoRequestError):
    pass


@dataclass(frozen=True, slots=True)
class OpenMeteoAuthConfig:
    mode: str = "public"
    key_env: str = "OPEN_METEO_API_KEY"

    def __post_init__(self) -> None:
        if self.mode not in {"public", "customer"}:
            raise OpenMeteoRequestError(f"unsupported Open-Meteo authentication mode: {self.mode}")
        if not self.key_env:
            raise OpenMeteoRequestError("Open-Meteo key_env cannot be empty")


class OpenMeteoApi(str, Enum):
    HISTORICAL = "historical"
    FORECAST = "forecast"
    HISTORICAL_FORECAST = "historical_forecast"
    ARCHIVED_FORECAST = "archived_forecast"
    PREVIOUS_RUNS = "previous_runs"
    SINGLE_RUNS = "single_runs"


@dataclass(frozen=True, slots=True)
class OpenMeteoRequest:
    latitude: float
    longitude: float
    start_date: date
    end_date: date
    variables: tuple[str, ...]
    api: OpenMeteoApi = OpenMeteoApi.HISTORICAL
    timezone: str = "UTC"
    model: str = "auto"
    elevation: float | None = None
    chunk_days: int | None = None


class HttpTransport(Protocol):
    def get(self, url: str, params: Mapping[str, str]) -> bytes: ...


class UrllibTransport:
    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self._timeout = timeout_seconds

    def get(self, url: str, params: Mapping[str, str]) -> bytes:
        request = Request(f"{url}?{urlencode(params)}", headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=self._timeout) as response:
                return response.read()
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise OpenMeteoAuthenticationError("Open-Meteo authentication failed") from exc
            if exc.code == 429:
                raise OpenMeteoRateLimitError("Open-Meteo rate limit exceeded") from exc
            raise OpenMeteoRequestError(f"Open-Meteo request failed with status {exc.code}") from exc
        except URLError as exc:
            raise OpenMeteoRequestError("Open-Meteo request could not be completed") from exc


DEFAULT_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "shortwave_radiation",
    "wind_speed_10m",
    "wind_direction_10m",
    "rain",
    "surface_pressure",
)


class OpenMeteoClient:
    source = "OPEN_METEO"
    forcing_type = "SIMULATION_FORCING"

    def __init__(
        self,
        transport: HttpTransport | None = None,
        public_endpoint: str = "https://api.open-meteo.com/v1/forecast",
        historical_endpoint: str = "https://archive-api.open-meteo.com/v1/archive",
        customer_endpoint: str | None = None,
        api_key: str | None = None,
        auth: OpenMeteoAuthConfig | None = None,
        timeout_seconds: float = 30.0,
        temperature_unit: str = "celsius",
        wind_speed_unit: str = "ms",
        precipitation_unit: str = "mm",
    ) -> None:
        if timeout_seconds <= 0 or not math.isfinite(timeout_seconds):
            raise OpenMeteoRequestError("timeout_seconds must be finite and positive")
        self._transport = transport or UrllibTransport(timeout_seconds)
        self._public_endpoint = public_endpoint
        self._historical_endpoint = historical_endpoint
        self._customer_endpoint = customer_endpoint or "https://customer-api.open-meteo.com/v1/forecast"
        self._api_key = api_key
        self._auth = auth or OpenMeteoAuthConfig()
        if (temperature_unit, wind_speed_unit, precipitation_unit) != (
            "celsius", "ms", "mm"
        ):
            raise OpenMeteoRequestError(
                "Open-Meteo units must be celsius, ms and mm"
            )
        self._temperature_unit = temperature_unit
        self._wind_speed_unit = wind_speed_unit
        self._precipitation_unit = precipitation_unit
        self._request_count = 0

    @property
    def request_count(self) -> int:
        """Number of successful HTTP requests made by the latest download."""
        return self._request_count

    def download(
        self,
        request: OpenMeteoRequest,
        output_csv: str | Path,
        metadata_path: str | Path | None = None,
        use_cache: bool = False,
        force_refresh: bool = False,
        metadata_context: Mapping[str, Any] | None = None,
    ) -> Path:
        self._validate_request(request)
        self._request_count = 0
        output = Path(output_csv)
        metadata_file = Path(metadata_path) if metadata_path else output.with_suffix(".metadata.json")
        if use_cache and not force_refresh:
            from agri_twin.infrastructure.weather_cache import WeatherCache
            cache = WeatherCache(
                output,
                metadata_file,
                endpoint=self._endpoint(request.api),
                authentication_mode=self._auth.mode,
                temperature_unit=self._temperature_unit,
                wind_speed_unit=self._wind_speed_unit,
                precipitation_unit=self._precipitation_unit,
            )
            if cache.is_compatible(request):
                return output

        rows: list[dict[str, Any]] = []
        responses: list[Mapping[str, Any]] = []
        for chunk_start, chunk_end in self._chunks(request):
            chunk_request = OpenMeteoRequest(
                latitude=request.latitude,
                longitude=request.longitude,
                start_date=chunk_start,
                end_date=chunk_end,
                variables=request.variables,
                api=request.api,
                timezone=request.timezone,
                model=request.model,
                elevation=request.elevation,
                chunk_days=None,
            )
            response = self._request(chunk_request)
            self._request_count += 1
            responses.append(response)
            rows.extend(self._normalize_response(response, chunk_request))
        rows = self._merge_rows(rows)
        self._validate_rows(rows, request)
        metadata = self._metadata(responses[-1], request, self._request_count)
        if metadata_context:
            metadata.update(metadata_context)
        self._write_dataset_atomically(output, metadata_file, rows, metadata)
        return output

    def _request(self, request: OpenMeteoRequest) -> Mapping[str, Any]:
        endpoint = self._endpoint(request.api)
        params = {
            "latitude": str(request.latitude),
            "longitude": str(request.longitude),
            "start_date": request.start_date.isoformat(),
            "end_date": request.end_date.isoformat(),
            "hourly": ",".join(request.variables),
            "timezone": request.timezone,
            "wind_speed_unit": self._wind_speed_unit,
            "temperature_unit": self._temperature_unit,
            "precipitation_unit": self._precipitation_unit,
        }
        if request.model != "auto":
            params["models"] = request.model
        if request.elevation is not None:
            params["elevation"] = str(request.elevation)
        if self._auth.mode == "customer":
            api_key = self._api_key or os.getenv(self._auth.key_env)
            if not api_key:
                raise OpenMeteoAuthenticationError("Open-Meteo customer API key is not configured")
            params["apikey"] = api_key
        try:
            raw = self._transport.get(endpoint, params)
            response = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OpenMeteoResponseError("Open-Meteo response was not valid JSON") from exc
        if not isinstance(response, dict):
            raise OpenMeteoResponseError("Open-Meteo response must be a JSON object")
        if response.get("error"):
            reason = str(response.get("reason", ""))
            if "model" in reason.lower():
                raise WeatherModelNotAvailable("requested Open-Meteo model is not available")
            raise OpenMeteoResponseError("Open-Meteo returned an error response")
        return response

    @staticmethod
    def _chunks(request: OpenMeteoRequest) -> list[tuple[date, date]]:
        if request.chunk_days is None:
            return [(request.start_date, request.end_date)]
        chunks = []
        current = request.start_date
        while current <= request.end_date:
            end = min(current + timedelta(days=request.chunk_days - 1), request.end_date)
            chunks.append((current, end))
            current = end + timedelta(days=1)
        return chunks

    @staticmethod
    def _merge_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for row in rows:
            timestamp = row["timestamp"]
            if timestamp in merged:
                raise OpenMeteoResponseError(f"duplicate timestamp in acquired dataset: {timestamp}")
            merged[timestamp] = row
        return [merged[timestamp] for timestamp in sorted(merged)]

    @staticmethod
    def _validate_rows(rows: list[dict[str, Any]], request: OpenMeteoRequest) -> None:
        if not rows:
            raise OpenMeteoResponseError("Open-Meteo returned an empty hourly series")
        timestamps = [datetime.fromisoformat(row["timestamp"]) for row in rows]
        if timestamps != sorted(timestamps):
            raise OpenMeteoResponseError("acquired timestamps are not ordered")
        for previous, current in zip(timestamps, timestamps[1:]):
            if current - previous != timedelta(hours=1):
                raise OpenMeteoResponseError("acquired hourly series contains a gap")

    def _endpoint(self, api: OpenMeteoApi) -> str:
        if api is OpenMeteoApi.HISTORICAL:
            return self._historical_endpoint
        if api is OpenMeteoApi.FORECAST:
            if self._auth.mode == "customer":
                return self._customer_endpoint
            return self._public_endpoint
        raise WeatherRangeNotAvailable(f"Acquisition API is not implemented: {api.value}")

    @staticmethod
    def _validate_request(request: OpenMeteoRequest) -> None:
        if not isinstance(request.start_date, date) or not isinstance(request.end_date, date):
            raise OpenMeteoResponseError("start_date and end_date must be dates")
        if not isinstance(request.latitude, (int, float)) or not math.isfinite(request.latitude) or not -90 <= request.latitude <= 90:
            raise OpenMeteoResponseError("latitude must be between -90 and 90")
        if not isinstance(request.longitude, (int, float)) or not math.isfinite(request.longitude) or not -180 <= request.longitude <= 180:
            raise OpenMeteoResponseError("longitude must be between -180 and 180")
        if request.start_date > request.end_date:
            raise WeatherRangeNotAvailable("start_date cannot be after end_date")
        if not request.variables:
            raise OpenMeteoResponseError("at least one hourly variable is required")
        if set(request.variables) != set(DEFAULT_VARIABLES):
            raise OpenMeteoResponseError("the normalized dataset requires the configured weather variables")
        if (
            request.chunk_days is not None
            and (
                not isinstance(request.chunk_days, int)
                or isinstance(request.chunk_days, bool)
                or request.chunk_days <= 0
            )
        ):
            raise OpenMeteoResponseError("chunk_days must be a positive integer")
        if request.api is OpenMeteoApi.FORECAST:
            horizon = (request.end_date - date.today()).days
            if horizon > 16:
                raise WeatherRangeNotAvailable("forecast horizon exceeds the supported 16 days")
        if request.timezone != "UTC":
            raise WeatherEngineValueError("weather acquisition must request timezone=UTC")
        if not request.model:
            raise WeatherModelNotAvailable("model cannot be empty")

    @staticmethod
    def _normalize_response(response: Mapping[str, Any], request: OpenMeteoRequest) -> list[dict[str, Any]]:
        hourly = response.get("hourly")
        if not isinstance(hourly, Mapping) or not isinstance(hourly.get("time"), list):
            raise OpenMeteoResponseError("Open-Meteo response has no hourly time series")
        required = set(DEFAULT_VARIABLES)
        if not required.issubset(hourly):
            missing = sorted(required - set(hourly))
            raise OpenMeteoResponseError(f"Open-Meteo response is missing variables: {', '.join(missing)}")
        lengths = {len(hourly[name]) for name in required | {"time"}}
        if len(lengths) != 1:
            raise OpenMeteoResponseError("Open-Meteo hourly arrays have different lengths")
        rows = []
        for index, value in enumerate(hourly["time"]):
            try:
                parsed_timestamp = datetime.fromisoformat(value)
                if parsed_timestamp.tzinfo is None and request.timezone == "UTC":
                    parsed_timestamp = parsed_timestamp.replace(tzinfo=timezone.utc)
                timestamp = normalize_utc(parsed_timestamp)
            except (TypeError, ValueError, WeatherEngineValueError) as exc:
                raise OpenMeteoResponseError(f"invalid timestamp at index {index}") from exc
            values = (
                hourly["temperature_2m"][index],
                hourly["relative_humidity_2m"][index],
                hourly["shortwave_radiation"][index],
                hourly["wind_speed_10m"][index],
                hourly["wind_direction_10m"][index] % 360,
                hourly["rain"][index],
                hourly["surface_pressure"][index],
            )
            try:
                state = WeatherState(*values)
            except (TypeError, ValueError) as exc:
                raise OpenMeteoResponseError(f"invalid weather value at index {index}") from exc
            rows.append({"timestamp": timestamp.isoformat(), **dict(zip(COLUMNS[1:], values))})
        return rows

    @staticmethod
    def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
        import csv
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

    @classmethod
    def _write_dataset_atomically(
        cls,
        csv_path: Path,
        metadata_path: Path,
        rows: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> None:
        csv_tmp = csv_path.with_name(f".{csv_path.name}.tmp")
        metadata_tmp = metadata_path.with_name(f".{metadata_path.name}.tmp")
        try:
            cls._write_csv(csv_tmp, rows)
            metadata_tmp.parent.mkdir(parents=True, exist_ok=True)
            metadata_tmp.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            csv_tmp.replace(csv_path)
            metadata_tmp.replace(metadata_path)
        except OSError as exc:
            for temporary in (csv_tmp, metadata_tmp):
                temporary.unlink(missing_ok=True)
            raise OpenMeteoResponseError("could not write weather dataset") from exc

    def _metadata(self, response: Mapping[str, Any], request: OpenMeteoRequest, request_count: int) -> dict[str, Any]:
        return {
            "source": "open-meteo",
            "provider": "open-meteo",
            "api": request.api.value,
            "dataset_type": request.api.value,
            "authentication_mode": self._auth.mode,
            "endpoint": self._endpoint(request.api),
            "model_requested": request.model,
            "model_returned": response.get("model"),
            "latitude": request.latitude,
            "longitude": request.longitude,
            "elevation_requested": request.elevation,
            "elevation": request.elevation if request.elevation is not None else response.get("elevation"),
            "timezone": "UTC",
            "start_date": request.start_date.isoformat(),
            "end_date": request.end_date.isoformat(),
            "resolution": "hourly",
            "variables": list(request.variables),
            "units": {
                "wind_speed": self._wind_speed_unit,
                "temperature": self._temperature_unit,
                "precipitation": self._precipitation_unit,
            },
            "wind_speed_unit": self._wind_speed_unit,
            "temperature_unit": self._temperature_unit,
            "precipitation_unit": self._precipitation_unit,
            "retrieved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "forecast_reference_time": response.get("forecast_reference_time"),
            "forecast_valid_from": response.get("forecast_valid_from"),
            "forecast_valid_to": response.get("forecast_valid_to"),
            "request_count": request_count,
            "client_version": "1.0",
        }
