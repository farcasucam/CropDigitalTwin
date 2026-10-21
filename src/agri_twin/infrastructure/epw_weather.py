"""Convert the project's hourly weather CSV into an EnergyPlus EPW file.

The CSV carries global horizontal radiation only, so direct and diffuse components are DERIVED here (Erbs
decomposition at the solar position of mid-hour). Fields the CSV does not carry are written as the EPW
"missing" code. Nothing is interpolated: gaps are rejected. The output is deterministic.

Time convention (``HourConvention``): EPW record N describes the hour ending at N. With END_OF_HOUR (default, the
Open-Meteo convention for radiation) a CSV row stamped T becomes the hour ending at T; the zone state at simulated
time T therefore sees that row at the end of the hour. START_OF_HOUR places the row in the hour beginning at T.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Sequence
from enum import Enum
from pathlib import Path

from agri_twin.domain.greenhouse import saturation_vapour_pressure_kpa
from agri_twin.domain.models import WeatherState

SOLAR_CONSTANT_W_M2 = 1367.0


class EpwConversionError(ValueError):
    """Raised when the weather series cannot be converted without inventing data."""


class HourConvention(str, Enum):
    END_OF_HOUR = "END_OF_HOUR"
    START_OF_HOUR = "START_OF_HOUR"


@dataclass(frozen=True, slots=True)
class EpwLocation:
    latitude_deg: float
    longitude_deg: float
    elevation_m: float
    name: str = "Greenhouse Site"
    country: str = "N/A"

    def __post_init__(self) -> None:
        if not -90 <= self.latitude_deg <= 90 or not -180 <= self.longitude_deg <= 180:
            raise EpwConversionError("latitude/longitude out of range")
        if not math.isfinite(self.elevation_m):
            raise EpwConversionError("elevation must be finite")


@dataclass(frozen=True, slots=True)
class EpwConversionReport:
    path: Path
    sha256: str
    records: int
    first_hour_end_utc: str
    last_hour_end_utc: str
    trimmed_rows: int
    hour_convention: str
    derived_fields: tuple[str, ...]
    missing_fields: tuple[str, ...]
    assumptions: tuple[str, ...]


def _solar(mid: datetime, location: EpwLocation) -> tuple[float, float]:
    """Return (cos zenith, extraterrestrial normal irradiance W/m2) at a UTC instant (NOAA approximations)."""
    doy = mid.timetuple().tm_yday
    frac_hour = mid.hour + mid.minute / 60.0 + mid.second / 3600.0
    g = 2.0 * math.pi / 365.0 * (doy - 1 + (frac_hour - 12.0) / 24.0)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g) - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    true_solar_minutes = frac_hour * 60.0 + eqtime + 4.0 * location.longitude_deg
    hour_angle = math.radians(true_solar_minutes / 4.0 - 180.0)
    lat = math.radians(location.latitude_deg)
    cos_zenith = math.sin(lat) * math.sin(decl) + math.cos(lat) * math.cos(decl) * math.cos(hour_angle)
    normal = SOLAR_CONSTANT_W_M2 * (1.0 + 0.033 * math.cos(2.0 * math.pi * doy / 365.0))
    return cos_zenith, normal


def erbs_components(ghi: float, cos_zenith: float, extraterrestrial_normal: float) -> tuple[float, float]:
    """Return (DNI, DHI) from global horizontal irradiance using the Erbs diffuse-fraction correlation."""
    if ghi <= 0.0 or cos_zenith <= 0.05:
        return 0.0, max(0.0, ghi)
    horizontal_et = extraterrestrial_normal * cos_zenith
    kt = min(1.0, ghi / horizontal_et)
    if kt <= 0.22:
        kd = 1.0 - 0.09 * kt
    elif kt <= 0.80:
        kd = 0.9511 - 0.1604 * kt + 4.388 * kt**2 - 16.638 * kt**3 + 12.336 * kt**4
    else:
        kd = 0.165
    dhi = kd * ghi
    dni = min(max(0.0, (ghi - dhi) / cos_zenith), extraterrestrial_normal)
    return dni, dhi


def dew_point_c(temperature_c: float, relative_humidity_pct: float) -> float:
    """Dew point as the temperature whose saturation pressure equals the actual vapour pressure.

    Inverts the project's single saturation-pressure definition by bisection instead of repeating its constants.
    """
    target = saturation_vapour_pressure_kpa(temperature_c) * max(relative_humidity_pct, 1.0) / 100.0
    low, high = -80.0, temperature_c
    for _ in range(80):
        middle = (low + high) / 2.0
        if saturation_vapour_pressure_kpa(middle) < target:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def _fmt(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}"


def write_epw(
    csv_path: str | Path,
    destination: str | Path,
    location: EpwLocation,
    hour_convention: HourConvention = HourConvention.END_OF_HOUR,
) -> EpwConversionReport:
    # csv_weather and the application package import each other; loading `application` first breaks the cycle.
    import agri_twin.application  # noqa: F401
    from agri_twin.infrastructure.csv_weather import CsvWeatherProvider

    provider = CsvWeatherProvider(csv_path)
    stamps = sorted(provider.timestamps)
    if not stamps:
        raise EpwConversionError("weather CSV has no rows")
    # CsvWeatherProvider already rejects gaps and non-hourly spacing, so the series is contiguous here.
    return write_epw_from_states([(stamp, provider.get(stamp)) for stamp in stamps], destination, location, hour_convention)


def write_epw_from_states(
    series: Sequence[tuple[datetime, WeatherState]],
    destination: str | Path,
    location: EpwLocation,
    hour_convention: HourConvention = HourConvention.END_OF_HOUR,
    solar_factors: Sequence[float] | None = None,
) -> EpwConversionReport:
    """Write an EPW from an in-memory hourly series of (timestamp, WeatherState).

    ``solar_factors`` optionally scales the solar radiation of each row (0..1), used to model an external shade screen
    before the light reaches the cover. The series must be strictly hourly and contiguous.
    """
    if not series:
        raise EpwConversionError("weather series is empty")
    stamps = [stamp for stamp, _ in series]
    states = [state for _, state in series]
    if solar_factors is not None and len(solar_factors) != len(series):
        raise EpwConversionError("solar_factors must have one value per row")
    step = timedelta(hours=1)
    if any(later - earlier != step for earlier, later in zip(stamps, stamps[1:])):
        raise EpwConversionError("weather series is not contiguous hourly")
    offset = timedelta(0) if hour_convention is HourConvention.END_OF_HOUR else step
    ends = [(s + offset).astimezone(timezone.utc) for s in stamps]

    # EPW days run hour 1..24; keep whole days only so EnergyPlus never sees a partial day.
    def epw_day(end: datetime) -> tuple[int, int, int]:
        day = end - timedelta(seconds=1)
        return day.year, day.month, day.day

    counts: dict[tuple[int, int, int], int] = {}
    for end in ends:
        counts[epw_day(end)] = counts.get(epw_day(end), 0) + 1
    keep = [i for i, end in enumerate(ends) if counts[epw_day(end)] == 24]
    if not keep:
        raise EpwConversionError("series does not contain a full 24-hour EPW day")
    trimmed = len(stamps) - len(keep)

    rows: list[str] = []
    for i in keep:
        end = ends[i]
        weather = states[i]
        factor = 1.0 if solar_factors is None else min(1.0, max(0.0, solar_factors[i]))
        ghi = weather.solar_radiation_w_m2 * factor
        mid = end - timedelta(minutes=30)
        cos_zenith, i0n = _solar(mid, location)
        dni, dhi = erbs_components(ghi, cos_zenith, i0n)
        et_horizontal = max(0.0, i0n * cos_zenith)
        day = epw_day(end)
        hour = 24 if end.hour == 0 else end.hour
        fields = [
            day[0], day[1], day[2], hour, 60,
            "?9?9?9?9E0?9?9?9?9?9?9?9?9?9?9?9?9?9?9?9*9*9?9?9?9",
            _fmt(weather.temperature_c), _fmt(dew_point_c(weather.temperature_c, weather.relative_humidity_pct)),
            _fmt(weather.relative_humidity_pct, 0), _fmt(weather.pressure_hpa * 100.0, 0),
            _fmt(et_horizontal, 0), _fmt(i0n, 0), "9999",
            _fmt(ghi, 0), _fmt(dni, 0), _fmt(dhi, 0),
            "999999", "999999", "999999", "9999",
            _fmt(weather.wind_direction_deg, 0), _fmt(weather.wind_speed_m_s),
            "99", "99", "9999", "99999", "1", "999999999", "999", ".999", "999", "99", "999",
            _fmt(weather.rain_rate_mm_h), "1",
        ]
        rows.append(",".join(str(f) for f in fields))

    first_end, last_end = ends[keep[0]], ends[keep[-1]]
    first_day, last_day = epw_day(first_end), epw_day(last_end)
    start_weekday = datetime(*first_day, tzinfo=timezone.utc).strftime("%A")
    header = [
        f"LOCATION,{location.name},N/A,{location.country},agri_twin CSV,000000,{location.latitude_deg:.4f},{location.longitude_deg:.4f},0.0,{location.elevation_m:.1f}",
        "DESIGN CONDITIONS,0",
        "TYPICAL/EXTREME PERIODS,0",
        "GROUND TEMPERATURES,0",
        "HOLIDAYS/DAYLIGHT SAVINGS,No,0,0,0",
        "COMMENTS 1,Generated from an hourly CSV; direct/diffuse radiation derived by Erbs decomposition; time zone is UTC",
        f"COMMENTS 2,Hour convention {hour_convention.value}; missing fields use EPW missing codes",
        f"DATA PERIODS,1,1,Data,{start_weekday},{first_day[1]}/{first_day[2]},{last_day[1]}/{last_day[2]}",
    ]
    text = "\n".join(header + rows) + "\n"
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8"))
    return EpwConversionReport(
        path=target,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        records=len(rows),
        first_hour_end_utc=first_end.isoformat(),
        last_hour_end_utc=last_end.isoformat(),
        trimmed_rows=trimmed,
        hour_convention=hour_convention.value,
        derived_fields=("dew_point_c", "extraterrestrial_radiation", "direct_normal_radiation", "diffuse_horizontal_radiation"),
        missing_fields=(
            "horizontal_infrared", "illuminance", "total_sky_cover", "opaque_sky_cover", "visibility", "ceiling_height",
            "present_weather", "precipitable_water", "aerosol_optical_depth", "snow_depth", "albedo",
        ),
        assumptions=(
            "time zone UTC",
            f"hour convention {hour_convention.value}",
            "Erbs decomposition (no measured DNI/DHI)",
            "sky cover/infrared missing: EnergyPlus derives sky temperature itself",
            "rain rate treated as liquid precipitation depth of the hour",
        ),
    )


__all__ = [
    "EpwConversionError", "EpwConversionReport", "EpwLocation", "HourConvention",
    "dew_point_c", "erbs_components", "write_epw", "write_epw_from_states",
]
