"""MQTT adapter for exterior weather and natural events."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from agri_twin.application.weather import WeatherEngine
from agri_twin.contracts import MessageEnvelope
from agri_twin.domain.models import WeatherState
from agri_twin.domain.weather import WeatherEventType, WeatherPerturbation, normalize_utc
from agri_twin.mqtt.client import MQTTClient, MQTTMessage
from agri_twin.mqtt.topics import Topics


class WeatherMQTTAdapter:
    def __init__(
        self,
        engine: WeatherEngine,
        client: MQTTClient,
        simulation_id: str,
        plot_id: str,
        source: str = "weather-engine",
    ) -> None:
        self._engine = engine
        self._client = client
        self._simulation_id = simulation_id
        self._plot_id = plot_id
        self._source = source
        self._weather_validator = self._load_validator("weather-1.0.json")
        self._event_validator = self._load_validator("natural-event-1.0.json")

    def connect(self) -> None:
        self._client.connect()
        self._client.subscribe(Topics.ENVIRONMENT_EVENTS, self._on_event, qos=1)

    def disconnect(self) -> None:
        self._client.disconnect()

    def publish(self, simulation_time: datetime) -> None:
        state = self._engine.generate(simulation_time)
        data = {
            "temperature_c": state.temperature_c,
            "relative_humidity_pct": state.relative_humidity_pct,
            "solar_radiation_w_m2": state.solar_radiation_w_m2,
            "wind_speed_m_s": state.wind_speed_m_s,
            "wind_direction_deg": state.wind_direction_deg,
            "rain_rate_mm_h": state.rain_rate_mm_h,
            "pressure_hpa": state.pressure_hpa,
        }
        self._weather_validator.validate(data)
        instant = normalize_utc(simulation_time)
        envelope = MessageEnvelope(
            simulation_id=self._simulation_id,
            plot_id=self._plot_id,
            simulation_time=instant.isoformat(),
            type="weather",
            source=self._source,
            data=data,
        )
        self._client.publish(
            Topics.ENVIRONMENT_WEATHER,
            json.dumps(envelope.to_dict(), separators=(",", ":")).encode("utf-8"),
            qos=0,
        )

    def _on_event(self, message: MQTTMessage) -> None:
        try:
            envelope = MessageEnvelope.from_dict(json.loads(message.payload.decode("utf-8")))
            self._event_validator.validate(envelope.data)
            data = envelope.data
            start_time = datetime.fromisoformat(data["start_time"])
            event = WeatherPerturbation(
                event_id=envelope.message_id,
                event_type=WeatherEventType(data["type"]),
                start_time=start_time,
                end_time=start_time + timedelta(seconds=data["duration_seconds"]),
                priority=int(data.get("priority", 0)),
                source=envelope.source,
                parameters=data["parameters"],
            )
            self._engine.add_perturbation(event)
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return

    @staticmethod
    def _load_validator(filename: str) -> Draft202012Validator:
        schema_path = Path(__file__).parents[3] / "schemas" / filename
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        return Draft202012Validator(schema, format_checker=FormatChecker())
