from datetime import datetime, timedelta, timezone

import pytest

from agri_twin.domain import ClimateStressEngine, CropGrowthState, WeatherState


T0 = datetime(2026, 7, 1, tzinfo=timezone.utc)


def state(**changes):
    values = dict(simulation_time=T0, crop_key="tomato", variety="unspecified", current_stage="vegetative_growth", leaf_area_index=2.0, biomass_total=100, biomass_leaf=100)
    values.update(changes)
    return CropGrowthState(**values)


def weather(**changes):
    values = dict(temperature_c=25, relative_humidity_pct=70, solar_radiation_w_m2=500, wind_speed_m_s=2, wind_direction_deg=180, rain_rate_mm_h=0, pressure_hpa=1012)
    values.update(changes)
    return WeatherState(**values)


def advance(engine, current, dt_seconds, **changes):
    return engine.advance(current, weather(**changes), dt_seconds)


def test_cold_and_heat_are_continuous_factors():
    engine = ClimateStressEngine()
    cold = advance(engine, state(), 3600, temperature_c=5)
    heat = advance(engine, state(), 3600, temperature_c=32)

    assert 0 < cold.cold_stress < 1
    assert 0 < heat.heat_stress < 1
    assert cold.temperature_factor < 1 and heat.temperature_factor < 1


def test_frost_duration_and_intensity_accumulate_differently():
    engine = ClimateStressEngine()
    short = advance(engine, state(), 600, temperature_c=-1)
    long = advance(engine, state(), 10 * 3600, temperature_c=-1)
    severe = advance(engine, state(), 3600, temperature_c=-8)

    assert long.state.frost_exposure_hours > short.state.frost_exposure_hours
    assert long.frost_damage > short.frost_damage
    assert severe.frost_damage > short.frost_damage
    assert long.state.frost_intensity_c == short.state.frost_intensity_c


def test_heat_wave_accumulates_over_consecutive_days():
    engine = ClimateStressEngine()
    current = state()
    isolated = advance(engine, current, 86400, temperature_c=35)
    consecutive = advance(engine, isolated.state, 86400, temperature_c=35)

    assert consecutive.state.heat_exposure_hours > isolated.state.heat_exposure_hours
    assert consecutive.heat_damage > isolated.heat_damage


def test_vpd_and_radiation_stress_reduce_their_separate_factors():
    engine = ClimateStressEngine()
    dry_air = advance(engine, state(), 3600, relative_humidity_pct=10)
    excessive_light = advance(engine, state(), 3600, solar_radiation_w_m2=1000)

    assert dry_air.vpd_stress > 0 and dry_air.vpd_factor < 1
    assert excessive_light.radiation_stress > 0 and excessive_light.radiation_factor < 1


def test_recovery_reduces_recoverable_damage_but_not_irreversible_damage():
    engine = ClimateStressEngine()
    stressed = advance(engine, state(), 12 * 3600, temperature_c=-8)
    recovered = advance(engine, stressed.state, 10 * 86400, temperature_c=25)

    assert recovered.frost_damage < stressed.frost_damage
    assert recovered.irreversible_damage >= stressed.irreversible_damage


def test_lai_and_stage_affect_climate_impact_and_growth_composition():
    engine = ClimateStressEngine()
    sparse = advance(engine, state(leaf_area_index=0.1), 3600, solar_radiation_w_m2=1000)
    dense = advance(engine, state(leaf_area_index=3.0), 3600, solar_radiation_w_m2=1000)
    result = advance(engine, state(), 3600, temperature_c=25, solar_radiation_w_m2=500)

    assert sparse.state.leaf_area_index < dense.state.leaf_area_index
    assert 0 <= result.growth_factor <= 1
    assert ClimateStressEngine.combine_growth(100, result) == pytest.approx(100 * result.temperature_factor * result.radiation_factor * result.water_factor * result.vpd_factor * result.nutrient_factor)


def test_phenology_stage_changes_climate_sensitivity():
    engine = ClimateStressEngine()
    establishment = advance(engine, state(current_stage="establishment"), 3600, temperature_c=32)
    maturation = advance(engine, state(current_stage="yield_maturation"), 3600, temperature_c=32)

    assert establishment.heat_stress != maturation.heat_stress or establishment.temperature_factor != maturation.temperature_factor


def test_water_and_nutrient_inputs_are_independent_factors():
    engine = ClimateStressEngine()
    result = engine.advance(state(water_stress=0.4, nutrient_status=0.3), weather(), 3600)

    assert result.water_factor == 0.6
    assert result.nutrient_factor == 0.3
    assert result.growth_factor <= result.water_factor * result.nutrient_factor


def test_large_timestep_is_deterministic_and_bounded():
    engine = ClimateStressEngine()
    first = advance(engine, state(), 30 * 86400, temperature_c=35)
    second = advance(engine, state(), 30 * 86400, temperature_c=35)

    assert first == second
    for value in (first.temperature_factor, first.vpd_factor, first.water_factor, first.radiation_factor, first.nutrient_factor, first.frost_damage, first.heat_damage, first.irreversible_damage):
        assert 0 <= value <= 1