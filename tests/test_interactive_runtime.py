"""Phase 5.39: runtime events, what-if branching, pause/resume, spatial view and static audit."""

from __future__ import annotations

import json
import time
from datetime import timedelta
from pathlib import Path

import pytest

from agri_twin.application import InteractiveRuntimeService, InteractiveSimulationService, parse_runtime_events
from agri_twin.application.interactive_runtime import static_audit_runtime
from agri_twin.application.interactive_simulation import ErrorCode, ExecutionStatus, SimulationApiError, canonicalize_request
from agri_twin.application.runtime_events import event_contract, event_sequence_hash
from agri_twin.interfaces.frontend_api import InteractiveFrontendAdapter

ROOT = Path(__file__).resolve().parents[1]
VARIABLES = ["crop_stage", "biomass_total_g_m2", "leaf_area_index", "temperature_c", "water_stress", "irrigation_mm", "co2_ppm"]
BASE = {"crop": "tomato", "environment": "greenhouse", "end_time": "2026-03-15T00:00:00+00:00",
        "options": {"variables": VARIABLES, "compute_trajectory_hash": True}}
BRANCH = "2026-02-25T00:00:00+00:00"
HEAT = {"event_type": "HEAT_WAVE", "start_simulation_time": "2026-02-27T00:00:00+00:00", "duration_hours": 48, "intensity": 6, "ramp_hours": 6}
DOC = {"request": BASE, "checkpoint_time": BRANCH, "events": [HEAT]}


def error_of(call) -> tuple[str, str | None]:
    with pytest.raises(SimulationApiError) as caught:
        call()
    return caught.value.code.value, caught.value.errors[0].path


@pytest.fixture(scope="module")
def service():
    return InteractiveRuntimeService()


@pytest.fixture(scope="module")
def what_if(service):
    return service.what_if(DOC)


# -- event contract and validation ------------------------------------------------------------


def test_contract_lists_supported_and_unsupported_events():
    contract = event_contract()
    supported = {item["event_type"] for item in contract["supported"]}
    assert supported == {"HEAT_WAVE", "COLD_WAVE", "DRYNESS", "RAIN", "HIGH_RADIATION", "LOW_RADIATION", "WIND", "IRRIGATION", "FERTILIZATION", "VENTILATION", "SHADING", "CO2"}
    assert [item["event_type"] for item in contract["not_supported"]] == ["WATER_STRESS"]
    assert contract["source"] == "USER_DEFINED_EVENT" and contract["classification"] == "USER_DEFINED_SYNTHETIC_FORCING"
    assert "wall" in contract["time_basis"]


@pytest.mark.parametrize("event, path", [
    ({**HEAT, "event_type": "WATER_STRESS"}, "events[0].event_type"),
    ({**HEAT, "intensity": 0}, "events[0].intensity"),
    ({**HEAT, "intensity": 500}, "events[0].intensity"),
    ({**HEAT, "start_simulation_time": "2026-02-20T00:00:00+00:00"}, "events[0].start_simulation_time"),
    ({**HEAT, "duration_hours": 0}, "events[0].duration_hours"),
    ({**HEAT, "start_simulation_time": "2026-02-27T00:30:00+00:00"}, "events[0].start_simulation_time"),
    ({**HEAT, "unexpected": 1}, "events[0].unexpected"),
    ({"event_type": "IRRIGATION", "start_simulation_time": HEAT["start_simulation_time"], "duration_hours": 2, "intensity": 3, "ramp_hours": 2}, "events[0].ramp_hours"),
])
def test_invalid_events_are_rejected_explicitly(service, event, path):
    _, reported = error_of(lambda: service.preview_events({**DOC, "events": [event]}))
    assert reported == path


def test_greenhouse_only_events_are_rejected_outdoors(service):
    document = {"request": {**BASE, "environment": "outdoor"}, "checkpoint_time": BRANCH,
                "events": [{"event_type": "VENTILATION", "start_simulation_time": HEAT["start_simulation_time"], "duration_hours": 6, "intensity": 0.5}]}
    assert error_of(lambda: service.preview_events(document))[0] == "UNSUPPORTED_ENVIRONMENT"


def test_events_past_the_campaign_end_and_duplicates_are_rejected(service):
    campaign_end = canonicalize_request({"crop": "tomato", "environment": "greenhouse"}).end_time
    late = {**HEAT, "start_simulation_time": (campaign_end - timedelta(hours=4)).isoformat(), "duration_hours": 10}
    assert error_of(lambda: service.preview_events({**DOC, "events": [late]}))[0] == "INVALID_TIME_RANGE"
    twin = [{**HEAT, "event_id": "same"}, {**HEAT, "event_id": "same", "start_simulation_time": "2026-03-03T00:00:00+00:00"}]
    assert error_of(lambda: service.preview_events({**DOC, "events": twin}))[0] == "INVALID_REQUEST"


def test_what_if_document_is_validated(service):
    assert error_of(lambda: service.what_if({**DOC, "checkpoint_time": "2026-01-01T00:00:00+00:00"}))[0] == "INVALID_TIME_RANGE"
    assert error_of(lambda: service.what_if({**DOC, "events": []}))[1] == "events"
    assert error_of(lambda: service.what_if({**DOC, "extra": 1}))[0] == "INVALID_REQUEST"
    assert error_of(lambda: service.what_if({**DOC, "request": {**BASE, "runtime_events": [HEAT]}}))[1] == "request"


def test_preview_describes_without_predicting(service):
    preview = service.preview_events(DOC)
    event = preview["events"][0]
    assert preview["history_modified"] is False and preview["affects_only_future"] is True
    assert event["requires_checkpoint"] and event["creates_new_branch"] and event["support"] == "SUPPORTED"
    assert event["provenance"] == "USER_DEFINED_EVENT" and "NOT_PREDICTED" in preview["consequences"]
    assert preview["event_sequence_hash"] == event_sequence_hash(parse_runtime_events(
        [HEAT], environment="greenhouse", earliest=canonicalize_request(BASE).start_time, latest=canonicalize_request(BASE).end_time, reserved_ids=()))


def test_event_sequence_hash_is_order_sensitive():
    kwargs = {"environment": "greenhouse", "earliest": canonicalize_request(BASE).start_time, "latest": canonicalize_request(BASE).end_time, "reserved_ids": ()}
    second = {"event_type": "COLD_WAVE", "start_simulation_time": "2026-03-03T00:00:00+00:00", "duration_hours": 12, "intensity": 3}
    ab = parse_runtime_events([HEAT, second], **kwargs)
    ba = parse_runtime_events([second, HEAT], **kwargs)
    assert event_sequence_hash(ab) != event_sequence_hash(ba)
    assert event_sequence_hash(ab) == event_sequence_hash(parse_runtime_events([HEAT, second], **kwargs))


def test_requests_without_events_keep_the_5_37_surface():
    response = InteractiveSimulationService().run_simulation({**BASE, "end_time": "2026-02-18T00:00:00+00:00"})
    assert "event_sequence_hash" not in response.hashes
    assert "runtime_events" not in response.effective_configuration


# -- what-if branching ---------------------------------------------------------------------------


def test_what_if_is_deterministic(service, what_if):
    again = service.what_if(DOC)
    assert again["what_if_hash"] == what_if["what_if_hash"] and again["hashes"] == what_if["hashes"]
    assert again["comparison"] == what_if["comparison"]


def test_branches_are_independent_and_labelled(what_if):
    baseline, intervention = (what_if["branches"][name]["provenance"] for name in ("baseline", "intervention"))
    assert baseline["trajectory_hash"] != intervention["trajectory_hash"]
    assert baseline["parent_checkpoint_sha256"] == intervention["parent_checkpoint_sha256"] == what_if["branch_point"]["checkpoint_sha256"]
    assert baseline["event_sequence_hash"] != intervention["event_sequence_hash"]
    assert "USER_DEFINED_EVENT" in intervention["forcing"] and "USER_DEFINED_EVENT" not in baseline["forcing"]
    flags = [v for v in what_if["scientific_status"].values() if isinstance(v, bool)]
    assert len(flags) == 5 and what_if["scientific_status"]["REAL_VERIFIED"] == 0 and not any(flags)


def test_history_before_the_branch_and_first_event_is_untouched(what_if):
    comparison = what_if["comparison"]
    assert comparison["unchanged_before_first_event"] is True
    assert comparison["variables"]["temperature_c"]["first_difference_time"] >= HEAT["start_simulation_time"]
    assert "temperature_c" in comparison["variables_changed"]
    assert comparison["variables"]["crop_stage"]["identical"] or comparison["variables"]["crop_stage"]["first_difference_time"] >= HEAT["start_simulation_time"]


def test_baseline_branch_equals_the_uninterrupted_run(service, what_if):
    full = InteractiveSimulationService().run_simulation(BASE).to_dict()["result"]["trajectory"]
    prefix = what_if["prefix"]["result"]["trajectory"]
    baseline = what_if["branches"]["baseline"]["response"]["result"]["trajectory"]
    keep = [i for i, t in enumerate(baseline["time"]) if t > prefix["time"][-1]]
    for name in ("time", "biomass_total_g_m2", "temperature_c", "leaf_area_index"):
        assert prefix[name] + [baseline[name][i] for i in keep] == full[name]


def test_events_do_not_change_the_baseline(service, what_if):
    other = service.what_if({**DOC, "events": [{**HEAT, "intensity": 12}]})
    assert other["hashes"]["baseline_trajectory_hash"] == what_if["hashes"]["baseline_trajectory_hash"]
    assert other["hashes"]["intervention_trajectory_hash"] != what_if["hashes"]["intervention_trajectory_hash"]
    assert other["what_if_hash"] != what_if["what_if_hash"]


def test_timings_are_operational_and_never_enter_hashes(what_if):
    timed = InteractiveRuntimeService(InteractiveSimulationService(timer=time.perf_counter)).what_if(DOC)
    assert timed["what_if_hash"] == what_if["what_if_hash"]
    segments = timed["operational"]["timings_seconds"]
    assert set(segments) == {"prefix", "baseline", "intervention"} and segments["baseline"]["simulation_seconds"] > 0
    assert "operational" not in json.dumps({key: what_if[key] for key in ("hashes", "comparison")})


@pytest.mark.parametrize("event_type, value", [("VENTILATION", 0.2), ("SHADING", 0.8), ("CO2", 0.5), ("IRRIGATION", 4), ("DRYNESS", None)])
def test_other_supported_events_run(service, event_type, value):
    event = {"event_type": event_type, "start_simulation_time": HEAT["start_simulation_time"], "duration_hours": 24}
    if value is not None:
        event["intensity"] = value
    result = service.what_if({**DOC, "events": [event]})
    assert result["comparison"]["unchanged_before_first_event"] is True
    assert result["branches"]["intervention"]["response"]["execution_status"] == "COMPLETED"


# -- pause / resume -----------------------------------------------------------------------------


def test_pause_returns_a_checkpoint_and_resume_continues_exactly():
    service = InteractiveSimulationService()
    request = {**BASE, "options": {**BASE["options"], "progress_interval_steps": 1}}
    created = service.create_simulation(request)
    paused = service.start_simulation(created.simulation_id, lambda p: service.pause_simulation(p.simulation_id) if p.completed_steps >= 48 else None)
    assert paused.execution_status is ExecutionStatus.CANCELLED and paused.checkpoint is not None
    assert paused.progress.completed_steps == 48 and "paused on request" in paused.errors[0].message
    resumed = service.run_simulation({key: value for key, value in request.items() if key != "start_time"} | {"checkpoint": paused.checkpoint.to_dict()})
    full = service.run_simulation(request)
    assert resumed.execution_status is ExecutionStatus.COMPLETED
    joined = paused.to_dict()["result"]["trajectory"]["biomass_total_g_m2"] + resumed.to_dict()["result"]["trajectory"]["biomass_total_g_m2"]
    assert joined[-len(full.to_dict()["result"]["trajectory"]["biomass_total_g_m2"]):] == full.to_dict()["result"]["trajectory"]["biomass_total_g_m2"]


# -- HTTP adapter ---------------------------------------------------------------------------------


def test_adapter_exposes_runtime_routes():
    adapter = InteractiveFrontendAdapter()
    assert adapter.capabilities()["runtime"]["source"] == "USER_DEFINED_EVENT"
    assert adapter.runtime_preview(DOC)["valid"] is True
    assert adapter.runtime_what_if(DOC)["kind"] == "WHAT_IF_BRANCHING"
    created = adapter.create(BASE)
    assert adapter.pause(created["simulation_id"])["execution_status"] == "CANCELLED"


# -- visualization and static audit ---------------------------------------------------------------


def test_frontend_declares_views_controller_and_mapping():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "runtime.js").read_text(encoding="utf-8")
    for token in ('data-view="TOP"', 'data-view="ISOMETRIC"', 'data-view="DETAIL"', "tc-play", "tc-back", "tc-fwd", "tc-speed", "tc-event", "tc-checkpoint", "USER-DEFINED SYNTHETIC FORCING", "runtime.js"):
        assert token in html
    assert "NOT_APPLICABLE" in script and "pointerdown" in script and "wheel" in script
    assert "per-plant" in html


def test_static_audit_passes_and_detects_violations(tmp_path):
    assert static_audit_runtime(ROOT)["status"] == "PASS"
    for name in ("src/agri_twin/application", "frontend"):
        (tmp_path / name).mkdir(parents=True)
    for name in ("runtime_events.py", "interactive_runtime.py"):
        (tmp_path / "src/agri_twin/application" / name).write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "frontend/runtime.js").write_text("const t = Math.exp(1) * Date.now();\nconst e = new THREE.Scene();\n", encoding="utf-8")
    result = static_audit_runtime(tmp_path)
    rules = {violation["rule"] for violation in result["violations"]}
    assert {"scientific_formula_in_javascript", "wall_clock_in_javascript", "external_library_in_javascript"} <= rules
    assert result["status"] == "FAIL"


def test_codes_used_for_events_are_existing_error_codes():
    assert {ErrorCode.INVALID_REQUEST, ErrorCode.INVALID_CONFIGURATION, ErrorCode.UNSUPPORTED_ENVIRONMENT, ErrorCode.INVALID_TIME_RANGE}
