"""Versioned cross-process message contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = "1.0"


def utc_timestamp() -> str:
    """Return an RFC 3339 UTC timestamp without coupling to simulation time."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class MessageEnvelope:
    """Transport envelope shared by every MQTT message."""

    simulation_id: str
    plot_id: str
    simulation_time: str
    type: str
    source: str
    data: dict[str, Any]
    schema_version: str = SCHEMA_VERSION
    message_id: str = field(default_factory=lambda: str(uuid4()))
    correlation_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: str = field(default_factory=utc_timestamp)

    def __post_init__(self) -> None:
        required = {
            "simulation_id": self.simulation_id,
            "plot_id": self.plot_id,
            "simulation_time": self.simulation_time,
            "type": self.type,
            "source": self.source,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"Envelope fields cannot be empty: {', '.join(missing)}")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"Unsupported schema version: {self.schema_version}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)