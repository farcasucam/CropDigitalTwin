"""MQTT adapter for SimulationClock commands and status publication."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from agri_twin.application.clock import SimulationClock, SimulationClockError
from agri_twin.contracts import MessageEnvelope
from agri_twin.mqtt.client import MQTTClient, MQTTMessage
from agri_twin.mqtt.topics import Topics


class SimulationClockMQTTAdapter:
    def __init__(
        self,
        clock: SimulationClock,
        client: MQTTClient,
        simulation_id: str,
        plot_id: str,
        source: str = "simulation-clock",
    ) -> None:
        self._clock = clock
        self._client = client
        self._simulation_id = simulation_id
        self._plot_id = plot_id
        self._source = source

    def connect(self) -> None:
        self._client.connect()
        self._client.subscribe(Topics.SIMULATION_CONTROL, self._on_control, qos=1)
        self.publish_status()

    def disconnect(self) -> None:
        self._client.disconnect()

    def publish_time(self) -> None:
        payload = {
            "simulation_time": self._iso_time(self._clock.now()),
            "state": self._clock.state.value,
        }
        self._publish(Topics.SIMULATION_TIME, "simulation_time", payload, qos=0)

    def publish_status(self, error: dict[str, str] | None = None) -> None:
        payload: dict[str, Any] = {
            "state": self._clock.state.value,
            "simulation_time": self._iso_time(self._clock.now()),
            "speed": self._clock.speed,
        }
        if error is not None:
            payload["error"] = error
        self._publish(Topics.SIMULATION_STATUS, "simulation_status", payload, qos=1, retain=True)

    def _on_control(self, message: MQTTMessage) -> None:
        try:
            envelope = json.loads(message.payload.decode("utf-8"))
            command_data = MessageEnvelope.from_dict(envelope).data
            self._validate_command(command_data)
            self._execute(command_data)
            self.publish_time()
            self.publish_status()
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
            SimulationClockError,
        ) as exc:
            self.publish_status(
                error={"code": type(exc).__name__, "message": str(exc)}
            )

    def _execute(self, data: dict[str, Any]) -> None:
        command = data.get("command")
        if command == "start":
            self._clock.start()
        elif command == "pause":
            self._clock.pause()
        elif command == "resume":
            self._clock.resume()
        elif command == "reset":
            self._clock.reset()
        elif command == "set_speed":
            self._clock.set_speed(data["speed"])
        else:
            raise ValueError(f"unsupported simulation command: {command}")

    @staticmethod
    def _validate_command(data: dict[str, Any]) -> None:
        command = data.get("command")
        valid_commands = {"start", "pause", "resume", "reset", "set_speed"}
        if command not in valid_commands:
            raise ValueError(f"unsupported simulation command: {command}")
        if command == "set_speed" and "speed" not in data:
            raise ValueError("set_speed requires speed")

    def _publish(
        self,
        topic: str,
        message_type: str,
        data: dict[str, Any],
        qos: int,
        retain: bool = False,
    ) -> None:
        envelope = MessageEnvelope(
            simulation_id=self._simulation_id,
            plot_id=self._plot_id,
            simulation_time=data["simulation_time"],
            type=message_type,
            source=self._source,
            data=data,
        )
        payload = json.dumps(envelope.to_dict(), separators=(",", ":")).encode("utf-8")
        self._client.publish(topic, payload, qos=qos, retain=retain)

    @staticmethod
    def _iso_time(value: datetime) -> str:
        return value.isoformat()
