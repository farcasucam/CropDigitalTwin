import json
from datetime import timedelta
from datetime import datetime, timezone

from agri_twin.application import WeatherEngine
from agri_twin.contracts import MessageEnvelope
from agri_twin.domain import WeatherConfiguration
from agri_twin.interfaces.weather_mqtt import WeatherMQTTAdapter
from agri_twin.mqtt import InMemoryMQTTClient, Topics


T0 = datetime(2026, 8, 27, 8, 0, tzinfo=timezone.utc)


def test_weather_adapter_does_not_publish_on_connect_and_publishes_valid_envelope() -> None:
    client = InMemoryMQTTClient()
    received = []
    client.subscribe(Topics.ENVIRONMENT_WEATHER, received.append)
    adapter = WeatherMQTTAdapter(WeatherEngine(WeatherConfiguration()), client, "sim", "plot")

    adapter.connect()
    assert received == []
    adapter.publish(T0)

    envelope = MessageEnvelope.from_dict(json.loads(received[0].payload))
    assert envelope.type == "weather"
    assert envelope.simulation_time == T0.isoformat()
    assert received[0].qos == 0


def test_weather_adapter_accepts_versioned_natural_event() -> None:
    client = InMemoryMQTTClient()
    engine = WeatherEngine(WeatherConfiguration())
    adapter = WeatherMQTTAdapter(engine, client, "sim", "plot")
    adapter.connect()
    event_data = {
        "type": "rain",
        "start_time": T0.isoformat(),
        "duration_seconds": 3600,
        "parameters": {"rate_mm_h": 12},
    }
    envelope = MessageEnvelope(
        simulation_id="sim",
        plot_id="plot",
        simulation_time=T0.isoformat(),
        type="natural_event",
        source="test",
        data=event_data,
    )

    client.publish(Topics.ENVIRONMENT_EVENTS, json.dumps(envelope.to_dict()).encode(), qos=1)

    assert engine.generate(T0).rain_rate_mm_h == 12


def test_weather_adapter_ignores_invalid_event_without_breaking_subscription() -> None:
    client = InMemoryMQTTClient()
    engine = WeatherEngine(WeatherConfiguration())
    adapter = WeatherMQTTAdapter(engine, client, "sim", "plot")
    adapter.connect()

    client.publish(Topics.ENVIRONMENT_EVENTS, b"{not-json", qos=1)

    assert engine.generate(T0).rain_rate_mm_h == 0
