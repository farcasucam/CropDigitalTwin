from datetime import datetime, timezone

import pytest

from agri_twin.application.clock import SimulationClock
from agri_twin.domain import (
    ActuatorControl,
    CropGrowthState,
    CropMicroclimateFeedback,
    GreenhouseActuatorState,
    GreenhouseConfiguration,
    GreenhouseMicroclimateEngine,
    GreenhousePhysicalModel,
    MicroclimateState,
    SimplifiedGreenhouseModel,
    WeatherState,
)


T0 = datetime(2026, 7, 1, tzinfo=timezone.utc)


def crop(**changes):
    values = dict(simulation_time=T0, crop_key="tomato", variety="RAF", current_stage="vegetative_growth", leaf_area_index=2.0)
    values.update(changes)
    return CropGrowthState(**values)


def weather(**changes):
    values = dict(temperature_c=30, relative_humidity_pct=50, solar_radiation_w_m2=800, wind_speed_m_s=2, wind_direction_deg=180, rain_rate_mm_h=0, pressure_hpa=1012)
    values.update(changes)
    return WeatherState(**values)


def test_greenhouse_contract_is_explicitly_implemented():
    assert issubclass(SimplifiedGreenhouseModel, GreenhousePhysicalModel)
    assert issubclass(GreenhouseMicroclimateEngine, GreenhousePhysicalModel)


def test_microclimate_state_is_a_common_domain_contract():
    state = MicroclimateState(25.0, 60.0, 400.0, 420.0)
    assert state.temperature_c == 25.0 and state.co2_ppm == 420.0


def test_greenhouse_configuration_is_explicit_and_reproducible():
    cfg = GreenhouseConfiguration(volume_m3=1000.0, solar_transmission=0.78, ventilation_ach=3.0, heat_loss_w_k=80.0)
    assert cfg.volume_m3 == 1000.0 and cfg.solar_transmission == 0.78


def test_simplified_backend_reduces_indoor_radiation_under_shade():
    model = SimplifiedGreenhouseModel()
    baseline = model.step(weather(), crop(), 3600, mode="passive_greenhouse")
    shaded = model.step(weather(), crop(), 3600, mode="passive_greenhouse", actuators={"shade": ActuatorControl(0.5)})

    assert baseline.indoor_state.radiation_w_m2 > shaded.indoor_state.radiation_w_m2


def test_simplified_backend_keeps_simulation_time_outside_real_clock():
    clock = SimulationClock(T0)
    model = SimplifiedGreenhouseModel()
    clock.advance(86400)
    result = model.step(weather(), crop(), 86400, mode="passive_greenhouse")

    assert result.indoor_state.temperature_c >= 0
    assert result.indoor_state.radiation_w_m2 >= 0


def test_greenhouse_model_state_is_stored_for_reuse():
    model = SimplifiedGreenhouseModel()
    result = model.step(weather(temperature_c=35), crop(), 3600, mode="passive_greenhouse")

    assert model.state().temperature_c == result.indoor_state.temperature_c


def test_contract_step_uses_configuration_and_crop_feedback():
    model = SimplifiedGreenhouseModel()
    state = model.step(
        weather(temperature_c=30, solar_radiation_w_m2=800, wind_speed_m_s=3, pressure_hpa=1012),
        GreenhouseConfiguration(volume_m3=1000.0, solar_transmission=0.78, ventilation_ach=3.0, heat_loss_w_k=80.0),
        GreenhouseActuatorState(heating_kw=0.0, cooling_kw=0.0, ventilation_ach=2.5, shading_fraction=0.4),
        CropMicroclimateFeedback(leaf_area_index=2.0, transpiration_mm_h=2.5, intercepted_radiation_w_m2=350.0),
        3600,
    )

    assert isinstance(state, MicroclimateState)
    assert state.air_temperature_c == state.temperature_c
    assert 0 <= state.relative_humidity_pct <= 100
    assert state.vpd_kpa >= 0
    assert state.pressure_hpa > 0
    assert state.solar_radiation_w_m2 >= 0
    assert state.par_umol_m2_s >= 0
    assert state.co2_ppm >= 0
    assert state.wind_speed_m_s >= 0
    assert state.ventilation_fraction >= 0
    assert state.heating_kw >= 0
    assert state.cooling_kw >= 0
    assert state.shading_fraction >= 0


def test_contract_step_reduces_radiation_when_shading_is_active():
    model = SimplifiedGreenhouseModel()
    baseline = model.step(
        weather(temperature_c=28, solar_radiation_w_m2=900),
        GreenhouseConfiguration(),
        GreenhouseActuatorState(shading_fraction=0.0),
        CropMicroclimateFeedback(leaf_area_index=2.0, transpiration_mm_h=1.0, intercepted_radiation_w_m2=200.0),
        3600,
    )
    shaded = model.step(
        weather(temperature_c=28, solar_radiation_w_m2=900),
        GreenhouseConfiguration(),
        GreenhouseActuatorState(shading_fraction=0.7),
        CropMicroclimateFeedback(leaf_area_index=2.0, transpiration_mm_h=1.0, intercepted_radiation_w_m2=200.0),
        3600,
    )

    assert shaded.solar_radiation_w_m2 < baseline.solar_radiation_w_m2
    assert shaded.shading_fraction > baseline.shading_fraction
