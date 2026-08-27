"""Domain configuration and perturbations for exterior weather."""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class WeatherEngineValueError(ValueError):
    """Raised when weather configuration or events are invalid."""


class WeatherEventType(str, Enum):
    RAIN = "rain"
    FROST = "frost"
    HEAT_WAVE = "heatwave"
    WIND = "wind"
    RADIATION_ANOMALY = "solar_radiation"


def normalize_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise WeatherEngineValueError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc)


def _finite(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise WeatherEngineValueError(f"{name} must be finite")
    return float(value)


def _finite_configuration(configuration: object) -> None:
    for item in fields(configuration):
        _finite(item.name, getattr(configuration, item.name))


@dataclass(frozen=True, slots=True)
class TemperatureConfiguration:
    minimum_c: float = 12.0
    maximum_c: float = 30.0
    minimum_hour: float = 5.0
    maximum_hour: float = 15.0
    variability_c: float = 0.5

    def __post_init__(self) -> None:
        _finite_configuration(self)
        if self.minimum_c > self.maximum_c:
            raise WeatherEngineValueError("temperature minimum cannot exceed maximum")
        if not 0 <= self.minimum_hour < 24 or not 0 <= self.maximum_hour < 24:
            raise WeatherEngineValueError("temperature hours must be within a day")
        if self.variability_c < 0:
            raise WeatherEngineValueError("temperature variability cannot be negative")


@dataclass(frozen=True, slots=True)
class RadiationConfiguration:
    maximum_w_m2: float = 900.0
    sunrise_hour: float = 6.0
    sunset_hour: float = 18.0
    variability_w_m2: float = 15.0

    def __post_init__(self) -> None:
        _finite_configuration(self)
        if self.maximum_w_m2 < 0 or self.variability_w_m2 < 0:
            raise WeatherEngineValueError("radiation values cannot be negative")
        if not 0 <= self.sunrise_hour < self.sunset_hour <= 24:
            raise WeatherEngineValueError("radiation hours must be ordered within a day")


@dataclass(frozen=True, slots=True)
class HumidityConfiguration:
    minimum_pct: float = 35.0
    maximum_pct: float = 90.0
    variability_pct: float = 2.0

    def __post_init__(self) -> None:
        _finite_configuration(self)
        if not 0 <= self.minimum_pct <= self.maximum_pct <= 100:
            raise WeatherEngineValueError("humidity limits must be between 0 and 100")
        if self.variability_pct < 0:
            raise WeatherEngineValueError("humidity variability cannot be negative")


@dataclass(frozen=True, slots=True)
class WindConfiguration:
    base_speed_m_s: float = 2.0
    variability_m_s: float = 0.5
    base_direction_deg: float = 180.0
    direction_variability_deg: float = 20.0

    def __post_init__(self) -> None:
        _finite_configuration(self)
        if self.base_speed_m_s < 0 or self.variability_m_s < 0:
            raise WeatherEngineValueError("wind speeds cannot be negative")
        if not 0 <= self.base_direction_deg < 360 or self.direction_variability_deg < 0:
            raise WeatherEngineValueError("wind direction configuration is invalid")


@dataclass(frozen=True, slots=True)
class PressureConfiguration:
    base_hpa: float = 1013.0
    variability_hpa: float = 4.0

    def __post_init__(self) -> None:
        _finite_configuration(self)
        if self.variability_hpa < 0:
            raise WeatherEngineValueError("pressure variability cannot be negative")


@dataclass(frozen=True, slots=True)
class WeatherSimulationConfiguration:
    seed: int = 0
    publication_interval_seconds: int = 60

    def __post_init__(self) -> None:
        if not isinstance(self.seed, int) or isinstance(self.seed, bool):
            raise WeatherEngineValueError("seed must be an integer")
        if (
            not isinstance(self.publication_interval_seconds, int)
            or isinstance(self.publication_interval_seconds, bool)
            or self.publication_interval_seconds <= 0
        ):
            raise WeatherEngineValueError("publication interval must be positive")


@dataclass(frozen=True, slots=True)
class WeatherConfiguration:
    temperature: TemperatureConfiguration = TemperatureConfiguration()
    radiation: RadiationConfiguration = RadiationConfiguration()
    humidity: HumidityConfiguration = HumidityConfiguration()
    wind: WindConfiguration = WindConfiguration()
    pressure: PressureConfiguration = PressureConfiguration()
    simulation: WeatherSimulationConfiguration = WeatherSimulationConfiguration()

    def __post_init__(self) -> None:
        if not all(isinstance(value, tuple(expected)) for value, expected in (
            (self.temperature, (TemperatureConfiguration,)),
            (self.radiation, (RadiationConfiguration,)),
            (self.humidity, (HumidityConfiguration,)),
            (self.wind, (WindConfiguration,)),
            (self.pressure, (PressureConfiguration,)),
            (self.simulation, (WeatherSimulationConfiguration,)),
        )):
            raise WeatherEngineValueError("weather configuration sections have invalid types")


@dataclass(frozen=True, slots=True)
class WeatherPerturbation:
    event_id: str
    event_type: WeatherEventType
    start_time: datetime
    end_time: datetime
    priority: int
    source: str
    parameters: Mapping[str, float]

    def __post_init__(self) -> None:
        start = normalize_utc(self.start_time)
        end = normalize_utc(self.end_time)
        if not self.event_id or not self.source or end < start:
            raise WeatherEngineValueError("event identity and interval are invalid")
        if not isinstance(self.priority, int) or isinstance(self.priority, bool):
            raise WeatherEngineValueError("priority must be an integer")
        if not isinstance(self.event_type, WeatherEventType):
            raise WeatherEngineValueError("event_type is invalid")
        values = dict(self.parameters)
        _validate_parameters(self.event_type, values)
        object.__setattr__(self, "start_time", start)
        object.__setattr__(self, "end_time", end)
        object.__setattr__(self, "parameters", MappingProxyType(values))

    def is_active(self, simulation_time: datetime) -> bool:
        instant = normalize_utc(simulation_time)
        return self.start_time <= instant < self.end_time


def _validate_parameters(event_type: WeatherEventType, parameters: dict[str, float]) -> None:
    expected = {
        WeatherEventType.RAIN: {"rate_mm_h"},
        WeatherEventType.FROST: {"temperature_c"},
        WeatherEventType.HEAT_WAVE: {"temperature_offset_c"},
        WeatherEventType.WIND: {"speed_multiplier", "direction_deg"},
        WeatherEventType.RADIATION_ANOMALY: {"radiation_multiplier", "radiation_offset_w_m2"},
    }
    if not parameters or not set(parameters).issubset(expected[event_type]):
        raise WeatherEngineValueError(f"invalid parameters for {event_type.value}")
    for name, value in parameters.items():
        _finite(name, value)
    if event_type is WeatherEventType.RAIN and parameters["rate_mm_h"] < 0:
        raise WeatherEngineValueError("rain rate cannot be negative")
    if event_type is WeatherEventType.WIND and "speed_multiplier" in parameters and parameters["speed_multiplier"] <= 0:
        raise WeatherEngineValueError("wind speed multiplier must be positive")
    if event_type is WeatherEventType.WIND and "direction_deg" in parameters and not 0 <= parameters["direction_deg"] < 360:
        raise WeatherEngineValueError("wind direction must be in [0, 360)")
    if event_type is WeatherEventType.RADIATION_ANOMALY and "radiation_multiplier" in parameters and parameters["radiation_multiplier"] < 0:
        raise WeatherEngineValueError("radiation multiplier cannot be negative")


