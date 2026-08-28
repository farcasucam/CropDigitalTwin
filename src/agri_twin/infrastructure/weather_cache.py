"""Compatibility checks for explicit offline weather datasets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agri_twin.infrastructure.open_meteo import OpenMeteoRequest


class WeatherCache:
    def __init__(
        self,
        csv_path: str | Path,
        metadata_path: str | Path | None = None,
        endpoint: str | None = None,
        authentication_mode: str = "public",
        temperature_unit: str = "celsius",
        wind_speed_unit: str = "ms",
        precipitation_unit: str = "mm",
    ) -> None:
        self.csv_path = Path(csv_path)
        self.metadata_path = Path(metadata_path) if metadata_path else self.csv_path.with_suffix(".metadata.json")
        self.endpoint = endpoint
        self.authentication_mode = authentication_mode
        self.temperature_unit = temperature_unit
        self.wind_speed_unit = wind_speed_unit
        self.precipitation_unit = precipitation_unit

    def is_compatible(self, request: OpenMeteoRequest) -> bool:
        if not self.csv_path.is_file() or not self.metadata_path.is_file():
            return False
        try:
            metadata: dict[str, Any] = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        expected_endpoint = self.endpoint or (
            "https://archive-api.open-meteo.com/v1/archive"
            if request.api.value == "historical"
            else "https://api.open-meteo.com/v1/forecast"
        )
        return (
            metadata.get("source") == "open-meteo"
            and metadata.get("provider") == "open-meteo"
            and metadata.get("api") == request.api.value
            and metadata.get("endpoint") == expected_endpoint
            and metadata.get("authentication_mode") == self.authentication_mode
            and metadata.get("model_requested") == request.model
            and metadata.get("latitude") == request.latitude
            and metadata.get("longitude") == request.longitude
            and metadata.get("elevation_requested", metadata.get("elevation")) == request.elevation
            and metadata.get("timezone") == request.timezone
            and metadata.get("start_date") == request.start_date.isoformat()
            and metadata.get("end_date") == request.end_date.isoformat()
            and metadata.get("resolution") == "hourly"
            and metadata.get("variables") == list(request.variables)
            and metadata.get("wind_speed_unit") == self.wind_speed_unit
            and metadata.get("temperature_unit") == self.temperature_unit
            and metadata.get("precipitation_unit") == self.precipitation_unit
            and metadata.get("units") == {
                "wind_speed": self.wind_speed_unit,
                "temperature": self.temperature_unit,
                "precipitation": self.precipitation_unit,
            }
        )
