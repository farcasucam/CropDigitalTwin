"""Validated, exact-match offline CSV weather provider."""

from __future__ import annotations

import csv
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agri_twin.application.providers import WeatherTimestampNotAvailable
from agri_twin.domain.models import WeatherState


class WeatherDatasetError(Exception):
    """Raised when a weather CSV is invalid."""


COLUMNS = (
    "timestamp", "temperature_c", "relative_humidity_pct",
    "solar_radiation_w_m2", "wind_speed_m_s", "wind_direction_deg",
    "rain_rate_mm_h", "pressure_hpa",
)


class CsvWeatherProvider:
    source = "REAL_WORLD"
    forcing_type = "SIMULATION_FORCING"

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._states: dict[datetime, WeatherState] = {}
        self._load()

    def get(self, simulation_time: datetime) -> WeatherState:
        if simulation_time.tzinfo is None:
            raise WeatherDatasetError("simulation_time must be timezone-aware")
        instant = simulation_time.astimezone(timezone.utc)
        try:
            return self._states[instant]
        except KeyError as exc:
            raise WeatherTimestampNotAvailable(instant.isoformat()) from exc

    @property
    def timestamps(self) -> tuple[datetime, ...]:
        return tuple(sorted(self._states))

    def _load(self) -> None:
        try:
            with self._path.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                if tuple(reader.fieldnames or ()) != COLUMNS:
                    raise WeatherDatasetError("CSV header must match the required columns")
                for row_number, row in enumerate(reader, start=2):
                    timestamp = self._parse_timestamp(row["timestamp"], row_number)
                    if timestamp in self._states:
                        raise WeatherDatasetError(f"duplicate timestamp at row {row_number}")
                    values = []
                    for column in COLUMNS[1:]:
                        try:
                            value = float(row[column])
                        except (TypeError, ValueError) as exc:
                            raise WeatherDatasetError(f"invalid {column} at row {row_number}") from exc
                        if not math.isfinite(value):
                            raise WeatherDatasetError(f"non-finite {column} at row {row_number}")
                        values.append(value)
                    try:
                        self._states[timestamp] = WeatherState(*values)
                    except ValueError as exc:
                        raise WeatherDatasetError(f"invalid weather state at row {row_number}: {exc}") from exc
        except FileNotFoundError as exc:
            raise WeatherDatasetError(f"dataset not found: {self._path}") from exc
        if not self._states:
            raise WeatherDatasetError("weather dataset is empty")
        timestamps = sorted(self._states)
        for previous, current in zip(timestamps, timestamps[1:]):
            if current - previous != timedelta(hours=1):
                raise WeatherDatasetError("weather dataset must contain a continuous hourly series")

    @staticmethod
    def _parse_timestamp(value: str, row_number: int) -> datetime:
        try:
            timestamp = datetime.fromisoformat(value)
        except ValueError as exc:
            raise WeatherDatasetError(f"invalid timestamp at row {row_number}") from exc
        if timestamp.tzinfo is None:
            raise WeatherDatasetError(f"timestamp must be timezone-aware at row {row_number}")
        return timestamp.astimezone(timezone.utc)
