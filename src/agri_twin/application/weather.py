"""Deterministic exterior weather generation."""

from __future__ import annotations

import hashlib
import math
from datetime import datetime
from threading import RLock

from agri_twin.domain.models import WeatherState
from agri_twin.domain.weather import (
    WeatherConfiguration,
    WeatherEngineValueError,
    WeatherPerturbation,
    WeatherEventType,
    normalize_utc,
)


class WeatherEngine:
    def __init__(self, configuration: WeatherConfiguration) -> None:
        self._configuration = configuration
        self._seed = configuration.simulation.seed
        self._events: dict[str, WeatherPerturbation] = {}
        self._lock = RLock()

    @property
    def configuration(self) -> WeatherConfiguration:
        return self._configuration

    @property
    def seed(self) -> int:
        return self._seed

    def generate(self, simulation_time: datetime) -> WeatherState:
        instant = normalize_utc(simulation_time)
        with self._lock:
            events = tuple(
                sorted(
                    (event for event in self._events.values() if event.is_active(instant)),
                    key=lambda event: (-event.priority, event.start_time, event.event_id),
                )
            )
        temperature = self._baseline_temperature(instant) + self._temperature_variability(instant)
        radiation = self._baseline_radiation(instant) + self._radiation_variability(instant)
        humidity = self._baseline_humidity(instant) + self._humidity_variability(instant)
        wind_speed, wind_direction = self._baseline_wind(instant)
        pressure = self._baseline_pressure(instant)
        humidity = min(
            self._configuration.humidity.maximum_pct,
            max(self._configuration.humidity.minimum_pct, humidity),
        )
        wind_speed = max(
            0.0,
            wind_speed + self._wave(instant, 4.0) * self._configuration.wind.variability_m_s,
        )
        wind_direction = (
            wind_direction
            + self._wave(instant, 5.0) * self._configuration.wind.direction_variability_deg
        ) % 360
        pressure += self._wave(instant, 6.0) * self._configuration.pressure.variability_hpa
        temperature, radiation, humidity, wind_speed, wind_direction = self._apply_events(
            events, temperature, radiation, humidity, wind_speed, wind_direction
        )
        return WeatherState(
            temperature_c=temperature,
            relative_humidity_pct=humidity,
            solar_radiation_w_m2=radiation,
            wind_speed_m_s=wind_speed,
            wind_direction_deg=wind_direction,
            rain_rate_mm_h=self._rain(events),
            pressure_hpa=pressure,
        )

    def add_perturbation(self, perturbation: WeatherPerturbation) -> None:
        with self._lock:
            if perturbation.event_id in self._events:
                raise WeatherEngineValueError(
                    f"perturbation already exists: {perturbation.event_id}"
                )
            self._events[perturbation.event_id] = perturbation

    def remove_perturbation(self, event_id: str) -> None:
        with self._lock:
            self._events.pop(event_id, None)

    def active_perturbations(self, simulation_time: datetime) -> tuple[WeatherPerturbation, ...]:
        instant = normalize_utc(simulation_time)
        with self._lock:
            return tuple(
                sorted(
                    (event for event in self._events.values() if event.is_active(instant)),
                    key=lambda event: (-event.priority, event.start_time, event.event_id),
                )
            )

    def reset(self) -> None:
        with self._lock:
            self._events.clear()

    def _baseline_temperature(self, instant: datetime) -> float:
        config = self._configuration.temperature
        hour = instant.hour + instant.minute / 60 + instant.second / 3600
        midpoint = (config.minimum_c + config.maximum_c) / 2
        amplitude = (config.maximum_c - config.minimum_c) / 2
        if config.minimum_hour <= hour <= config.maximum_hour:
            progress = (hour - config.minimum_hour) / (
                config.maximum_hour - config.minimum_hour
            )
            profile = -math.cos(math.pi * progress)
        else:
            elapsed = (hour - config.maximum_hour) % 24
            duration = (config.minimum_hour - config.maximum_hour) % 24
            profile = math.cos(math.pi * elapsed / duration)
        return midpoint + amplitude * profile

    def _temperature_variability(self, instant: datetime) -> float:
        return self._wave(instant, 1.0) * self._configuration.temperature.variability_c

    def _baseline_radiation(self, instant: datetime) -> float:
        config = self._configuration.radiation
        hour = instant.hour + instant.minute / 60 + instant.second / 3600
        if hour <= config.sunrise_hour or hour >= config.sunset_hour:
            return 0.0
        daylight = (hour - config.sunrise_hour) / (config.sunset_hour - config.sunrise_hour)
        profile = math.sin(math.pi * daylight)
        return config.maximum_w_m2 * profile

    def _radiation_variability(self, instant: datetime) -> float:
        return self._wave(instant, 2.0) * self._configuration.radiation.variability_w_m2

    def _baseline_humidity(self, instant: datetime) -> float:
        config = self._configuration.humidity
        midpoint = (config.minimum_pct + config.maximum_pct) / 2
        amplitude = (config.maximum_pct - config.minimum_pct) / 2
        hour = instant.hour + instant.minute / 60 + instant.second / 3600
        phase = 2 * math.pi * (hour - 5.0) / 24
        value = midpoint - amplitude * math.cos(phase)
        return value

    def _humidity_variability(self, instant: datetime) -> float:
        return self._wave(instant, 3.0) * self._configuration.humidity.variability_pct

    def _baseline_wind(self, instant: datetime) -> tuple[float, float]:
        config = self._configuration.wind
        speed = config.base_speed_m_s
        direction = config.base_direction_deg
        return max(0.0, speed), direction

    def _baseline_pressure(self, instant: datetime) -> float:
        config = self._configuration.pressure
        return config.base_hpa

    def _apply_events(
        self,
        events: tuple[WeatherPerturbation, ...],
        temperature: float,
        radiation: float,
        humidity: float,
        wind_speed: float,
        wind_direction: float,
    ) -> tuple[float, float, float, float, float]:
        heat_offset = sum(
            event.parameters["temperature_offset_c"]
            for event in events
            if event.event_type is WeatherEventType.HEAT_WAVE
        )
        frost_events = [event for event in events if event.event_type is WeatherEventType.FROST]
        if frost_events:
            temperature = frost_events[0].parameters["temperature_c"]
        temperature += heat_offset
        wind_multiplier = math.prod(
            event.parameters["speed_multiplier"]
            for event in events
            if event.event_type is WeatherEventType.WIND
            and "speed_multiplier" in event.parameters
        )
        wind_speed *= wind_multiplier
        direction_events = [
            event for event in events
            if event.event_type is WeatherEventType.WIND and "direction_deg" in event.parameters
        ]
        if direction_events:
            wind_direction = direction_events[0].parameters["direction_deg"]
        radiation_multiplier = math.prod(
            event.parameters["radiation_multiplier"]
            for event in events
            if event.event_type is WeatherEventType.RADIATION_ANOMALY
            and "radiation_multiplier" in event.parameters
        )
        radiation_offset = sum(
            event.parameters["radiation_offset_w_m2"]
            for event in events
            if event.event_type is WeatherEventType.RADIATION_ANOMALY
            and "radiation_offset_w_m2" in event.parameters
        )
        radiation = max(0.0, radiation * radiation_multiplier + radiation_offset)
        return temperature, radiation, humidity, wind_speed, wind_direction

    @staticmethod
    def _rain(events: tuple[WeatherPerturbation, ...]) -> float:
        rates = [
            event.parameters["rate_mm_h"]
            for event in events
            if event.event_type is WeatherEventType.RAIN
        ]
        return max(rates, default=0.0)

    def _wave(self, instant: datetime, channel: float) -> float:
        day = instant.date().toordinal()
        seconds = (
            instant.hour * 3600 + instant.minute * 60 + instant.second
            + instant.microsecond / 1_000_000
        )
        digest = hashlib.blake2b(
            f"{self._seed}:{day}:{channel}".encode("ascii"), digest_size=8
        ).digest()
        phase = int.from_bytes(digest, "big") / 2**64 * 2 * math.pi
        return math.sin(2 * math.pi * seconds / 86400 + phase)
