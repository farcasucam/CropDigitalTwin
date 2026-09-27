"""Phase 5.33 environment- and hemisphere-independent dormancy / chilling framework."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agri_twin.application.dormancy_chilling_framework import (
    DormancyChillingFrameworkSuite,
    DormancyOutcome,
    ReplayedWeather,
    hemisphere,
    initial_dormant_state,
    location_weather,
    record_series,
    run_dormancy_season,
)
from agri_twin.domain import WeatherState
from agri_twin.domain.parameter_audit import ParameterRegistry
from agri_twin.domain.phenology import (
    ChillingModel,
    ChillingModelType,
    ChillingStartPolicy,
    ChillingStartPolicyType,
    DormancyChillingController,
    PhenologyEngine,
    PhenologyError,
)

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
FIXTURE_LOCATIONS = ("NH_38N_MEDITERRANEAN", "NH_50N_CONTINENTAL", "SH_35S_TEMPERATE", "SH_20S_WARM_WINTER")


@pytest.fixture(scope="module")
def report():
    return DormancyChillingFrameworkSuite(ROOT, locations=FIXTURE_LOCATIONS).build_report()


@pytest.fixture(scope="module")
def payload(report):
    return report.to_dict()


def matrix(payload, location, crop, experiment):
    return next(row for row in payload["experiments"]["policy_matrix"]["rows"] if row["location_id"] == location and row["crop"] == crop and row["experiment"] == experiment)


def constant(temperature):
    return lambda _t: WeatherState(temperature, 70.0, 0.0, 2.0, 180.0, 0.0, 1013.0)


START = datetime(2026, 1, 1, tzinfo=UTC)


# --- controller: default equals the previous rule -----------------------------------------


def test_default_controller_reproduces_the_existing_chilling_hours_rule():
    engine = PhenologyEngine()
    state = initial_dormant_state("peach", START)
    cold = engine.advance(state, constant(4.0)(None), START + timedelta(hours=1), 3600.0)
    warm = engine.advance(state, constant(12.0)(None), START + timedelta(hours=1), 3600.0)
    assert cold.chilling_hours == 1.0 and warm.chilling_hours == 0.0
    assert engine.dormancy.policy.policy_type is ChillingStartPolicyType.DORMANCY_STATE
    assert engine.dormancy.model.model_type is ChillingModelType.CHILLING_HOURS


def test_fixed_date_policy_requires_an_explicit_instant_and_no_default_date_exists():
    with pytest.raises(PhenologyError):
        ChillingStartPolicy(ChillingStartPolicyType.FIXED_DATE)
    with pytest.raises(PhenologyError):
        ChillingStartPolicy(ChillingStartPolicyType.DORMANCY_STATE, START)
    policy = ChillingStartPolicy(ChillingStartPolicyType.FIXED_DATE, START + timedelta(days=10))
    assert not policy.counting(START) and policy.counting(START + timedelta(days=10))


def test_unimplemented_models_and_policies_report_model_not_supported():
    for model in (ChillingModel(ChillingModelType.UTAH), ChillingModel(ChillingModelType.DYNAMIC)):
        assert run_dormancy_season("peach", constant(4.0), START, 2, model=model).outcome is DormancyOutcome.MODEL_NOT_SUPPORTED
    assert run_dormancy_season("peach", constant(4.0), START, 2, policy=ChillingStartPolicy(ChillingStartPolicyType.MODEL_DEFINED)).outcome is DormancyOutcome.MODEL_NOT_SUPPORTED


# --- hemispheres ------------------------------------------------------------------------------


def test_hemisphere_is_geographic_metadata_derived_from_latitude():
    assert (hemisphere(38.0), hemisphere(-35.0), hemisphere(0.0)) == ("NORTHERN", "SOUTHERN", "EQUATORIAL")


def test_northern_hemisphere_releases_after_its_winter(payload):
    row = matrix(payload, "NH_38N_MEDITERRANEAN", "peach", "DORMANCY_STATE")
    assert row["outcome"] == "RELEASED" and row["dormancy_release"][5:7] in {"12", "01", "02", "03"}


def test_southern_hemisphere_releases_after_its_winter(payload):
    row = matrix(payload, "SH_35S_TEMPERATE", "peach", "DORMANCY_STATE")
    assert row["outcome"] == "RELEASED" and row["dormancy_release"][5:7] in {"06", "07", "08", "09"}


def test_hemisphere_inversion_uses_one_physiological_abstraction(payload):
    inversion = payload["experiments"]["hemisphere_inversion"]
    assert inversion["status"] == "PASS"
    assert all(row["release_elapsed_difference_h"] == 0.0 for row in inversion["rows"])


def test_northern_calendar_anchor_would_fail_the_inversion(payload):
    control = payload["experiments"]["hemisphere_inversion"]["negative_control"]
    assert control["detected"] and control["anchored_chill_h"] < 0.5 * control["calendar_free_chill_h"]


# --- calendar, latitude, longitude ----------------------------------------------------------------


def test_same_thermal_sequence_at_different_dates_accumulates_identically(payload):
    calendar = payload["experiments"]["calendar_independence"]
    assert calendar["dormancy_state_calendar_independent"] and len({row["dormancy_state_elapsed_hash"] for row in calendar["rows"]}) == 1


def test_explicit_fixed_date_is_the_only_calendar_dependence(payload):
    calendar = payload["experiments"]["calendar_independence"]
    assert calendar["fixed_date_depends_on_calendar"] and calendar["rows"][0]["fixed_date_excluded_chill_h"] > 0


def test_latitude_and_longitude_are_metadata_only(payload):
    location = payload["experiments"]["location_metadata_independence"]
    assert location["status"] == "PASS" and len(set(location["trajectory_hashes"].values())) == 1
    assert location["physiology_location_tokens"] == []


# --- policies ----------------------------------------------------------------------------------------


def test_fixed_date_protocol_excludes_chill_before_its_instant(payload):
    row = matrix(payload, "NH_50N_CONTINENTAL", "peach", "FIXED_DATE_PROTOCOL")
    assert row["chill_excluded_by_policy_h"] > 0 and row["counting_start"].startswith("2025-11-01")


def test_environmental_onset_matches_dormancy_state_under_chilling_hours(payload):
    for location in FIXTURE_LOCATIONS:
        a, b = matrix(payload, location, "apple", "DORMANCY_STATE"), matrix(payload, location, "apple", "EFFECTIVE_CHILL_ONSET")
        assert (a["dormancy_release"], a["chill_total_h"], a["first_effective_chill"]) == (b["dormancy_release"], b["chill_total_h"], b["first_effective_chill"])


def test_model_defined_onset_is_not_supported(payload):
    assert matrix(payload, "NH_38N_MEDITERRANEAN", "plum", "MODEL_DEFINED")["outcome"] == "MODEL_NOT_SUPPORTED"


# --- temporal context ---------------------------------------------------------------------------------


def test_late_campaign_is_insufficient_temporal_context_not_impossible_requirement(payload):
    rows = {(row["crop"], row["campaign_start"]): row for row in payload["experiments"]["phase532_reproduction"]["rows"]}
    for crop in ("peach", "apple"):
        assert rows[(crop, "01-Feb")]["outcome"] == "INSUFFICIENT_TEMPORAL_CONTEXT"
        assert rows[(crop, "01-Nov")]["outcome"] == "RELEASED"
    assert "WINDOW" in payload["experiments"]["phase532_reproduction"]["diagnosis"]


def test_no_chill_is_distinguished_from_missing_context(payload):
    row = matrix(payload, "SH_20S_WARM_WINTER", "peach", "DORMANCY_STATE")
    assert row["outcome"] == "NO_CHILL" and row["chill_total_h"] == 0.0


def test_dormancy_not_released_with_complete_context():
    result = run_dormancy_season("peach", constant(12.0), START, 3)
    assert result.outcome is DormancyOutcome.NO_CHILL
    partial = run_dormancy_season("peach", lambda t: constant(4.0 if t >= START + timedelta(days=2) else 12.0)(t), START, 5)
    assert partial.outcome is DormancyOutcome.DORMANCY_NOT_RELEASED and partial.chill_total > 0


# --- dormancy, release, forcing, budburst ---------------------------------------------------------------


def test_dormancy_blocks_thermal_time_until_release_then_forcing_then_budburst(payload):
    row = matrix(payload, "NH_38N_MEDITERRANEAN", "peach", "DORMANCY_STATE")
    assert row["first_effective_chill"] < row["dormancy_release"] <= row["forcing_start"] < row["budburst"]


def test_release_happens_exactly_at_the_requirement():
    result = run_dormancy_season("plum", constant(4.0), START, 30)
    assert result.chill_at_release == PhenologyEngine().profile_for("plum").chilling_requirement_hours
    assert result.dormancy_release == START + timedelta(hours=500)


@pytest.mark.parametrize("crop", ["peach", "apple", "plum"])
def test_each_species_is_a_compatible_test_case(payload, crop):
    north, south = matrix(payload, "NH_38N_MEDITERRANEAN", crop, "DORMANCY_STATE"), matrix(payload, "SH_35S_TEMPERATE", crop, "DORMANCY_STATE")
    requirement = PhenologyEngine().profile_for(crop).chilling_requirement_hours
    assert north["outcome"] == south["outcome"] == "RELEASED"
    assert north["chill_at_release_h"] == south["chill_at_release_h"] == requirement


# --- climate --------------------------------------------------------------------------------------------------


def test_warm_winter_accumulates_less_chill_and_may_not_release(payload):
    for row in payload["experiments"]["climate_comparison"]["rows"]:
        assert row["warm"]["chill_total_h"] <= row["moderate"]["chill_total_h"]
        assert row["warm"]["outcome"] == "DORMANCY_NOT_RELEASED"


def test_cold_and_variable_winters_release_and_stay_finite(payload):
    for row in payload["experiments"]["climate_comparison"]["rows"]:
        assert row["cold"]["outcome"] == row["high_variability"]["outcome"] == "RELEASED"
        assert row["all_finite"]


# --- integration, multi-plot, multi-cycle, restart ------------------------------------------------------------


def test_full_twin_growth_is_eligible_only_after_release(payload):
    twin = payload["experiments"]["twin_integration"]
    assert twin["status"] == "PASS" and not twin["growth_before_release"] and twin["growth_after_release"]


def test_full_twin_checkpoint_restart_is_exact(payload):
    restart = payload["experiments"]["twin_integration"]["restart"]
    assert restart["status"] == "PASS" and all(row["max_difference"] == 0.0 for row in restart["checkpoints"])


def test_dormancy_checkpoint_mid_chilling_restarts_exactly():
    location_weather_source = constant(4.0)
    continuous = run_dormancy_season("apple", location_weather_source, START, 40)
    first = run_dormancy_season("apple", location_weather_source, START, 10)
    resumed = run_dormancy_season("apple", location_weather_source, START + timedelta(days=10), 30, initial=first.final_state)
    assert resumed.final_state == continuous.final_state and resumed.dormancy_release == continuous.dormancy_release


def test_multi_plot_dormancy_is_isolated_on_one_clock(payload):
    section = payload["experiments"]["multi_plot"]
    assert section["status"] == "PASS" and section["combined_equals_isolated"]


def test_multi_cycle_second_season_starts_fresh(payload):
    section = payload["experiments"]["multi_cycle"]
    assert section["second_season_starts_fresh"] and section["carrying_released_state_would_skip_chilling"]
    assert "OPEN_MODEL_CAPABILITY" in section["capability"]


# --- determinism, integrity, audit, decision --------------------------------------------------------------------


def test_replayed_experiments_are_identical(payload):
    assert payload["determinism"]["status"] == "PASS" and payload["determinism"]["mismatches"] == []


def test_report_json_is_deterministic(tmp_path):
    first = DormancyChillingFrameworkSuite(ROOT, species=("plum",), locations=("SH_35S_TEMPERATE",), include_twin=False).build_report()
    second = DormancyChillingFrameworkSuite(ROOT, species=("plum",), locations=("SH_35S_TEMPERATE",), include_twin=False).build_report()
    assert first.to_json() == second.to_json()
    report_path, readme_path = DormancyChillingFrameworkSuite(ROOT).write_report(first, tmp_path)
    assert json.loads(report_path.read_text(encoding="utf-8"))["report_hash"] == first.to_dict()["report_hash"]
    assert "Nothing here is calibration" in readme_path.read_text(encoding="utf-8")


def test_parameters_and_configurations_are_not_mutated(payload):
    integrity = payload["parameter_integrity"]
    assert integrity["status"] == "PASS" and integrity["before"] == integrity["after"]


def test_no_nan_or_inf_in_any_experiment(payload):
    assert all(row["finite"] for row in payload["experiments"]["policy_matrix"]["rows"])


def test_physiology_has_no_hardcoded_dates_months_or_location_logic(payload):
    audit = payload["static_audit"]
    assert audit["status"] == "PASS"
    assert audit["hardcoded_month_names"] == [] and audit["calendar_constructors"] == [] and audit["calendar_attributes"] == []
    assert audit["phenology_and_chilling_engines"] == ["agri_twin/domain/phenology.py:DormancyChillingController", "agri_twin/domain/phenology.py:PhenologyEngine"]


def test_chilling_parameters_are_traceable_and_not_literature_without_evidence():
    registry = ParameterRegistry.from_repository(ROOT)
    for crop in ("peach", "apple", "plum", "grape"):
        record = registry.get(f"phenology.{crop}.chilling_requirement_hours")
        assert record.value == PhenologyEngine().profile_for(crop).chilling_requirement_hours
        assert record.source_type == "engineering_default" and record.calibration_status == "candidate_for_calibration"
    assert registry.get("phenology.chilling_start_policy").value == "DORMANCY_STATE"
    assert registry.get("phenology.chilling_hours.upper_threshold").value == 7.2


def test_scientific_decision_is_policy_uncertainty_without_universal_date(payload):
    decision = payload["scientific_decision"]
    assert decision["outcome"] == "POLICY_UNCERTAINTY" and decision["universal_start_date"] == "NOT_JUSTIFIED"
    assert {item["decision"] for item in payload["open_scientific_decisions"]} >= {"CHILLING_START_POLICY", "CHILLING_MODEL_SELECTION", "DORMANCY_INDUCTION"}
    assert payload["calibration_performed"] is False and payload["biological_validity_claimed"] is False


def test_software_results_are_separated_from_scientific_evidence(payload):
    assert payload["scientific_evidence"] and all(row["result_type"] == "SCIENTIFIC_EVIDENCE" for row in payload["scientific_evidence"])
    assert all(row["result_type"] == "SOFTWARE_RESULT" for row in payload["experiments"]["policy_matrix"]["rows"])
