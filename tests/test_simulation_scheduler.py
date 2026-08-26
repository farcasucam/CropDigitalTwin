from datetime import datetime

import pytest

from agri_twin.application import (
    SimulationClock,
    SimulationScheduler,
    SimulationSchedulerValueError,
)


INITIAL_TIME = datetime(2026, 8, 27, 8, 0, 0)


def test_scheduler_runs_periodic_tasks_in_registration_order_without_drift() -> None:
    clock = SimulationClock(INITIAL_TIME)
    scheduler = SimulationScheduler(clock, timestep_seconds=60)
    calls: list[tuple[str, int]] = []

    scheduler.register("weather", 60, lambda moment: calls.append(("weather", moment.minute)))
    scheduler.register("state", 120, lambda moment: calls.append(("state", moment.minute)))

    scheduler.advance(300)

    assert calls == [
        ("weather", 1),
        ("weather", 2),
        ("state", 2),
        ("weather", 3),
        ("weather", 4),
        ("state", 4),
        ("weather", 5),
    ]


def test_scheduler_can_run_pending_after_automatic_clock_progression() -> None:
    class Source:
        value = 0.0

        def now(self) -> float:
            return self.value

    source = Source()
    clock = SimulationClock(INITIAL_TIME, source=source)
    scheduler = SimulationScheduler(clock, timestep_seconds=1)
    moments = []
    scheduler.register("task", 10, moments.append)
    clock.start()
    source.value = 20

    scheduler.run_pending()

    assert len(moments) == 2


def test_scheduler_rebases_tasks_after_clock_reset() -> None:
    clock = SimulationClock(INITIAL_TIME)
    scheduler = SimulationScheduler(clock, timestep_seconds=60)
    calls = []
    scheduler.register("task", 60, calls.append)

    scheduler.advance(60)
    clock.reset()
    scheduler.advance(30)
    assert len(calls) == 1
    scheduler.advance(30)

    assert len(calls) == 2
    assert calls[-1].isoformat() == "2026-08-27T08:01:00"


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_scheduler_rejects_invalid_values_with_specific_error(value: float) -> None:
    with pytest.raises(SimulationSchedulerValueError):
        SimulationScheduler(SimulationClock(INITIAL_TIME), value)
