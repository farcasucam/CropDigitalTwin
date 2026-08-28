"""Explicit orchestration from plot identity to local weather data."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

from agri_twin.application.weather_configuration import (
    WeatherDatasetResult,
    build_open_meteo_client,
    build_open_meteo_request,
    load_weather_source_configuration,
)
from agri_twin.domain.crop import CropConfigRepository
from agri_twin.domain.crop_engine import CropEngine
from agri_twin.domain.models import CropState
from agri_twin.domain.digital_twin import CropDigitalTwinState
from agri_twin.domain.farm import FarmConfigRepository
from agri_twin.infrastructure.csv_weather import CsvWeatherProvider
from agri_twin.infrastructure.weather_cache import WeatherCache


def download_weather_for_plot(
    plot_id: str,
    farm_config_path: str | Path,
    crop_config_path: str | Path,
    app_config_path: str | Path,
    output_path: str | Path,
    start_date: date | str,
    end_date: date | str,
) -> WeatherDatasetResult:
    """Acquire a dataset for a plot, using app.json only for technical settings."""
    farm = FarmConfigRepository(farm_config_path)
    plot = farm.get_plot(plot_id)
    crop = CropConfigRepository(crop_config_path).get_crop(plot.crop_key)
    crop.resolve_stage(plot.current_stage)
    configuration = load_weather_source_configuration(app_config_path)
    settings = configuration.open_meteo
    request = build_open_meteo_request(settings, _date(start_date), _date(end_date))
    request = replace(
        request,
        latitude=plot.latitude,
        longitude=plot.longitude,
        elevation=plot.elevation,
    )
    client = build_open_meteo_client(settings)
    output = Path(output_path)
    metadata_path = output.with_suffix(".metadata.json")
    cached = False
    if settings.cache_enabled and not settings.force_refresh:
        cached = WeatherCache(
            output,
            metadata_path,
            endpoint=settings.endpoint,
            authentication_mode=settings.authentication_mode,
            temperature_unit=settings.temperature_unit,
            wind_speed_unit=settings.wind_speed_unit,
            precipitation_unit=settings.precipitation_unit,
        ).is_compatible(request)
    client.download(
        request,
        output,
        metadata_path=metadata_path,
        use_cache=settings.cache_enabled,
        force_refresh=settings.force_refresh,
        metadata_context={
            "plot_id": plot.plot_id,
            "farm_name": plot.farm_name,
            "crop_key": plot.crop_key,
            "variety": plot.variety,
            "initial_stage": plot.initial_stage,
        },
    )
    return WeatherDatasetResult(output, metadata_path, client.request_count, cached)


def build_crop_digital_twin_state(
    plot_id: str,
    farm_config_path: str | Path,
    crop_config_path: str | Path,
    csv_path: str | Path,
    timestamp: datetime,
    crop_state: CropState | None = None,
) -> CropDigitalTwinState:
    """Build the initial plot/crop state from an already acquired local dataset."""
    plot = FarmConfigRepository(farm_config_path).get_plot(plot_id)
    crop = CropConfigRepository(crop_config_path).get_crop(plot.crop_key)
    stage = crop.resolve_stage(plot.current_stage)
    weather = CsvWeatherProvider(csv_path).get(timestamp)
    return CropDigitalTwinState(
        plot_id=plot.plot_id,
        crop_key=crop.crop_key,
        variety=plot.variety,
        current_stage=stage.stage_key,
        timestamp=timestamp,
        weather_state=weather,
        agronomic_state={"soil_type": plot.soil_type, "irrigation_type": plot.irrigation_type},
        crop_state=crop_state,
    )


def _date(value: date | str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("dates must use ISO format YYYY-MM-DD") from exc
