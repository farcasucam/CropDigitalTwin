from datetime import datetime, timedelta, timezone

import pytest

from agri_twin.application import SimulationClock
from agri_twin.domain import CropGrowthState, PhenologyEngine, PhenologyProfile, WeatherState


T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


class FixedClockSource:
    def now(self) -> float:
        return 0.0


def weather(temperature_c: float) -> WeatherState:
    return WeatherState(temperature_c, 60, 300, 1, 180, 0, 1012)


def state(crop_key="tomato", stage="establishment", **changes) -> CropGrowthState:
    values = {"simulation_time": T0, "crop_key": crop_key, "variety": "unspecified", "current_stage": stage}
    values.update(changes)
    return CropGrowthState(**values)


def advance(engine, current, temperature, hours=24):
    return engine.advance(current, weather(temperature), current.simulation_time + timedelta(hours=hours), hours * 3600)


def test_accumulates_gdd_and_clips_to_base_and_upper_temperature():
    profile = PhenologyProfile("test", False, 10, 30, (100, 200, 300), 400)
    engine = PhenologyEngine({"test": profile})
    initial = state(crop_key="test")

    assert advance(engine, initial, 5).gdd_accumulated == 0
    assert advance(engine, initial, 20).gdd_accumulated == 10
    assert advance(engine, initial, 40).gdd_accumulated == 20


def test_annual_transitions_through_existing_stages_and_matures_continuously():
    engine = PhenologyEngine({"test": PhenologyProfile("test", False, 0, 40, (10, 20, 30), 40)})
    initial = state(crop_key="test")
    first = advance(engine, initial, 10)
    final = advance(engine, first, 40)

    assert first.current_stage == "vegetative_growth"
    assert final.current_stage == "post_harvest_dormancy"
    assert 0 < first.maturity_index < 1
    assert final.maturity_index == 1
    assert final.harvest_ready is False


def test_perennial_remains_dormant_until_chilling_requirement_then_forces():
    profile = PhenologyProfile("test", True, 5, 30, (10, 20, 30), 40, chilling_requirement_hours=24)
    engine = PhenologyEngine({"test": profile})
    initial = state(crop_key="test", stage="post_harvest_dormancy", dormancy_released=False)
    dormant = advance(engine, initial, 5, 12)
    released = advance(engine, dormant, 5, 12)
    forcing = advance(engine, released, 15, 24)

    assert dormant.gdd_accumulated == 0 and dormant.dormancy_released is False
    assert released.dormancy_released is True
    assert forcing.gdd_accumulated == 10


def test_pause_resume_and_large_jumps_are_explicit_and_deterministic():
    clock = SimulationClock(T0, source=FixedClockSource())
    engine = PhenologyEngine()
    initial = state()
    clock.start()
    clock.pause()
    paused = initial.advance(clock.now(), 0)
    clock.resume()
    dt = clock.advance(10 * 86400)
    first = engine.advance(paused, weather(25), clock.now(), dt.total_seconds())
    second = engine.advance(paused, weather(25), clock.now(), dt.total_seconds())

    assert paused == initial
    assert first == second
    assert first.gdd_accumulated == 150


@pytest.mark.parametrize("crop_key", ["tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple"])
def test_all_supported_crops_have_deterministic_profiles(crop_key):
    engine = PhenologyEngine()
    initial = state(crop_key=crop_key, dormancy_released=crop_key not in {"grape", "peach", "plum", "apple"})

    result = advance(engine, initial, 20)

    assert result.phenology_model == "ENGINEERING_APPROXIMATION"