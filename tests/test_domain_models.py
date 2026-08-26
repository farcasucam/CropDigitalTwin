import pytest

from agri_twin.domain import ActuatorState, WeatherState


def test_weather_rejects_invalid_relative_humidity() -> None:
    with pytest.raises(ValueError, match="relative_humidity_pct"):
        WeatherState(20, 101, 0, 0, 0, 0, 1013)


def test_actuator_keeps_commanded_and_actual_values_distinct() -> None:
    actuator = ActuatorState(1.0, 0.4, 0, 1, 0.1, True, False)

    assert actuator.commanded_value == 1.0
    assert actuator.actual_value == 0.4