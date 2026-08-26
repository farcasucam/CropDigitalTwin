"""Deterministic scheduler driven by a simulation clock."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from typing import Callable

from agri_twin.application.clock import SimulationClock


ScheduledTask = Callable[[datetime], None]


class SimulationSchedulerValueError(ValueError):
    """Raised when a scheduler argument is invalid."""


@dataclass(slots=True)
class _Task:
    name: str
    interval: timedelta
    callback: ScheduledTask
    next_run: datetime


class SimulationScheduler:
    def __init__(self, clock: SimulationClock, timestep_seconds: float) -> None:
        self._validate_seconds(timestep_seconds, "timestep_seconds", positive=True)
        self._clock = clock
        self._timestep = timedelta(seconds=timestep_seconds)
        self._tasks: list[_Task] = []
        self._epoch = clock.epoch

    @property
    def timestep(self) -> timedelta:
        return self._timestep

    def register(
        self,
        name: str,
        interval_seconds: float,
        callback: ScheduledTask,
    ) -> None:
        if not name:
            raise SimulationSchedulerValueError("task name cannot be empty")
        self._validate_seconds(interval_seconds, "interval_seconds", positive=True)
        if any(task.name == name for task in self._tasks):
            raise SimulationSchedulerValueError(f"task already registered: {name}")
        self._tasks.append(
            _Task(
                name=name,
                interval=timedelta(seconds=interval_seconds),
                callback=callback,
                next_run=self._clock.now() + timedelta(seconds=interval_seconds),
            )
        )

    def advance(self, seconds: float) -> None:
        self._validate_seconds(seconds, "seconds")
        self._rebase_if_needed()
        remaining = seconds
        timestep_seconds = self._timestep.total_seconds()
        while remaining > 0:
            step = min(remaining, timestep_seconds)
            self._clock.advance(step)
            self.run_pending()
            remaining -= step

    def run_pending(self) -> None:
        self._rebase_if_needed()
        current = self._clock.now()
        while True:
            due_tasks = [task for task in self._tasks if task.next_run <= current]
            if not due_tasks:
                return
            task = min(due_tasks, key=lambda candidate: self._tasks.index(candidate))
            task.callback(task.next_run)
            task.next_run += task.interval

    def clear(self) -> None:
        self._tasks.clear()

    def _rebase_if_needed(self) -> None:
        current_epoch = self._clock.epoch
        if current_epoch == self._epoch:
            return
        current_time = self._clock.now()
        for task in self._tasks:
            task.next_run = current_time + task.interval
        self._epoch = current_epoch

    @staticmethod
    def _validate_seconds(value: float, name: str, positive: bool = False) -> None:
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or (value <= 0 if positive else value < 0)
        ):
            qualifier = "greater than 0" if positive else "non-negative"
            raise SimulationSchedulerValueError(f"{name} must be finite and {qualifier}")
