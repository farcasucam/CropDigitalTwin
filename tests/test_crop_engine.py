from datetime import datetime, timedelta, timezone

import pytest

from agri_twin.application import OpenFieldPhysicalModel, WeatherEngine
from agri_twin.domain import (
    CropConfigRepository,
    CropEngine,
    CropEngineError,
    FarmConfigRepository,
    SoilState,
    WeatherConfiguration,
    WeatherState,
)
from agri_twin.infrastructure import CsvWeatherProvider


FARM = "src/farm_config.json"
CROP = "src/crop_config.json"
T0 = datetime(2026, 8, 28, 12, tzinfo=timezone.utc)


def weather(**changes):
    values = dict(
        temperature_c=25.0,
        relative_humidity_pct=50.0,
        solar_radiation_w_m2=600.0,
        wind_speed_m_s=2.0,
        wind_direction_deg=180.0,
        rain_rate_mm_h=0.0,
        pressure_hpa=1012.0,
    )
    values.update(changes)
    return WeatherState(**values)


def environment(state):
    return OpenFieldPhysicalModel().evaluate(state, SoilState(0.25, 20, 0.35, 0.10, 0, 0.25), 3600).environment


def test_crop_engine_uses_valid_crop_and_stage_thresholds():
    crop = CropConfigRepository(CROP).get_crop("plum")
    stage = crop.resolve_stage("yield_maturation")
    state = CropEngine().evaluate(crop, stage, weather(), environment(weather()), SoilState(0.25, 20, 0.35, 0.10, 0, 0.25), T0)

    assert state.development_stage == "yield_maturation"
    assert 0 <= state.temperature_stress <= 1
    assert 0 <= state.water_stress <= 1
    assert 0 <= state.vpd_stress <= 1
    assert 0 <= state.total_stress <= 1
    assert 0 <= state.growth_factor <= 1


def test_extreme_temperature_increases_thermal_stress():
    engine = CropEngine()
    crop = CropConfigRepository(CROP).get_crop("plum")
    stage = crop.resolve_stage("yield_maturation")
    normal = engine.evaluate(crop, stage, weather(), environment(weather()), SoilState(0.25, 20, 0.35, 0.10, 0, 0.25), T0)
    extreme_weather = weather(temperature_c=40)
    extreme = engine.evaluate(crop, stage, extreme_weather, environment(extreme_weather), SoilState(0.25, 20, 0.35, 0.10, 0, 0.25), T0)

    assert extreme.temperature_stress > normal.temperature_stress
    assert extreme.growth_factor < normal.growth_factor


def test_dry_soil_increases_water_stress():
    engine = CropEngine()
    crop = CropConfigRepository(CROP).get_crop("plum")
    stage = crop.resolve_stage("yield_maturation")
    dry = SoilState(0.11, 20, 0.35, 0.10, 0, 0.11)
    wet = SoilState(0.25, 20, 0.35, 0.10, 0, 0.25)
    dry_state = engine.evaluate(crop, stage, weather(), environment(weather()), dry, T0)
    wet_state = engine.evaluate(crop, stage, weather(), environment(weather()), wet, T0)

    assert dry_state.water_stress > wet_state.water_stress


def test_high_vpd_increases_environmental_stress():
    engine = CropEngine()
    crop = CropConfigRepository(CROP).get_crop("plum")
    stage = crop.resolve_stage("yield_maturation")
    low_vpd_weather = weather(relative_humidity_pct=90)
    high_vpd_weather = weather(relative_humidity_pct=10)
    soil = SoilState(0.25, 20, 0.35, 0.10, 0, 0.25)
    low = engine.evaluate(crop, stage, low_vpd_weather, environment(low_vpd_weather), soil, T0)
    high = engine.evaluate(crop, stage, high_vpd_weather, environment(high_vpd_weather), soil, T0)

    assert high.environmental_stress > low.environmental_stress


def test_crop_engine_rejects_unknown_stage_and_naive_timestamp():
    crop = CropConfigRepository(CROP).get_crop("plum")
    engine = CropEngine()
    soil = SoilState(0.25, 20, 0.35, 0.10, 0, 0.25)
    with pytest.raises(Exception):
        engine.evaluate(crop, "missing", weather(), environment(weather()), soil, T0)
    with pytest.raises(CropEngineError):
        engine.evaluate(crop, "yield_maturation", weather(), environment(weather()), soil, datetime(2026, 8, 28, 12))


def test_csv_to_weather_engine_to_physical_to_crop_engine_is_offline():
    provider = CsvWeatherProvider("data/weather/manual_forecast.csv")
    weather_engine = WeatherEngine(WeatherConfiguration(), provider=provider)
    timestamp = provider.timestamps[0]
    weather_state = weather_engine.generate(timestamp)
    physical = OpenFieldPhysicalModel().evaluate(weather_state, SoilState(0.25, 20, 0.35, 0.10, 0, 0.25), 3600)
    plot = FarmConfigRepository(FARM).get_plot("plot_14705")
    crop = CropConfigRepository(CROP).get_crop(plot.crop_key)
    crop_state = CropEngine().evaluate(crop, plot.current_stage, weather_state, physical.environment, physical.soil, timestamp)

    assert crop_state.development_stage == plot.current_stage
    assert crop_state.biomass >= 0
    assert 0 <= crop_state.total_stress <= 1
