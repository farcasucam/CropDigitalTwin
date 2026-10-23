"""Site resources (equipment, prices, conversions in one configuration) and the season results computed with them."""

from __future__ import annotations

import json
import shutil

import pytest

from agri_twin.application.season_kpis import season_kpis
from agri_twin.application.site_resources import SITE_RESOURCES_FILE, SiteResources, SiteResourcesError, load_site_resources, save_site_resources
from agri_twin.interfaces.frontend_api import InteractiveFrontendAdapter

STEPS = 48
TIMES = [f"2026-04-{1 + h // 24:02d}T{h % 24:02d}:00:00+00:00" for h in range(STEPS)]


def resources(**sections) -> SiteResources:
    base = {"equipment": {}, "prices": {"currency": "EUR", "electricity": {}, "water": {}}, "crops": {}}
    for key, value in sections.items():
        base[key] = {**base[key], **value} if isinstance(base[key], dict) else value
    return SiteResources.from_mapping(base)


def series(**overrides):
    base = {"biomass_fruit_g_m2": [0.0] + [10.0] * (STEPS - 1), "biomass_total_g_m2": [100.0] + [160.0] * (STEPS - 1), "irrigation_mm": [0.5] * STEPS, "drainage_mm": [0.05] * STEPS,
            "precipitation_mm": [0.0] * STEPS, "transpiration_mm": [0.2] * STEPS, "greenhouse_heating_kw": [10.0] * STEPS, "greenhouse_cooling_kw": [0.0] * STEPS,
            "temperature_c": [20.0] * STEPS, "crop_stage": ["vegetative_growth"] * STEPS, "frost_damage": [0.0] * STEPS, "accumulated_stress": [0.2] * STEPS,
            "heat_stress": [0.1] * STEPS, "water_stress": [0.0] * STEPS}
    base.update(overrides)
    return base


# ---- the configuration ---------------------------------------------------------------------------------------------------------------------------
def test_the_template_is_empty_and_valid_and_nothing_is_assumed():
    loaded, document = load_site_resources()
    assert document["contract"] == "site_resources" and loaded.equipment.heating_efficiency is None and loaded.equipment.cooling_cop is None
    assert loaded.electricity.flat_per_kwh is None and not loaded.water.defined and loaded.heating_energy is None and all(fraction is None for _, fraction in loaded.fruit_dry_matter_fraction)
    assert loaded.content_hash == load_site_resources()[0].content_hash and len(loaded.content_hash) == 64


@pytest.mark.parametrize("document, path", [({"extra": 1}, "extra"), ({"equipment": {"toaster": 1}}, "equipment"), ({"prices": {"currency": ""}}, "prices.currency"),
                                            ({"prices": {"water": {"flat_per_m3": -1}}}, "prices.water.flat_per_m3"), ({"prices": {"water": {"gallons": 1}}}, "prices.water.gallons"),
                                            ({"prices": {"water": {"yearly": {"x": 1}}}}, "prices.water.yearly"), ({"prices": {"bread": 1}}, "prices.bread"),
                                            ({"crops": {"kale": {"fruit_dry_matter_fraction": 0.1}}}, "crops.kale"), ({"crops": {"tomato": {"fruit_dry_matter_fraction": 1.5}}}, "crops.tomato.fruit_dry_matter_fraction"),
                                            ({"crops": {"tomato": {"price": 1}}}, "crops.tomato")])
def test_an_invalid_configuration_is_rejected_with_a_path(document, path):
    with pytest.raises(SiteResourcesError) as caught:
        SiteResources.from_mapping(document)
    assert caught.value.path == path


def test_saving_validates_first_keeps_the_notes_and_never_half_writes(tmp_path):
    target = tmp_path / "site_resources.json"
    shutil.copy(SITE_RESOURCES_FILE, target)
    saved = save_site_resources({"equipment": {"heating_efficiency": 0.9, "cooling_cop": 3.0}, "prices": {"water": {"flat_per_m3": 0.8}}, "crops": {"tomato": {"fruit_dry_matter_fraction": 0.055}}}, target)
    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["status"] == "USER_DEFINED" and document["meanings"] and document["contract"] == "site_resources" and document["note"]
    assert saved.equipment.heating_efficiency == 0.9 and saved.water.flat_per_m3 == 0.8 and saved.fraction_for("tomato") == 0.055
    before = target.read_text(encoding="utf-8")
    with pytest.raises(SiteResourcesError):
        save_site_resources({"equipment": {"heating_efficiency": -2}}, target)
    with pytest.raises(SiteResourcesError):
        save_site_resources({"meanings": {}}, target)
    assert target.read_text(encoding="utf-8") == before and not list(tmp_path.glob("*.tmp"))


# ---- the season results --------------------------------------------------------------------------------------------------------------------------
def test_yield_converts_dry_matter_to_fresh_product_only_with_the_users_share_and_area():
    bare = season_kpis(resources(), crop="tomato", times=TIMES, series=series(), area_m2=1000.0, area_source="test")
    assert bare["yield"]["fruit_dry_matter_g_m2"] == 10.0 and bare["yield"]["dry_matter_kg"] == pytest.approx(10.0) and bare["yield"]["fresh_product_kg"] is None
    assert "fruit_dry_matter_fraction of tomato" in bare["missing"] and bare["yield"]["calibre"] == "not modelled"
    full = season_kpis(resources(crops={"tomato": {"fruit_dry_matter_fraction": 0.05}}), crop="tomato", times=TIMES, series=series(), area_m2=1000.0, area_source="test")
    assert full["yield"]["fresh_product_kg_m2"] == pytest.approx(0.2) and full["yield"]["fresh_product_kg"] == pytest.approx(200.0) and full["yield"]["fresh_product_t_ha"] == pytest.approx(2.0)


def test_water_is_volume_from_the_area_and_priced_per_calendar_year_with_a_single_price_fallback():
    kpi = season_kpis(resources(prices={"currency": "EUR", "electricity": {}, "water": {"flat_per_m3": 1.0, "yearly": {"2026": 2.0}}}), crop="tomato", times=TIMES, series=series(), area_m2=1000.0, area_source="test")
    assert kpi["water"]["irrigation_mm"] == pytest.approx(24.0) and kpi["water"]["irrigation_m3"] == pytest.approx(24.0)  # 24 mm over 1000 m2 = 24 m3
    assert kpi["water"]["cost"] == pytest.approx(48.0) and kpi["water"]["cost_per_m2"] == pytest.approx(0.048)  # 2026 costs 2 per m3
    assert kpi["water"]["drained_share"] == pytest.approx(0.1)
    unpriced = season_kpis(resources(), crop="tomato", times=TIMES, series=series(), area_m2=1000.0, area_source="test")
    assert unpriced["water"]["cost"] is None and "water price" in unpriced["missing"]


def test_energy_is_thermal_power_over_the_efficiency_and_what_is_not_defined_is_listed_not_assumed():
    nothing = season_kpis(resources(), crop="tomato", times=TIMES, series=series(), area_m2=100.0, area_source="test")
    assert nothing["energy"]["heating_thermal_kwh"] == pytest.approx(480.0) and nothing["energy"]["input_kwh"] is None and any("heating_efficiency" in item for item in nothing["missing"])
    defined = season_kpis(resources(equipment={"heating_efficiency": 0.8}), crop="tomato", times=TIMES, series=series(), area_m2=100.0, area_source="test")
    assert defined["energy"]["heating_input_kwh"] == pytest.approx(600.0) and defined["energy"]["cooling_input_kwh"] == 0.0  # no cooling ran: no COP needed
    assert defined["energy"]["input_kwh_per_m2"] == pytest.approx(6.0)
    cooled = season_kpis(resources(equipment={"heating_efficiency": 0.8, "cooling_cop": 3.0, "extractor_power_kw": 2.0}), crop="tomato", times=TIMES,
                         series=series(greenhouse_cooling_kw=[30.0] * STEPS, control_extractor_level=[0.5] * STEPS), area_m2=100.0, area_source="test")
    assert cooled["energy"]["cooling_input_kwh"] == pytest.approx(480.0) and cooled["energy"]["extractor_kwh"] == pytest.approx(48.0) and cooled["energy"]["input_kwh"] == pytest.approx(1128.0)


def test_the_request_equipment_overrides_the_configured_field_by_field():
    kpi = season_kpis(resources(equipment={"heating_efficiency": 0.8}), crop="tomato", times=TIMES, series=series(), area_m2=100.0, area_source="test", equipment={"heating_efficiency": 0.5})
    assert kpi["energy"]["heating_input_kwh"] == pytest.approx(960.0)


def test_heating_has_its_own_price_when_given_and_otherwise_uses_the_electricity_tariff():
    priced = {"equipment": {"heating_efficiency": 1.0, "cooling_cop": 2.0}}
    both = season_kpis(resources(**priced, prices={"currency": "EUR", "electricity": {"flat_per_kwh": 0.2}, "heating_energy": {"flat_per_kwh": 0.05}, "water": {"flat_per_m3": 1.0}}), crop="tomato", times=TIMES,
                       series=series(greenhouse_cooling_kw=[20.0] * STEPS), area_m2=100.0, area_source="test")
    assert both["energy"]["cost"] == pytest.approx(480.0 * 0.05 + 480.0 * 0.2)  # heating at the fuel price, cooling at the electricity price
    shared = season_kpis(resources(**priced, prices={"currency": "EUR", "electricity": {"flat_per_kwh": 0.2}, "water": {"flat_per_m3": 1.0}}), crop="tomato", times=TIMES, series=series(), area_m2=100.0, area_source="test")
    assert shared["energy"]["cost"] == pytest.approx(480.0 * 0.2)
    missing = season_kpis(resources(**priced), crop="tomato", times=TIMES, series=series(), area_m2=100.0, area_source="test")
    assert missing["energy"]["cost"] is None and any("energy price" in item for item in missing["missing"])


def test_the_cost_of_resources_has_no_fruit_price_and_is_per_m2_and_per_kg():
    kpi = season_kpis(resources(equipment={"heating_efficiency": 1.0}, prices={"currency": "EUR", "electricity": {"flat_per_kwh": 0.1}, "water": {"flat_per_m3": 1.0}}, crops={"tomato": {"fruit_dry_matter_fraction": 0.05}}),
                      crop="tomato", times=TIMES, series=series(), area_m2=100.0, area_source="test")
    cost = kpi["cost"]
    assert cost["resource_cost"] == pytest.approx(48.0 + 2.4) and cost["resource_cost_per_m2"] == pytest.approx(0.504) and cost["resource_cost_per_kg_product"] == pytest.approx(50.4 / 20.0)
    assert cost["energy_share"] == pytest.approx(48.0 / 50.4) and "no price" in cost["note"] and kpi["energy"]["kwh_per_kg_product"] == pytest.approx(480.0 / 20.0)


def test_risk_counts_hours_against_the_stage_thresholds_of_the_crop_catalogue():
    hot = [31.0 if h < 5 else 20.0 for h in range(STEPS)]
    kpi = season_kpis(resources(), crop="tomato", times=TIMES, series=series(temperature_c=hot), area_m2=None, area_source="unknown")
    assert kpi["risk"]["hours_above_max_temp"] == 5.0 and kpi["risk"]["hours_below_min_temp"] == 0.0 and kpi["risk"]["peak_accumulated_stress"] == 0.2
    assert any("area" in item for item in kpi["missing"]) and kpi["area"]["m2"] is None and kpi["yield"]["dry_matter_kg"] is None  # per-m2 results do not need the area
    undefined = season_kpis(resources(), crop="tomato", times=TIMES, series=series(crop_stage=["not_a_stage"] * STEPS), area_m2=1.0, area_source="test")
    assert undefined["risk"]["hours_above_max_temp"] == 0.0 and undefined["risk"]["undefined_thresholds"]  # a stage without thresholds is listed, never invented


def test_a_plot_larger_than_the_simulated_unit_is_scaled_linearly_and_says_so():
    kpi = season_kpis(resources(equipment={"heating_efficiency": 1.0}, crops={"tomato": {"fruit_dry_matter_fraction": 0.05}}), crop="tomato", times=TIMES, series=series(), area_m2=1000.0, area_source="test", plot_area_m2=32500.0)
    scaling = kpi["plot_scaling"]
    assert scaling["factor"] == pytest.approx(32.5) and scaling["fresh_product_kg"] == pytest.approx(200.0 * 32.5) and scaling["input_kwh"] == pytest.approx(480.0 * 32.5) and "linear" in scaling["assumption"]
    assert season_kpis(resources(), crop="tomato", times=TIMES, series=series(), area_m2=1000.0, area_source="test", plot_area_m2=1000.0)["plot_scaling"] is None


def test_an_open_field_run_has_no_climate_equipment_energy():
    kpi = season_kpis(resources(), crop="grape", times=TIMES, series={k: v for k, v in series().items() if not k.startswith("greenhouse_")}, area_m2=124000.0, area_source="plot")
    assert kpi["energy"]["input_kwh"] is None and "open field" in kpi["energy"]["basis"] and kpi["cost"]["resource_cost"] is None
    assert kpi["statement"].startswith("simulated results of an uncalibrated model")


# ---- through the API on a real run -----------------------------------------------------------------------------------------------------------------
def test_the_api_serves_the_configuration_with_the_plot_areas_of_the_farm_json_and_computes_a_real_run():
    from agri_twin.application.interactive_simulation import InteractiveSimulationService

    adapter = InteractiveFrontendAdapter()
    configuration = adapter.site_resources()
    assert configuration["plots"]["tomato"]["area_m2"] == pytest.approx(32500.0) and configuration["content_hash"]
    assert configuration["plots"]["lettuce"]["typical"] and configuration["plots"]["lettuce"]["area_m2"] == pytest.approx(30000.0) and not configuration["plots"]["tomato"]["typical"]
    equipment = {"vent_max_ach": 30, "extractor_max_ach": 20, "extractor_power_kw": 20, "cooling_capacity_kw": 400, "cooling_cop": 3, "heating_capacity_kw": 150, "heating_efficiency": 0.9}
    control = {"actuators": {"vents": "AUTO", "extractors": "AUTO", "cooling": "AUTO", "heating": "AUTO"}, "equipment": equipment}
    run = InteractiveSimulationService().run_simulation({"crop": "tomato", "environment": "greenhouse", "end_time": "2026-03-01T00:00:00+00:00", "control": control,
                                                         "options": {"include_trajectory": True, "compute_trajectory_hash": False}}).result.trajectory
    body = {"crop": "tomato", "environment": "greenhouse", "times": run["time"], "series": {k: v for k, v in run.items() if k != "time"}, "equipment": equipment}
    kpi = adapter.season_kpis(body)
    assert kpi["area"]["m2"] == pytest.approx(864.0) and "layout" in kpi["area"]["source"] and kpi["plot_scaling"]["factor"] == pytest.approx(32500.0 / 864.0)
    assert kpi["energy"]["input_kwh"] is not None and kpi["energy"]["input_kwh"] >= 0.0 and kpi["yield"]["fruit_dry_matter_g_m2"] is not None
    with pytest.raises(ValueError):
        adapter.season_kpis({"crop": "tomato"})
    assert adapter.season_kpis({**body, "environment": "outdoor", "equipment": None, "series": {k: v for k, v in body["series"].items() if not k.startswith("greenhouse_")}})["area"]["m2"] == pytest.approx(32500.0)
