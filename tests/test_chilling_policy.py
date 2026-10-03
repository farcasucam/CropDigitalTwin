"""Phase 5.34 chilling model policy, STRICT fallback and canonical configuration."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agri_twin.application.chilling_policy import NEGATIVE_CASES, REQUESTS, ChillingPolicySuite, request
from agri_twin.application.dormancy_chilling_framework import LOCATIONS, SEASON_YEAR, DormancyOutcome, initial_dormant_state, location_weather, run_dormancy_season
from agri_twin.domain import WeatherState
from agri_twin.domain.calibration import ParameterSet
from agri_twin.domain.parameter_audit import ParameterRegistry
from agri_twin.domain.phenology import (
    APPROXIMATE_PROFILES,
    DEFAULT_DORMANCY_CONFIGURATION,
    ChillingFallbackPolicy,
    ChillingModel,
    ChillingModelType,
    ChillingStartPolicy,
    ChillingStartPolicyType,
    DormancyChillingController,
    DormancyConfiguration,
    PhenologyEngine,
    PhenologyError,
    canonicalize_dormancy_configuration,
    parse_dormancy_configuration_json,
)

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)
LOCATION = next(item for item in LOCATIONS if item.location_id == "SH_35S_TEMPERATE")


def canon(model: str, fallback: str = "STRICT", **kwargs) -> DormancyConfiguration:
    return canonicalize_dormancy_configuration(request(model, fallback, **kwargs))


def constant(temperature):
    return lambda _t: WeatherState(temperature, 70.0, 0.0, 2.0, 180.0, 0.0, 1013.0)


@pytest.fixture(scope="module")
def weather():
    return location_weather(LOCATION, 533)


def season(weather, crop="peach", **kwargs):
    return run_dormancy_season(crop, weather, LOCATION.analysis_start(SEASON_YEAR), 365, location=LOCATION, **kwargs)


@pytest.fixture(scope="module")
def report():
    return ChillingPolicySuite(ROOT, species=("peach",), equivalence_locations=("SH_35S_TEMPERATE",), include_twin=False).build_report()


@pytest.fixture(scope="module")
def payload(report):
    return report.to_dict()


# --- A. DEFAULT / STRICT ---------------------------------------------------------------------


@pytest.mark.parametrize("model", [model.value for model in ChillingModelType])
def test_default_equals_strict_configuration(model):
    default, strict = canon(model, "DEFAULT"), canon(model, "STRICT")
    assert default == strict and default.fallback_policy is strict.fallback_policy is ChillingFallbackPolicy.STRICT
    assert default.effective_dict() == strict.effective_dict()
    assert default.effective_hash == strict.effective_hash and default.configuration_hash == strict.configuration_hash


def test_strict_is_the_only_fallback_policy():
    assert [policy.value for policy in ChillingFallbackPolicy] == ["STRICT"]


def test_default_and_strict_give_the_same_simulation(weather):
    default, strict = season(weather, configuration=request("CHILLING_HOURS", "DEFAULT")), season(weather, configuration=request("CHILLING_HOURS", "STRICT"))
    assert default.to_dict() == strict.to_dict() and default.final_state == strict.final_state


# --- B. CHILLING_HOURS ------------------------------------------------------------------------------


def test_chilling_hours_does_not_activate_fallback():
    config = canon("CHILLING_HOURS")
    assert not config.fallback_applied and config.requested_chilling_model is config.effective_chilling_model is ChillingModelType.CHILLING_HOURS


def test_default_configuration_is_the_phase533_default_controller(weather):
    controller = DormancyChillingController()
    assert controller.configuration == DEFAULT_DORMANCY_CONFIGURATION == canon("CHILLING_HOURS", "DEFAULT")
    assert controller.policy == ChillingStartPolicy() and controller.model == ChillingModel()
    legacy, configured = season(weather), season(weather, configuration=request("CHILLING_HOURS", "DEFAULT"))
    assert legacy.to_dict() == configured.to_dict() and legacy.final_state == configured.final_state


# --- C. Dynamic / D. Utah -----------------------------------------------------------------------------


@pytest.mark.parametrize("model", ["DYNAMIC", "UTAH"])
def test_unsupported_model_uses_strict_fallback_to_chilling_hours(model):
    config = canon(model)
    assert config.effective_chilling_model is ChillingModelType.CHILLING_HOURS and config.fallback_applied
    assert config.requested_chilling_model is ChillingModelType(model)
    assert config.to_dict()["dormancy"]["requested_chilling_model"] == model


@pytest.mark.parametrize("model", ["DYNAMIC", "UTAH"])
def test_unsupported_model_result_is_identical_to_explicit_chilling_hours(weather, model):
    requested, explicit = season(weather, configuration=request(model, "STRICT")), season(weather, configuration=request("CHILLING_HOURS", "STRICT"))
    assert requested.to_dict() == explicit.to_dict() and requested.final_state == explicit.final_state
    assert requested.configuration.requested_chilling_model is ChillingModelType(model) and requested.configuration.fallback_applied


def test_no_utah_or_dynamic_formula_is_implemented():
    # Phase 5.35: the formulations exist, but without a requirement in their unit they are not ready to decide release.
    profile = PhenologyEngine().profile_for("peach")
    for model in (ChillingModelType.UTAH, ChillingModelType.DYNAMIC):
        assert not ChillingModel(model).ready
        with pytest.raises(PhenologyError, match="MODEL_NOT_READY"):
            ChillingModel(model).required(profile)


def test_one_fallback_rule_for_all_unsupported_models():
    dynamic, utah = canon("DYNAMIC"), canon("UTAH")
    assert dynamic.effective_dict() == utah.effective_dict() == canon("CHILLING_HOURS").effective_dict()


def test_injected_unimplemented_model_is_not_a_silent_fallback():
    for model in (ChillingModelType.UTAH, ChillingModelType.DYNAMIC):
        result = run_dormancy_season("peach", constant(4.0), START, 2, model=ChillingModel(model))
        assert result.outcome is DormancyOutcome.MODEL_NOT_READY and result.configuration is None  # Phase 5.35: was MODEL_NOT_SUPPORTED


def test_fallback_does_not_change_start_policy_or_profile_values():
    fixed = canon("DYNAMIC", start_policy="FIXED_DATE", start_time="2025-11-01T00:00:00+00:00")
    assert fixed.effective_start_policy is fixed.requested_start_policy is ChillingStartPolicyType.FIXED_DATE
    assert fixed.start_time == datetime(2025, 11, 1, tzinfo=UTC)
    model_defined = canon("DYNAMIC", start_policy="MODEL_DEFINED")
    assert model_defined.effective_start_policy is ChillingStartPolicyType.MODEL_DEFINED and not model_defined.start_policy_implemented
    assert run_dormancy_season("peach", constant(4.0), START, 2, configuration=request("DYNAMIC", "STRICT", "MODEL_DEFINED")).outcome is DormancyOutcome.MODEL_NOT_SUPPORTED


def test_release_with_fallback_happens_at_the_unchanged_requirement():
    result = run_dormancy_season("plum", constant(4.0), START, 30, configuration=request("DYNAMIC", "STRICT"))
    assert result.chill_at_release == APPROXIMATE_PROFILES["plum"].chilling_requirement_hours == 500.0
    assert result.dormancy_release == START + timedelta(hours=500)


# --- E. Canonicalization -----------------------------------------------------------------------------------


@pytest.mark.parametrize("label,document", REQUESTS)
def test_round_trip_json(label, document):
    config = canonicalize_dormancy_configuration(document)
    assert canonicalize_dormancy_configuration(config.to_dict()) == config
    assert parse_dormancy_configuration_json(config.to_json()) == config
    assert parse_dormancy_configuration_json(config.to_json()).to_json() == config.to_json()
    assert canonicalize_dormancy_configuration(json.loads(json.dumps(config.to_dict()))) == config


def test_canonicalization_is_idempotent_and_hashable():
    config = canon("DYNAMIC")
    assert canonicalize_dormancy_configuration(config) is config
    assert len({config, canon("DYNAMIC", "DEFAULT"), canon("UTAH")}) == 2


def test_equivalent_configurations_give_the_same_json_and_hash():
    pairs = [
        (request("CHILLING_HOURS", "DEFAULT"), request("CHILLING_HOURS", "STRICT")),
        (request("DYNAMIC", "DEFAULT"), {"dormancy": {"fallback_policy": "STRICT", "chilling_model": "DYNAMIC", "start_policy": "DORMANCY_STATE"}}),
        (request("CHILLING_HOURS", "STRICT"), {"dormancy": {**request("CHILLING_HOURS", "STRICT")["dormancy"], "start_time": None}}),
        (request("DYNAMIC", "STRICT", "FIXED_DATE", "2025-11-01T00:00:00+00:00"), request("DYNAMIC", "DEFAULT", "FIXED_DATE", "2025-11-01T01:00:00+01:00")),
    ]
    for left, right in pairs:
        a, b = canonicalize_dormancy_configuration(left), canonicalize_dormancy_configuration(right)
        assert a.to_json() == b.to_json() and a.configuration_hash == b.configuration_hash


def test_requested_effective_and_fallback_metadata_are_separated():
    dynamic, explicit = canon("DYNAMIC"), canon("CHILLING_HOURS")
    assert dynamic.effective_hash == explicit.effective_hash
    assert dynamic.configuration_hash != explicit.configuration_hash
    assert dynamic.to_dict() == {"dormancy": {"requested_start_policy": "DORMANCY_STATE", "effective_start_policy": "DORMANCY_STATE", "start_time": None,
                                              "requested_chilling_model": "DYNAMIC", "effective_chilling_model": "CHILLING_HOURS", "fallback_policy": "STRICT", "fallback_applied": True}}


def test_configuration_hash_is_sha256_of_canonical_json():
    config = canon("UTAH")
    assert config.configuration_hash == hashlib.sha256(config.to_json().encode("utf-8")).hexdigest()


def test_direct_construction_cannot_bypass_the_fallback_contract():
    with pytest.raises(PhenologyError):
        DormancyConfiguration(ChillingStartPolicyType.DORMANCY_STATE, ChillingStartPolicyType.DORMANCY_STATE, None, ChillingModelType.DYNAMIC, ChillingModelType.DYNAMIC, ChillingFallbackPolicy.STRICT, False)
    with pytest.raises(PhenologyError):
        DormancyConfiguration(ChillingStartPolicyType.DORMANCY_STATE, ChillingStartPolicyType.FIXED_DATE, None, ChillingModelType.CHILLING_HOURS, ChillingModelType.CHILLING_HOURS, ChillingFallbackPolicy.STRICT, False)


def test_controller_takes_configuration_or_policy_model_not_both():
    with pytest.raises(PhenologyError):
        DormancyChillingController(ChillingStartPolicy(), configuration=request("DYNAMIC", "STRICT"))
    controller = DormancyChillingController(configuration=request("DYNAMIC", "STRICT"))
    assert controller.model == ChillingModel() and controller.configuration.requested_chilling_model is ChillingModelType.DYNAMIC


# --- negative cases ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("label,kind,value", NEGATIVE_CASES)
def test_invalid_configuration_is_rejected_explicitly(label, kind, value):
    parse = parse_dormancy_configuration_json if kind == "json" else canonicalize_dormancy_configuration
    with pytest.raises(PhenologyError) as first:
        parse(value)
    with pytest.raises(PhenologyError) as second:
        parse(value)
    assert str(first.value) == str(second.value) and str(first.value)


# --- F. Immutability ------------------------------------------------------------------------------------------------


def test_canonicalization_mutates_nothing():
    registry = ParameterRegistry.from_repository(ROOT)
    records = [record.to_dict() for record in registry.records]
    parameters = ParameterSet.from_registry(registry, crop="peach").value_map()
    profiles = copy.deepcopy(APPROXIMATE_PROFILES)
    weather_profiles = {location.location_id: location.profile() for location in LOCATIONS}
    documents = copy.deepcopy([document for _, document in REQUESTS])
    for _, document in REQUESTS:
        canonicalize_dormancy_configuration(document)
        run_dormancy_season("peach", constant(4.0), START, 1, configuration=document)
    assert [record.to_dict() for record in registry.records] == records
    assert ParameterSet.from_registry(registry, crop="peach").value_map() == parameters
    assert APPROXIMATE_PROFILES == profiles
    assert {location.location_id: location.profile() for location in LOCATIONS} == weather_profiles
    assert [document for _, document in REQUESTS] == documents


def test_report_parameter_mutation_check(payload):
    mutation = payload["parameter_mutation_result"]
    assert mutation["status"] == "PASS" and mutation["before"] == mutation["after"]


# --- G. Determinism, matrices, traceability, audit -------------------------------------------------------------------


def test_report_is_byte_identical_and_hash_stable(report, tmp_path):
    again = ChillingPolicySuite(ROOT, species=("peach",), equivalence_locations=("SH_35S_TEMPERATE",), include_twin=False).build_report()
    assert report.to_json() == again.to_json()
    first, _ = ChillingPolicySuite(ROOT).write_report(report, tmp_path / "a")
    second, readme = ChillingPolicySuite(ROOT).write_report(again, tmp_path / "b")
    assert hashlib.sha256(first.read_bytes()).hexdigest() == hashlib.sha256(second.read_bytes()).hexdigest()
    text = readme.read_text(encoding="utf-8")
    assert "DEFAULT is an alias of STRICT" in text and "| DYNAMIC | STRICT | CHILLING_HOURS | true |" in text


def test_report_status_and_sections(payload):
    assert payload["status"] == "PASS", payload["section_status"]
    assert payload["determinism_result"]["mismatches"] == []


def test_fallback_and_policy_matrices(payload):
    rows = {row["requested_model"]: (row["fallback"], row["effective_model"], row["fallback_applied"]) for row in payload["fallback_matrix"]}
    assert rows == {"CHILLING_HOURS": ("STRICT", "CHILLING_HOURS", False), "DYNAMIC": ("STRICT", "CHILLING_HOURS", True), "UTAH": ("STRICT", "CHILLING_HOURS", True)}
    assert {row["policy"]: row["canonical_policy"] for row in payload["policy_matrix"]} == {"DEFAULT": "STRICT", "STRICT": "STRICT"}


def test_traceability_records_requested_and_effective_fields(payload):
    trace = payload["software_result"]["traceability"]
    assert trace["status"] == "PASS" and trace["no_literature_calibrated_or_real_verified_label"]
    registry = ParameterRegistry.from_repository(ROOT)
    record = registry.get("phenology.chilling_fallback_policy")
    assert record.value == "STRICT" and record.source_type == "engineering_default"
    fields = {entry["field"] for entry in canon("DYNAMIC").audit_entries()}
    assert fields >= {"requested_chilling_model", "effective_chilling_model", "fallback_policy", "fallback_applied", "requested_start_policy", "effective_start_policy"}


def test_static_audit_passes(payload):
    audit = payload["software_result"]["static_audit"]
    assert audit["status"] == "PASS" and audit["findings"] == [] and audit["new_core_classes"] == []


def test_scientific_status_makes_no_claim(payload):
    assert payload["scientific_evidence"] == []
    assert "DYNAMIC NOT IMPLEMENTED" in payload["scientific_status"] and "DEFAULT == STRICT" in payload["scientific_status"]
    assert not any("SCIENTIFICALLY VALIDATED" in line for line in payload["scientific_status"])
    for flag in ("real_agricultural_data_verified", "calibration_performed", "experimental_validation_performed", "biological_validity_claimed", "field_accuracy_claimed", "data_assimilation_implemented"):
        assert payload[flag] is False


# --- H. Compatibility ------------------------------------------------------------------------------------------------


def test_phase533_artifact_rows_are_reproduced(payload):
    regression = payload["regression_result"]["regression_533"]
    assert regression["status"] == "PASS" and regression["rows"]
    assert all(row["default_identical"] and row["dynamic_fallback_identical"] for row in regression["rows"])


def test_equivalence_rows(payload):
    equivalence = payload["software_result"]["equivalence"]
    assert equivalence["status"] == "PASS"
    assert all(row["identical_to_effective_reference"] for row in equivalence["rows"])


def test_phenology_engine_with_dynamic_request_matches_default():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    states = {}
    for label, phenology in (("legacy", PhenologyEngine()), ("dynamic", PhenologyEngine(dormancy=DormancyChillingController(configuration=request("DYNAMIC", "STRICT"))))):
        state = initial_dormant_state("apple", start)
        for hour in range(700):
            state = phenology.advance(state, constant(4.0)(None), start + timedelta(hours=hour + 1), 3600.0)
        states[label] = state
    assert states["legacy"] == states["dynamic"] and states["legacy"].dormancy_released
