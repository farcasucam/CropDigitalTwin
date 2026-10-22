"""Reference evapotranspiration by the FAO-56 Penman-Monteith equation for hourly periods.

Allen, Pereira, Raes and Smith (1998), FAO Irrigation and Drainage Paper 56, "Crop evapotranspiration": equation 53 (hourly ET0), 28 (hourly extraterrestrial radiation),
37 (clear-sky radiation), 39 and 40 (net radiation), 47 (wind at 2 m) and 7, 12, 13 (pressure, saturation vapour pressure and its slope). Every constant below is the paper's.
It replaces nothing by default: the historical Hargreaves-like estimate of ``WaterBalanceEngine`` stays the default so earlier phases and hashes do not move.

What the equation needs and where each input comes from:
* air temperature, relative humidity, wind speed, pressure and solar radiation: the ``WeatherState`` of the step (the crop's microclimate inside a greenhouse);
* the site (latitude, longitude, elevation): the plot or the weather location, never a default;
* the radiation ratio Rs/Rso of the sky (clipped to 0.3-1.0 as in the paper): computed from the outdoor radiation of the step; at night, as the paper prescribes, from the hour two hours
  before the last sunlit hour (``radiation_probe`` supplies the outdoor radiation of a past step: weather is a pure function of time, so probing is exact and repeatable).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from agri_twin.domain.models import WeatherState

SOLAR_CONSTANT_MJ_M2_MIN = 0.0820
STEFAN_BOLTZMANN_MJ_K4_M2_H = 2.043e-10  # 4.903e-9 MJ K-4 m-2 day-1 per hour
ALBEDO = 0.23  # FAO-56 reference grass
MIN_CLOUDINESS, MAX_CLOUDINESS = 0.3, 1.0
W_M2_TO_MJ_M2_H = 0.0036


class EvapotranspirationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Et0Site:
    latitude_deg: float
    longitude_deg: float  # east positive
    elevation_m: float | None = None  # None: derived from the station pressure of the weather (FAO-56 eq. 7 inverted)

    def __post_init__(self) -> None:
        if not (-90.0 <= self.latitude_deg <= 90.0 and -180.0 <= self.longitude_deg <= 180.0):
            raise EvapotranspirationError("site coordinates are out of range")


def saturation_vapour_pressure_kpa(temperature_c: float) -> float:
    return 0.6108 * math.exp(17.27 * temperature_c / (temperature_c + 237.3))


def saturation_slope_kpa_c(temperature_c: float) -> float:
    return 4098.0 * saturation_vapour_pressure_kpa(temperature_c) / (temperature_c + 237.3) ** 2


def elevation_from_pressure_m(pressure_kpa: float) -> float:
    return (293.0 - 293.0 * (pressure_kpa / 101.3) ** (1.0 / 5.26)) / 0.0065


def wind_at_2_m(speed_m_s: float, height_m: float) -> float:
    if height_m <= 0.0:
        raise EvapotranspirationError("the wind measurement height must be positive")
    return speed_m_s if height_m == 2.0 else speed_m_s * 4.87 / math.log(67.8 * height_m - 5.42)


def penman_monteith_hourly_mm(temperature_c: float, actual_vapour_pressure_kpa: float, wind_2m_m_s: float, net_radiation_mj_m2_h: float, soil_heat_flux_mj_m2_h: float,
                              pressure_kpa: float) -> float:
    """FAO-56 equation 53, mm per hour. The core of the method, separated so it can be checked against the paper's worked example."""
    delta = saturation_slope_kpa_c(temperature_c)
    gamma = 0.000665 * pressure_kpa
    saturation_deficit = max(0.0, saturation_vapour_pressure_kpa(temperature_c) - actual_vapour_pressure_kpa)
    radiative = 0.408 * delta * (net_radiation_mj_m2_h - soil_heat_flux_mj_m2_h)
    aerodynamic = gamma * 37.0 / (temperature_c + 273.0) * wind_2m_m_s * saturation_deficit
    return max(0.0, (radiative + aerodynamic) / (delta + gamma * (1.0 + 0.34 * wind_2m_m_s)))


def extraterrestrial_radiation_mj_m2(site: Et0Site, midpoint_utc: datetime, hours: float = 1.0) -> float:
    """FAO-56 equation 28 for a period of ``hours`` centred on ``midpoint_utc`` (zero when the sun is below the horizon). Solar time uses the site longitude (zone centre = UTC)."""
    when = midpoint_utc.astimezone(timezone.utc)
    day_of_year = when.timetuple().tm_yday
    latitude = math.radians(site.latitude_deg)
    earth_sun = 1.0 + 0.033 * math.cos(2.0 * math.pi * day_of_year / 365.0)
    declination = 0.409 * math.sin(2.0 * math.pi * day_of_year / 365.0 - 1.39)
    b = 2.0 * math.pi * (day_of_year - 81.0) / 364.0
    seasonal_correction_h = 0.1645 * math.sin(2.0 * b) - 0.1255 * math.cos(b) - 0.025 * math.sin(b)
    clock_h = when.hour + when.minute / 60.0 + when.second / 3600.0
    solar_h = clock_h + site.longitude_deg / 15.0 + seasonal_correction_h
    omega = math.pi / 12.0 * (solar_h - 12.0)
    omega = (omega + math.pi) % (2.0 * math.pi) - math.pi
    argument = -math.tan(latitude) * math.tan(declination)
    sunset = math.pi if argument <= -1.0 else 0.0 if argument >= 1.0 else math.acos(argument)
    start, end = max(omega - math.pi * hours / 24.0, -sunset), min(omega + math.pi * hours / 24.0, sunset)
    if end <= start:
        return 0.0
    ra = 12.0 * 60.0 / math.pi * SOLAR_CONSTANT_MJ_M2_MIN * earth_sun * ((end - start) * math.sin(latitude) * math.sin(declination)
                                                                          + math.cos(latitude) * math.cos(declination) * (math.sin(end) - math.sin(start)))
    return max(0.0, ra)


class PenmanMonteithEt0:
    """Hourly FAO-56 reference evapotranspiration of a site."""

    def __init__(self, site: Et0Site, wind_height_m: float, radiation_probe: Callable[[datetime], float], indoor_wind_m_s: float = 0.0) -> None:
        if wind_height_m <= 0.0 or indoor_wind_m_s < 0.0 or not math.isfinite(indoor_wind_m_s):
            raise EvapotranspirationError("wind height must be positive and the indoor wind speed non-negative")
        self.site, self.wind_height_m, self.indoor_wind_m_s, self._probe = site, wind_height_m, indoor_wind_m_s, radiation_probe

    def cloudiness(self, label: datetime, elevation_m: float, hours: float) -> float:
        """Rs/Rso of the sky for the period ending at ``label``, clipped to the paper's 0.3-1.0. By night: the value two hours before the last sunlit hour (paper, section on net radiation)."""
        def at(step_label: datetime) -> float | None:
            ra = extraterrestrial_radiation_mj_m2(self.site, step_label - timedelta(hours=hours / 2.0), hours)
            if ra <= 0.0:
                return None
            clear_sky = (0.75 + 2e-5 * elevation_m) * ra
            return min(MAX_CLOUDINESS, max(MIN_CLOUDINESS, self._probe(step_label) * W_M2_TO_MJ_M2_H * hours / clear_sky))

        value = at(label)
        if value is not None:
            return value
        last_sunlit = next((back for back in range(1, 37) if at(label - timedelta(hours=back * hours)) is not None), None)
        if last_sunlit is None:  # polar night: no sunlit hour in the last day and a half
            return MAX_CLOUDINESS
        earlier = at(label - timedelta(hours=(last_sunlit + 2) * hours))
        return earlier if earlier is not None else at(label - timedelta(hours=last_sunlit * hours))  # type: ignore[return-value]

    def mm(self, weather: WeatherState, label: datetime, dt_seconds: float, indoors: bool = False) -> float:
        hours = dt_seconds / 3600.0
        pressure_kpa = weather.pressure_hpa / 10.0
        elevation_m = self.site.elevation_m if self.site.elevation_m is not None else elevation_from_pressure_m(pressure_kpa)
        temperature = weather.temperature_c
        saturation = saturation_vapour_pressure_kpa(temperature)
        actual = saturation * min(100.0, max(0.0, weather.relative_humidity_pct)) / 100.0
        solar_mj = weather.solar_radiation_w_m2 * W_M2_TO_MJ_M2_H * hours
        ratio = self.cloudiness(label, elevation_m, hours)
        net_shortwave = (1.0 - ALBEDO) * solar_mj
        net_longwave = STEFAN_BOLTZMANN_MJ_K4_M2_H * hours * (temperature + 273.16) ** 4 * (0.34 - 0.14 * math.sqrt(actual)) * (1.35 * ratio - 0.35)
        net = net_shortwave - net_longwave
        ra = extraterrestrial_radiation_mj_m2(self.site, label - timedelta(hours=hours / 2.0), hours)
        soil_flux = (0.1 if ra > 0.0 else 0.5) * net  # daylight / night, FAO-56 eq. 45-46
        wind = self.indoor_wind_m_s if indoors else wind_at_2_m(weather.wind_speed_m_s, self.wind_height_m)
        rate = penman_monteith_hourly_mm(temperature, actual, wind, net / hours, soil_flux / hours, pressure_kpa)
        return rate * hours
