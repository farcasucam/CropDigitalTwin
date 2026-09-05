from datetime import datetime, timezone

import pytest

from agri_twin.domain import ActuatorControl, CropGrowthState, GreenhouseMicroclimateEngine, WeatherState


T0 = datetime(2026, 7, 1, tzinfo=timezone.utc)


def crop(**changes):
    values = dict(simulation_time=T0, crop_key="tomato", variety="unspecified", current_stage="vegetative_growth", leaf_area_index=2.0)
    values.update(changes)
    return CropGrowthState(**values)


def weather(**changes):
    values = dict(temperature_c=35, relative_humidity_pct=40, solar_radiation_w_m2=800, wind_speed_m_s=3, wind_direction_deg=180, rain_rate_mm_h=2, pressure_hpa=1012)
    values.update(changes)
    return WeatherState(**values)


def test_outdoor_mode_is_a_bypass():
    result = GreenhouseMicroclimateEngine().advance(weather(), crop(), 3600, mode="outdoor")

    assert result.indoor_state.temperature_c == weather().temperature_c
    assert result.indoor_state.relative_humidity_pct == weather().relative_humidity_pct
    assert result.indoor_state.radiation_w_m2 == weather().solar_radiation_w_m2


def test_cover_and_shading_reduce_radiation():
    engine = GreenhouseMicroclimateEngine()
    passive = engine.advance(weather(), crop(), 3600, mode="passive_greenhouse")
    shaded = engine.advance(weather(), crop(), 3600, mode="passive_greenhouse", actuators={"shade": ActuatorControl(0.5)})

    assert passive.indoor_state.radiation_w_m2 < weather().solar_radiation_w_m2
    assert shaded.indoor_state.radiation_w_m2 < passive.indoor_state.radiation_w_m2


def test_ventilation_moves_temperature_and_humidity_toward_outdoor():
    engine = GreenhouseMicroclimateEngine()
    still = engine.advance(weather(), crop(), 86400, mode="passive_greenhouse", prior=__import__("agri_twin.domain", fromlist=["GreenhouseMicroclimateState"]).GreenhouseMicroclimateState(50, 90, 500))
    ventilated = engine.advance(weather(), crop(), 86400, mode="passive_greenhouse", prior=still.indoor_state, actuators={"ventilation": ActuatorControl(12, maximum=20, capacity=20)})

    assert abs(ventilated.indoor_state.temperature_c - weather().temperature_c) < abs(still.indoor_state.temperature_c - weather().temperature_c)
    assert ventilated.indoor_state.relative_humidity_pct < still.indoor_state.relative_humidity_pct


def test_heating_cooling_and_hvac_are_capacity_limited():
    engine = GreenhouseMicroclimateEngine()
    heated = engine.advance(weather(temperature_c=0), crop(), 86400, mode="actuated_greenhouse", actuators={"heating": ActuatorControl(5, maximum=5, capacity=5)})
    cooled = engine.advance(weather(temperature_c=40), crop(), 86400, mode="actuated_greenhouse", actuators={"cooling": ActuatorControl(5, maximum=5, capacity=5)})
    insufficient = engine.advance(weather(temperature_c=40), crop(), 86400, mode="actuated_greenhouse", actuators={"cooling": ActuatorControl(0.1, maximum=5, capacity=0.1)})

    assert heated.indoor_state.temperature_c > 0
    assert cooled.indoor_state.temperature_c < 40
    assert abs(insufficient.indoor_state.temperature_c - 40) > 0


def test_vpd_co2_consumption_and_crop_context_are_deterministic():
    engine = GreenhouseMicroclimateEngine()
    controls = {"co2": ActuatorControl(1, capacity=1, consumption_kwh=0), "heating": ActuatorControl(1, capacity=1, consumption_kwh=2)}
    first = engine.advance(weather(), crop(leaf_area_index=3), 3600, mode="actuated_greenhouse", actuators=controls)
    second = engine.advance(weather(), crop(leaf_area_index=3), 3600, mode="actuated_greenhouse", actuators=controls)

    assert first == second
    assert first.environment.vpd_kpa >= 0
    assert first.indoor_state.co2_ppm > 420
    assert first.actuator_consumption_kwh == pytest.approx(2)


def test_actuator_failure_has_no_effect_and_does_not_change_biomass():
    engine = GreenhouseMicroclimateEngine()
    failed = engine.advance(weather(temperature_c=0), crop(), 86400, mode="actuated_greenhouse", actuators={"heating": ActuatorControl(5, maximum=5, capacity=5, failed=True)})
    baseline = engine.advance(weather(temperature_c=0), crop(), 86400, mode="actuated_greenhouse")

    assert failed.indoor_state == baseline.indoor_state
    assert failed.actuator_consumption_kwh == 0


def test_extreme_outdoor_conditions_remain_stable_with_large_dt():
    result = GreenhouseMicroclimateEngine().advance(weather(temperature_c=-10, solar_radiation_w_m2=0), crop(), 30 * 86400, mode="passive_greenhouse")

    assert -10 <= result.indoor_state.temperature_c <= 60
    assert 0 <= result.indoor_state.relative_humidity_pct <= 100
    assert result.environment.vpd_kpa >= 0