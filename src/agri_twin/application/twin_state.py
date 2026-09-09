"""In-memory temporal state contracts for the simulated digital twin."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol


class TwinStateError(ValueError):
    """Raised when a simulated state or history operation is invalid."""


class TwinStateConflict(TwinStateError):
    """Raised when one logical state key receives a different value."""


@dataclass(frozen=True, slots=True)
class TwinState:
    """One simulated plot/cycle state at one SimulationClock instant."""

    simulation_time: datetime
    plot_id: str
    cycle_id: str
    crop: str
    variety: str
    cycle_status: str
    phenological_stage: str
    state_provenance: str = "SIMULATION"
    lai: float | None = None
    biomass_g_m2: float | None = None
    maturity: float | None = None
    stress: float | None = None
    soil_water_m3_m3: float | None = None
    temperature_c: float | None = None
    relative_humidity_pct: float | None = None
    vpd_kpa: float | None = None
    radiation_w_m2: float | None = None
    co2_ppm: float | None = None
    weather_source: str | None = None
    weather_timestamp: datetime | None = None

    def __post_init__(self) -> None:
        if self.simulation_time.tzinfo is None or not self.plot_id or not self.cycle_id or not self.crop:
            raise TwinStateError("state time, plot, cycle and crop are required")
        if self.state_provenance != "SIMULATION":
            raise TwinStateError("TwinState provenance must be SIMULATION")
        if self.weather_timestamp is not None and self.weather_timestamp.tzinfo is None:
            raise TwinStateError("weather_timestamp must be timezone-aware")

    @property
    def key(self) -> tuple[str, str, datetime]:
        return self.plot_id, self.cycle_id, self.simulation_time

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for item in fields(self):
            value = getattr(self, item.name)
            result[item.name] = value.isoformat() if isinstance(value, datetime) else value
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TwinState":
        values = dict(payload)
        for name in ("simulation_time", "weather_timestamp"):
            if values.get(name) is not None and isinstance(values[name], str):
                values[name] = datetime.fromisoformat(values[name])
        return cls(**{item.name: values.get(item.name) for item in fields(cls) if item.name in values})


@dataclass(frozen=True, slots=True)
class TwinSnapshot:
    """All available simulated plot/cycle states at one instant."""

    simulation_time: datetime
    states: tuple[TwinState, ...]
    state_provenance: str = "SIMULATION"

    def __post_init__(self) -> None:
        if self.simulation_time.tzinfo is None or self.state_provenance != "SIMULATION":
            raise TwinStateError("snapshot time and simulation provenance are required")
        if any(state.simulation_time != self.simulation_time for state in self.states):
            raise TwinStateError("snapshot states must share its simulation_time")
        keys = [state.key for state in self.states]
        if len(keys) != len(set(keys)):
            raise TwinStateError("snapshot contains duplicate state keys")
        if tuple(sorted(self.states, key=lambda state: (state.plot_id, state.cycle_id))) != self.states:
            raise TwinStateError("snapshot states must be deterministically ordered")

    def for_plot(self, plot_id: str) -> tuple[TwinState, ...]:
        return tuple(state for state in self.states if state.plot_id == plot_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "simulation_time": self.simulation_time.isoformat(),
            "state_provenance": self.state_provenance,
            "states": [state.to_dict() for state in self.states],
        }


class TwinStateRepository(Protocol):
    def save(self, state: TwinState) -> TwinState: ...
    def save_snapshot(self, snapshot: TwinSnapshot) -> TwinSnapshot: ...
    def get_exact(self, plot_id: str, cycle_id: str, simulation_time: datetime) -> TwinState: ...
    def latest_at_or_before(self, plot_id: str, cycle_id: str, simulation_time: datetime) -> TwinState | None: ...
    def latest(self, plot_id: str, cycle_id: str) -> TwinState | None: ...
    def history(self, plot_id: str, cycle_id: str | None = None) -> tuple[TwinState, ...]: ...
    def snapshot(self, simulation_time: datetime) -> TwinSnapshot: ...
    def latest_snapshot(self) -> TwinSnapshot | None: ...


class InMemoryTwinStateRepository:
    """Deterministic repository; no filesystem, network, or wall-clock access."""

    def __init__(self) -> None:
        self._states: dict[tuple[str, str, datetime], TwinState] = {}
        self._snapshots: dict[datetime, TwinSnapshot] = {}

    def save(self, state: TwinState) -> TwinState:
        existing = self._states.get(state.key)
        if existing is not None and existing != state:
            raise TwinStateConflict(f"state key already contains a different value: {state.key}")
        self._states[state.key] = state
        return state

    def save_snapshot(self, snapshot: TwinSnapshot) -> TwinSnapshot:
        existing = self._snapshots.get(snapshot.simulation_time)
        if existing is not None and existing != snapshot:
            raise TwinStateConflict(f"snapshot timestamp already contains a different value: {snapshot.simulation_time}")
        conflicts = [
            state.key for state in snapshot.states
            if self._states.get(state.key) is not None and self._states[state.key] != state
        ]
        if conflicts:
            raise TwinStateConflict(f"snapshot contains conflicting state keys: {conflicts}")
        for state in snapshot.states:
            self._states[state.key] = state
        self._snapshots[snapshot.simulation_time] = snapshot
        return snapshot

    def get_exact(self, plot_id: str, cycle_id: str, simulation_time: datetime) -> TwinState:
        try:
            return self._states[(plot_id, cycle_id, simulation_time)]
        except KeyError as exc:
            raise KeyError((plot_id, cycle_id, simulation_time)) from exc

    def latest_at_or_before(self, plot_id: str, cycle_id: str, simulation_time: datetime) -> TwinState | None:
        candidates = [state for state in self._states.values() if state.plot_id == plot_id and state.cycle_id == cycle_id and state.simulation_time <= simulation_time]
        return max(candidates, key=lambda state: state.simulation_time, default=None)

    def latest(self, plot_id: str, cycle_id: str) -> TwinState | None:
        return self.latest_at_or_before(plot_id, cycle_id, datetime.max.replace(tzinfo=timezone.utc))

    def history(self, plot_id: str, cycle_id: str | None = None) -> tuple[TwinState, ...]:
        result = [state for state in self._states.values() if state.plot_id == plot_id and (cycle_id is None or state.cycle_id == cycle_id)]
        return tuple(sorted(result, key=lambda state: (state.simulation_time, state.cycle_id)))

    def snapshot(self, simulation_time: datetime) -> TwinSnapshot:
        try:
            return self._snapshots[simulation_time]
        except KeyError as exc:
            raise KeyError(simulation_time) from exc

    def latest_snapshot(self) -> TwinSnapshot | None:
        return max(self._snapshots.values(), key=lambda snapshot: snapshot.simulation_time, default=None)


__all__ = ["InMemoryTwinStateRepository", "TwinSnapshot", "TwinState", "TwinStateConflict", "TwinStateError", "TwinStateRepository"]
