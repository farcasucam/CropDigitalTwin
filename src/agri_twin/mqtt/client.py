"""MQTT port plus a deterministic in-memory adapter for Phase 0 tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass(frozen=True, slots=True)
class MQTTMessage:
    topic: str
    payload: bytes
    qos: int
    retain: bool


MessageHandler = Callable[[MQTTMessage], None]


class MQTTClient(Protocol):
    def connect(self) -> None: ...

    def disconnect(self) -> None: ...

    def publish(self, topic: str, payload: bytes, qos: int = 0, retain: bool = False) -> None: ...

    def subscribe(self, topic: str, handler: MessageHandler, qos: int = 0) -> None: ...


class InMemoryMQTTClient:
    """Synchronous test adapter; production Paho adapter belongs to a later phase."""

    def __init__(self) -> None:
        self.connected = False
        self._subscriptions: dict[str, list[MessageHandler]] = {}

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def publish(self, topic: str, payload: bytes, qos: int = 0, retain: bool = False) -> None:
        if not self.connected:
            raise ConnectionError("MQTT client is not connected")
        if qos not in (0, 1, 2):
            raise ValueError("MQTT QoS must be 0, 1, or 2")
        message = MQTTMessage(topic=topic, payload=payload, qos=qos, retain=retain)
        for handler in self._subscriptions.get(topic, []):
            handler(message)

    def subscribe(self, topic: str, handler: MessageHandler, qos: int = 0) -> None:
        if qos not in (0, 1, 2):
            raise ValueError("MQTT QoS must be 0, 1, or 2")
        self._subscriptions.setdefault(topic, []).append(handler)