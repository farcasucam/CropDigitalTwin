"""Versioned cross-process message contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import UUID, uuid4

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
            "message_id": self.message_id,
            "correlation_id": self.correlation_id,
            "simulation_id": self.simulation_id,
            "plot_id": self.plot_id,
            "timestamp": self.timestamp,
            "simulation_time": self.simulation_time,
            "type": self.type,
            "source": self.source,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"Envelope fields cannot be empty: {', '.join(missing)}")
        non_strings = [
            name for name, value in required.items() if not isinstance(value, str)
        ]
        if non_strings:
            raise ValueError(
                f"Envelope fields must be strings: {', '.join(non_strings)}"
            )
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"Unsupported schema version: {self.schema_version}")
        if not isinstance(self.data, dict):
            raise ValueError("Envelope data must be an object")
        try:
            UUID(self.message_id)
            UUID(self.correlation_id)
        except (AttributeError, ValueError, TypeError) as exc:
            raise ValueError("Envelope message IDs must be UUIDs") from exc
        try:
            datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))
        except (AttributeError, ValueError, TypeError) as exc:
            raise ValueError("Envelope timestamp must be an ISO 8601 datetime") from exc

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MessageEnvelope":
        """Parse and validate a complete versioned envelope."""
        if not isinstance(payload, Mapping):
            raise ValueError("Envelope must be an object")
        required = {
            "schema_version", "message_id", "correlation_id", "simulation_id",
            "plot_id", "timestamp", "simulation_time", "type", "source", "data",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ValueError(f"Envelope fields are missing: {', '.join(missing)}")
        return cls(
            simulation_id=payload["simulation_id"],
            plot_id=payload["plot_id"],
            simulation_time=payload["simulation_time"],
            type=payload["type"],
            source=payload["source"],
            data=payload["data"],
            schema_version=payload["schema_version"],
            message_id=payload["message_id"],
            correlation_id=payload["correlation_id"],
            timestamp=payload["timestamp"],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)