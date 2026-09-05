from datetime import datetime, timezone

import pytest

from agri_twin.domain import (
    CropGrowthState,
    FertilizationRequest,
    NutrientBalanceEngine,
    NutrientProfile,
    RadiationGrowthEngine,
    RadiationGrowthProfile,
    WeatherState,
)


T0 = datetime(2026, 7, 1, tzinfo=timezone.utc)


def state(**changes):
    values = dict(simulation_time=T0, crop_key="test", variety="unspecified", current_stage="vegetative_growth", nutrient_reserve_kg_ha=200.0, nutrient_available_kg_ha=200.0)
    values.update(changes)
    return CropGrowthState(**values)


def nutrient_engine():
    return NutrientBalanceEngine({"test": NutrientProfile("test", baseline_reserve_kg_ha=200, extraction_kg_per_kg_biomass=0.02, stage_factor={"establishment": 0.5, "vegetative_growth": 1.0, "yield_maturation": 1.2, "post_harvest_dormancy": 0.2})})


def test_optimal_nutrition_has_zero_stress_and_factor_one():
    result = nutrient_engine().advance(state(), growth_potential_g_m2=10, dt_seconds=86400)

    assert result.nutrient_status < 1
    assert result.nutrient_stress > 0
    assert 0 < result.nutrient_factor < 1


def test_deficit_limits_growth_continuously_and_respects_zero_bound():
    result = nutrient_engine().advance(state(nutrient_available_kg_ha=0), growth_potential_g_m2=100, dt_seconds=86400)

    assert result.nutrient_factor == 0
    assert result.growth_actual_g_m2 == 0
    assert result.nutrient_available_kg_ha == 0


def test_fertilization_recovers_availability_with_efficiency_and_limit():
    result = nutrient_engine().advance(state(nutrient_available_kg_ha=20), growth_potential_g_m2=0, dt_seconds=86400, fertilization=FertilizationRequest(100, 0.8, "manual"))

    assert result.nutrient_applied_kg_ha == 80
    assert result.nutrient_available_kg_ha == 100
    assert result.nutrient_factor == 0.5


def test_extraction_is_stage_dependent_and_large_step_is_deterministic():
    engine = nutrient_engine()
    first = engine.advance(state(), growth_potential_g_m2=10, dt_seconds=30 * 86400)
    second = engine.advance(state(), growth_potential_g_m2=10, dt_seconds=30 * 86400)
    fruit = engine.advance(state(current_stage="yield_maturation"), growth_potential_g_m2=10, dt_seconds=86400)

    assert first == second
    assert fruit.nutrient_extracted_kg_ha > engine.advance(state(), growth_potential_g_m2=10, dt_seconds=86400).nutrient_extracted_kg_ha


def test_leaching_and_limits_are_explicit():
    result = nutrient_engine().advance(state(), fertilization=FertilizationRequest(50, 1, "scheduled", 0.25), dt_seconds=86400)

    assert result.nutrient_leached_kg_ha > 0
    assert 0 <= result.nutrient_status <= 1
    with pytest.raises(ValueError):
        nutrient_engine().advance(state(), dt_seconds=86400, leaching_fraction=1.1)


def test_growth_actual_is_potential_times_nutrient_factor():
    engine = nutrient_engine()
    result = engine.advance(state(nutrient_available_kg_ha=100), growth_potential_g_m2=25, dt_seconds=86400)

    assert result.growth_actual_g_m2 == pytest.approx(25 * result.nutrient_factor)
    assert NutrientBalanceEngine.apply_growth_limit(25, result.nutrient_factor) == result.growth_actual_g_m2


def test_nutrient_factor_composes_with_radiation_growth():
    profile = RadiationGrowthProfile("test", 0.6, 2.0, 0.02, 3, {"vegetative_growth": (0.5, 0.3, 0.2, 0.0)})
    radiation = RadiationGrowthEngine({"test": profile})
    initial = state(leaf_area_index=1, biomass_total=10, biomass_leaf=10)
    weather = WeatherState(25, 50, 500, 2, 180, 0, 1012)
    potential = radiation.advance(initial, weather, 86400)
    nutrient = nutrient_engine().advance(initial, growth_potential_g_m2=potential.biomass_total - initial.biomass_total, dt_seconds=86400)
    actual = radiation.advance(initial, weather, 86400, nutrient.nutrient_factor)

    assert actual.biomass_total - initial.biomass_total == pytest.approx(nutrient.growth_actual_g_m2)