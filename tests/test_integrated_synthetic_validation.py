from __future__ import annotations

import json
import math
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agri_twin.application.integrated_synthetic_validation import (
    INVARIANT_DEFINITIONS,
    IntegratedSyntheticValidationSuite,
    SyntheticScenarioKind,
    SyntheticValidationStatus,
    build_scenario,
    checkpoint_payload,
    restore_checkpoint,
    resumed_scenario,
    static_audit,
    synthetic_weather_factory,
    twin_state_from_snapshot,
    validate_trajectory,
)
from agri_twin.application.scenarios import Scenario, ScenarioError, ScenarioEvent, ScenarioKind, ScenarioRunner
from agri_twin.domain.models import CropGrowthState, SoilState, WeatherState
from agri_twin.domain.parameter_audit import ParameterRegistry

ROOT = Path(__file__).resolve().parents[1]
PASSING = {SyntheticValidationStatus.PASS.value, SyntheticValidationStatus.PASS_WITH_WARNINGS.value}


@pytest.fixture(scope="module")
def report():
    return IntegratedSyntheticValidationSuite(ROOT).build_report()


@pytest.fixture(scope="module")
def payload(report):
    return report.to_dict()


def case(payload, case_id):
    return next(item for item in payload["cases"] if item["case_id"] == case_id)


def metric(item, name):
    return next(entry for entry in item["metrics"] if entry["name"] == name)


def short_run(days=2):
    scenario = build_scenario("tomato", "outdoor", SyntheticScenarioKind.NORMAL_SEASON)
    end = scenario.start + timedelta(days=days)
    short = replace(scenario, end=end, events=tuple(replace(event, end=min(event.end, end)) for event in scenario.events))
    return short, ScenarioRunner(synthetic_weather_factory).run(short.to_scenario())


def violated(metrics):
    return {entry.name.split(".")[1] for entry in metrics if entry.name.startswith("invariant.") and entry.value}


def test_no_real_data_required_and_scientific_status(payload):
    status = payload["summary"]["scientific_status"]
    assert payload["metadata"]["real_agronomic_data_used"] is False
    assert payload["metadata"]["validation_kind"] == "SYNTHETIC_INTEGRATED_VALIDATION"
    assert status["REAL_VERIFIED"] == 0
    assert status["CALIBRATION_PERFORMED"] is False
    assert status["EXPERIMENTAL_VALIDATION_PERFORMED"] is False
    assert status["BIOLOGICAL_VALIDITY_CLAIMED"] is False
    assert status["SCIENTIFIC_EXPERIMENTAL_VALIDATION"] == "DEFERRED_TO_FINAL_VALIDATION_STAGE"


def test_every_case_has_synthetic_provenance(payload):
    for item in payload["cases"]:
        provenance = item["provenance"]
        assert provenance["source_type"] == "SYNTHETIC"
        assert provenance["observations_used"] is False
        assert provenance["calibration_performed"] is False
        assert provenance["seed"] == 529
        assert provenance["configuration_hash"] == item["configuration_hash"]
        assert {"crop", "variety", "plot_id", "environment", "cycle_id", "simulation_range", "generator"} <= provenance.keys()


def test_normal_season_completes_full_annual_cycle(payload):
    item = case(payload, "p529_tomato_outdoor_normal_season")
    assert item["status"] == "PASS"
    assert list(item["observed_outputs"]["stage_entry_times"]) == ["establishment", "vegetative_growth", "yield_maturation", "post_harvest_dormancy"]
    assert item["observed_outputs"]["harvest_ready"] is True
    assert item["observed_outputs"]["final_maturity"] == 1.0
    assert metric(item, "behaviour.post_harvest_senescence")["passed"] is True


def test_perennial_cycle_releases_dormancy_then_completes(payload):
    item = case(payload, "p529_plum_outdoor_normal_season")
    assert item["status"] == "PASS"
    assert item["observed_outputs"]["dormancy_release_time"] is not None
    assert metric(item, "behaviour.dormancy_release")["passed"] is True
    assert metric(item, "behaviour.full_stage_sequence")["passed"] is True
    assert metric(item, "invariant.dormancy_gates_thermal_time.violations")["value"] == 0
    # Phase 5.30: endodormancy blocks active growth.
    assert metric(item, "behaviour.growth_during_dormancy")["value"] == 0.0
    assert item["warnings"] == []


def test_water_stress_increases_and_reduces_growth(payload):
    item = case(payload, "p529_tomato_outdoor_water_stress_recovery")
    assert item["status"] == "PASS"
    assert metric(item, "behaviour.water_stress_increase")["value"] > 0
    assert metric(item, "behaviour.growth_reduction")["value"] < 0


def test_water_recovery_is_gradual_without_state_reset(payload):
    item = case(payload, "p529_tomato_outdoor_water_stress_recovery")
    assert metric(item, "behaviour.recovery_after_irrigation")["passed"] is True
    gradual = metric(item, "behaviour.gradual_recovery")
    assert gradual["passed"] is True and gradual["threshold_kind"] == "ENGINEERING_TEST_THRESHOLD"
    assert metric(item, "behaviour.persistent_biomass_deficit")["value"] < 0


def test_heat_wave_stress_and_recovery_use_existing_thresholds(payload):
    for crop in ("tomato", "lettuce", "apple"):
        item = case(payload, f"p529_{crop}_outdoor_heat_wave_recovery")
        assert item["status"] == "PASS"
        assert metric(item, "behaviour.heat_stress_response")["value"] > 0
        assert "ClimateStressProfile.max_temp_c" in metric(item, "behaviour.heat_stress_response")["definition"]
        assert metric(item, "behaviour.heat_damage_recovery")["passed"] is True


def test_low_radiation_reduces_potential_growth(payload):
    item = case(payload, "p529_tomato_outdoor_low_radiation")
    assert item["status"] == "PASS"
    assert metric(item, "behaviour.potential_growth_response")["value"] < 0


def test_high_radiation_increases_potential_growth_within_bounds(payload):
    item = case(payload, "p529_tomato_outdoor_high_radiation")
    assert item["status"] == "PASS"
    assert metric(item, "behaviour.potential_growth_response")["value"] > 0
    assert metric(item, "behaviour.radiation_physically_bounded")["value"] <= 1400.0
    assert metric(item, "behaviour.photoinhibition_observed")["passed"] is None


def test_greenhouse_ventilation_acts_through_microclimate(payload):
    item = case(payload, "p529_tomato_greenhouse_greenhouse_ventilation")
    assert item["status"] == "PASS"
    assert metric(item, "behaviour.outdoor_forcing_unchanged")["value"] is True
    assert metric(item, "behaviour.air_exchange_response")["value"] > 0
    assert metric(item, "behaviour.indoor_temperature_toward_outdoor")["value"] < 0
    assert metric(item, "behaviour.crop_uses_indoor_temperature")["value"] is True


def test_greenhouse_shading_transmission_and_causal_path(payload):
    item = case(payload, "p529_tomato_greenhouse_greenhouse_shading")
    assert item["status"] == "PASS"
    assert metric(item, "behaviour.indoor_radiation_transmission")["value"] == pytest.approx(0.5)
    causal = payload["greenhouse"]["actuator_causal_path"]
    assert causal["status"] == "PASS"
    assert causal["microclimate_identical"] is True and causal["crop_state_identical"] is True


def test_greenhouse_co2_response_uses_single_path_and_persists(payload):
    item = case(payload, "p529_tomato_greenhouse_greenhouse_co2")
    assert item["status"] == "PASS"
    assert metric(item, "behaviour.indoor_co2_response")["value"] > 0
    assert metric(item, "behaviour.co2_state_persists")["passed"] is True
    assert metric(item, "behaviour.co2_decays_by_air_exchange")["passed"] is True
    assert metric(item, "behaviour.co2_response_single_path")["passed"] is True
    memory = payload["greenhouse"]["crop_greenhouse_feedback"]["greenhouse_state_memory"]
    assert memory["co2_state_carried_between_steps"] is True and memory["ventilation_monotonic"] is True


def test_combined_stress_keeps_valid_state(payload):
    item = case(payload, "p529_tomato_greenhouse_combined_stress")
    assert item["status"] == "PASS"
    assert all(entry["value"] == 0 for entry in item["metrics"] if entry["name"].startswith("invariant."))
    assert metric(item, "behaviour.combined_growth_reduction")["value"] < 0


def test_crop_greenhouse_feedback_converges_without_saturation_violation(payload):
    feedback = payload["greenhouse"]["crop_greenhouse_feedback"]
    runs = feedback["runs"]
    for run in runs.values():
        assert run["converged_steps"] == run["steps"]
        assert run["max_iterations"] <= run["configured_max_iterations"]
        assert run["all_finite"] is True
        assert run["latent_flux_at_saturation_steps"] == 0
    assert runs["ventilated_3ach"]["status"] == "PASS"
    assert runs["closed_0ach"]["configured_ventilation_ach"] == 0.0
    assert runs["closed_0ach"]["status"] in PASSING
    assert feedback["status"] in PASSING
    qualification = payload["summary"]["qualification"]
    assert qualification["GREENHOUSE_CROP_INTEGRATION"] == qualification["FEEDBACK_LOOP"] == qualification["MICROCLIMATE_TO_CROP_COUPLING"] == "QUALIFIED"
    assert qualification["DORMANCY_PHENOLOGY_CONSISTENCY"] == "QUALIFIED"
    assert not any(finding["code"] == "OPEN_PHYSICAL_ISSUE" for finding in payload["findings"])


def test_validate_trajectory_passes_clean_run_and_detects_biomass_loss():
    scenario, result = short_run()
    metrics, issues = validate_trajectory(scenario, result.snapshots)
    assert not violated(metrics) and not issues
    snapshots = list(result.snapshots)
    lost = replace(snapshots[10].crop, biomass_total=0.0, biomass_leaf=0.0, biomass_stem=0.0, biomass_root=0.0, biomass_fruit=0.0)
    snapshots[10] = replace(snapshots[10], crop=lost)
    metrics, issues = validate_trajectory(scenario, snapshots)
    assert "biomass_non_decreasing" in violated(metrics)
    assert any(issue.code == "INVARIANT_VIOLATION" for issue in issues)


def test_validate_trajectory_detects_non_finite_values():
    scenario, result = short_run()
    snapshots = list(result.snapshots)
    snapshots[5] = replace(snapshots[5], potential_growth_g_m2=math.nan)
    metrics, issues = validate_trajectory(scenario, snapshots)
    assert "finite_state" in violated(metrics)
    assert any(issue.code == "NUMERICAL_FAILURE" for issue in issues)


def test_validate_trajectory_detects_time_gap_and_stage_regression():
    scenario, result = short_run()
    gap = list(result.snapshots)
    del gap[7]
    assert "time_continuity" in violated(validate_trajectory(scenario, gap)[0])
    regressed = list(result.snapshots)
    regressed[3] = replace(regressed[3], crop=replace(regressed[3].crop, current_stage="vegetative_growth"))
    assert "stage_monotonic" in violated(validate_trajectory(scenario, regressed)[0])


def test_restart_from_checkpoint_equals_continuous_run(payload):
    restart = payload["restart"]
    assert restart["status"] == "PASS"
    assert {item["case_id"] for item in restart["cases"]} == {"p529_tomato_outdoor_water_stress_recovery", "p529_plum_outdoor_normal_season", "p529_tomato_greenhouse_greenhouse_co2"}
    for item in restart["cases"]:
        assert len(item["checkpoints"]) == 3
        for checkpoint in item["checkpoints"]:
            assert checkpoint["equivalent"] is True
            assert checkpoint["max_abs_difference"] <= checkpoint["tolerance"]
            assert checkpoint["time_axis_aligned"] and checkpoint["checkpoint_round_trip_exact"]


def test_checkpoint_json_round_trip_is_exact():
    _, result = short_run()
    snapshot = result.snapshots[20]
    restored_time, crop, soil, microclimate = restore_checkpoint(checkpoint_payload(snapshot))
    assert restored_time == snapshot.simulation_time
    assert crop == snapshot.crop and soil == snapshot.soil
    assert microclimate.to_dict() == snapshot.microclimate.indoor_state.to_dict()


def test_resumed_scenario_rejects_checkpoint_on_event_boundary():
    scenario = build_scenario("tomato", "outdoor", SyntheticScenarioKind.WATER_STRESS_RECOVERY)
    boundary = scenario.window[0]
    crop = replace(scenario.initial_crop, simulation_time=boundary)
    with pytest.raises(ScenarioError):
        resumed_scenario(scenario.to_scenario(), boundary, crop, scenario.initial_soil)


def test_persisted_snapshots_match_computed_state(payload):
    persistence = payload["persistence"]
    assert persistence["status"] == "PASS"
    assert persistence["states_persisted"] == 130
    assert persistence["snapshot_mismatches"] == []
    assert persistence["idempotent_resave"] and persistence["conflicting_write_rejected"] and persistence["history_ordered"]


def test_multi_plot_states_are_isolated(payload):
    section = payload["multi_plot"]
    assert section["status"] == "PASS"
    assert section["combined_equals_isolated_runs"] is True
    assert section["perturbation_isolated"] is True
    assert section["repository_histories_isolated"] and section["one_state_per_plot_per_snapshot"]


def test_multi_cycle_states_are_isolated(payload):
    section = payload["multi_cycle"]
    assert section["status"] in PASSING
    assert section["second_cycle_starts_from_fresh_state"] is True
    assert section["cycle_histories_disjoint"] is True
    for cycle in section["lettuce_cycles"].values():
        assert cycle["stepped_only_within_cycle_dates"] and cycle["not_reactivated"]
    assert section["perennial_campaign"]["status_sequence_valid"] is True
    assert section["perennial_campaign"]["next_campaign_transition"] == "NOT_APPLICABLE"


def test_all_cases_are_deterministic(payload):
    determinism = payload["determinism"]
    assert determinism["status"] == "PASS"
    assert determinism["cases_rerun"] == len(payload["cases"]) == 30
    assert determinism["mismatched_cases"] == []


def test_parameters_and_configuration_are_not_mutated(payload):
    mutation = payload["mutation"]
    assert mutation["status"] == "PASS"
    assert mutation["before"] == mutation["after"]
    assert mutation["calibration_performed"] is False
    fresh = ParameterRegistry.from_repository(ROOT)
    assert len(fresh.records) == len(IntegratedSyntheticValidationSuite(ROOT, crops=("tomato",)).registry.records)


def test_twin_state_is_immutable():
    scenario, result = short_run(1)
    state = twin_state_from_snapshot(result.snapshots[-1], scenario)
    with pytest.raises(FrozenInstanceError):
        state.lai = 0.0  # type: ignore[misc]
    assert state.lai == result.snapshots[-1].crop.leaf_area_index
    assert state.state_provenance == "SIMULATION"


def test_all_seven_crops_are_covered(payload):
    matrix = {row["crop"]: row for row in payload["coverage_matrix"]}
    assert set(matrix) == {"tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple"}
    for crop, row in matrix.items():
        assert row["outdoor"] == row["stress"] == row["recovery"] == row["full_cycle"] == "PASS"
        if row["life_cycle"] == "annual":
            assert row["greenhouse"] == "PASS"
        else:
            assert row["greenhouse"].startswith("NOT_APPLICABLE")


def test_known_varieties_use_documented_species_fallback(payload):
    matrix = {row["crop"]: row for row in payload["coverage_matrix"]}
    assert {matrix[crop]["variety"] for crop in ("tomato", "pepper", "grape", "plum")} == {"RAF", "Lamuyo", "Monastrell", "Suplum 26"}
    assert all(row["variety_parameters"] == "SPECIES_FALLBACK" for row in matrix.values())
    parameters = case(payload, "p529_tomato_outdoor_normal_season")["provenance"]["model_configuration"]["variety_parameters"]
    assert parameters["known_variety"] is True and parameters["variety_model_parameter_records"] == []


def test_transferability_integration_remains_data_insufficient(payload):
    section = payload["transferability"]
    assert section["status"] == "DATA_INSUFFICIENT"
    assert section["real_verified_sources"] == 0
    assert section["readiness"] == "INSUFFICIENT_DATA"
    assert section["calibration_performed"] is False


def test_phase_5_22_robustness_cases_are_integrated(payload):
    section = payload["robustness"]
    assert section["status"] == "PASS"
    assert section["cases_per_environment"] == {"GREENHOUSE": 12, "OUTDOOR": 12}
    assert section["passed"] == section["total"] == 24


def test_final_report_is_deterministic_and_written(tmp_path):
    first = IntegratedSyntheticValidationSuite(ROOT, crops=("tomato",), include_extended=False, include_integration_suites=False).build_report()
    second = IntegratedSyntheticValidationSuite(ROOT, crops=("tomato",), include_extended=False, include_integration_suites=False).build_report()
    assert first.to_json() == second.to_json()
    assert first.to_dict()["report_hash"] == second.to_dict()["report_hash"]
    assert "timings_seconds" in first.execution_metadata and "timings_seconds" not in first.to_json()
    report_path, readme_path = IntegratedSyntheticValidationSuite(ROOT, crops=("tomato",)).write_report(first, tmp_path)
    assert json.loads(report_path.read_text(encoding="utf-8"))["report_hash"] == first.to_dict()["report_hash"]
    assert "does not establish biological validity" in readme_path.read_text(encoding="utf-8")


def test_static_audit_passes_and_detects_injected_violation(tmp_path, payload):
    assert payload["static_audit"]["status"] == "PASS"
    assert payload["static_audit"]["duplicate_core_classes"] == {}
    source = tmp_path / "src" / "agri_twin"
    for layer in ("domain", "application"):
        (source / layer).mkdir(parents=True)
    real = ROOT / "src" / "agri_twin"
    (source / "application" / "integrated_synthetic_validation.py").write_text((real / "application" / "integrated_synthetic_validation.py").read_text(encoding="utf-8"), encoding="utf-8")
    (source / "domain" / "dynamics.py").write_text("from datetime import datetime\nimport time\nclass SimulationClock: ...\ndef tick():\n    time.sleep(1)\n    return datetime.now()\n", encoding="utf-8")
    audit = static_audit(tmp_path)
    assert audit["status"] == "FAIL"
    assert {violation["detail"] for violation in audit["violations"]} == {"time.sleep", "datetime.now"}


def test_energyplus_remains_optional(payload):
    energyplus = payload["greenhouse"]["energyplus"]
    assert energyplus["status"] in {"NOT_APPLICABLE", "PASS"}
    assert energyplus["adapter_contract_check"]["produces_microclimate_state"] is True
    assert "never ground truth" in energyplus["role"]


def test_invalid_configurations_are_rejected():
    with pytest.raises(ScenarioError):
        build_scenario("grape", "greenhouse", SyntheticScenarioKind.NORMAL_SEASON)
    with pytest.raises(ScenarioError):
        build_scenario("banana", "outdoor", SyntheticScenarioKind.NORMAL_SEASON)
    with pytest.raises(ScenarioError):
        build_scenario("tomato", "outdoor", SyntheticScenarioKind.GREENHOUSE_CO2)
    with pytest.raises(ScenarioError):
        IntegratedSyntheticValidationSuite(ROOT, crops=("banana",))


def test_scenario_runner_without_factory_keeps_constant_base_weather():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    crop = CropGrowthState(start, "tomato", "RAF", "vegetative_growth", biomass_total=10.0, biomass_leaf=4.0, biomass_stem=3.0, biomass_root=3.0, leaf_area_index=1.0, soil_water_vwc=0.25, phenology_model="TEST")
    weather = WeatherState(24.0, 65.0, 500.0, 2.0, 180.0, 0.0, 1013.0)
    scenario = Scenario("constant", "constant", "", "tomato", "RAF", start, start + timedelta(hours=6), 3600, ScenarioKind.SYNTHETIC, crop, SoilState(0.25, 20.0, 0.35, 0.10, 0.0, 100.0), weather, "outdoor", (ScenarioEvent("warm", "heat", start, start + timedelta(hours=6), 5.0, {"temperature_offset_c": 5.0}),))
    result = ScenarioRunner().run(scenario)
    assert result.status == "SUCCESS"
    assert {snapshot.weather.temperature_c for snapshot in result.snapshots} == {29.0}


def test_invariant_catalogue_is_reported(payload):
    assert set(payload["invariant_results"]["violations_by_invariant"]) == set(INVARIANT_DEFINITIONS)
    assert payload["invariant_results"]["status"] == "PASS"
    assert payload["summary"]["total_cases"] == 30
