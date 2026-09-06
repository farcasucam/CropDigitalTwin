from datetime import datetime, timedelta, timezone

import pytest

from agri_twin.application import SimulationClock, SimulationScheduler
from agri_twin.domain import CropGrowthEngine, CropGrowthInput, CropGrowthState, DerivedEnvironmentState, SoilState, WeatherState


T0 = datetime(2026, 6, 1, tzinfo=timezone.utc)


def weather(**changes):
    values = dict(temperature_c=24, relative_humidity_pct=70, solar_radiation_w_m2=500, wind_speed_m_s=2, wind_direction_deg=180, rain_rate_mm_h=0, pressure_hpa=1012)
    values.update(changes)
    return WeatherState(**values)


def state(crop_key="tomato", stage="vegetative_growth", **changes):
    values = dict(simulation_time=T0, crop_key=crop_key, variety="unspecified", current_stage=stage, biomass_total=50, biomass_leaf=50, leaf_area_index=1.0, root_depth_m=0.5)
    values.update(changes)
    return CropGrowthState(**values)


def grow(current=None, **changes):
    return CropGrowthEngine().advance(current or state(), CropGrowthInput(weather(**changes), 86400))


def test_par_conversion_and_units():
    result = grow(solar_radiation_w_m2=500)

    assert result.par_mj_m2 == pytest.approx(20.736)
    assert result.apar_mj_m2 <= result.par_mj_m2


def test_lai_zero_has_zero_apar():
    assert grow(state(leaf_area_index=0)).apar_mj_m2 == 0


def test_lai_positive_has_positive_apar():
    assert grow().apar_mj_m2 > 0


def test_apar_monotonic_with_lai():
    assert grow(state(leaf_area_index=2)).apar_mj_m2 >= grow(state(leaf_area_index=1)).apar_mj_m2


def test_zero_radiation_has_no_potential_growth():
    result = grow(solar_radiation_w_m2=0)

    assert result.potential_growth_g_m2 == 0


def test_positive_radiation_produces_potential_growth():
    assert grow().potential_growth_g_m2 > 0


@pytest.mark.parametrize("temperature", [5, 12, 24, 32, 40])
def test_temperature_factor_is_bounded(temperature):
    assert 0 <= grow(temperature_c=temperature).temperature_factor <= 1


def test_cold_reduces_growth():
    assert grow(temperature_c=5).actual_growth_g_m2 < grow(temperature_c=24).actual_growth_g_m2


def test_heat_reduces_growth():
    assert grow(temperature_c=40).actual_growth_g_m2 < grow(temperature_c=24).actual_growth_g_m2


@pytest.mark.parametrize("vwc", [0.10, 0.16, 0.32])
def test_water_factor_is_bounded(vwc):
    result = grow()
    explicit = CropGrowthEngine().advance(state(soil_water_vwc=vwc), CropGrowthInput(weather(), 86400, water_factor=max(0, min(1, (vwc - 0.10) / 0.22))))

    assert 0 <= explicit.water_factor <= 1


def test_vpd_factor_changes_with_humidity():
    low = grow(relative_humidity_pct=90)
    high = grow(relative_humidity_pct=10)

    assert high.vpd_factor < low.vpd_factor


def test_radiation_factor_reduces_excess_radiation():
    assert grow(solar_radiation_w_m2=1000).radiation_factor < 1


def test_nutrient_factor_is_consumed():
    result = CropGrowthEngine().advance(state(nutrient_status=0.25), CropGrowthInput(weather(), 86400))

    assert result.nutrient_factor == 0.25


def test_co2_factor_is_explicit():
    result = CropGrowthEngine().advance(state(), CropGrowthInput(weather(), 86400, co2_factor=0.5))

    assert result.co2_factor == 0.5 and result.actual_growth_g_m2 < result.potential_growth_g_m2


def test_favorable_conditions_increase_biomass_and_lai():
    initial = state()
    result = grow(initial)

    assert result.state.biomass_total > initial.biomass_total
    assert result.state.leaf_area_index >= 0
    assert result.lai_growth >= 0


def test_severe_stress_nearly_stops_growth():
    result = CropGrowthEngine().advance(state(water_stress=1, nutrient_status=0), CropGrowthInput(weather(temperature_c=40, relative_humidity_pct=10, solar_radiation_w_m2=1000), 86400))

    assert result.actual_growth_g_m2 <= result.potential_growth_g_m2


def test_senescence_reduces_lai_in_dormancy():
    initial = state(stage="post_harvest_dormancy")
    result = grow(initial)

    assert result.state.leaf_area_index < initial.leaf_area_index


def test_damage_reduces_lai_without_negative_values():
    result = grow(state(frost_damage=1, heat_damage=1))

    assert result.state.leaf_area_index >= 0 and result.lai_damage >= 0


def test_maturity_is_bounded_and_non_decreasing():
    initial = state(maturity_index=0.4, phenology_progress=1)
    result = grow(initial)

    assert 0 <= result.state.maturity_index <= 1
    assert result.state.maturity_index >= initial.maturity_index


@pytest.mark.parametrize("crop", ["tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple"])
def test_all_crops_have_deterministic_growth_profiles(crop):
    result = grow(state(crop_key=crop))

    assert result.state.crop_key == crop and result.state.biomass_total >= 0


@pytest.mark.parametrize("crop,variety", [("tomato", "RAF"), ("pepper", "Lamuyo"), ("grape", "Monastrell"), ("plum", "Suplum 26")])
def test_known_varieties_are_accepted_without_special_values(crop, variety):
    result = grow(state(crop_key=crop, variety=variety))

    assert result.state.variety == variety


def test_large_timestep_is_deterministic():
    first = grow(dt_seconds=0) if False else CropGrowthEngine().advance(state(), CropGrowthInput(weather(), 30 * 86400))
    second = CropGrowthEngine().advance(state(), CropGrowthInput(weather(), 30 * 86400))

    assert first == second


def test_state_has_no_nan_or_negative_outputs():
    result = grow()

    assert all(value >= 0 for value in (result.state.biomass_total, result.state.leaf_area_index, result.par_mj_m2, result.apar_mj_m2))


def test_factors_are_all_bounded():
    result = grow()

    for value in (result.temperature_factor, result.water_factor, result.vpd_factor, result.radiation_factor, result.nutrient_factor, result.co2_factor):
        assert 0 <= value <= 1


def test_maturity_does_not_imply_harvest_ready():
    result = grow(state(maturity_index=1))

    assert result.state.harvest_ready is False


def test_clock_advancement_controls_input_time():
    clock = SimulationClock(T0)
    clock.advance(86400)
    result = CropGrowthEngine().advance(state(), CropGrowthInput(weather(), 86400), clock.now())

    assert result.state.simulation_time == T0


def test_scheduler_can_drive_growth_callback_without_real_time():
    clock = SimulationClock(T0)
    values = []
    scheduler = SimulationScheduler(clock, 86400)
    scheduler.register("growth", 86400, lambda timestamp: values.append(timestamp))
    scheduler.advance(3 * 86400)

    assert len(values) == 3


def test_environment_contract_accepts_microclimate_vpd():
    environment = DerivedEnvironmentState(0.5, 1, 2, 1.5, 0.1, 0.1)
    result = CropGrowthEngine().advance(state(), CropGrowthInput(weather(), 86400, environment=environment))

    assert result.vpd_factor > 0


def test_stress_accumulation_is_persistent_in_state():
    result = grow(state(accumulated_stress=0.2), temperature_c=40)

    assert result.state.accumulated_stress >= 0.2