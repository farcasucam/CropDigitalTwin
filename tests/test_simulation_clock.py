from datetime import datetime, timedelta

import pytest

from agri_twin.application import (
    SimulationClock,
    SimulationClockState,
    SimulationClockStateError,
    SimulationClockValueError,
)


class FakeClockSource:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def now(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


INITIAL_TIME = datetime(2026, 8, 27, 8, 0, 0)


def test_clock_starts_stopped_at_initial_time() -> None:
    clock = SimulationClock(INITIAL_TIME)

    assert clock.state is SimulationClockState.STOPPED
    assert clock.now() == INITIAL_TIME
    assert clock.speed == 1.0


def test_start_pause_and_resume_follow_the_state_machine() -> None:
    source = FakeClockSource()
    clock = SimulationClock(INITIAL_TIME, source=source)

    clock.start()
    assert clock.state is SimulationClockState.RUNNING
    source.advance(2)
    clock.pause()
    assert clock.state is SimulationClockState.PAUSED
    assert clock.now() == INITIAL_TIME + timedelta(seconds=2)

    source.advance(100)
    assert clock.now() == INITIAL_TIME + timedelta(seconds=2)
    clock.resume()
    source.advance(3)
    assert clock.now() == INITIAL_TIME + timedelta(seconds=5)


def test_invalid_transitions_raise_specific_error() -> None:
    clock = SimulationClock(INITIAL_TIME)

    with pytest.raises(SimulationClockStateError):
        clock.resume()
    with pytest.raises(SimulationClockStateError):
        clock.pause()
    clock.start()
    with pytest.raises(SimulationClockStateError):
        clock.start()
    clock.pause()
    with pytest.raises(SimulationClockStateError):
        clock.pause()


def test_reset_restores_initial_time_and_stopped_state_but_keeps_speed() -> None:
    source = FakeClockSource()
    clock = SimulationClock(INITIAL_TIME, speed=3600, source=source)
    clock.start()
    source.advance(2)

    clock.reset()

    assert clock.state is SimulationClockState.STOPPED
    assert clock.now() == INITIAL_TIME
    assert clock.speed == 3600


def test_reset_from_stopped_is_valid_and_stays_stopped() -> None:
    clock = SimulationClock(INITIAL_TIME)

    clock.reset()

    assert clock.state is SimulationClockState.STOPPED
    assert clock.now() == INITIAL_TIME


def test_clock_preserves_one_datetime_timezone_policy() -> None:
    aware_time = datetime.fromisoformat("2026-08-27T08:00:00+00:00")
    clock = SimulationClock(aware_time)

    clock.advance(1)

    assert clock.now().tzinfo == aware_time.tzinfo
    assert clock.now() == datetime.fromisoformat("2026-08-27T08:00:01+00:00")


def test_advance_is_exact_and_independent_of_state_and_speed() -> None:
    clock = SimulationClock(INITIAL_TIME, speed=86400)

    assert clock.advance(3600) == timedelta(hours=1)
    assert clock.now() == INITIAL_TIME + timedelta(hours=1)
    assert clock.advance(60) == timedelta(minutes=1)


def test_advance_works_while_running_and_paused() -> None:
    source = FakeClockSource()
    clock = SimulationClock(INITIAL_TIME, source=source)
    clock.start()
    source.advance(1)
    clock.advance(10)
    clock.pause()

    assert clock.now() == INITIAL_TIME + timedelta(seconds=11)
    clock.advance(20)
    assert clock.now() == INITIAL_TIME + timedelta(seconds=31)


def test_automatic_progression_uses_elapsed_real_time_times_speed() -> None:
    for speed, expected in ((1, 1), (3600, 3600), (86400, 86400)):
        source = FakeClockSource()
        clock = SimulationClock(INITIAL_TIME, speed=speed, source=source)
        clock.start()
        source.advance(1)
        assert clock.now() == INITIAL_TIME + timedelta(seconds=expected)


def test_changing_speed_reanchors_real_time_without_a_jump() -> None:
    source = FakeClockSource()
    clock = SimulationClock(INITIAL_TIME, speed=10, source=source)
    clock.start()
    source.advance(2)
    clock.set_speed(100)
    assert clock.now() == INITIAL_TIME + timedelta(seconds=20)
    source.advance(3)
    assert clock.now() == INITIAL_TIME + timedelta(seconds=320)


def test_advance_zero_and_monotonicity() -> None:
    clock = SimulationClock(INITIAL_TIME)
    before = clock.now()

    assert clock.advance(0) == timedelta(0)
    assert clock.now() == before
    clock.advance(1)
    assert clock.now() >= before


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), float("-inf")])
def test_invalid_advance_values_raise_specific_error(value: float) -> None:
    clock = SimulationClock(INITIAL_TIME)

    with pytest.raises(SimulationClockValueError):
        clock.advance(value)


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_invalid_speeds_raise_specific_error(value: float) -> None:
    with pytest.raises(SimulationClockValueError):
        SimulationClock(INITIAL_TIME, speed=value)
    clock = SimulationClock(INITIAL_TIME)
    with pytest.raises(SimulationClockValueError):
        clock.set_speed(value)
