"""Deterministic simulation clock with injectable wall-clock source."""

from __future__ import annotations

import math
import time
from datetime import datetime, timedelta
from enum import Enum
from threading import RLock
from typing import Protocol


class ClockSource(Protocol):
    def now(self) -> float: ...


class MonotonicClockSource:
    def now(self) -> float:
        return time.monotonic()


class SimulationClockState(str, Enum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"


class SimulationClockError(Exception):
    """Base exception for simulation clock failures."""


class SimulationClockStateError(SimulationClockError):
    """Raised when an operation is invalid for the current clock state."""


class SimulationClockValueError(SimulationClockError):
    """Raised when a clock value is invalid."""


class SimulationClock:
    def __init__(
        self,
        initial_time: datetime,
        speed: float = 1.0,
        source: ClockSource | None = None,
    ) -> None:
        if not isinstance(initial_time, datetime):
            raise SimulationClockValueError("initial_time must be a datetime")
        self._validate_speed(speed)
        self._source = source or MonotonicClockSource()
        self._initial_time = initial_time
        self._simulation_time = initial_time
        self._speed = speed
        self._state = SimulationClockState.STOPPED
        self._last_real_time: float | None = None
        self._epoch = 0
        self._lock = RLock()

    @property
    def state(self) -> SimulationClockState:
        with self._lock:
            return self._state

    @property
    def speed(self) -> float:
        with self._lock:
            return self._speed

    @property
    def initial_time(self) -> datetime:
        with self._lock:
            return self._initial_time

    @property
    def epoch(self) -> int:
        with self._lock:
            return self._epoch

    def now(self) -> datetime:
        with self._lock:
            self._sync_from_real_time()
            return self._simulation_time

    def start(self) -> None:
        with self._lock:
            if self._state is not SimulationClockState.STOPPED:
                raise SimulationClockStateError(
                    f"Cannot start clock from {self._state.value}"
                )
            self._last_real_time = self._source.now()
            self._state = SimulationClockState.RUNNING

    def pause(self) -> None:
        with self._lock:
            if self._state is not SimulationClockState.RUNNING:
                raise SimulationClockStateError(
                    f"Cannot pause clock from {self._state.value}"
                )
            self._sync_from_real_time()
            self._state = SimulationClockState.PAUSED
            self._last_real_time = None

    def resume(self) -> None:
        with self._lock:
            if self._state is not SimulationClockState.PAUSED:
                raise SimulationClockStateError(
                    f"Cannot resume clock from {self._state.value}"
                )
            self._last_real_time = self._source.now()
            self._state = SimulationClockState.RUNNING

    def reset(self) -> None:
        with self._lock:
            self._simulation_time = self._initial_time
            self._state = SimulationClockState.STOPPED
            self._last_real_time = None
            self._epoch += 1

    def set_speed(self, multiplier: float) -> None:
        with self._lock:
            self._validate_speed(multiplier)
            self._sync_from_real_time()
            self._speed = multiplier

    def advance(self, seconds: float) -> timedelta:
        with self._lock:
            self._validate_seconds(seconds)
            self._sync_from_real_time()
            before = self._simulation_time
            self._simulation_time += timedelta(seconds=seconds)
            return self._simulation_time - before

    def _sync_from_real_time(self) -> None:
        if self._state is not SimulationClockState.RUNNING:
            return
        current = self._source.now()
        if self._last_real_time is None:
            self._last_real_time = current
            return
        elapsed = current - self._last_real_time
        if not math.isfinite(elapsed):
            raise SimulationClockValueError("clock source returned a non-finite value")
        if elapsed < 0:
            raise SimulationClockValueError("clock source moved backwards")
        self._simulation_time += timedelta(seconds=elapsed * self._speed)
        self._last_real_time = current

    @staticmethod
    def _validate_speed(multiplier: float) -> None:
        if not isinstance(multiplier, (int, float)) or isinstance(multiplier, bool):
            raise SimulationClockValueError("speed must be a finite number greater than 0")
        if not math.isfinite(multiplier) or multiplier <= 0:
            raise SimulationClockValueError("speed must be a finite number greater than 0")

    @staticmethod
    def _validate_seconds(seconds: float) -> None:
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
            raise SimulationClockValueError("seconds must be a finite number >= 0")
        if not math.isfinite(seconds) or seconds < 0:
            raise SimulationClockValueError("seconds must be a finite number >= 0")
