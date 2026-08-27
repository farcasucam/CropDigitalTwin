"""Runtime source selection without implicit network acquisition."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from math import isfinite
from pathlib import Path
from typing import Any

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agri_twin.application.providers import WeatherProvider


class WeatherConfigurationError(ValueError):
    """Raised when runtime weather source configuration is invalid."""


@dataclass(frozen=True, slots=True)
class WeatherDatasetResult:
    csv_path: Path
    metadata_path: Path
    request_count: int
    cached: bool


@dataclass(frozen=True, slots=True)
class OpenMeteoSourceConfiguration:
    enabled: bool = False
    api: str = "forecast"
    endpoint: str = "https://api.open-meteo.com/v1/forecast"
    authentication_mode: str = "public"
    api_key_env: str = "OPEN_METEO_API_KEY"
    timeout_seconds: float = 30.0
    model: str = "auto"
    timezone: str = "UTC"
    temperature_unit: str = "celsius"
    wind_speed_unit: str = "ms"
    precipitation_unit: str = "mm"
    variables: tuple[str, ...] = ()
    cache_enabled: bool = True
    force_refresh: bool = False
    cache_directory: str = "data/weather"
    chunk_days: int | None = 7
    latitude: float = 40.0
    longitude: float = -3.0
    elevation: float | None = None

    def __post_init__(self) -> None:
        if self.api not in {"historical", "forecast"}:
            raise WeatherConfigurationError(f"unsupported Open-Meteo API: {self.api}")
        if not self.endpoint:
            raise WeatherConfigurationError("Open-Meteo endpoint cannot be empty")
        if self.authentication_mode not in {"public", "customer"}:
            raise WeatherConfigurationError("authentication mode must be public or customer")
        if self.authentication_mode == "customer" and not self.api_key_env:
            raise WeatherConfigurationError("customer authentication requires api_key_env")
        if self.timeout_seconds <= 0:
            raise WeatherConfigurationError("timeout_seconds must be positive")
        if self.timezone != "UTC":
            raise WeatherConfigurationError("weather configuration must use timezone UTC")
        if (self.temperature_unit, self.wind_speed_unit, self.precipitation_unit) != (
            "celsius", "ms", "mm"
        ):
            raise WeatherConfigurationError(
                "weather acquisition units must be celsius, ms and mm"
            )
        if len(set(self.variables)) != len(self.variables):
            raise WeatherConfigurationError("Open-Meteo variables cannot be duplicated")
        if self.chunk_days is not None and self.chunk_days <= 0:
            raise WeatherConfigurationError("chunk_days must be positive")
        if not isfinite(self.latitude) or not -90 <= self.latitude <= 90:
            raise WeatherConfigurationError("latitude must be between -90 and 90")
        if not isfinite(self.longitude) or not -180 <= self.longitude <= 180:
            raise WeatherConfigurationError("longitude must be between -180 and 180")
        if self.elevation is not None and not isfinite(self.elevation):
            raise WeatherConfigurationError("elevation must be finite")


@dataclass(frozen=True, slots=True)
class WeatherSourceConfiguration:
    provider: str = "synthetic"
    dataset_path: str | None = None
    open_meteo: OpenMeteoSourceConfiguration = OpenMeteoSourceConfiguration()

    def __post_init__(self) -> None:
        if self.provider not in {"synthetic", "csv", "open_meteo"}:
            raise WeatherConfigurationError(f"unsupported weather provider: {self.provider}")
        if self.provider == "csv" and not self.dataset_path:
            raise WeatherConfigurationError("csv provider requires dataset_path")
        if self.provider == "open_meteo" and not self.open_meteo.enabled:
            raise WeatherConfigurationError("open_meteo provider requires open_meteo.enabled=true")


def load_weather_source_configuration(path: str | Path) -> WeatherSourceConfiguration:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        weather = payload.get("weather", {})
        if not isinstance(weather, dict):
            raise WeatherConfigurationError("weather configuration must be an object")
        dataset = weather.get("dataset", {})
        open_meteo = weather.get("open_meteo", payload.get("open_meteo", {}))
        if not isinstance(dataset, dict) or not isinstance(open_meteo, dict):
            raise WeatherConfigurationError("weather dataset and Open-Meteo settings must be objects")
        auth = open_meteo.get("authentication", {})
        if not isinstance(auth, dict):
            raise WeatherConfigurationError("Open-Meteo authentication must be an object")
        legacy_api = open_meteo.get("api", {})
        if isinstance(legacy_api, dict) and not auth:
            auth = legacy_api
        location = open_meteo.get("location", {})
        units = open_meteo.get("units", {})
        cache = open_meteo.get("cache", {})
        acquisition = open_meteo.get("acquisition", {})
        variables = tuple(open_meteo.get("variables", ()))
        return WeatherSourceConfiguration(
            provider=weather.get("provider", "synthetic"),
            dataset_path=dataset.get("path"),
            open_meteo=OpenMeteoSourceConfiguration(
                enabled=bool(open_meteo.get("enabled", False)),
                api=open_meteo.get("api", "forecast") if isinstance(open_meteo.get("api", "forecast"), str) else "forecast",
                endpoint=open_meteo.get("endpoint", OpenMeteoSourceConfiguration.endpoint),
                authentication_mode=auth.get("mode", "public"),
                api_key_env=auth.get("api_key_env", auth.get("key_env", "OPEN_METEO_API_KEY")),
                timeout_seconds=float(open_meteo.get("timeout_seconds", open_meteo.get("request", {}).get("timeout_seconds", 30))),
                model=open_meteo.get("model", "auto"),
                timezone=open_meteo.get("timezone", "UTC"),
                temperature_unit=units.get("temperature", "celsius"),
                wind_speed_unit=units.get("wind_speed", "ms"),
                precipitation_unit=units.get("precipitation", "mm"),
                variables=variables,
                cache_enabled=bool(cache.get("enabled", True)),
                force_refresh=bool(cache.get("force_refresh", False)),
                cache_directory=cache.get("directory", "data/weather"),
                chunk_days=acquisition.get("chunk_days", 7),
                latitude=float(location.get("latitude", 40.0)),
                longitude=float(location.get("longitude", -3.0)),
                elevation=location.get("elevation"),
            ),
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise WeatherConfigurationError("invalid weather source configuration") from exc


def create_offline_weather_provider(configuration: WeatherSourceConfiguration) -> WeatherProvider:
    if configuration.provider != "csv":
        raise WeatherConfigurationError(
            "only csv can be constructed offline without an existing WeatherEngine"
        )
    from agri_twin.infrastructure.csv_weather import CsvWeatherProvider

    return CsvWeatherProvider(configuration.dataset_path)


def build_open_meteo_client(configuration: OpenMeteoSourceConfiguration) -> Any:
    """Build acquisition configuration without performing a download."""
    from agri_twin.infrastructure.open_meteo import OpenMeteoAuthConfig, OpenMeteoClient

    return OpenMeteoClient(
        public_endpoint=(
            configuration.endpoint
            if configuration.authentication_mode == "public"
            else "https://api.open-meteo.com/v1/forecast"
        ),
        historical_endpoint=(
            configuration.endpoint
            if configuration.api == "historical"
            else "https://archive-api.open-meteo.com/v1/archive"
        ),
        customer_endpoint=(
            configuration.endpoint
            if configuration.authentication_mode == "customer"
            else None
        ),
        auth=OpenMeteoAuthConfig(
            mode=configuration.authentication_mode,
            key_env=configuration.api_key_env,
        ),
        timeout_seconds=configuration.timeout_seconds,
        temperature_unit=configuration.temperature_unit,
        wind_speed_unit=configuration.wind_speed_unit,
        precipitation_unit=configuration.precipitation_unit,
    )


def build_open_meteo_request(
    configuration: OpenMeteoSourceConfiguration,
    start_date: date,
    end_date: date,
) -> Any:
    from agri_twin.infrastructure.open_meteo import (
        DEFAULT_VARIABLES,
        OpenMeteoApi,
        OpenMeteoRequest,
    )

    variables = configuration.variables or DEFAULT_VARIABLES
    return OpenMeteoRequest(
        latitude=configuration.latitude,
        longitude=configuration.longitude,
        start_date=start_date,
        end_date=end_date,
        variables=tuple(variables),
        api=OpenMeteoApi(configuration.api),
        timezone=configuration.timezone,
        model=configuration.model,
        elevation=configuration.elevation,
        chunk_days=configuration.chunk_days,
    )


def download_weather_dataset_from_config(
    config_path: str | Path,
    output_path: str | Path,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
) -> WeatherDatasetResult:
    """Explicitly acquire an Open-Meteo dataset from application config."""
    configuration = load_weather_source_configuration(config_path)
    if configuration.provider != "open_meteo":
        raise WeatherConfigurationError(
            "weather provider must be open_meteo for dataset acquisition"
        )
    settings = configuration.open_meteo
    resolved_start = _coerce_date(start_date)
    resolved_end = _coerce_date(end_date)
    if resolved_start is None or resolved_end is None:
        raise WeatherConfigurationError(
            "start_date and end_date are required for Open-Meteo acquisition"
        )
    request = build_open_meteo_request(settings, resolved_start, resolved_end)
    client = build_open_meteo_client(settings)
    csv_path = Path(output_path)
    metadata_path = csv_path.with_suffix(".metadata.json")
    cached = False
    if settings.cache_enabled and not settings.force_refresh:
        from agri_twin.infrastructure.weather_cache import WeatherCache

        cached = WeatherCache(
            csv_path,
            metadata_path,
            endpoint=settings.endpoint,
        ).is_compatible(request)
    client.download(
        request,
        csv_path,
        metadata_path=metadata_path,
        use_cache=settings.cache_enabled,
        force_refresh=settings.force_refresh,
    )
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        request_count = int(metadata.get("request_count", 0))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise WeatherConfigurationError("download metadata is invalid") from exc
    return WeatherDatasetResult(csv_path, metadata_path, request_count, cached)


def _coerce_date(value: date | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise WeatherConfigurationError("dates must use ISO format YYYY-MM-DD") from exc