"""Phase 5.35 alternative chilling models: Utah and Dynamic (SOFTWARE_TEST_ONLY)."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agri_twin.application.chilling_models_framework import CONFIGURATIONS, NEGATIVE_CASES, TEST_REQUIREMENTS, ChillingModelsSuite, request, software_test_requirement
from agri_twin.application.chilling_models_framework import _chillr_dynamic_reference, _negative_document
from agri_twin.application.chilling_policy import REQUESTS as PHASE534_REQUESTS
from agri_twin.application.dormancy_chilling_framework import LOCATIONS, SEASON_YEAR, DormancyOutcome, initial_dormant_state, location_weather, run_dormancy_season
from agri_twin.domain import WeatherState
from agri_twin.domain.calibration import ParameterSet
from agri_twin.domain.chilling_models import DYNAMIC_PARAMETERS, UTAH_BANDS, UTAH_PUBLISHED_ROWS, ChillingModelError, dynamic_step, utah_step, utah_weight
from agri_twin.domain.models import ChillingAccumulation, CropGrowthState
from agri_twin.domain.parameter_audit import ParameterRegistry
from agri_twin.domain.phenology import (
    APPROXIMATE_PROFILES,
    ChillingFallbackPolicy,
    ChillingModel,
    ChillingModelStatus,
    ChillingModelType,
    ChillingRequirement,
    ChillingStartPolicyType,
    ChillingUnit,
    DormancyChillingController,
    DormancyConfiguration,
    PhenologyEngine,
    PhenologyError,
    RequirementEvidence,
    canonicalize_dormancy_configuration,
    parse_dormancy_configuration_json,
)

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)
PROFILE = APPROXIMATE_PROFILES["peach"]
LOCATION = next(item for item in LOCATIONS if item.location_id == "NH_38N_MEDITERRANEAN")
UTAH_TEST = request("UTAH", requirement=software_test_requirement("UTAH"))
DYNAMIC_TEST = request("DYNAMIC", requirement=software_test_requirement("DYNAMIC"))


def constant(temperature):
    return lambda _t: WeatherState(temperature, 70.0, 0.0, 2.0, 180.0, 0.0, 1013.0)


@pytest.fixture(scope="module")
def weather():
    return location_weather(LOCATION, 533)


def season(weather, crop="peach", days=365, **kwargs):
    return run_dormancy_season(crop, weather, LOCATION.analysis_start(SEASON_YEAR), days, location=LOCATION, **kwargs)


@pytest.fixture(scope="module")
def report():
    return ChillingModelsSuite(ROOT, species=("peach",), include_twin=False, include_regression=False).build_report()


@pytest.fixture(scope="module")
def payload(report):
    return report.to_dict()


# --- A. CHILLING_HOURS ----------------------------------------------------------------------------


@pytest.mark.parametrize("temperature,dt,expected", [(-0.1, 3600.0, 0.0), (0.0, 3600.0, 1.0), (7.2, 3600.0, 1.0), (7.3, 3600.0, 0.0), (30.0, 3600.0, 0.0), (3.0, 1800.0, 0.5)])
def test_chilling_hours_limits_and_dt_weighting(temperature, dt, expected):
    assert ChillingModel().increment(temperature, PROFILE, dt) == expected


def test_chilling_hours_known_accumulation():
    result = run_dormancy_season("plum", constant(4.0), START, 30)
    assert result.dormancy_release == START + timedelta(hours=500) and result.chill_at_release == 500.0 and result.final_state.chilling_state is None


def test_chilling_hours_default_and_strict_match_the_phase534_path(weather):
    legacy = season(weather)
    for fallback in ("DEFAULT", "STRICT"):
        configured = season(weather, configuration=request("CHILLING_HOURS", fallback))
        assert configured.to_dict() == legacy.to_dict() and configured.final_state == legacy.final_state


def test_chilling_hours_state_representation_is_unchanged():
    state = initial_dormant_state("peach", START)
    assert "chilling_state" not in state.to_dict() and CropGrowthState.from_dict(state.to_dict()) == state


# --- B. UTAH -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("low,high,weight", UTAH_PUBLISHED_ROWS)
def test_utah_reproduces_every_published_table_row(low, high, weight):
    for point in (low, high):
        if math.isfinite(point):
            assert utah_weight(point) == weight


@pytest.mark.parametrize("temperature,weight", [(1.45, 0.5), (2.45, 1.0), (9.15, 0.5), (12.45, 0.0), (15.95, -0.5), (18.05, -1.0), (-40.0, 0.0), (45.0, -1.0)])
def test_utah_boundary_convention_and_out_of_range(temperature, weight):
    assert utah_weight(temperature) == weight


def test_utah_weight_shape_is_monotonic_on_each_side_of_the_optimum():
    grid = [round(-5.0 + 0.05 * i, 2) for i in range(701)]
    rising = [utah_weight(t) for t in grid if t <= 9.1]
    falling = [utah_weight(t) for t in grid if t >= 2.5]
    assert all(a <= b for a, b in zip(rising, rising[1:])) and all(a >= b for a, b in zip(falling, falling[1:]))
    assert {utah_weight(t) for t in grid} == {weight for _, weight in UTAH_BANDS}


def test_utah_accumulates_and_can_go_negative():
    total = 0.0
    for temperature in (6.0, 6.0, 20.0, 20.0, 20.0):
        total = utah_step(total, temperature, 3600.0)
    assert total == -1.0
    result = run_dormancy_season("peach", constant(20.0), START, 2, configuration=UTAH_TEST)
    assert result.chill_total == -48.0 and result.outcome is DormancyOutcome.NO_CHILL


def test_utah_unit_is_never_hours():
    result = run_dormancy_season("peach", constant(6.0), START, 3, configuration=UTAH_TEST)
    row = result.to_dict()
    assert row["chill_unit"] == "utah_chill_units" and "chill_total_h" not in row and row["chill_total"] == 72.0
    assert result.final_state.chilling_hours == 0.0 and result.final_state.chilling_state.unit == "utah_chill_units"


def test_utah_release_at_the_explicit_test_requirement():
    result = run_dormancy_season("peach", constant(6.0), START, 60, configuration=UTAH_TEST)
    assert result.dormancy_release == START + timedelta(hours=int(TEST_REQUIREMENTS["UTAH"])) and result.chill_at_release == TEST_REQUIREMENTS["UTAH"]


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_utah_rejects_non_finite_temperatures(value):
    with pytest.raises(ChillingModelError):
        utah_weight(value)


def test_utah_is_hourly_only():
    with pytest.raises(PhenologyError, match="MODEL_NOT_APPLICABLE"):
        ChillingModel(ChillingModelType.UTAH).increment(6.0, PROFILE, 1800.0)


@pytest.mark.parametrize("unit", ["chill_hours", "chill_portions"])
def test_utah_rejects_incompatible_requirement_units(unit):
    with pytest.raises(PhenologyError, match=f"model UTAH expects 'utah_chill_units', received '{unit}'"):
        canonicalize_dormancy_configuration(request("UTAH", requirement={"value": 100.0, "unit": unit, "evidence": "SOFTWARE_TEST_ONLY"}))


# --- C. DYNAMIC ------------------------------------------------------------------------------------------


def test_dynamic_matches_the_reference_loop_hour_by_hour():
    series = [5.0 + 9.0 * math.sin(h / 24.0 * 2.0 * math.pi) + (h % 5) * 0.4 for h in range(1500)]
    reference = _chillr_dynamic_reference(series)
    intermediate, fraction, portions = 0.0, 0.0, []
    for temperature in series[1:]:
        step = dynamic_step(intermediate, fraction, temperature, 3600.0)
        intermediate, fraction = step.intermediate, step.transfer_fraction
        portions.append(step.portion)
    assert portions == reference[1:] and sum(portions) > 0


def test_dynamic_one_hour_closed_form():
    p = DYNAMIC_PARAMETERS
    tk = 4.0 + 273.0
    xs, k1 = (p.a0 / p.a1) * math.exp((p.e1 - p.e0) / tk), p.a1 * math.exp(-p.e1 / tk)
    step = dynamic_step(0.0, 0.0, 4.0, 3600.0)
    assert step.intermediate == xs - xs * math.exp(-k1) and step.portion == 0.0
    assert step.transfer_fraction == math.exp(p.slope * p.tf * (tk - p.tf) / tk) / (1.0 + math.exp(p.slope * p.tf * (tk - p.tf) / tk))


def test_dynamic_internal_state_evolution_and_irreversibility():
    chill = ChillingModel(ChillingModelType.DYNAMIC, ChillingRequirement(50.0, ChillingUnit.CHILL_PORTIONS, RequirementEvidence.SOFTWARE_TEST_ONLY))
    state = chill.initial()
    seen, portions = [], []
    for hour in range(600):
        state = chill.accumulate(state, 6.0 if (hour // 48) % 2 == 0 else 22.0, PROFILE, 3600.0)
        seen.append(state.intermediate)
        portions.append(state.accumulated)
    assert all(a <= b for a, b in zip(portions, portions[1:])) and portions[-1] > 0
    assert all(value >= 0.0 for value in seen) and max(seen) >= 1.0
    assert 0.0 < state.previous_transfer_fraction < 1.0


def test_dynamic_warm_hours_destroy_the_intermediate_before_any_portion():
    model = ChillingModel(ChillingModelType.DYNAMIC, ChillingRequirement(50.0, ChillingUnit.CHILL_PORTIONS, RequirementEvidence.SOFTWARE_TEST_ONLY))
    state = model.initial()
    for _ in range(10):
        state = model.accumulate(state, 6.0, PROFILE, 3600.0)
    built = state.intermediate
    for _ in range(10):
        state = model.accumulate(state, 25.0, PROFILE, 3600.0)
    assert state.intermediate < built and state.accumulated == 0.0


def test_dynamic_accumulates_chill_portions_not_hours():
    result = run_dormancy_season("peach", constant(6.0), START, 10, configuration=DYNAMIC_TEST)
    row = result.to_dict()
    assert row["chill_unit"] == "chill_portions" and "chill_total_h" not in row and 0.0 < row["chill_total"] < 240.0
    assert result.final_state.chilling_hours == 0.0


def test_dynamic_is_deterministic(weather):
    first, second = season(weather, configuration=DYNAMIC_TEST), season(weather, configuration=DYNAMIC_TEST)
    assert first.to_dict() == second.to_dict() and first.final_state == second.final_state


@pytest.mark.parametrize("label", ["UTAH", "DYNAMIC"])
def test_checkpoint_restart_through_json_is_exact(weather, label):
    config = UTAH_TEST if label == "UTAH" else DYNAMIC_TEST
    start = LOCATION.analysis_start(SEASON_YEAR)
    continuous = season(weather, days=200, configuration=config)
    first = season(weather, days=120, configuration=config)
    checkpoint = json.loads(json.dumps(first.final_state.to_dict()))
    assert "chilling_state" in checkpoint
    restored = CropGrowthState.from_dict(checkpoint)
    assert restored == first.final_state
    resumed = run_dormancy_season("peach", weather, start + timedelta(days=120), 80, location=LOCATION, configuration=config, initial=restored)
    assert resumed.final_state == continuous.final_state and resumed.dormancy_release == continuous.dormancy_release


@pytest.mark.parametrize("call", [
    lambda: dynamic_step(0.0, 0.0, 6.0, 1800.0),
    lambda: dynamic_step(0.0, 0.0, math.nan, 3600.0),
    lambda: dynamic_step(0.0, 0.0, -300.0, 3600.0),
    lambda: dynamic_step(-0.5, 0.0, 6.0, 3600.0),
    lambda: dynamic_step(0.0, 1.5, 6.0, 3600.0),
])
def test_dynamic_rejects_invalid_inputs(call):
    with pytest.raises(ChillingModelError):
        call()


def test_dynamic_stateless_increment_is_refused():
    with pytest.raises(PhenologyError, match="stateful"):
        ChillingModel(ChillingModelType.DYNAMIC).increment(6.0, PROFILE, 3600.0)


@pytest.mark.parametrize("requirement", [{"unit": "chill_portions", "evidence": "SOFTWARE_TEST_ONLY"}, {"value": 50.0, "unit": "chill_portions"}, {"value": 50.0, "evidence": "SOFTWARE_TEST_ONLY"}])
def test_dynamic_rejects_incomplete_requirement(requirement):
    with pytest.raises(PhenologyError, match="dormancy.chilling_requirement is incomplete"):
        canonicalize_dormancy_configuration(request("DYNAMIC", requirement=requirement))


# --- D. CONFIGURATION -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("label,document", CONFIGURATIONS)
def test_round_trip_and_canonical_json(label, document):
    config = canonicalize_dormancy_configuration(document)
    assert canonicalize_dormancy_configuration(config.to_dict()) == config
    assert parse_dormancy_configuration_json(config.to_json()) == config and parse_dormancy_configuration_json(config.to_json()).to_json() == config.to_json()
    assert config.configuration_hash == hashlib.sha256(config.to_json().encode("utf-8")).hexdigest()


def test_parameterized_canonical_form():
    config = canonicalize_dormancy_configuration(DYNAMIC_TEST)
    assert config.to_dict()["dormancy"] == {
        "requested_start_policy": "DORMANCY_STATE", "effective_start_policy": "DORMANCY_STATE", "start_time": None,
        "requested_chilling_model": "DYNAMIC", "effective_chilling_model": "DYNAMIC", "fallback_policy": "STRICT", "fallback_applied": False,
        "chilling_requirement": {"value": 50.0, "unit": "chill_portions", "evidence": "SOFTWARE_TEST_ONLY"},
        "model_parameter_set": "DYNAMIC_EREZ_1990", "parameterization_status": "SOFTWARE_TEST_ONLY"}


def test_equivalent_configurations_normalize_identically():
    integer = request("DYNAMIC", "DEFAULT", requirement={"evidence": "SOFTWARE_TEST_ONLY", "unit": "chill_portions", "value": 50})
    assert canonicalize_dormancy_configuration(integer).to_json() == canonicalize_dormancy_configuration(DYNAMIC_TEST).to_json()


def test_phase534_canonical_json_and_hashes_are_unchanged(payload):
    preservation = payload["results"]["phase534_hash_preservation"]
    assert preservation["status"] == "PASS" and len(preservation["rows"]) == len(PHASE534_REQUESTS)


def test_hash_separation():
    fallback, hours, executed = (canonicalize_dormancy_configuration(document) for document in (request("DYNAMIC"), request("CHILLING_HOURS"), DYNAMIC_TEST))
    assert fallback.effective_hash == hours.effective_hash and fallback.configuration_hash != hours.configuration_hash
    assert executed.effective_hash != hours.effective_hash and executed.configuration_hash != fallback.configuration_hash


@pytest.mark.parametrize("label,kind,value", NEGATIVE_CASES)
def test_negative_cases_are_explicit_deterministic_and_name_the_field(label, kind, value):
    kind, document = _negative_document(kind, value)
    parse = parse_dormancy_configuration_json if kind == "json" else canonicalize_dormancy_configuration
    with pytest.raises(PhenologyError) as first:
        parse(document)
    with pytest.raises(PhenologyError) as second:
        parse(document)
    assert str(first.value) == str(second.value) and "dormancy" in str(first.value)


def test_unit_error_names_field_model_expected_and_received():
    with pytest.raises(PhenologyError) as error:
        canonicalize_dormancy_configuration(request("DYNAMIC", requirement={"value": 600.0, "unit": "chill_hours", "evidence": "SOFTWARE_TEST_ONLY"}))
    assert str(error.value) == "dormancy.chilling_requirement.unit: model DYNAMIC expects 'chill_portions', received 'chill_hours'"


def test_direct_construction_cannot_bypass_the_contract():
    requirement = ChillingRequirement(50.0, ChillingUnit.CHILL_PORTIONS, RequirementEvidence.SOFTWARE_TEST_ONLY)
    state, dynamic, hours = ChillingStartPolicyType.DORMANCY_STATE, ChillingModelType.DYNAMIC, ChillingModelType.CHILLING_HOURS
    with pytest.raises(PhenologyError, match="inconsistent with the STRICT fallback"):  # parameterized request marked as fallback
        DormancyConfiguration(state, state, None, dynamic, hours, ChillingFallbackPolicy.STRICT, True, requirement)
    with pytest.raises(PhenologyError, match="cannot be combined"):  # executed model with an onset policy it does not support
        DormancyConfiguration(ChillingStartPolicyType.MODEL_DEFINED, ChillingStartPolicyType.MODEL_DEFINED, None, dynamic, dynamic, ChillingFallbackPolicy.STRICT, False, requirement)
    assert DormancyConfiguration(state, state, None, dynamic, dynamic, ChillingFallbackPolicy.STRICT, False, requirement) == canonicalize_dormancy_configuration(DYNAMIC_TEST)
    with pytest.raises(PhenologyError):
        ChillingModel(ChillingModelType.UTAH, requirement)
    with pytest.raises(PhenologyError):
        ChillingModel(ChillingModelType.CHILLING_HOURS, requirement)


# --- E. FALLBACK -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("model", ["DYNAMIC", "UTAH"])
def test_unparameterized_request_falls_back_strictly_and_keeps_the_request(weather, model):
    config = canonicalize_dormancy_configuration(request(model))
    assert config.effective_chilling_model is ChillingModelType.CHILLING_HOURS and config.fallback_applied
    assert config.requested_chilling_model is ChillingModelType(model) and config.requested_model_status is ChillingModelStatus.IMPLEMENTED_UNPARAMETERIZED
    assert config.fallback_reason == "REQUESTED_MODEL_NOT_PARAMETERIZED"
    assert {entry["field"]: entry["value"] for entry in config.audit_entries()}["fallback_reason"] == "REQUESTED_MODEL_NOT_PARAMETERIZED"
    requested, explicit = season(weather, configuration=request(model)), season(weather, configuration=request("CHILLING_HOURS"))
    assert requested.to_dict() == explicit.to_dict() and requested.final_state == explicit.final_state


@pytest.mark.parametrize("model", ["DYNAMIC", "UTAH"])
def test_parameterized_request_executes_the_requested_model(model):
    config = canonicalize_dormancy_configuration(request(model, requirement=software_test_requirement(model)))
    assert config.effective_chilling_model is ChillingModelType(model) and not config.fallback_applied and config.fallback_reason is None
    assert config.parameterization_status is RequirementEvidence.SOFTWARE_TEST_ONLY and config.describe()["scientifically_active"] is False


@pytest.mark.parametrize("model", [ChillingModelType.UTAH, ChillingModelType.DYNAMIC])
def test_injected_model_without_requirement_is_not_ready_and_never_falls_back(model):
    result = run_dormancy_season("peach", constant(4.0), START, 2, model=ChillingModel(model))
    assert result.outcome is DormancyOutcome.MODEL_NOT_READY and result.configuration is None
    with pytest.raises(PhenologyError, match="MODEL_NOT_READY"):
        ChillingModel(model).required(PROFILE)


# --- F. BACKWARD COMPATIBILITY -------------------------------------------------------------------------------------


def test_default_controller_is_unchanged():
    controller = DormancyChillingController()
    assert controller.model == ChillingModel() and controller.model.requirement is None and controller.configuration.to_dict()["dormancy"]["effective_chilling_model"] == "CHILLING_HOURS"


def test_phase533_artifact_rows_reproduced():
    section = ChillingModelsSuite(ROOT, species=("plum",), include_twin=False).regression_533()
    assert section["status"] == "PASS" and section["rows"]


# --- G. STATE ------------------------------------------------------------------------------------------------------------


def test_chilling_state_serialization_round_trip():
    state = ChillingAccumulation("DYNAMIC", "chill_portions", 12.5, 0.75, 0.25)
    assert ChillingAccumulation.from_dict(json.loads(json.dumps(state.to_dict()))) == state
    with pytest.raises(ValueError):
        ChillingAccumulation.from_dict({"model": "DYNAMIC", "unit": "chill_portions", "accumulated": 1.0})
    with pytest.raises(ValueError):
        ChillingAccumulation("DYNAMIC", "chill_portions", 1.0, -0.1, 0.0)


def test_mismatched_state_and_model_are_rejected():
    dynamic_state = run_dormancy_season("peach", constant(6.0), START, 1, configuration=DYNAMIC_TEST).final_state
    with pytest.raises(PhenologyError, match="CHILLING_HOURS counts chill_hours"):
        PhenologyEngine().advance(dynamic_state, constant(6.0)(None), dynamic_state.simulation_time + timedelta(hours=1), 3600.0)
    utah = PhenologyEngine(dormancy=DormancyChillingController(configuration=UTAH_TEST))
    with pytest.raises(PhenologyError, match="UTAH counts utah_chill_units"):
        utah.advance(dynamic_state, constant(6.0)(None), dynamic_state.simulation_time + timedelta(hours=1), 3600.0)


def test_evaluation_mutates_nothing():
    registry = ParameterRegistry.from_repository(ROOT)
    records = [record.to_dict() for record in registry.records]
    parameters = ParameterSet.from_registry(registry, crop="peach").value_map()
    profiles = copy.deepcopy(APPROXIMATE_PROFILES)
    weather_profiles = {location.location_id: location.profile() for location in LOCATIONS}
    documents = copy.deepcopy([document for _, document in CONFIGURATIONS])
    for _, document in CONFIGURATIONS:
        run_dormancy_season("peach", constant(6.0), START, 1, configuration=document)
    assert [record.to_dict() for record in registry.records] == records and ParameterSet.from_registry(registry, crop="peach").value_map() == parameters
    assert APPROXIMATE_PROFILES == profiles and {location.location_id: location.profile() for location in LOCATIONS} == weather_profiles
    assert [document for _, document in CONFIGURATIONS] == documents


def test_report_parameter_mutation(payload):
    assert payload["software_result"]["parameter_mutation"]["status"] == "PASS"


# --- H. SCIENTIFIC GUARDRAILS -------------------------------------------------------------------------------------------


def test_no_requirement_is_activated_for_any_species():
    engine = PhenologyEngine()
    for crop in ("grape", "peach", "plum", "apple"):
        for model in (ChillingModelType.UTAH, ChillingModelType.DYNAMIC):
            with pytest.raises(PhenologyError, match="MODEL_NOT_READY"):
                ChillingModel(model).required(engine.profile_for(crop))


@pytest.mark.parametrize("evidence", ["LITERATURE", "CALIBRATED", "REAL_VERIFIED", "ENGINEERING_DEFAULT"])
def test_only_software_test_requirements_are_accepted(evidence):
    with pytest.raises(PhenologyError, match="allowed: SOFTWARE_TEST_ONLY"):
        canonicalize_dormancy_configuration(request("DYNAMIC", requirement={"value": 50.0, "unit": "chill_portions", "evidence": evidence}))


def test_model_parameters_are_registered_as_fixed_literature_constants(payload):
    trace = payload["software_result"]["traceability"]
    assert trace["status"] == "PASS" and trace["requirement_records_in_utah_units_or_portions"] == []
    assert all(row["source_type"] == "literature" and row["calibration_status"] == "fixed" and not row["calibration_allowed"] for row in trace["model_parameter_records"])
    assert len(trace["model_parameter_records"]) == 2 * len(UTAH_BANDS) - 1 + 7


def test_report_status_and_claims(payload):
    assert payload["status"] == "PASS", payload["section_status"]
    assert payload["scientific_claims"] == [] and payload["evidence"]["activated_requirement_rows"] == []
    assert payload["models_implemented"] == ["CHILLING_HOURS", "UTAH", "DYNAMIC"] and payload["models_blocked"] == ["UTAH", "DYNAMIC"]
    for flag in ("real_agricultural_data_verified", "calibration_performed", "experimental_validation_performed", "biological_validity_claimed", "field_accuracy_claimed", "data_assimilation_implemented"):
        assert payload[flag] is False
    assert not any("VALIDATED" in line and "NOT" not in line for line in payload["scientific_status"])


def test_synthetic_runs_are_labelled_software_test_only(payload):
    assert all(row["label"] == "SOFTWARE_TEST_ONLY" for row in payload["results"]["seasons"]["rows"])
    assert payload["results"]["analytical_cases"]["label"] == "SOFTWARE_TEST_ONLY"


def test_report_is_byte_identical_across_builds(report, tmp_path):
    again = ChillingModelsSuite(ROOT, species=("peach",), include_twin=False, include_regression=False).build_report()
    assert report.to_json() == again.to_json()
    first, _ = ChillingModelsSuite(ROOT).write_report(report, tmp_path / "a")
    second, readme = ChillingModelsSuite(ROOT).write_report(again, tmp_path / "b")
    assert first.read_bytes() == second.read_bytes()
    assert "SCIENTIFIC_CLAIM: none" in readme.read_text(encoding="utf-8")


def test_static_audit(payload):
    audit = payload["software_result"]["static_audit"]
    assert audit["status"] == "PASS" and audit["findings"] == [] and audit["unique_core_classes"]
