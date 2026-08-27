"""Offline weather provider abstractions and scenario composition."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Protocol

from agri_twin.application.weather import WeatherEngine
from agri_twin.domain.models import WeatherState
from agri_twin.domain.weather import WeatherEventType, WeatherPerturbation, normalize_utc


class WeatherProvider(Protocol):
    def get(self, simulation_time: datetime) -> WeatherState: ...


class WeatherProviderError(Exception):
    """Base error for weather providers."""


class WeatherTimestampNotAvailable(WeatherProviderError):
    """Raised when a provider has no exact observation for a timestamp."""


class SyntheticWeatherProvider:
    """Provider facade that delegates all generation to WeatherEngine."""

    def __init__(self, engine: WeatherEngine) -> None:
        self._engine = engine

    def get(self, simulation_time: datetime) -> WeatherState:
        return self._engine.generate(simulation_time)

    def add_perturbation(self, perturbation: WeatherPerturbation) -> None:
        self._engine.add_perturbation(perturbation)

    def remove_perturbation(self, event_id: str) -> None:
        self._engine.remove_perturbation(event_id)

    def reset(self) -> None:
        self._engine.reset()


class ScenarioWeatherProvider:
    """Apply immutable perturbations to any base weather provider."""

    def __init__(self, base_provider: WeatherProvider) -> None:
        self._base_provider = base_provider
        self._events: dict[str, WeatherPerturbation] = {}

    def get(self, simulation_time: datetime) -> WeatherState:
        instant = normalize_utc(simulation_time)
        state = self._base_provider.get(instant)
        events = tuple(
            sorted(
                (event for event in self._events.values() if event.is_active(instant)),
                key=lambda event: (-event.priority, event.start_time, event.event_id),
            )
        )
        return self._apply_events(state, events)

    def add_perturbation(self, perturbation: WeatherPerturbation) -> None:
        if perturbation.event_id in self._events:
            raise WeatherProviderError(f"perturbation already exists: {perturbation.event_id}")
        self._events[perturbation.event_id] = perturbation

    def remove_perturbation(self, event_id: str) -> None:
        self._events.pop(event_id, None)

    def reset(self) -> None:
        self._events.clear()

    @staticmethod
    def _apply_events(
        state: WeatherState,
        events: tuple[WeatherPerturbation, ...],
    ) -> WeatherState:
        temperature = state.temperature_c
        radiation = state.solar_radiation_w_m2
        wind_speed = state.wind_speed_m_s
        wind_direction = state.wind_direction_deg
        heat_offset = sum(
            event.parameters["temperature_offset_c"]
            for event in events
            if event.event_type is WeatherEventType.HEAT_WAVE
        )
        frost_events = [event for event in events if event.event_type is WeatherEventType.FROST]
        if frost_events:
            temperature = frost_events[0].parameters["temperature_c"]
        temperature += heat_offset
        wind_speed *= math.prod(
            event.parameters["speed_multiplier"]
            for event in events
            if event.event_type is WeatherEventType.WIND
            and "speed_multiplier" in event.parameters
        )
        direction_events = [
            event for event in events
            if event.event_type is WeatherEventType.WIND
            and "direction_deg" in event.parameters
        ]
        if direction_events:
            wind_direction = direction_events[0].parameters["direction_deg"]
        radiation = max(
            0.0,
            radiation * math.prod(
                event.parameters["radiation_multiplier"]
                for event in events
                if event.event_type is WeatherEventType.RADIATION_ANOMALY
                and "radiation_multiplier" in event.parameters
            )
            + sum(
                event.parameters["radiation_offset_w_m2"]
                for event in events
                if event.event_type is WeatherEventType.RADIATION_ANOMALY
                and "radiation_offset_w_m2" in event.parameters
            ),
        )
        rain_rates = [
            event.parameters["rate_mm_h"]
            for event in events
            if event.event_type is WeatherEventType.RAIN
        ]
        return WeatherState(
            temperature_c=temperature,
            relative_humidity_pct=state.relative_humidity_pct,
            solar_radiation_w_m2=radiation,
            wind_speed_m_s=max(0.0, wind_speed),
            wind_direction_deg=wind_direction % 360,
            rain_rate_mm_h=max([state.rain_rate_mm_h, *rain_rates], default=0.0),
            pressure_hpa=state.pressure_hpa,
        )
