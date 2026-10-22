"""Local historical weather datasets, as a simulation uses them: coverage, provenance and hourly weather read from the downloaded year files.

Everything here is offline and clock-free. Downloading (the only place that uses the network, the wall clock and pauses) lives in
``agri_twin.infrastructure.weather_archive``.

One file per location and calendar year: ``data/weather/archive/<location>/<year>.csv`` plus ``<year>.metadata.json``. A year is *complete* when its file holds every
hour of the year. The data are a modelled reanalysis used as simulation FORCING (``DataSourceClassification.FORCING``): not station measurements, never ``REAL_VERIFIED``.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from agri_twin.application.providers import WeatherTimestampNotAvailable
from agri_twin.domain.models import WeatherState
from agri_twin.infrastructure.csv_weather import COLUMNS

ROOT = Path(__file__).resolve().parents[3]
LOCATIONS_FILE = ROOT / "src" / "weather_locations.json"
ARCHIVE_DIR = ROOT / "data" / "weather" / "archive"
FIRST_YEAR = 2015
CLASSIFICATION = "FORCING"
SOURCE_NOTE = ("Modelled reanalysis from the Open-Meteo historical (archive) API used as simulation forcing; not station measurements, never REAL_VERIFIED. "
               "Attribution: weather data by Open-Meteo.com; check its current licence terms before redistributing.")
LOCAL_SOURCE = "LOCAL_ARCHIVE"


class WeatherDatasetsError(ValueError):
    """Invalid request for a local dataset (unknown location, bad year range, ...)."""


@dataclass(frozen=True, slots=True)
class Location:
    id: str
    label: str
    crops: tuple[str, ...]
    latitude: float
    longitude: float
    status: str

    def directory(self, archive: Path | None = None) -> Path:
        return (archive or ARCHIVE_DIR) / self.id


def load_locations(path: Path = LOCATIONS_FILE) -> dict[str, Location]:
    document = json.loads(path.read_text(encoding="utf-8"))
    status = str(document.get("coordinate_status", "UNKNOWN"))
    locations = {}
    for key, item in document["locations"].items():
        latitude, longitude = float(item["latitude"]), float(item["longitude"])
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise WeatherDatasetsError(f"location {key}: coordinates out of range")
        locations[key] = Location(key, str(item["label"]), tuple(item["crops"]), latitude, longitude, status)
    return locations


def location_for_crop(crop: str, locations: Mapping[str, Location] | None = None) -> Location:
    for location in (locations or load_locations()).values():
        if crop in location.crops:
            return location
    raise WeatherDatasetsError(f"no weather location is configured for crop {crop!r}")


def _year_file(location: Location, year: int, archive: Path) -> Path:
    return location.directory(archive) / f"{year}.csv"


def _is_complete(csv_path: Path, year: int) -> bool:
    """A year file is complete when its metadata says so and it holds every hour of that year (cached by the files' size and modification time)."""
    metadata_path = csv_path.with_suffix(".metadata.json")
    try:
        csv_stat, metadata_stat = csv_path.stat(), metadata_path.stat()
    except OSError:
        return False
    return _is_complete_cached(str(csv_path), year, csv_stat.st_mtime_ns, csv_stat.st_size, metadata_stat.st_mtime_ns)


@lru_cache(maxsize=2048)
def _is_complete_cached(csv_path: str, year: int, csv_mtime: int, csv_size: int, metadata_mtime: int) -> bool:
    del csv_mtime, csv_size, metadata_mtime  # cache key only
    path = Path(csv_path)
    try:
        metadata = json.loads(path.with_suffix(".metadata.json").read_text(encoding="utf-8"))
        with path.open("rb") as handle:  # counting newlines in binary is an order of magnitude faster than parsing lines
            rows = sum(chunk.count(b"\n") for chunk in iter(lambda: handle.read(1 << 20), b"")) - 1
    except (OSError, ValueError):
        return False
    days = (date(year, 12, 31) - date(year, 1, 1)).days + 1
    return metadata.get("complete") is True and metadata.get("year") == year and rows == 24 * days


def _consecutive(years: Sequence[int]) -> list[list[int]]:
    runs: list[list[int]] = []
    for year in years:
        if runs and year == runs[-1][-1] + 1:
            runs[-1].append(year)
        else:
            runs.append([year])
    return runs


@dataclass(frozen=True, slots=True)
class DatasetInfo:
    """The continuous run of complete years a crop's location can offer to a simulation."""

    location: Location
    years: tuple[int, ...]
    first: datetime   # first hour available (UTC)
    last: datetime    # last hour available (UTC)

    def to_dict(self) -> dict[str, Any]:
        return {"location_id": self.location.id, "label": self.location.label, "latitude": self.location.latitude, "longitude": self.location.longitude,
                "coordinate_status": self.location.status, "classification": CLASSIFICATION, "years": list(self.years),
                "first": self.first.isoformat(), "last": self.last.isoformat()}


def _complete_years(location: Location, archive: Path) -> list[int]:
    directory = location.directory(archive)
    if not directory.is_dir():
        return []
    years = sorted(int(path.stem) for path in directory.glob("*.csv") if path.stem.isdigit())
    return [year for year in years if _is_complete(_year_file(location, year, archive), year)]


def dataset_info(crop: str, archive: Path | None = None, locations: Mapping[str, Location] | None = None) -> DatasetInfo | None:
    """The most recent continuous run of complete years for the crop's location; ``None`` when nothing has been downloaded. Offline."""
    archive = archive or ARCHIVE_DIR
    location = location_for_crop(crop, locations)
    years = _complete_years(location, archive)
    if not years:
        return None
    run = _consecutive(years)[-1]
    return DatasetInfo(location, tuple(run), datetime(run[0], 1, 1, tzinfo=timezone.utc), datetime(run[-1], 12, 31, 23, tzinfo=timezone.utc))


def dataset_fingerprint(location_id: str, years: Iterable[int], archive: Path | None = None) -> str:
    """Identity of the data a run read (provenance of the files, not their bytes): changes when a file is re-downloaded or its location changes."""
    archive = archive or ARCHIVE_DIR
    parts = []
    for year in sorted(years):
        metadata = json.loads((archive / location_id / f"{year}.metadata.json").read_text(encoding="utf-8"))
        parts.append([year, metadata.get("retrieved_at"), metadata.get("latitude"), metadata.get("longitude"), metadata.get("elevation"), metadata.get("endpoint")])
    return hashlib.sha256(json.dumps([location_id, parts], sort_keys=True).encode("utf-8")).hexdigest()


@lru_cache(maxsize=24)
def _load_year(location_id: str, year: int, archive: str, fingerprint: str) -> dict[datetime, WeatherState]:
    del fingerprint  # part of the cache key only: a re-downloaded file is read again
    states: dict[datetime, WeatherState] = {}
    with (Path(archive) / location_id / f"{year}.csv").open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise WeatherDatasetsError(f"{location_id}/{year}.csv: header does not match the required columns")
        for row in reader:
            values = [float(row[name]) for name in COLUMNS[1:]]
            if not all(math.isfinite(value) for value in values):
                raise WeatherDatasetsError(f"{location_id}/{year}.csv: non-finite value at {row['timestamp']}")
            states[datetime.fromisoformat(row["timestamp"]).astimezone(timezone.utc)] = WeatherState(*values)
    return states


class ArchiveWeatherProvider:
    """Hourly weather of one location read from the local year files. Never uses the network; an hour outside the downloaded years is an error, not a guess."""

    source = "LOCAL_ARCHIVE_REANALYSIS"
    forcing_type = "SIMULATION_FORCING"

    def __init__(self, location_id: str, archive: Path | None = None) -> None:
        self._location, self._archive = location_id, archive or ARCHIVE_DIR
        self._fingerprints: dict[int, str] = {}

    def _year(self, year: int) -> dict[datetime, WeatherState]:
        path = self._archive / self._location / f"{year}.csv"
        if year not in self._fingerprints:
            if not path.is_file():
                raise WeatherTimestampNotAvailable(f"no local weather for {self._location} in {year}")
            self._fingerprints[year] = dataset_fingerprint(self._location, [year], self._archive)
        return _load_year(self._location, year, str(self._archive), self._fingerprints[year])

    def get(self, simulation_time: datetime) -> WeatherState:
        if simulation_time.tzinfo is None:
            raise WeatherDatasetsError("simulation_time must be timezone-aware")
        instant = simulation_time.astimezone(timezone.utc)
        try:
            return self._year(instant.year)[instant]
        except KeyError:
            raise WeatherTimestampNotAvailable(instant.isoformat()) from None


def archive_weather_factory(location_id: str, archive: Path | None = None) -> Callable[[Any], ArchiveWeatherProvider]:
    return lambda _scenario: ArchiveWeatherProvider(location_id, archive)
