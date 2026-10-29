"""Level 1 of the nutrient line: the optional NITROGEN_DEMAND model (placeholder parameters). The tests check the STRUCTURE and the contract, never an agronomic value."""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from agri_twin.application.model_options import ModelOptionsError, parse_model_options
from agri_twin.domain import CropGrowthState, FertilizationRequest, NitrogenDemandEngine, NitrogenParameters, NutrientBalanceError
from agri_twin.interfaces.xai_adapter import TwinSimulator
from tsxai.core import Intervention, ScenarioDescriptor

NOW = datetime(2026, 5, 1, tzinfo=timezone.utc)


def state(**changes) -> CropGrowthState:
    values = dict(simulation_time=NOW, crop_key="tomato", variety="v", current_stage="vegetative_growth", biomass_total=300.0, biomass_leaf=300.0)
    values.update(changes)
    return CropGrowthState(**values)


def test_the_critical_nitrogen_is_continuous_at_one_tonne_and_grows_with_the_biomass_but_slower_than_it():
    engine = NitrogenDemandEngine()
    below, at, above = engine.critical_nitrogen_kg_ha(99.99), engine.critical_nitrogen_kg_ha(100.0), engine.critical_nitrogen_kg_ha(100.01)
    assert math.isclose(below, at, rel_tol=1e-3) and math.isclose(at, above, rel_tol=1e-3)
    assert engine.critical_nitrogen_kg_ha(0.0) == 0.0
    small, large = engine.critical_nitrogen_kg_ha(200.0), engine.critical_nitrogen_kg_ha(800.0)
    assert large > small and large / small < 4.0  # dilution: the nitrogen per unit biomass falls as the crop grows


def test_the_first_step_starts_the_crop_at_its_critical_nitrogen_and_a_missing_soil_nitrogen_limits_it():
    engine = NitrogenDemandEngine(NitrogenParameters(initial_soil_nitrogen_kg_ha=0.0))
    result = engine.advance(state(), growth_potential_g_m2=20.0, dt_seconds=3600.0)
    assert result.plant_nitrogen_kg_ha is not None and result.nutrient_extracted_kg_ha == 0.0
    assert result.nutrient_status < 1.0 and math.isclose(result.growth_actual_g_m2, 20.0 * result.nutrient_status)
    assert result.state.plant_nitrogen_kg_ha == result.plant_nitrogen_kg_ha


def test_a_dose_is_taken_up_by_demand_not_capped_at_a_reserve_and_the_excess_stays_in_the_soil():
    engine = NitrogenDemandEngine(NitrogenParameters(initial_soil_nitrogen_kg_ha=0.0))
    first = engine.advance(state(), 20.0, 3600.0)
    dosed = engine.advance(first.state, 20.0, 3600.0, FertilizationRequest(500.0, 1.0, "scheduled"))
    assert dosed.nutrient_applied_kg_ha == 500.0 and dosed.nutrient_available_kg_ha > 200.0  # no cap at the 200 kg/ha reserve of the reduced model
    assert dosed.state.nutrient_available_kg_ha <= dosed.state.nutrient_reserve_kg_ha  # the state's invariant holds
    assert dosed.nutrient_status >= first.nutrient_status


def test_leaching_follows_the_drainage_fraction_given_by_the_orchestrator():
    engine = NitrogenDemandEngine()
    dry = engine.advance(state(), 10.0, 3600.0, None, 0.0)
    wet = engine.advance(state(), 10.0, 3600.0, None, 0.2)
    assert dry.nutrient_leached_kg_ha == 0.0 and wet.nutrient_leached_kg_ha > 0.0
    assert wet.nutrient_available_kg_ha < dry.nutrient_available_kg_ha
    with pytest.raises(NutrientBalanceError):
        engine.advance(state(), 10.0, 3600.0, None, 1.5)


def test_the_option_is_validated_and_the_default_leaves_the_request_without_a_block():
    assert parse_model_options({"nutrient_model": "REDUCED_POOL"}, "outdoor") is None
    options = parse_model_options({"nutrient_model": "nitrogen_demand", "soil_nitrogen_initial_kg_ha": 50}, "outdoor")
    assert options.nutrient_model == "NITROGEN_DEMAND" and options.to_dict() == {"nutrient_model": "NITROGEN_DEMAND", "soil_nitrogen_initial_kg_ha": 50.0}
    with pytest.raises(ModelOptionsError):
        parse_model_options({"nutrient_model": "OTHER"}, "outdoor")
    with pytest.raises(ModelOptionsError):
        parse_model_options({"soil_nitrogen_initial_kg_ha": 50}, "outdoor")  # needs the NITROGEN_DEMAND model
    with pytest.raises(ModelOptionsError):
        parse_model_options({"nutrient_model": "NITROGEN_DEMAND", "soil_nitrogen_initial_kg_ha": -1}, "outdoor")


def test_a_historical_state_keeps_its_representation_without_the_crop_nitrogen():
    assert "plant_nitrogen_kg_ha" not in state().to_dict()
    with_nitrogen = state(plant_nitrogen_kg_ha=12.0)
    assert with_nitrogen.to_dict()["plant_nitrogen_kg_ha"] == 12.0 and CropGrowthState.from_dict(with_nitrogen.to_dict()) == with_nitrogen
    with pytest.raises(ValueError):
        state(plant_nitrogen_kg_ha=-1.0)


@pytest.fixture(scope="module")
def runs():
    simulator = TwinSimulator()
    labels = {"crop": "tomato", "environment": "outdoor", "control": "off"}
    base = dict(simulator.scenario_options(labels, 34))
    nitrogen = {**base, "model_options": {"nutrient_model": "NITROGEN_DEMAND", "soil_nitrogen_initial_kg_ha": 60.0}}
    return (simulator.run(ScenarioDescriptor(labels, 34, 1500, 120, base), ()), simulator.run(ScenarioDescriptor(labels, 34, 1500, 120, nitrogen), ()),
            simulator.run(ScenarioDescriptor(labels, 34, 1500, 120, nitrogen), (Intervention("FERTILIZATION", 10, 24, 60.0),)))


def test_the_crop_nitrogen_series_exist_only_with_the_nitrogen_model(runs):
    reduced, nitrogen, _ = runs
    assert "plant_nitrogen_kg_ha" not in reduced.series and "critical_nitrogen_kg_ha" not in reduced.series
    assert "plant_nitrogen_kg_ha" in nitrogen.series and all(a <= b + 1e-9 for a, b in zip(nitrogen.series["plant_nitrogen_kg_ha"], nitrogen.series["critical_nitrogen_kg_ha"]))


def test_a_dose_raises_the_nitrogen_status_and_the_biomass_when_the_soil_is_short(runs):
    _, nitrogen, dosed = runs
    assert min(nitrogen.series["nutrient_status"]) < 1.0
    assert dosed.series["nutrient_status"][-1] > nitrogen.series["nutrient_status"][-1]
    assert dosed.series["biomass_total_g_m2"][-1] > nitrogen.series["biomass_total_g_m2"][-1]
