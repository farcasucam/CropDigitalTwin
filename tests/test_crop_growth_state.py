from datetime import datetime, timedelta, timezone

import pytest

from agri_twin.application import SimulationClock
from agri_twin.domain import CropGrowthState


T0 = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)


def state(**changes) -> CropGrowthState:
    values = {
        "simulation_time": T0,
        "crop_key": "tomato",
        "variety": "RAF",
        "current_stage": "vegetative_growth",
        "soil_water_vwc": 0.25,
    }
    values.update(changes)
    return CropGrowthState(**values)


def test_initial_state_is_zero_growth_and_is_timestamped_by_simulation_time():
    initial = state()

    assert initial.simulation_time == T0
    assert initial.biomass_total == 0
    assert initial.phenology_progress == 0
    assert initial.harvest_ready is False


def test_state_enforces_biomass_and_harvest_invariants():
    valid = state(biomass_total=3.0, biomass_leaf=1.0, biomass_stem=1.0, biomass_root=1.0)
    assert valid.biomass_total == 3.0
    with pytest.raises(ValueError, match="partitioned"):
        state(biomass_total=1.0, biomass_leaf=0.5)
    with pytest.raises(ValueError, match="harvest_ready"):
        state(harvest_ready=True)


@pytest.mark.parametrize("changes", [
    {"simulation_time": datetime(2026, 9, 5, 12)},
    {"soil_water_vwc": 1.1},
    {"heat_stress": -0.1},
    {"biomass_total": -1.0},
    {"crop_key": ""},
])
def test_state_rejects_values_outside_its_contract(changes):
    with pytest.raises(ValueError):
        state(**changes)


def test_advance_uses_explicit_simulation_time_and_supports_multiple_days():
    initial = state()
    future = T0 + timedelta(days=3, hours=6)

    advanced = initial.advance(future, 3 * 86400 + 6 * 3600)

    assert advanced.simulation_time == future
    assert advanced.to_dict()["simulation_time"] == future.isoformat()
    assert advanced.biomass_total == initial.biomass_total


def test_advance_is_deterministic_and_rejects_time_mismatch():
    initial = state()
    future = T0 + timedelta(hours=4)

    assert initial.advance(future, 14400) == initial.advance(future, 14400)
    with pytest.raises(ValueError, match="advance by dt_seconds"):
        initial.advance(future, 1)


def test_advance_accepts_the_explicit_delta_from_simulation_clock():
    clock = SimulationClock(T0)
    initial = state()

    dt = clock.advance(7200)
    advanced = initial.advance(clock.now(), dt.total_seconds())

    assert advanced.simulation_time == T0 + timedelta(hours=2)


def test_serialization_is_json_ready_and_preserves_all_state_fields():
    payload = state(biomass_total=2.0, biomass_leaf=2.0).to_dict()

    assert payload["simulation_time"] == T0.isoformat()
    assert payload["biomass_leaf"] == 2.0
    assert __import__("json").dumps(payload)


@pytest.mark.parametrize("crop_key,variety,current_stage", [
    ("lettuce", "generic", "establishment"),
    ("plum", "Suplum 26", "yield_maturation"),
])
def test_state_supports_annual_and_perennial_crops(crop_key, variety, current_stage):
    growth_state = state(crop_key=crop_key, variety=variety, current_stage=current_stage)

    assert growth_state.crop_key == crop_key
    assert growth_state.current_stage == current_stage