from datetime import datetime, timezone

import pytest

from agri_twin.application import (
    OpenFieldPhysicalModel,
    PhysicalModelError,
)
from agri_twin.domain import SoilState, WeatherState


def weather(**changes):
    values = {
        "temperature_c": 25.0,
        "relative_humidity_pct": 50.0,
        "solar_radiation_w_m2": 600.0,
        "wind_speed_m_s": 2.0,
        "wind_direction_deg": 180.0,
        "rain_rate_mm_h": 0.0,
        "pressure_hpa": 1012.0,
    }
    values.update(changes)
    return WeatherState(**values)


def soil(vwc=0.25):
    return SoilState(vwc, 20.0, 0.35, 0.10, 0.0, 0.25)


def test_open_field_model_derives_vpd_and_preserves_invariants():
    model = OpenFieldPhysicalModel()
    result = model.evaluate(weather(), soil(), 3600)

    assert result.environment.vpd_kpa > 0
    assert result.environment.vapor_pressure < result.environment.saturation_vapor_pressure
    assert 0.10 <= result.soil.vwc_m3_m3 <= 0.35
    assert result.soil.soil_temperature_c == 25.0


def test_rain_and_irrigation_increase_soil_water_causally():
    model = OpenFieldPhysicalModel()
    dry = model.evaluate(weather(), soil(), 3600)
    wet = model.evaluate(weather(rain_rate_mm_h=20), soil(), 3600, irrigation_mm=10)

    assert wet.soil.vwc_m3_m3 > dry.soil.vwc_m3_m3
    assert wet.soil.root_zone_water > dry.soil.root_zone_water


def test_same_input_is_reproducible():
    model = OpenFieldPhysicalModel()
    assert model.evaluate(weather(), soil(), 3600) == model.evaluate(weather(), soil(), 3600)


@pytest.mark.parametrize("seconds", (0, -1))
def test_invalid_timestep_is_rejected(seconds):
    with pytest.raises(PhysicalModelError):
        OpenFieldPhysicalModel().evaluate(weather(), soil(), seconds)


def test_invalid_irrigation_and_soil_bounds_are_rejected():
    model = OpenFieldPhysicalModel()
    with pytest.raises(PhysicalModelError):
        model.evaluate(weather(), soil(), 3600, irrigation_mm=-1)
    with pytest.raises(ValueError):
        model.evaluate(weather(), SoilState(0.2, 20, 0.1, 0.2, 0, 0.2), 3600)