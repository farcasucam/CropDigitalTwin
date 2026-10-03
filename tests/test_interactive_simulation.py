"""Phase 5.37: interactive simulation API and execution contract."""

from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

import pytest

from agri_twin.application import InteractiveSimulationService, canonicalize_request
from agri_twin.application.integrated_synthetic_validation import checkpoint_payload, restore_checkpoint, trajectory_hash
from agri_twin.application.interactive_simulation import (
    API_VERSION,
    CHECKPOINT_FORMAT,
    COST_MODEL,
    DEFAULT_PROGRESS_INTERVAL_STEPS,
    SCIENTIFIC_STATUS,
    VARIABLES,
    Availability,
    ErrorCode,
    ExecutionMode,
    ExecutionStatus,
    InteractiveSimulationApiSuite,
    SimulationApiError,
    configuration_fingerprint,
    contract_description,
    materialize,
    negative_cases,
    plan_execution,
    static_audit_api,
)
from agri_twin.application.performance_audit import truncated
from agri_twin.application.scenarios import ScenarioRunner
from agri_twin.application.seasonal_synthetic_campaign import build_campaign, seasonal_weather_factory
from agri_twin.application.twin_state import TwinState
from agri_twin.domain.phenology import DEFAULT_DORMANCY_CONFIGURATION, DormancyChillingController, PhenologyEngine

ROOT = Path(__file__).resolve().parents[1]
TOMATO = {"crop": "tomato", "environment": "outdoor"}
WEEK = {**TOMATO, "end_time": "2026-02-22T00:00:00+00:00"}
DYNAMIC = {"start_policy": "DORMANCY_STATE", "chilling_model": "DYNAMIC", "fallback_policy": "STRICT",
           "chilling_requirement": {"value": 50.0, "unit": "chill_portions", "evidence": "SOFTWARE_TEST_ONLY"}}  # Phase 5.35 software-test threshold


def code_of(call) -> tuple[str, str | None]:
    with pytest.raises(SimulationApiError) as caught:
        call()
    return caught.value.code.value, caught.value.errors[0].path


@pytest.fixture(scope="module")
def fingerprint_before():
    return configuration_fingerprint(ROOT)


@pytest.fixture(scope="module")
def week():
    return InteractiveSimulationService().run_simulation(WEEK)


@pytest.fixture(scope="module")
def season():
    events = []
    response = InteractiveSimulationService().run_simulation(TOMATO, events.append)
    return response, events


@pytest.fixture(scope="module")
def direct_season():
    return ScenarioRunner(seasonal_weather_factory).run(build_campaign("tomato", "outdoor", "BASE_SEASON").scenario)


# -- canonical request ------------------------------------------------------------------


def test_valid_request_defaults_come_from_existing_configuration():
    request = canonicalize_request({"crop": "tomato"})
    assert (request.variety, request.plot, request.environment, request.scenario, request.seed) == ("RAF", "plot_12010", "greenhouse", "BASE_SEASON", 532)
    assert request.dormancy == DEFAULT_DORMANCY_CONFIGURATION
    assert request.start_time.isoformat() == "2026-02-15T00:00:00+00:00" and request.end_time.isoformat() == "2026-07-21T00:00:00+00:00"


def test_canonical_request_normalizes_names_timestamps_and_numbers():
    request = canonicalize_request({"crop": " Tomato ", "environment": "OUTDOOR", "scenario": "heat_wave", "end_time": "2026-02-22T01:00:00+01:00",
                                    "weather": {"profile_overrides": {"temperature_max_c": 26}}})
    assert (request.crop, request.environment, request.scenario) == ("tomato", "outdoor", "HEAT_WAVE")
    assert request.end_time.isoformat() == "2026-02-22T00:00:00+00:00"
    assert request.to_dict()["weather"] == {"source": "SYNTHETIC_SEASONAL", "profile_overrides": {"temperature_max_c": 26.0}}


def test_canonical_json_is_stable_and_round_trips():
    request = canonicalize_request(WEEK)
    again = canonicalize_request(json.loads(request.canonical_json()))
    assert again == request and again.canonical_json() == request.canonical_json()
    assert canonicalize_request(request) == request


def test_request_hash_is_sha256_of_canonical_json_and_deterministic():
    first, second = canonicalize_request(WEEK), canonicalize_request(dict(WEEK))
    assert first.request_hash == second.request_hash == hashlib.sha256(first.canonical_json().encode("utf-8")).hexdigest()
    assert canonicalize_request({**WEEK, "seed": 1}).request_hash != first.request_hash


def test_request_contains_no_execution_timestamp():
    assert set(canonicalize_request(WEEK).to_dict()) == {"api_version", "crop", "variety", "environment", "plot", "scenario", "start_time", "end_time", "seed",
                                                         "weather", "dormancy", "checkpoint", "options"}


def test_dormancy_request_is_canonicalized_through_the_single_path():
    request = canonicalize_request({"crop": "peach", "dormancy": {"start_policy": "DORMANCY_STATE", "chilling_model": "UTAH", "fallback_policy": "DEFAULT"}})
    assert request.dormancy.fallback_applied and request.dormancy.effective_chilling_model.value == "CHILLING_HOURS"
    assert request.to_dict()["dormancy"]["requested_chilling_model"] == "UTAH"


# -- structured errors ------------------------------------------------------------------


def test_invalid_request_not_a_mapping():
    assert code_of(lambda: canonicalize_request(["tomato"])) == ("INVALID_REQUEST", None)


def test_unknown_field_rejected_with_path():
    assert code_of(lambda: canonicalize_request({**TOMATO, "latitude": 38.0})) == ("INVALID_REQUEST", "latitude")


def test_unknown_crop():
    assert code_of(lambda: canonicalize_request({"crop": "banana"})) == ("UNSUPPORTED_CROP", "crop")


def test_unknown_environment():
    assert code_of(lambda: canonicalize_request({**TOMATO, "environment": "vertical_farm"})) == ("UNSUPPORTED_ENVIRONMENT", "environment")
    assert code_of(lambda: canonicalize_request({"crop": "apple", "environment": "greenhouse"})) == ("UNSUPPORTED_ENVIRONMENT", "environment")


def test_invalid_date_range():
    assert code_of(lambda: canonicalize_request({**TOMATO, "end_time": "2026-02-01T00:00:00+00:00"})) == ("INVALID_TIME_RANGE", "end_time")
    assert code_of(lambda: canonicalize_request({**TOMATO, "end_time": "2027-01-01T00:00:00+00:00"})) == ("INVALID_TIME_RANGE", "end_time")
    assert code_of(lambda: canonicalize_request({**TOMATO, "start_time": "2026-03-01T00:00:00+00:00"})) == ("INVALID_TIME_RANGE", "start_time")


def test_ambiguous_naive_timestamp_rejected():
    assert code_of(lambda: canonicalize_request({**TOMATO, "end_time": "2026-03-01T00:00:00"})) == ("INVALID_REQUEST", "end_time")


def test_invalid_scenario():
    assert code_of(lambda: canonicalize_request({**TOMATO, "scenario": "MONSOON"})) == ("INVALID_SCENARIO", "scenario")


def test_invalid_configuration_points_to_the_field():
    assert code_of(lambda: canonicalize_request({**TOMATO, "variety": "Cherry"})) == ("INVALID_CONFIGURATION", "variety")
    assert code_of(lambda: canonicalize_request({**TOMATO, "weather": {"profile_overrides": {"temperature_min_c": 30.0, "temperature_max_c": 10.0}}})) == \
        ("INVALID_CONFIGURATION", "weather.profile_overrides")
    assert code_of(lambda: canonicalize_request({**TOMATO, "weather": {"source": "OPEN_METEO"}})) == ("INVALID_CONFIGURATION", "weather.source")


def test_model_not_ready_when_requested_chilling_model_would_fall_back():
    document = {"crop": "peach", "dormancy": {"start_policy": "DORMANCY_STATE", "chilling_model": "DYNAMIC", "fallback_policy": "STRICT"},
                "options": {"require_requested_chilling_model": True}}
    assert code_of(lambda: canonicalize_request(document)) == ("MODEL_NOT_READY", "dormancy.chilling_model")


def test_every_negative_case_has_its_stable_code_and_path():
    for case_id, document, code, path in negative_cases():
        observed = code_of(lambda document=document: canonicalize_request(document))
        assert observed == (code.value, path), case_id


def test_error_codes_are_serializable_with_category():
    with pytest.raises(SimulationApiError) as caught:
        canonicalize_request({"crop": "banana"})
    payload = json.loads(json.dumps(caught.value.to_dict()))
    assert payload["errors"][0] == {"code": "UNSUPPORTED_CROP", "category": "CONFIGURATION", "message": payload["errors"][0]["message"], "path": "crop"}
    assert {code.value for code in ErrorCode} >= {"INVALID_REQUEST", "INVALID_CONFIGURATION", "UNSUPPORTED_CROP", "UNSUPPORTED_ENVIRONMENT", "INVALID_TIME_RANGE",
                                                   "INVALID_SCENARIO", "INVALID_CHECKPOINT", "MODEL_NOT_READY", "CANCELLATION_REQUESTED", "INTERNAL_EXECUTION_ERROR"}


def test_unknown_simulation_id_and_double_start():
    service = InteractiveSimulationService()
    assert code_of(lambda: service.get_simulation("sim-unknown")) == ("INVALID_REQUEST", "simulation_id")
    response = service.run_simulation(WEEK)
    assert code_of(lambda: service.start_simulation(response.simulation_id)) == ("INVALID_REQUEST", "simulation_id")


def test_listener_failure_is_an_execution_error_not_a_model_result():
    service = InteractiveSimulationService()

    def broken(_progress):
        raise RuntimeError("frontend failure")

    response = service.run_simulation({**WEEK, "options": {"progress_interval_steps": 10}}, broken)
    assert response.execution_status is ExecutionStatus.FAILED and response.errors[0].code is ErrorCode.INTERNAL_EXECUTION_ERROR
    assert response.progress.completed_steps == 10 and not response.result.complete


# -- execution, response and determinism ------------------------------------------------


def test_canonical_response_sections(week):
    payload = json.loads(week.to_json())
    for key in ("request", "effective_configuration", "execution_status", "progress", "result", "diagnostics", "warnings", "errors", "hashes", "scientific_status"):
        assert key in payload
    assert payload["execution_status"] == "COMPLETED" and payload["api_version"] == API_VERSION
    assert payload["result"]["result_type"] == "MODEL_RESULT" and payload["diagnostics"]["kind"].startswith("EXECUTION_DIAGNOSTICS")


def test_response_serialization_round_trip_and_hash_excludes_operational(week):
    payload = json.loads(week.to_json())
    assert json.loads(json.dumps(payload, sort_keys=True)) == payload
    assert "timings_seconds" in payload["operational"]
    assert "operational" not in week.deterministic_dict() and "elapsed_seconds" not in json.dumps(week.deterministic_dict())


def test_deterministic_execution(week):
    again = InteractiveSimulationService().run_simulation(WEEK)
    assert again.deterministic_dict() == week.deterministic_dict()
    assert again.hashes == week.hashes and again.response_hash == week.response_hash


def test_api_trajectory_equals_direct_scenario_runner(season, direct_season):
    response, _ = season
    assert response.hashes["trajectory_hash"] == trajectory_hash(direct_season.snapshots)
    assert response.progress.completed_steps == len(direct_season.snapshots)


def test_short_horizon_is_an_exact_prefix_of_the_season(week, direct_season):
    assert week.hashes["trajectory_hash"] == trajectory_hash(direct_season.snapshots[:week.progress.completed_steps])


def test_effective_configuration_is_hashed_and_separate_from_request(week):
    assert week.hashes["configuration_hash"] == hashlib.sha256(json.dumps(week.effective_configuration, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    effective = week.effective_configuration
    assert effective["greenhouse_mode"] == "outdoor" and effective["period"]["total_steps"] == 168
    assert effective["weather"]["classification"] == "SYNTHETIC_FORCING" and effective["weather"]["represents_real_climatology"] is False


def test_scientific_status_propagation(week):
    status = week.deterministic_dict()["scientific_status"]
    assert status == dict(SCIENTIFIC_STATUS)
    assert status["REAL_VERIFIED"] == 0 and status["CALIBRATION_PERFORMED"] is False and status["EXPERIMENTAL_VALIDATION_PERFORMED"] is False


def test_software_warnings_are_not_biological(week):
    response = InteractiveSimulationService().run_simulation({"crop": "peach", "end_time": "2026-02-08T00:00:00+00:00",
                                                              "dormancy": {"start_policy": "DORMANCY_STATE", "chilling_model": "UTAH", "fallback_policy": "STRICT"}})
    categories = {warning.code: warning.category for warning in response.warnings}
    assert categories["CHILLING_MODEL_FALLBACK"] == "CONFIGURATION" and categories["DORMANCY_NOT_RELEASED"] == "MODEL_BEHAVIOR"
    assert all(warning.category in {"CONFIGURATION", "SOFTWARE", "MODEL_BEHAVIOR"} for warning in response.warnings + week.warnings)


# -- progress -------------------------------------------------------------------------


def test_progress_events_for_a_season(season):
    response, events = season
    assert len(events) == math.ceil(response.progress.total_steps / DEFAULT_PROGRESS_INTERVAL_STEPS)
    fractions = [event.fraction for event in events]
    assert fractions == sorted(fractions) and fractions[-1] == 1.0
    trajectory = response.result.trajectory
    assert all(event.simulated_time.isoformat() == trajectory["time"][event.completed_steps - 1] for event in events)
    assert all(event.current_stage == trajectory["crop_stage"][event.completed_steps - 1] for event in events)


def test_progress_current_state_is_twin_state_and_operational(season):
    _, events = season
    event = events[3]
    assert TwinState.from_dict(event.current_state).to_dict() == dict(event.current_state)
    assert event.deterministic_dict()["kind"] == "OPERATIONAL_PROGRESS_NOT_SCIENTIFIC_EVIDENCE" and "elapsed_seconds" not in event.deterministic_dict()


def test_interactive_runs_emit_only_the_final_progress():
    events = []
    InteractiveSimulationService().run_simulation(WEEK, events.append)
    assert len(events) == 1 and events[0].fraction == 1.0


def test_progress_query_before_and_after_execution():
    service = InteractiveSimulationService()
    created = service.create_simulation(WEEK)
    assert created.execution_status is ExecutionStatus.CREATED and service.get_simulation_progress(created.simulation_id).completed_steps == 0
    service.start_simulation(created.simulation_id)
    assert service.get_simulation_progress(created.simulation_id).fraction == 1.0


# -- cancellation -------------------------------------------------------------------------


def _cancel_at(step: int):
    service = InteractiveSimulationService()
    created = service.create_simulation({**TOMATO, "options": {"progress_interval_steps": 1}})
    return service, service.start_simulation(created.simulation_id, lambda progress: service.cancel_simulation(progress.simulation_id) if progress.completed_steps >= step else None)


def test_cancellation_is_cooperative_deterministic_and_operational():
    (_, first), (_, second) = _cancel_at(30), _cancel_at(30)
    assert first.execution_status is ExecutionStatus.CANCELLED and first.progress.completed_steps == 30
    assert first.deterministic_dict() == second.deterministic_dict()
    assert first.errors[0].code is ErrorCode.CANCELLATION_REQUESTED and first.errors[0].to_dict()["category"] == "OPERATIONAL"
    assert first.result is not None and first.result.complete is False


def test_cancelled_trajectory_is_the_completed_prefix(direct_season):
    _, cancelled = _cancel_at(30)
    assert cancelled.hashes["trajectory_hash"] == trajectory_hash(direct_season.snapshots[:30])


def test_cancel_before_start_and_terminal_states():
    service = InteractiveSimulationService()
    created = service.create_simulation(WEEK)
    cancelled = service.cancel_simulation(created.simulation_id)
    assert cancelled.execution_status is ExecutionStatus.CANCELLED and cancelled.result is None and cancelled.checkpoint is None
    assert code_of(lambda: service.get_simulation_result(created.simulation_id))[0] == "CANCELLATION_REQUESTED"
    assert code_of(lambda: service.cancel_simulation(created.simulation_id))[0] == "INVALID_REQUEST"


# -- checkpoint / resume -------------------------------------------------------------------


def test_checkpoint_wraps_the_existing_payload_format(week):
    checkpoint = week.checkpoint
    assert checkpoint.format == CHECKPOINT_FORMAT and checkpoint.sha256 == hashlib.sha256(checkpoint.payload.encode("utf-8")).hexdigest()
    assert restore_checkpoint(checkpoint.payload)[0] == checkpoint.simulation_time
    assert checkpoint.resume_hash == canonicalize_request(WEEK).resume_hash


def test_full_run_equals_partial_run_plus_checkpoint_resume(season):
    full, _ = season
    service = InteractiveSimulationService()
    partial = service.run_simulation({**TOMATO, "end_time": "2026-04-10T00:00:00+00:00"})
    resumed = service.start_simulation(service.resume_simulation({**TOMATO, "checkpoint": partial.checkpoint.to_dict()}).simulation_id)
    a, b, c = full.result.trajectory, partial.result.trajectory, resumed.result.trajectory
    assert all(a[key] == b[key] + c[key] for key in a)
    assert full.result.final_state == resumed.result.final_state and full.checkpoint.payload == resumed.checkpoint.payload


def test_dynamic_chilling_state_survives_checkpoint_resume():
    service = InteractiveSimulationService()
    base = {"crop": "peach", "dormancy": DYNAMIC, "end_time": "2026-03-01T00:00:00+00:00"}
    full = service.run_simulation(base)
    partial = service.run_simulation({**base, "end_time": "2026-02-10T00:00:00+00:00"})
    resumed = service.run_simulation({**base, "checkpoint": partial.checkpoint.to_dict()})
    assert json.loads(partial.checkpoint.payload)["crop"]["chilling_state"]["unit"] == "chill_portions"
    assert full.result.trajectory["chilling_accumulated"] == partial.result.trajectory["chilling_accumulated"] + resumed.result.trajectory["chilling_accumulated"]
    assert full.checkpoint.payload == resumed.checkpoint.payload


def test_invalid_checkpoints_are_rejected(week):
    checkpoint = week.checkpoint.to_dict()
    tampered = {**checkpoint, "payload": checkpoint["payload"].replace('"vwc_m3_m3": 0.', '"vwc_m3_m3": 1.', 1)}
    assert code_of(lambda: canonicalize_request({**TOMATO, "checkpoint": tampered})) == ("INVALID_CHECKPOINT", "checkpoint.sha256")
    assert code_of(lambda: canonicalize_request({**TOMATO, "seed": 9, "checkpoint": checkpoint})) == ("INVALID_CHECKPOINT", "checkpoint.resume_hash")
    assert code_of(lambda: canonicalize_request({**TOMATO, "checkpoint": {"payload": "{}"}})) == ("INVALID_CHECKPOINT", "checkpoint")
    assert code_of(lambda: InteractiveSimulationService().resume_simulation(TOMATO)) == ("INVALID_CHECKPOINT", "checkpoint")


def test_restore_checkpoint_round_trips_chilling_hours_states_unchanged(direct_season):
    snapshot = direct_season.snapshots[100]
    _, crop, soil, microclimate = restore_checkpoint(checkpoint_payload(snapshot))
    assert crop == snapshot.crop and soil == snapshot.soil and microclimate == snapshot.microclimate.indoor_state


# -- result contract -------------------------------------------------------------------------


def test_result_availability_and_required_variables(week):
    availability = {item["name"]: item["availability"] for item in week.result.variables}
    for name in ("crop_stage", "biomass_total_g_m2", "soil_water_vwc_m3_m3", "irrigation_mm", "precipitation_mm", "drainage_mm", "transpiration_mm",
                 "evaporation_mm", "temperature_c", "relative_humidity_pct", "vpd_kpa", "radiation_w_m2", "water_stress", "heat_stress", "growth_factor"):
        assert availability[name] == "AVAILABLE", name
    assert all(len(week.result.trajectory[name]) == week.result.steps for name, value in availability.items() if value == "AVAILABLE")


def test_not_applicable_variables_have_no_series(week):
    availability = {item["name"]: item["availability"] for item in week.result.variables}
    for name in ("co2_ppm", "greenhouse_ventilation_fraction", "outdoor_temperature_c", "chilling_accumulated", "dormancy_released"):
        assert availability[name] == "NOT_APPLICABLE" and name not in week.result.trajectory


def test_greenhouse_and_perennial_variables_become_available():
    greenhouse = InteractiveSimulationService().run_simulation({"crop": "lettuce", "environment": "greenhouse", "end_time": "2026-01-17T00:00:00+00:00"})
    peach = InteractiveSimulationService().run_simulation({"crop": "peach", "end_time": "2026-02-03T00:00:00+00:00"})
    assert {item["name"]: item["availability"] for item in greenhouse.result.variables}["co2_ppm"] == "AVAILABLE"
    peach_availability = {item["name"]: item for item in peach.result.variables}
    assert peach_availability["chilling_accumulated"]["availability"] == "AVAILABLE" and peach_availability["chilling_accumulated"]["unit"] == "chill_hours"


def test_not_supported_variables_are_never_fabricated(week):
    unsupported = [item for item in week.result.variables if item["availability"] == "NOT_SUPPORTED"]
    assert {item["name"] for item in unsupported} == {spec.name for spec in VARIABLES if spec.scope == "NONE"}
    assert all(item["reason"] and item["name"] not in week.result.trajectory for item in unsupported)


def test_variable_selection_option():
    response = InteractiveSimulationService().run_simulation({**TOMATO, "end_time": "2026-02-16T00:00:00+00:00", "options": {"variables": ["vpd_kpa", "fruit_count"]}})
    assert [item["name"] for item in response.result.variables] == ["vpd_kpa", "fruit_count"] and set(response.result.trajectory) == {"time", "vpd_kpa"}


def test_totals_and_final_state(week):
    assert set(week.result.totals) == {"irrigation_mm", "precipitation_mm", "drainage_mm", "transpiration_mm", "evaporation_mm", "et0_mm"}
    assert math.isclose(week.result.totals["irrigation_mm"], math.fsum(week.result.trajectory["irrigation_mm"]))
    assert TwinState.from_dict(week.result.final_state).biomass_g_m2 == week.result.trajectory["biomass_total_g_m2"][-1]


# -- execution modes ------------------------------------------------------------------------


def test_interactive_classification():
    assert plan_execution(canonicalize_request(WEEK)).mode is ExecutionMode.INTERACTIVE
    assert plan_execution(canonicalize_request({"crop": "lettuce", "environment": "greenhouse"})).mode is ExecutionMode.INTERACTIVE


def test_interactive_with_progress_classification():
    plan = plan_execution(canonicalize_request(TOMATO))
    assert plan.mode is ExecutionMode.INTERACTIVE_WITH_PROGRESS and plan.total_steps == 3744
    assert plan.estimated_seconds == round(3744 * COST_MODEL["seconds_per_plot_step"], 6)


def test_background_classification_for_multi_plot():
    plan = plan_execution(tuple(canonicalize_request({"crop": crop}) for crop in ("tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple")))
    assert plan.mode is ExecutionMode.BACKGROUND and plan.plots == 7 and plan.to_dict()["requires_background_executor"] is True


# -- immutability, audit, contract and overhead ---------------------------------------------


def test_parameter_and_configuration_immutability(fingerprint_before, season, week):
    InteractiveSimulationService().run_simulation({"crop": "peach", "dormancy": DYNAMIC, "end_time": "2026-02-05T00:00:00+00:00"})
    assert configuration_fingerprint(ROOT) == fingerprint_before


def test_twin_state_and_inputs_are_not_mutated(week):
    document = json.loads(json.dumps({**TOMATO, "checkpoint": week.checkpoint.to_dict(), "end_time": "2026-02-24T00:00:00+00:00"}))
    frozen = json.loads(json.dumps(document))
    spec = build_campaign("tomato", "outdoor", "BASE_SEASON")
    final_state = dict(week.result.final_state)
    InteractiveSimulationService().run_simulation(document)
    assert document == frozen and build_campaign("tomato", "outdoor", "BASE_SEASON") == spec and dict(week.result.final_state) == final_state


def test_scenario_runner_hooks_default_to_historical_behaviour():
    scenario = truncated(build_campaign("tomato", "outdoor", "BASE_SEASON").scenario, 6.0)
    plain = ScenarioRunner(seasonal_weather_factory).run(scenario)
    configured = ScenarioRunner(seasonal_weather_factory).run(scenario, phenology=PhenologyEngine(dormancy=DormancyChillingController(configuration=DEFAULT_DORMANCY_CONFIGURATION)))
    stopped = ScenarioRunner(seasonal_weather_factory).run(scenario, observer=lambda _snapshot, completed: completed < 10)
    assert plain.status == "SUCCESS" and trajectory_hash(plain.snapshots) == trajectory_hash(configured.snapshots)
    assert stopped.status == "STOPPED" and trajectory_hash(stopped.snapshots) == trajectory_hash(plain.snapshots[:10])


def test_static_audit():
    audit = static_audit_api(ROOT)
    assert audit["status"] == "PASS", audit["violations"]
    assert not audit["project_static_audit"]["duplicate_core_classes"] and not audit["project_static_audit"]["missing_core_classes"]


def test_contract_description_is_frontend_consumable():
    contract = json.loads(json.dumps(contract_description()))
    assert contract["statuses"] == ["CREATED", "RUNNING", "COMPLETED", "CANCELLED", "FAILED"]
    assert contract["modes"] == ["INTERACTIVE", "INTERACTIVE_WITH_PROGRESS", "BACKGROUND"]
    assert contract["availability"] == [item.value for item in Availability]
    assert {"create_simulation", "get_simulation", "start_simulation", "get_simulation_progress", "cancel_simulation", "get_simulation_result", "resume_simulation"} <= set(contract["surface"])


def test_api_overhead_benchmark_is_measured_and_separated():
    suite = InteractiveSimulationApiSuite(ROOT, repeats=1, timer=time.perf_counter)
    performance = suite.performance()
    for row in performance["rows"]:
        assert row["direct_execution_seconds"] > 0 and row["SIMULATION_TIME"] > 0
        assert set(row["API_OVERHEAD"]) >= {"canonicalization_seconds", "preparation_seconds", "result_projection_seconds", "api_total_minus_direct_seconds"}
        assert row["SERIALIZATION_TIME"]["response_bytes"] > 0 and math.isfinite(row["API_OVERHEAD"]["relative_to_direct"])
    assert performance["classification"] == "PERFORMANCE_MEASUREMENT" and performance["canonicalization_seconds_per_request"] > 0


def test_materialize_uses_the_phase_535_software_test_threshold():
    assert materialize({"crop": "peach", "dormancy": "DYNAMIC_SOFTWARE_TEST"})["dormancy"] == DYNAMIC


def test_api_layer_reads_no_clock_without_an_injected_timer(week):
    assert week.operational["timings_seconds"] == {} and week.progress.elapsed_seconds is None
    timed = InteractiveSimulationService(timer=time.perf_counter).run_simulation(WEEK)
    assert set(timed.operational["timings_seconds"]) >= {"canonicalization_seconds", "simulation_seconds", "result_projection_seconds"}
    assert timed.deterministic_dict() == week.deterministic_dict()
    assert static_audit_api(ROOT)["operational_timer"]["clock_reads_in_api_module"] == 0
