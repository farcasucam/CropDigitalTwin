"""Local historical weather datasets: explicit, incremental acquisition from the Open-Meteo archive and offline coverage queries.

One file per location and calendar year (``data/weather/archive/<location>/<year>.csv`` plus ``<year>.metadata.json``), so a new year is a new file and nothing already
downloaded is ever fetched again. A year is *complete* when its file holds every hour of the year; the current year is never downloaded as complete.

Nothing here runs in a simulation: simulations read the local CSV files only. The network is used by ``execute`` alone, through the explicit
``OpenMeteoClient``; ``plan`` and ``status`` never touch it.

The data are a modelled reanalysis used as simulation FORCING (``DataSourceClassification.FORCING``). They are not station measurements and are never
``REAL_VERIFIED``.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from agri_twin.infrastructure.open_meteo import (
    DEFAULT_VARIABLES,
    OpenMeteoApi,
    OpenMeteoClient,
    OpenMeteoRateLimitError,
    OpenMeteoRequest,
    OpenMeteoRequestError,
)

ROOT = Path(__file__).resolve().parents[3]
LOCATIONS_FILE = ROOT / "src" / "weather_locations.json"
ARCHIVE_DIR = ROOT / "data" / "weather" / "archive"
FIRST_YEAR = 2015
ARCHIVE_LAG_DAYS = 7  # the archive trails real time by a few days; a year ending later than today - lag is not complete yet
CLASSIFICATION = "FORCING"
SOURCE_NOTE = ("Modelled reanalysis from the Open-Meteo historical (archive) API used as simulation forcing; not station measurements, never REAL_VERIFIED. "
               "Attribution: weather data by Open-Meteo.com; check its current licence terms before redistributing.")


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

    def directory(self, archive: Path = ARCHIVE_DIR) -> Path:
        return archive / self.id


@dataclass(frozen=True, slots=True)
class PlanItem:
    location: str
    year: int
    start: date
    end: date
    csv_path: Path
    action: str          # DOWNLOAD (missing) | PRESENT (complete, nothing to do)
    requests: int

    def to_dict(self) -> dict[str, Any]:
        return {"location": self.location, "year": self.year, "start": self.start.isoformat(), "end": self.end.isoformat(), "file": str(self.csv_path), "action": self.action, "requests": self.requests}


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


def last_complete_year(today: date | None = None) -> int:
    today = today or datetime.now(timezone.utc).date()
    return today.year if date(today.year, 12, 31) <= today - timedelta(days=ARCHIVE_LAG_DAYS) else today.year - 1


def _year_file(location: Location, year: int, archive: Path) -> Path:
    return location.directory(archive) / f"{year}.csv"


def _is_complete(csv_path: Path, year: int) -> bool:
    """A year file is complete when its metadata says so and it holds every hour of that year."""
    metadata_path = csv_path.with_suffix(".metadata.json")
    if not (csv_path.is_file() and metadata_path.is_file()):
        return False
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        with csv_path.open(encoding="utf-8") as handle:
            rows = sum(1 for _ in handle) - 1
    except (OSError, ValueError):
        return False
    days = (date(year, 12, 31) - date(year, 1, 1)).days + 1
    return metadata.get("complete") is True and metadata.get("year") == year and rows == 24 * days


def plan(location_ids: Iterable[str] | None = None, start_year: int = FIRST_YEAR, end_year: int | None = None, *, today: date | None = None,
         archive: Path = ARCHIVE_DIR, locations: Mapping[str, Location] | None = None) -> list[PlanItem]:
    """What a download would do. Pure: reads the local files, never the network."""
    locations = dict(locations or load_locations())
    ids = list(location_ids) if location_ids is not None else list(locations)
    unknown = [item for item in ids if item not in locations]
    if unknown:
        raise WeatherDatasetsError(f"unknown locations: {', '.join(unknown)}; available: {', '.join(locations)}")
    end_year = last_complete_year(today) if end_year is None else end_year
    if start_year > end_year:
        raise WeatherDatasetsError("start_year cannot be after end_year")
    if end_year > last_complete_year(today):
        raise WeatherDatasetsError(f"{end_year} is not complete yet (the archive trails real time by about {ARCHIVE_LAG_DAYS} days); the last complete year is {last_complete_year(today)}")
    items = []
    for key in ids:
        location = locations[key]
        for year in range(start_year, end_year + 1):
            path = _year_file(location, year, archive)
            present = _is_complete(path, year)
            items.append(PlanItem(key, year, date(year, 1, 1), date(year, 12, 31), path, "PRESENT" if present else "DOWNLOAD", 0 if present else 1))
    return items


def execute(items: Sequence[PlanItem], client: OpenMeteoClient | None = None, *, pause_seconds: float = 2.0, retry_wait_seconds: float = 65.0, retries: int = 2,
            locations: Mapping[str, Location] | None = None, sleep: Callable[[float], None] = time.sleep,
            progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Download what ``plan`` marked DOWNLOAD (the ONLY place that uses the network). Stops at the first failure; files already written stay, so a re-run resumes."""
    locations = dict(locations or load_locations())
    client = client or OpenMeteoClient(timeout_seconds=120.0)
    say = progress or (lambda _text: None)
    done, failed = [], None
    pending = [item for item in items if item.action == "DOWNLOAD"]
    for index, item in enumerate(pending):
        location = locations[item.location]
        request = OpenMeteoRequest(location.latitude, location.longitude, item.start, item.end, DEFAULT_VARIABLES, OpenMeteoApi.HISTORICAL, "UTC", "auto", None, None)
        attempt = 0
        while True:
            try:
                say(f"[{index + 1}/{len(pending)}] {item.location} {item.year} ...")
                client.download(request, item.csv_path, metadata_context={
                    "location_id": location.id, "location_label": location.label, "crops": list(location.crops), "year": item.year, "complete": True,
                    "coordinate_status": location.status, "classification": CLASSIFICATION, "source_note": SOURCE_NOTE})
                done.append(item.to_dict())
                break
            except OpenMeteoRateLimitError as exc:
                attempt += 1
                if attempt > retries:
                    failed = {**item.to_dict(), "error": f"rate limit: {exc}"}
                    break
                say(f"  rate limit; waiting {retry_wait_seconds:.0f} s (attempt {attempt}/{retries})")
                sleep(retry_wait_seconds)
            except OpenMeteoRequestError as exc:
                failed = {**item.to_dict(), "error": str(exc)}
                break
        if failed:
            break
        if index + 1 < len(pending):
            sleep(pause_seconds)
    return {"downloaded": done, "failed": failed, "skipped_present": sum(1 for item in items if item.action == "PRESENT"), "remaining": len(pending) - len(done) - (1 if failed else 0)}


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# offline queries
# ---------------------------------------------------------------------------------------------------------------------------------------------------
def status(archive: Path = ARCHIVE_DIR, locations: Mapping[str, Location] | None = None, today: date | None = None) -> list[dict[str, Any]]:
    """Per location: the complete years on disk, the continuous coverage and what the next update would add. Offline."""
    rows = []
    for key, location in (locations or load_locations()).items():
        years = sorted(year for year in range(FIRST_YEAR, last_complete_year(today) + 1) if _is_complete(_year_file(location, year, archive), year))
        runs = _consecutive(years)
        missing = [year for year in range(FIRST_YEAR, last_complete_year(today) + 1) if year not in years]
        rows.append({"location": key, "label": location.label, "crops": list(location.crops), "years": years,
                     "coverage": [{"from": f"{run[0]}-01-01T00:00:00+00:00", "to": f"{run[-1]}-12-31T23:00:00+00:00"} for run in runs], "missing_years": missing,
                     "latitude": location.latitude, "longitude": location.longitude, "coordinate_status": location.status, "classification": CLASSIFICATION})
    return rows


def _consecutive(years: Sequence[int]) -> list[list[int]]:
    runs: list[list[int]] = []
    for year in years:
        if runs and year == runs[-1][-1] + 1:
            runs[-1].append(year)
        else:
            runs.append([year])
    return runs


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local historical weather datasets (Open-Meteo archive). 'plan' and 'status' never use the network.")
    parser.add_argument("command", choices=("plan", "status", "download", "update"))
    parser.add_argument("--locations", nargs="*", help="location ids (default: all)")
    parser.add_argument("--start-year", type=int, default=FIRST_YEAR)
    parser.add_argument("--end-year", type=int, default=None, help="default: the last complete year")
    parser.add_argument("--pause", type=float, default=2.0, help="seconds between requests")
    parser.add_argument("--confirm-network", action="store_true", help="required by download and update: they call the Open-Meteo archive")
    args = parser.parse_args(argv)
    if args.command == "status":
        print(json.dumps(status(), indent=2))
        return 0
    start = FIRST_YEAR if args.command == "update" else args.start_year
    items = plan(args.locations, start, args.end_year)
    if args.command == "plan":
        todo = [item for item in items if item.action == "DOWNLOAD"]
        print(json.dumps({"requests": len(todo), "present": len(items) - len(todo), "items": [item.to_dict() for item in items]}, indent=2))
        return 0
    if not args.confirm_network:
        parser.error("download/update call the network: add --confirm-network (see 'plan' first)")
    report = execute(items, pause_seconds=args.pause, progress=print)
    print(json.dumps(report, indent=2))
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
