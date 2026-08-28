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


def test_current_stress_and_growth_recover_after_conditions_improve():
    engine = CropEngine()
    crop = CropConfigRepository(CROP).get_crop("plum")
    stage = crop.resolve_stage("yield_maturation")
    soil = SoilState(0.25, 20, 0.35, 0.10, 0, 0.25)
    extreme_weather = weather(temperature_c=40, relative_humidity_pct=10)
    normal_weather = weather()
    stressed = engine.evaluate(crop, stage, extreme_weather, environment(extreme_weather), soil, T0)
    recovered = engine.evaluate(crop, stage, normal_weather, environment(normal_weather), soil, T0, previous=stressed)

    assert recovered.total_stress < stressed.total_stress
    assert recovered.growth_factor > stressed.growth_factor


def test_crop_engine_rejects_unknown_stage_and_naive_timestamp():
    crop = CropConfigRepository(CROP).get_crop("plum")
    engine = CropEngine()
    soil = SoilState(0.25, 20, 0.35, 0.10, 0, 0.25)
    with pytest.raises(Exception):
        engine.evaluate(crop, "missing", weather(), environment(weather()), soil, T0)
    with pytest.raises(CropEngineError):
        engine.evaluate(crop, "yield_maturation", weather(), environment(weather()), soil, datetime(2026, 8, 28, 12))


def test_crop_engine_rejects_stage_from_another_crop():
    crops = CropConfigRepository(CROP)
    engine = CropEngine()
    soil = SoilState(0.25, 20, 0.35, 0.10, 0, 0.25)
    foreign_stage = crops.get_crop("tomato").resolve_stage("yield_maturation")
    with pytest.raises(CropEngineError):
        engine.evaluate(crops.get_crop("plum"), foreign_stage, weather(), environment(weather()), soil, T0)


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


def test_advance_is_explicit_deterministic_and_preserves_stage():
    crops = CropConfigRepository(CROP)
    crop = crops.get_crop("plum")
    stage = crop.resolve_stage("yield_maturation")
    soil = SoilState(0.25, 20, 0.35, 0.10, 0, 0.25)
    current_weather = weather()
    environment_state = environment(current_weather)
    engine = CropEngine()
    initial = engine.evaluate(crop, stage, current_weather, environment_state, soil, T0)

    unchanged = engine.advance(crop, stage, initial, current_weather, environment_state, soil, T0, 0)
    first = engine.advance(crop, stage, initial, current_weather, environment_state, soil, T0, 3600)
    second = engine.advance(crop, stage, initial, current_weather, environment_state, soil, T0, 3600)

    assert unchanged == initial
    assert first == second
    assert first.development_stage == "yield_maturation"
    assert first.development_index > initial.development_index
    assert first.biomass >= initial.biomass


def test_advance_rejects_negative_dt():
    crops = CropConfigRepository(CROP)
    crop = crops.get_crop("plum")
    stage = crop.resolve_stage("yield_maturation")
    soil = SoilState(0.25, 20, 0.35, 0.10, 0, 0.25)
    current_weather = weather()
    initial = CropEngine().evaluate(crop, stage, current_weather, environment(current_weather), soil, T0)

    with pytest.raises(CropEngineError):
        CropEngine().advance(crop, stage, initial, current_weather, environment(current_weather), soil, T0, -1)


def test_stage_thresholds_affect_temporal_growth_without_confusing_stress_and_development():
    crops = CropConfigRepository(CROP)
    crop = crops.get_crop("plum")
    soil = SoilState(0.25, 20, 0.35, 0.10, 0, 0.25)
    favorable = weather(temperature_c=24, relative_humidity_pct=80)
    excessive = weather(temperature_c=40, relative_humidity_pct=10)
    engine = CropEngine()
    stage = crop.resolve_stage("yield_maturation")
    favorable_initial = engine.evaluate(crop, stage, favorable, environment(favorable), soil, T0)
    excessive_initial = engine.evaluate(crop, stage, excessive, environment(excessive), soil, T0)
    favorable_final = engine.advance(crop, stage, favorable_initial, favorable, environment(favorable), soil, T0, 86400)
    excessive_final = engine.advance(crop, stage, excessive_initial, excessive, environment(excessive), soil, T0, 86400)

    assert favorable_final.development_index > excessive_final.development_index
    assert favorable_final.biomass > excessive_final.biomass
