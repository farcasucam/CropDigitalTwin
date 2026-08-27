from datetime import datetime, timedelta, timezone

import pytest

from agri_twin.application import SimulationClock, SimulationScheduler, WeatherEngine
from agri_twin.domain import (
    WeatherConfiguration,
    WeatherEngineValueError,
    WeatherEventType,
    WeatherPerturbation,
    TemperatureConfiguration,
    RadiationConfiguration,
    HumidityConfiguration,
    WindConfiguration,
    PressureConfiguration,
    WeatherSimulationConfiguration,
    WeatherState,
)


T0 = datetime(2026, 8, 27, 8, 0, tzinfo=timezone.utc)


def event(event_id, event_type, parameters, priority=0, start=T0, duration=3600):
    return WeatherPerturbation(
        event_id=event_id,
        event_type=event_type,
        start_time=start,
        end_time=start + timedelta(seconds=duration),
        priority=priority,
        source="test",
        parameters=parameters,
    )


def test_generate_is_repeatable_and_independent_of_call_history() -> None:
    engine = WeatherEngine(WeatherConfiguration())
    first = engine.generate(T0)
    engine.generate(T0 + timedelta(hours=1))
    assert engine.generate(T0) == first
    assert engine.generate(T0) == engine.generate(T0)


def test_profiles_are_continuous_and_weather_state_stays_in_range() -> None:
    engine = WeatherEngine(WeatherConfiguration())
    before = engine.generate(T0 - timedelta(seconds=1))
    after = engine.generate(T0 + timedelta(seconds=1))

    assert abs(after.temperature_c - before.temperature_c) < 1
    assert 0 <= after.relative_humidity_pct <= 100
    assert after.solar_radiation_w_m2 >= 0
    assert after.wind_speed_m_s >= 0
    assert 0 <= after.wind_direction_deg < 360


def test_baseline_respects_nominal_temperature_and_radiation_limits() -> None:
    configuration = WeatherConfiguration(
        temperature=TemperatureConfiguration(variability_c=0),
        radiation=RadiationConfiguration(variability_w_m2=0),
    )
    engine = WeatherEngine(configuration)
    states = [engine.generate(T0 + timedelta(minutes=minute)) for minute in range(1440)]

    assert min(state.temperature_c for state in states) >= configuration.temperature.minimum_c
    assert max(state.temperature_c for state in states) <= configuration.temperature.maximum_c
    assert min(state.solar_radiation_w_m2 for state in states) >= 0
    assert max(state.solar_radiation_w_m2 for state in states) <= configuration.radiation.maximum_w_m2


def test_normal_variability_has_configured_envelopes() -> None:
    configuration = WeatherConfiguration(
        temperature=TemperatureConfiguration(variability_c=0.5),
        radiation=RadiationConfiguration(variability_w_m2=15),
    )
    engine = WeatherEngine(configuration)
    states = [engine.generate(T0 + timedelta(minutes=minute)) for minute in range(1440)]

    assert min(state.temperature_c for state in states) >= configuration.temperature.minimum_c - 0.5
    assert max(state.temperature_c for state in states) <= configuration.temperature.maximum_c + 0.5
    assert max(state.solar_radiation_w_m2 for state in states) <= configuration.radiation.maximum_w_m2 + 15
    assert all(configuration.humidity.minimum_pct <= state.relative_humidity_pct <= configuration.humidity.maximum_pct for state in states)
    assert all(state.wind_speed_m_s >= 0 and 0 <= state.wind_direction_deg < 360 for state in states)
    assert all(configuration.pressure.base_hpa - configuration.pressure.variability_hpa <= state.pressure_hpa <= configuration.pressure.base_hpa + configuration.pressure.variability_hpa for state in states)


def test_normal_variability_can_exceed_nominal_temperature_and_radiation_maxima() -> None:
    configuration = WeatherConfiguration(
        temperature=TemperatureConfiguration(variability_c=5),
        radiation=RadiationConfiguration(variability_w_m2=1000),
    )
    engine = WeatherEngine(configuration)
    states = [engine.generate(T0 + timedelta(minutes=minute)) for minute in range(1440)]

    assert any(state.temperature_c > configuration.temperature.maximum_c for state in states)
    assert any(state.solar_radiation_w_m2 > configuration.radiation.maximum_w_m2 for state in states)


def test_perturbations_combine_using_the_approved_rules() -> None:
    engine = WeatherEngine(WeatherConfiguration())
    engine.add_perturbation(event("rain-a", WeatherEventType.RAIN, {"rate_mm_h": 10}))
    engine.add_perturbation(event("rain-b", WeatherEventType.RAIN, {"rate_mm_h": 20}))
    engine.add_perturbation(event("heat-a", WeatherEventType.HEAT_WAVE, {"temperature_offset_c": 2}))
    engine.add_perturbation(event("heat-b", WeatherEventType.HEAT_WAVE, {"temperature_offset_c": 3}))
    engine.add_perturbation(event("wind-a", WeatherEventType.WIND, {"speed_multiplier": 2}))
    engine.add_perturbation(event("wind-b", WeatherEventType.WIND, {"speed_multiplier": 1.5}))

    state = engine.generate(T0)
    base = WeatherEngine(WeatherConfiguration()).generate(T0)

    assert state.rain_rate_mm_h == 20
    assert state.temperature_c == base.temperature_c + 5
    assert state.wind_speed_m_s == pytest.approx(base.wind_speed_m_s * 3)


def test_absolute_conflicts_use_priority_then_start_then_id() -> None:
    engine = WeatherEngine(WeatherConfiguration())
    engine.add_perturbation(event("z", WeatherEventType.FROST, {"temperature_c": -4}, priority=1))
    engine.add_perturbation(event("a", WeatherEventType.FROST, {"temperature_c": -2}, priority=1))
    engine.add_perturbation(event("direction", WeatherEventType.WIND, {"direction_deg": 270}, priority=2))

    state = engine.generate(T0)

    assert state.temperature_c == -2
    assert state.wind_direction_deg == 270


def test_reset_clears_events_but_keeps_configuration_and_seed() -> None:
    configuration = WeatherConfiguration()
    engine = WeatherEngine(configuration)
    engine.add_perturbation(event("rain", WeatherEventType.RAIN, {"rate_mm_h": 20}))
    engine.reset()

    assert engine.configuration == configuration
    assert engine.seed == configuration.simulation.seed
    assert engine.generate(T0).rain_rate_mm_h == 0


def test_events_are_applied_after_normal_variability_without_nominal_clamping() -> None:
    engine = WeatherEngine(WeatherConfiguration())
    engine.add_perturbation(event("frost", WeatherEventType.FROST, {"temperature_c": -10}))
    engine.add_perturbation(event("heat", WeatherEventType.HEAT_WAVE, {"temperature_offset_c": 20}))
    engine.add_perturbation(event("radiation", WeatherEventType.RADIATION_ANOMALY, {"radiation_multiplier": 3}))
    engine.add_perturbation(event("rain", WeatherEventType.RAIN, {"rate_mm_h": 50}))
    engine.add_perturbation(event("wind", WeatherEventType.WIND, {"speed_multiplier": 3, "direction_deg": 359}))

    state = engine.generate(T0)

    assert state.temperature_c == 10
    assert state.solar_radiation_w_m2 > 900
    assert state.rain_rate_mm_h == 50
    assert state.wind_speed_m_s >= 0
    assert 0 <= state.wind_direction_deg < 360
    assert 0 <= state.relative_humidity_pct <= 100


def test_weather_engine_integrates_with_scheduler_without_real_time() -> None:
    clock = SimulationClock(T0)
    scheduler = SimulationScheduler(clock, timestep_seconds=60)
    engine = WeatherEngine(WeatherConfiguration())
    generated = []
    scheduler.register("weather", 60, lambda moment: generated.append(engine.generate(moment)))

    scheduler.advance(3600)

    assert len(generated) == 60
    assert generated[0] == engine.generate(T0 + timedelta(minutes=1))


@pytest.mark.parametrize(
    "event_type, parameters",
    [
        (WeatherEventType.RAIN, {"rate_mm_h": -1}),
        (WeatherEventType.WIND, {"direction_deg": 360}),
        (WeatherEventType.WIND, {"speed_multiplier": 0}),
        (WeatherEventType.HEAT_WAVE, {"rate_mm_h": 1}),
    ],
)
def test_event_parameters_are_validated_by_event_type(event_type, parameters) -> None:
    with pytest.raises(WeatherEngineValueError):
        event("bad", event_type, parameters)


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(WeatherEngineValueError):
        WeatherEngine(WeatherConfiguration()).generate(datetime(2026, 8, 27, 8))


@pytest.mark.parametrize(
    "factory",
    [
        lambda: TemperatureConfiguration(minimum_c=float("nan")),
        lambda: RadiationConfiguration(maximum_w_m2=float("inf")),
        lambda: HumidityConfiguration(variability_pct=float("nan")),
        lambda: WindConfiguration(base_speed_m_s=float("inf")),
        lambda: PressureConfiguration(base_hpa=float("nan")),
        lambda: WeatherSimulationConfiguration(publication_interval_seconds=0),
    ],
)
def test_configuration_rejects_non_finite_or_invalid_values(factory) -> None:
    with pytest.raises(WeatherEngineValueError):
        factory()


def test_weather_state_rejects_direction_360_and_non_finite_values() -> None:
    with pytest.raises(ValueError):
        WeatherState(20, 50, 100, 2, 360, 0, 1013)
    with pytest.raises(ValueError):
        WeatherState(float("nan"), 50, 100, 2, 180, 0, 1013)
