"""Phase 5.32 season-scale synthetic campaigns.

The shared fixture runs all seven crops (outdoor, and greenhouse for tomato,
lettuce and pepper) under five representative scenarios plus multi-plot and
multi-cycle; all twelve mandatory scenarios are exercised on the short lettuce
campaign. The full 12-scenario x 7-crop matrix is produced by the manual script.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agri_twin.application.scenarios import Scenario, ScenarioEvent, ScenarioKind, ScenarioRunner, _ScenarioWeatherProvider
from agri_twin.application.seasonal_synthetic_campaign import (
    BEHAVIOR_CONSISTENT,
    MANDATORY_SCENARIOS,
    CampaignStatus,
    SeasonalSyntheticCampaignSuite,
    build_campaign,
    campaign_cycle,
    climate_profile,
    stress_exposure,
    weather_configuration,
)
from agri_twin.application.weather import WeatherEngine
from agri_twin.domain import CropGrowthState, GreenhouseConfiguration, SoilState, WeatherConfiguration, WeatherState
from agri_twin.domain.weather import SeasonalConfiguration

ROOT = Path(__file__).resolve().parents[1]
CROPS = ("tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple")
FIXTURE_SCENARIOS = ("BASE_SEASON", "HEAT_WAVE", "LOW_RADIATION", "DRY_SEASON", "RECOVERY_AFTER_STRESS")


@pytest.fixture(scope="module")
def report():
    return SeasonalSyntheticCampaignSuite(ROOT, crops=CROPS, scenarios=FIXTURE_SCENARIOS, supplementary=False).build_report()


@pytest.fixture(scope="module")
def runs(report):
    return {result.spec.run_id: result for result in report.campaigns}


@pytest.fixture(scope="module")
def directions(report):
    return {row["run_id"]: row for row in report.sections["directions"]}


@pytest.fixture(scope="module")
def lettuce_suite():
    suite = SeasonalSyntheticCampaignSuite(ROOT, crops=("lettuce",), supplementary=False, include_multi=False)
    specs = [build_campaign("lettuce", "outdoor", scenario_id) for scenario_id in MANDATORY_SCENARIOS]
    raw = {spec.run_id: suite.run(spec) for spec in specs}
    results = {spec.run_id: suite.evaluate(spec, raw[spec.run_id]) for spec in specs}
    return suite, results, {row["run_id"]: row for row in suite.directions(results, raw)}


def check(row, name):
    return next(item for item in row["direction_checks"] if item["check"] == name)


# --- climate profiles --------------------------------------------------------------------


@pytest.fixture(scope="module")
def climate(report):
    return report.sections["climate_profiles"]["checks"]


@pytest.mark.parametrize("name", [
    "seasonal_gradient", "seasonal_daylength", "continuity_across_days", "night_radiation_zero",
    "radiation_peak_midday", "diurnal_temperature_phase", "physical_bounds", "daily_variability_reproducible",
    "event_gradual_onset_and_decay", "return_to_base_after_event",
])
def test_climate_profile_property(climate, name):
    assert climate[name]["passed"] is True, climate[name]


def test_seasonal_cycle_is_warmer_and_longer_in_summer(climate):
    assert climate["seasonal_gradient"]["july_mean_c"] > climate["seasonal_gradient"]["january_mean_c"] + 10.0
    assert climate["seasonal_daylength"]["july_daylight_h"] > climate["seasonal_daylength"]["january_daylight_h"]


def test_weather_engine_without_seasonal_configuration_is_unchanged():
    instants = [datetime(2026, 4, 1, tzinfo=timezone.utc) + timedelta(hours=h) for h in range(72)]
    default = WeatherEngine(WeatherConfiguration())
    explicit_none = WeatherEngine(WeatherConfiguration(seasonal=None, daily_variability=None))
    zero = WeatherEngine(WeatherConfiguration(seasonal=SeasonalConfiguration()))
    assert [default.generate(t) for t in instants] == [explicit_none.generate(t) for t in instants]
    assert [default.generate(t).temperature_c for t in instants] == [zero.generate(t).temperature_c for t in instants]


def test_unramped_scenario_events_are_unchanged():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    crop = CropGrowthState(start, "tomato", "RAF", "vegetative_growth", biomass_total=10.0, biomass_leaf=4.0, biomass_stem=3.0, biomass_root=3.0, leaf_area_index=1.0, phenology_model="TEST")
    events = (ScenarioEvent("cold", "cold", start, start + timedelta(hours=3), 4.0, {"temperature_c": 4.0}), ScenarioEvent("rad", "low_radiation", start, start + timedelta(hours=3), 0.3, {"radiation_multiplier": 0.3}))
    scenario = Scenario("u", "u", "", "tomato", "RAF", start, start + timedelta(hours=3), 3600, ScenarioKind.SYNTHETIC, crop, SoilState(0.25, 20.0, 0.35, 0.10, 0.0, 100.0), WeatherState(20.3, 60.0, 500.0, 2.0, 180.0, 0.0, 1013.0), "outdoor", events)
    weather = _ScenarioWeatherProvider(scenario).get(start + timedelta(hours=1))
    assert weather.temperature_c == 4.0 and weather.solar_radiation_w_m2 == 500.0 * 0.3


def test_climate_scenario_hash_is_deterministic_and_seed_sensitive():
    first, second = build_campaign("tomato", "outdoor", "HEAT_WAVE"), build_campaign("tomato", "outdoor", "HEAT_WAVE")
    other = build_campaign("tomato", "outdoor", "HEAT_WAVE", seed=999)
    assert first.climate.deterministic_hash == second.climate.deterministic_hash != other.climate.deterministic_hash


def test_scenario_profiles_shift_the_season():
    base, hot, dry = climate_profile("BASE_SEASON"), climate_profile("HOT_SEASON"), climate_profile("DRY_SEASON")
    assert hot["temperature_max_c"] == base["temperature_max_c"] + 3.0
    assert dry["humidity_max_pct"] == base["humidity_max_pct"] - 20.0
    assert weather_configuration(base, 1).seasonal is not None


def test_campaign_dates_come_from_existing_synthetic_cycles():
    cycle, start, end = campaign_cycle("tomato")
    assert start.date() == cycle.planting_date and end.date() == cycle.harvest_end + timedelta(days=1)
    grape_cycle, grape_start, _ = campaign_cycle("grape")
    assert grape_cycle.planting_date is None and grape_start.date().isoformat() == "2026-01-01"


# --- crop campaigns ------------------------------------------------------------------------


@pytest.mark.parametrize("crop", CROPS)
def test_full_campaign_runs_for_every_crop(runs, crop):
    result = runs[f"p532_{crop}_outdoor_base_season"]
    assert result.status is not CampaignStatus.FAIL, result.failures
    assert result.steps == result.spec.days * 24
    assert all(count == 0 for count in result.invariants.values())
    assert result.to_dict()["variety_parameters"] == "SPECIES_FALLBACK"


def test_every_fixture_campaign_passes_invariants(report):
    assert all(result.status is not CampaignStatus.FAIL for result in report.campaigns)
    assert all(all(value is True for value in result.extra_invariants.values()) for result in report.campaigns)


def test_stress_exposure_uses_existing_factors_and_is_non_negative(runs):
    exposure = runs["p532_tomato_outdoor_base_season"].stress
    assert set(exposure) == {"heat", "cold", "water", "vpd", "radiation", "nutrient"}
    assert all(item["hours"] >= 0 and item["stress_hours"] >= 0 for item in exposure.values())


def test_perennial_campaign_releases_dormancy_then_matures(runs):
    metrics = runs["p532_plum_outdoor_base_season"].metrics
    assert metrics["dormancy_release_time"] is not None and metrics["maturity_time"] is not None
    assert metrics["dormancy_release_time"] < metrics["maturity_time"]


def test_unmet_chilling_is_reported_as_open_scientific_decision(report):
    decisions = {item["crop"]: item for item in report.open_decisions}
    assert {"peach", "apple"} <= set(decisions) and "plum" not in decisions and "grape" not in decisions
    assert all(item["classification"] == "OPEN_SCIENTIFIC_DECISION" for item in decisions.values())
    assert report.to_dict()["scientific_status"]["season_responses_not_characterised"] == sorted(decisions)


def test_known_varieties_are_kept(report):
    assert {"RAF", "Lamuyo", "Monastrell", "Suplum 26"} <= set(report.summary()["varieties"])


# --- greenhouse -------------------------------------------------------------------------------


@pytest.mark.parametrize("crop", ["tomato", "lettuce", "pepper"])
def test_greenhouse_crop_consumes_indoor_microclimate(runs, crop):
    result = runs[f"p532_{crop}_greenhouse_base_season"]
    assert result.extra_invariants["crop_consumes_correct_environment"] is True
    assert result.extra_invariants["co2_single_response"] is True


def test_greenhouse_section_passes(report):
    greenhouse = report.sections["greenhouse"]
    assert greenhouse["status"] == "PASS" and greenhouse["campaigns"] == 3 * len(FIXTURE_SCENARIOS)


def test_greenhouse_differs_from_outdoor_through_the_microclimate(runs):
    outdoor, greenhouse = runs["p532_tomato_outdoor_base_season"].metrics, runs["p532_tomato_greenhouse_base_season"].metrics
    assert greenhouse["mean_crop_radiation_w_m2"] < outdoor["mean_crop_radiation_w_m2"]
    assert greenhouse["precipitation_mm"] == 0.0


# --- stress responses -------------------------------------------------------------------------


def test_heat_wave_response_is_consistent(directions):
    row = directions["p532_tomato_outdoor_heat_wave"]
    assert row["classification"] == BEHAVIOR_CONSISTENT and row["biological_validation"] == "NOT_CLAIMED"
    assert check(row, "window_vpd_higher")["value"] > 0 and check(row, "window_growth_delta")["passed"] is None


def test_low_radiation_lowers_apar_under_controlled_conditions(directions):
    row = directions["p532_tomato_outdoor_low_radiation"]
    assert check(row, "controlled_apar_response")["value"] < 0 and check(row, "cumulative_apar_delta")["value"] < 0


def test_dry_season_raises_vpd_and_water_limitation(directions):
    row = directions["p532_pepper_outdoor_dry_season"]
    assert check(row, "drier_air_higher_vpd")["passed"] and check(row, "water_limitation_higher")["passed"]


def test_recovery_after_stress_does_not_restore_lost_biomass(directions):
    for crop in ("tomato", "pepper", "plum"):
        row = directions[f"p532_{crop}_outdoor_recovery_after_stress"]
        assert check(row, "stress_decreases_after_event")["passed"] and check(row, "lost_biomass_not_restored")["passed"]
        assert check(row, "identical_before_event")["passed"]


def test_all_direction_rows_are_model_behavior_consistent(report):
    assert report.summary()["inconsistent_rows"] == 0
    assert all(row["classification"] == BEHAVIOR_CONSISTENT for row in report.sections["directions"])


@pytest.mark.parametrize("scenario_id", MANDATORY_SCENARIOS)
def test_every_mandatory_scenario_runs_on_the_lettuce_campaign(lettuce_suite, scenario_id):
    _, results, rows = lettuce_suite
    run_id = f"p532_lettuce_outdoor_{scenario_id.lower()}"
    assert results[run_id].status is not CampaignStatus.FAIL, results[run_id].failures
    if scenario_id != "BASE_SEASON":
        assert rows[run_id]["classification"] == BEHAVIOR_CONSISTENT, rows[run_id]["direction_checks"]


def test_cold_wave_raises_cold_stress_on_lettuce(lettuce_suite):
    _, _, rows = lettuce_suite
    assert check(rows["p532_lettuce_outdoor_cold_wave"], "window_cold_stress_not_lower")["value"] > 0


# --- multi-plot and multi-cycle ---------------------------------------------------------------------


def test_multi_plot_states_are_isolated_under_seasonal_weather(report):
    section = report.sections["multi_plot"]
    assert section["status"] == "PASS" and section["combined_equals_isolated_runs"]


def test_multi_plot_perturbation_stays_in_its_plot(report):
    assert report.sections["multi_plot"]["perturbation_isolated"] is True


def test_multi_plot_repository_is_isolated(report):
    section = report.sections["multi_plot"]
    assert section["repository_histories_isolated"] and section["one_state_per_plot_per_snapshot"]


def test_second_lettuce_cycle_starts_fresh(report):
    assert report.sections["multi_cycle"]["second_cycle_starts_from_fresh_state"] is True


def test_finished_cycles_are_not_reactivated(report):
    assert all(cycle["not_reactivated"] and cycle["stepped_only_within_cycle_dates"] for cycle in report.sections["multi_cycle"]["lettuce_cycles"].values())


def test_perennial_campaign_sequence_and_next_campaign_capability(report):
    perennial = report.sections["multi_cycle"]["perennial_campaign"]
    assert perennial["status_sequence_valid"] is True and perennial["next_campaign_transition"] == "NOT_APPLICABLE"
    assert any(item["capability"] == "PERENNIAL_CONSECUTIVE_CAMPAIGNS" for item in report.unsupported)


# --- checkpoint / restart --------------------------------------------------------------------------


@pytest.mark.parametrize("run_id", ["p532_tomato_outdoor_base_season", "p532_plum_outdoor_base_season"])
def test_restart_from_checkpoint_equals_continuous_campaign(report, run_id):
    run = next(item for item in report.sections["restart"]["runs"] if item["run_id"] == run_id)
    assert [row["fraction"] for row in run["checkpoints"]] == [0.25, 0.5, 0.75]
    assert all(row["equivalent"] and row["max_difference"] == 0.0 for row in run["checkpoints"])


def test_checkpoint_hashes_are_recorded(report):
    assert report.sections["restart"]["status"] == "PASS"
    assert all(len(row["checkpoint_hash"]) == 64 for run in report.sections["restart"]["runs"] for row in run["checkpoints"])


# --- determinism, immutability, audit ---------------------------------------------------------------


def test_replayed_campaigns_are_identical(report):
    determinism = report.sections["determinism"]
    assert determinism["status"] == "PASS" and determinism["mismatches"] == []
    assert {f"p532_tomato_outdoor_{s.lower()}" for s in FIXTURE_SCENARIOS} <= set(determinism["replayed_runs"])


def test_report_json_is_deterministic(tmp_path):
    first = SeasonalSyntheticCampaignSuite(ROOT, crops=("lettuce",), scenarios=("BASE_SEASON", "HEAT_WAVE"), supplementary=False, include_multi=False).build_report()
    second = SeasonalSyntheticCampaignSuite(ROOT, crops=("lettuce",), scenarios=("BASE_SEASON", "HEAT_WAVE"), supplementary=False, include_multi=False).build_report()
    assert first.to_json() == second.to_json()
    report_path, readme_path = SeasonalSyntheticCampaignSuite(ROOT, crops=("lettuce",)).write_report(first, tmp_path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["report_hash"] == first.to_dict()["report_hash"] and "execution_metadata" in payload
    assert "not accuracy" in readme_path.read_text(encoding="utf-8")


def test_parameters_and_configuration_are_immutable(report):
    immutability = report.sections["immutability"]
    assert immutability["status"] == "PASS" and immutability["before"] == immutability["after"]


def test_greenhouse_configuration_default_is_untouched(report):
    assert GreenhouseConfiguration().ventilation_ach == 3.0 and GreenhouseConfiguration().volume_m3 == 1000.0


def test_static_audit_passes(report):
    audit = report.sections["static_audit"]
    assert audit["status"] == "PASS" and audit["duplicate_core_classes"] == {} and audit["violations"] == []


def test_scientific_status_is_conservative(report):
    status = report.to_dict()["scientific_status"]
    assert status["REAL_VERIFIED"] == 0 and status["CALIBRATION_PERFORMED"] is False
    assert status["EXPERIMENTAL_VALIDATION_PERFORMED"] is False and status["BIOLOGICAL_VALIDITY_CLAIMED"] is False
    assert status["outcome_classification"] == BEHAVIOR_CONSISTENT


def test_stress_exposure_window_subset_is_bounded_by_the_season(runs):
    result = runs["p532_tomato_outdoor_heat_wave"]
    for name, window in result.window_stress.items():
        assert window["hours"] <= result.stress[name]["hours"]
