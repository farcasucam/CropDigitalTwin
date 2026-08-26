import json
from datetime import datetime

from agri_twin.application import SimulationClock, SimulationClockState
from agri_twin.contracts import MessageEnvelope
from agri_twin.interfaces.clock_mqtt import SimulationClockMQTTAdapter
from agri_twin.mqtt import InMemoryMQTTClient, Topics


INITIAL_TIME = datetime(2026, 8, 27, 8, 0, 0)


def envelope(command_data: dict) -> bytes:
    return json.dumps(
        MessageEnvelope(
            simulation_id="sim-001",
            plot_id="plot-001",
            simulation_time=INITIAL_TIME.isoformat(),
            type="simulation_control",
            source="test",
            data=command_data,
        ).to_dict()
    ).encode("utf-8")


def test_adapter_publishes_versioned_time_and_status_envelopes() -> None:
    clock = SimulationClock(INITIAL_TIME)
    client = InMemoryMQTTClient()
    time_messages = []
    status_messages = []
    client.subscribe(Topics.SIMULATION_TIME, time_messages.append)
    client.subscribe(Topics.SIMULATION_STATUS, status_messages.append)
    adapter = SimulationClockMQTTAdapter(clock, client, "sim-001", "plot-001")

    adapter.connect()
    adapter.publish_time()

    time_payload = json.loads(time_messages[0].payload)
    status_payload = json.loads(status_messages[0].payload)
    assert time_payload["schema_version"] == "1.0"
    assert time_payload["data"]["simulation_time"] == INITIAL_TIME.isoformat()
    assert time_payload["data"]["state"] == "STOPPED"
    assert status_payload["data"]["speed"] == 1.0


def test_adapter_translates_control_envelopes_to_clock_api() -> None:
    clock = SimulationClock(INITIAL_TIME)
    client = InMemoryMQTTClient()
    adapter = SimulationClockMQTTAdapter(clock, client, "sim-001", "plot-001")
    adapter.connect()

    client.publish(Topics.SIMULATION_CONTROL, envelope({"command": "start"}), qos=1)
    assert clock.state is SimulationClockState.RUNNING
    client.publish(Topics.SIMULATION_CONTROL, envelope({"command": "set_speed", "speed": 3600}), qos=1)
    assert clock.speed == 3600


def test_adapter_reports_invalid_commands_without_breaking_subscriber() -> None:
    clock = SimulationClock(INITIAL_TIME)
    client = InMemoryMQTTClient()
    status_messages = []
    client.subscribe(Topics.SIMULATION_STATUS, status_messages.append)
    adapter = SimulationClockMQTTAdapter(clock, client, "sim-001", "plot-001")
    adapter.connect()

    client.publish(Topics.SIMULATION_CONTROL, envelope({"command": "pause"}), qos=1)

    error_status = json.loads(status_messages[-1].payload)["data"]
    assert error_status["state"] == "STOPPED"
    assert error_status["error"]["code"] == "SimulationClockStateError"
    assert clock.state is SimulationClockState.STOPPED


def test_adapter_reports_incomplete_and_malformed_envelopes() -> None:
    clock = SimulationClock(INITIAL_TIME)
    client = InMemoryMQTTClient()
    status_messages = []
    client.subscribe(Topics.SIMULATION_STATUS, status_messages.append)
    adapter = SimulationClockMQTTAdapter(clock, client, "sim-001", "plot-001")
    adapter.connect()
    valid = json.loads(envelope({"command": "start"}))

    del valid["message_id"]
    client.publish(Topics.SIMULATION_CONTROL, json.dumps(valid).encode(), qos=1)
    assert json.loads(status_messages[-1].payload)["data"]["error"]["code"] == "ValueError"

    valid = json.loads(envelope({"command": "start"}))
    valid["message_id"] = "invalid"
    client.publish(Topics.SIMULATION_CONTROL, json.dumps(valid).encode(), qos=1)
    assert json.loads(status_messages[-1].payload)["data"]["error"]["code"] == "ValueError"
