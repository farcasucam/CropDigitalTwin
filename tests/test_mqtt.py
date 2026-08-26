import pytest

from agri_twin.mqtt import InMemoryMQTTClient, Topics


def test_in_memory_mqtt_delivers_messages_only_when_connected() -> None:
    client = InMemoryMQTTClient()
    received = []
    client.subscribe(Topics.ENVIRONMENT_WEATHER, received.append)

    with pytest.raises(ConnectionError):
        client.publish(Topics.ENVIRONMENT_WEATHER, b"{}")

    client.connect()
    client.publish(Topics.ENVIRONMENT_WEATHER, b"{}", qos=1)

    assert received[0].topic == Topics.ENVIRONMENT_WEATHER
    assert received[0].payload == b"{}"