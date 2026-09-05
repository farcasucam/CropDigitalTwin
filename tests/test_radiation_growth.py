from datetime import datetime, timezone

import pytest

from agri_twin.domain import CropGrowthState, PhenologyEngine, RadiationGrowthEngine, RadiationGrowthProfile, WeatherState


T0 = datetime(2026, 6, 1, tzinfo=timezone.utc)


def weather(radiation: float) -> WeatherState:
    return WeatherState(25, 60, radiation, 1, 180, 0, 1012)


def state(**changes) -> CropGrowthState:
    values = {
        "simulation_time": T0, "crop_key": "test", "variety": "unspecified",
        "current_stage": "vegetative_growth", "biomass_total": 50.0,
        "biomass_leaf": 50.0, "leaf_area_index": 1.0,
    }
    values.update(changes)
    return CropGrowthState(**values)


def profile() -> RadiationGrowthProfile:
    return RadiationGrowthProfile("test", 0.6, 2.0, 0.02, 3.0, {
        "establishment": (0.6, 0.2, 0.2, 0.0),
        "vegetative_growth": (0.5, 0.3, 0.2, 0.0),
        "yield_maturation": (0.2, 0.2, 0.1, 0.5),
        "post_harvest_dormancy": (0.0, 0.5, 0.5, 0.0),
    })


def engine() -> RadiationGrowthEngine:
    return RadiationGrowthEngine({"test": profile()})


def test_par_conversion_integrates_interval_radiation():
    assert RadiationGrowthEngine.par_mj_m2(500, 3600) == pytest.approx(0.864)


def test_zero_radiation_produces_no_growth():
    initial = state()
    result = engine().advance(initial, weather(0), 86400)

    assert result.biomass_total == initial.biomass_total
    assert result.leaf_area_index == initial.leaf_area_index


def test_positive_radiation_and_lai_drive_intercepted_growth():
    initial = state()
    low_lai = engine().advance(state(leaf_area_index=0.2), weather(500), 86400)
    high_lai = engine().advance(initial, weather(500), 86400)

    assert high_lai.biomass_total > initial.biomass_total
    assert high_lai.biomass_total > low_lai.biomass_total


def test_partition_conserves_biomass_and_yield_stage_allocates_fruit():
    result = engine().advance(state(current_stage="yield_maturation"), weather(500), 86400)

    assert result.biomass_total == pytest.approx(result.biomass_leaf + result.biomass_stem + result.biomass_root + result.biomass_fruit)
    assert result.biomass_fruit > 0


def test_lai_is_capped_and_senescence_reduces_lai_without_losing_mass():
    capped = engine().advance(state(leaf_area_index=3, biomass_total=150, biomass_leaf=150), weather(900), 86400)
    dormant = engine().advance(capped.__class__(**(capped.to_dict() | {"simulation_time": T0, "current_stage": "post_harvest_dormancy"})), weather(900), 86400)

    assert capped.leaf_area_index <= profile().maximum_lai
    assert dormant.leaf_area_index < capped.leaf_area_index
    assert dormant.biomass_total == pytest.approx(capped.biomass_total)


def test_limitation_and_large_dt_are_bounded_and_deterministic():
    initial = state()
    unlimited = engine().advance(initial, weather(500), 30 * 86400)
    limited = engine().advance(initial, weather(500), 30 * 86400, limitation_factor=0.5)
    same = engine().advance(initial, weather(500), 30 * 86400, limitation_factor=0.5)

    assert limited == same
    assert limited.biomass_total >= initial.biomass_total
    assert limited.biomass_total < unlimited.biomass_total
    assert 0 <= limited.leaf_area_index <= profile().maximum_lai


def test_growth_uses_the_stage_after_phenology_transition():
    initial = state(crop_key="tomato", current_stage="establishment")
    phenological = PhenologyEngine().advance(initial, weather(25), T0.replace(day=21), 20 * 86400)
    growth = RadiationGrowthEngine().advance(phenological, weather(500), 20 * 86400)

    assert phenological.current_stage == "vegetative_growth"
    assert growth.current_stage == "vegetative_growth"
    assert growth.biomass_stem > phenological.biomass_stem


def test_invalid_growth_inputs_are_rejected():
    with pytest.raises(ValueError):
        RadiationGrowthEngine.par_mj_m2(-1, 3600)
    with pytest.raises(ValueError):
        engine().advance(state(), weather(500), 3600, limitation_factor=1.1)