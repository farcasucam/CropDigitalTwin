from datetime import datetime, timezone

import pytest

from agri_twin.domain import CropGrowthState, IrrigationRequest, SoilState, WaterBalanceEngine, WeatherState


T0 = datetime(2026, 7, 1, tzinfo=timezone.utc)


def weather(**changes):
    values = dict(temperature_c=25, relative_humidity_pct=50, solar_radiation_w_m2=500, wind_speed_m_s=2, wind_direction_deg=180, rain_rate_mm_h=0, pressure_hpa=1012)
    values.update(changes)
    return WeatherState(**values)


def soil(vwc=0.25):
    return SoilState(vwc, 20, 0.35, 0.10, 20, 0)


def crop(**changes):
    values = dict(simulation_time=T0, crop_key="tomato", variety="unspecified", current_stage="vegetative_growth", leaf_area_index=2.0, root_depth_m=0.5, soil_water_vwc=0.25)
    values.update(changes)
    return CropGrowthState(**values)


def test_rain_increases_water_and_drought_increases_stress():
    engine = WaterBalanceEngine()
    dry = engine.advance(soil(0.20), weather(), 3600, crop())
    rain = engine.advance(soil(0.20), weather(rain_rate_mm_h=20), 3600, crop())

    assert rain.soil.vwc_m3_m3 > dry.soil.vwc_m3_m3
    assert dry.water_stress > 0


def test_manual_scheduled_and_vwc_target_irrigation_apply_efficiency_and_limits():
    engine = WaterBalanceEngine()
    manual = engine.advance(soil(), weather(), 3600, crop(), IrrigationRequest("manual", 20, irrigation_type="overhead"))
    scheduled = engine.advance(soil(), weather(), 3600, crop(), IrrigationRequest("scheduled", 20, irrigation_type="drip"))
    targeted = engine.advance(soil(), weather(), 3600, crop(), IrrigationRequest("vwc_target", target_vwc=0.30, maximum_mm=5))

    assert manual.irrigation_applied_mm == pytest.approx(15)
    assert scheduled.irrigation_applied_mm == pytest.approx(19)
    assert targeted.irrigation_applied_mm == pytest.approx(4.75)


def test_overwatering_drains_and_storage_stays_within_field_capacity():
    result = WaterBalanceEngine().advance(soil(0.34), weather(), 3600, crop(), IrrigationRequest("manual", 100))

    assert result.drainage_mm > 0
    assert result.soil.vwc_m3_m3 <= result.soil.field_capacity
    assert result.soil.vwc_m3_m3 >= result.soil.wilting_point


def test_et_responds_to_radiation_and_lai_changes_transpiration():
    engine = WaterBalanceEngine()
    low_lai = engine.advance(soil(), weather(), 86400, crop(leaf_area_index=0.1))
    high_lai = engine.advance(soil(), weather(), 86400, crop(leaf_area_index=3.0))

    assert low_lai.et0_mm == high_lai.et0_mm
    assert high_lai.transpiration_mm > low_lai.transpiration_mm
    assert low_lai.evaporation_mm > high_lai.evaporation_mm


def test_determinism_large_timestep_and_physical_limits():
    engine = WaterBalanceEngine()
    first = engine.advance(soil(0.15), weather(rain_rate_mm_h=2), 30 * 86400, crop())
    second = engine.advance(soil(0.15), weather(rain_rate_mm_h=2), 30 * 86400, crop())

    assert first == second
    assert 0.10 <= first.soil.vwc_m3_m3 <= 0.35
    assert 0 <= first.water_stress <= 1


@pytest.mark.parametrize("vwc", [0.10, 0.35])
def test_wilting_point_and_field_capacity_are_respected(vwc):
    result = WaterBalanceEngine().advance(soil(vwc), weather(solar_radiation_w_m2=0), 3600, crop())

    assert 0.10 <= result.soil.vwc_m3_m3 <= 0.35


def test_invalid_water_inputs_are_rejected():
    with pytest.raises(ValueError):
        WaterBalanceEngine().advance(soil(), weather(), 0, crop())
    with pytest.raises(ValueError):
        IrrigationRequest("vwc_target")