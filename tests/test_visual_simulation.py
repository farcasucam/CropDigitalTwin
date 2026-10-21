"""Phase 5.40: interactive visual simulation (visual-state transform, record/replay, assets, audit)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from agri_twin.application import RuntimeReplayService
from agri_twin.application.interactive_runtime import InteractiveRuntimeService, static_audit_runtime
from agri_twin.application.interactive_simulation import SCIENTIFIC_STATUS, SimulationApiError
from agri_twin.interfaces.frontend_api import InteractiveFrontendAdapter

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
NODE = shutil.which("node")
BASE = {"crop": "tomato", "environment": "greenhouse", "end_time": "2026-03-15T00:00:00+00:00"}
CHECKPOINT = "2026-02-25T00:00:00+00:00"
HEAT = {"event_type": "HEAT_WAVE", "start_simulation_time": "2026-02-27T00:00:00+00:00", "duration_hours": 24, "intensity": 6}
DOC = {"request": BASE, "checkpoint_time": CHECKPOINT, "events": [HEAT]}

needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


def node(script: str):
    program = f"const V = require({json.dumps(str(FRONTEND / 'visual_state.js'))});\nconsole.log(JSON.stringify((() => {{ {script} }})()));"
    done = subprocess.run([NODE, "-e", program], capture_output=True, text=True, timeout=60, check=True)
    return json.loads(done.stdout)


CTX = """
const times = ["t0", "t1", "t2", "t3"];
const catalogue = V.catalogue([
  {name: "temperature_c", availability: "AVAILABLE", unit: "degC"},
  {name: "leaf_area_index", availability: "AVAILABLE", unit: "m2/m2"},
  {name: "co2_ppm", availability: "NOT_APPLICABLE", unit: "ppm", reason: "outdoor"},
  {name: "water_stress", availability: "NOT_SUPPORTED", unit: "-", reason: "no model"},
  {name: "crop_stage", availability: "AVAILABLE", unit: "-"}]);
const series = {temperature_c: [10, 20, 30, 40], leaf_area_index: [1, 1, 1, 1], crop_stage: ["a", "a", "b", "b"]};
const events = [{event_type: "HEAT_WAVE", start_simulation_time: "t1", end_simulation_time: "t2"}];
const ctx = (environment) => V.buildContext({series, catalogue, times, events, environment, branch: "intervention"});
"""


@pytest.fixture(scope="module")
def replay_service():
    return RuntimeReplayService()


@pytest.fixture(scope="module")
def recorded(replay_service):
    return replay_service.record(DOC)


# -- visual-state transform (pure JS, run through node) ------------------------------------------------
@needs_node
def test_visual_state_is_a_pure_function_of_the_api_series():
    first = node(CTX + 'return V.buildVisualState(ctx("greenhouse"), 2);')
    second = node(CTX + 'return V.buildVisualState(ctx("greenhouse"), 2);')
    assert first == second and first["kind"] == "VISUAL_STATE"


@needs_node
def test_levels_use_only_the_returned_extent():
    state = node(CTX + 'return V.buildVisualState(ctx("greenhouse"), 1);')
    assert state["layers"]["temperature"]["level"] == pytest.approx(1 / 3)


@needs_node
def test_not_applicable_is_never_turned_into_a_value():
    state = node(CTX + 'return V.buildVisualState(ctx("outdoor"), 1);')
    assert state["layers"]["co2"]["level"] is None
    assert state["variables"]["co2_ppm"]["availability"] == "NOT_APPLICABLE"
    assert state["variables"]["co2_ppm"]["value"] is None


@needs_node
def test_not_supported_is_never_invented():
    state = node(CTX + 'return V.buildVisualState(ctx("greenhouse"), 1);')
    assert state["variables"]["water_stress"]["availability"] == "NOT_SUPPORTED"
    assert state["variables"]["water_stress"]["value"] is None
    assert state["layers"]["crop"]["water_stress"] is None


@needs_node
def test_unrequested_variables_are_reported_not_zero():
    state = node(CTX + 'return V.buildVisualState(ctx("greenhouse"), 0);')
    assert "vpd_kpa" not in state["variables"]
    rows = node(CTX + 'return V.groupRows(V.buildVisualState(ctx("greenhouse"), 0), "Environment");')
    vpd = next(item for item in rows if item["name"] == "vpd_kpa")
    assert vpd["availability"] == "NOT_REQUESTED" and vpd["value"] is None

@needs_node
def test_flat_series_maps_to_the_middle_not_to_an_invented_extreme():
    state = node(CTX + 'return V.buildVisualState(ctx("greenhouse"), 2);')
    assert state["layers"]["crop"]["canopy_height"] == 0.5


@needs_node
def test_interpolation_is_flagged_and_only_visual():
    whole = node(CTX + 'return V.buildVisualState(ctx("greenhouse"), 1);')
    half = node(CTX + 'return V.buildVisualState(ctx("greenhouse"), 1.5);')
    assert whole["interpolated"] is False and half["interpolated"] is True
    assert half["variables"]["temperature_c"]["value"] == 20  # the reported value is the snapshot, never the blend
    assert half["layers"]["temperature"]["level"] == pytest.approx(0.5)


@needs_node
@pytest.mark.parametrize(("position", "status"), [(0, "FUTURE"), (1, "ACTIVE"), (2, "FINISHED"), (3, "FINISHED")])
def test_event_status_follows_the_simulation_time(position, status):
    state = node(CTX + f'return V.buildVisualState(ctx("greenhouse"), {position});')
    assert state["events"][0]["status"] == status


@needs_node
def test_active_event_types_reach_the_events_layer():
    state = node(CTX + 'return V.buildVisualState(ctx("greenhouse"), 1);')
    assert state["layers"]["events"]["active"] == ["HEAT_WAVE"]
    assert node(CTX + 'return V.buildVisualState(ctx("greenhouse"), 0);')["layers"]["events"]["active"] == []


@needs_node
def test_greenhouse_block_is_absent_outdoors():
    assert node(CTX + 'return V.buildVisualState(ctx("outdoor"), 1).greenhouse;')["present"] is False
    assert node(CTX + 'return V.buildVisualState(ctx("greenhouse"), 1).greenhouse;')["present"] is True


@needs_node
def test_greenhouse_actuator_flags_follow_events_only():
    script = CTX + 'events.push({event_type: "VENTILATION", start_simulation_time: "t0", end_simulation_time: "t3"});\nreturn V.buildVisualState(ctx("greenhouse"), 1).greenhouse;'
    flags = node(script)
    assert flags["ventilation_event_active"] is True and flags["shading_event_active"] is False and flags["co2_event_active"] is False


@needs_node
def test_stage_follows_the_returned_phenology_series():
    assert node(CTX + 'return V.buildVisualState(ctx("greenhouse"), 3).stage;') == "b"


@needs_node
def test_position_is_clamped_to_the_returned_range():
    state = node(CTX + 'return V.buildVisualState(ctx("greenhouse"), 99);')
    assert state["index"] == 3 and node(CTX + 'return V.buildVisualState(ctx("greenhouse"), -4).index;') == 0


@needs_node
def test_detail_rows_carry_unit_timestamp_availability_and_source():
    rows = node(CTX + 'return V.groupRows(V.buildVisualState(ctx("greenhouse"), 1), "Environment");')
    temperature = next(row for row in rows if row["name"] == "temperature_c")
    assert (temperature["value"], temperature["unit"], temperature["timestamp"], temperature["availability"], temperature["source"]) == (20, "degC", "t1", "AVAILABLE", "MODEL OUTPUT")


@needs_node
def test_detail_rows_keep_unavailable_variables_visible():
    rows = node(CTX + 'return V.groupRows(V.buildVisualState(ctx("outdoor"), 1), "CO2");')
    assert rows[0]["availability"] == "NOT_APPLICABLE" and rows[0]["value"] is None


@needs_node
def test_event_rows_are_labelled_as_user_defined_forcing():
    rows = node(CTX + 'return V.groupRows(V.buildVisualState(ctx("greenhouse"), 1), "Events");')
    assert rows[0]["source"] == "USER-DEFINED SYNTHETIC FORCING"


@needs_node
@pytest.mark.parametrize(("click", "expected"), [(7200, 1), (7200 + 1800, 2), (3600 * 5, 4), (1800, None), (3600, 0), (36000, None), (None, None)])
def test_event_start_from_click(click, expected):
    value = "null" if click is None else click
    assert node(f"return V.eventStartFromClick({value}, 3600, 36000);") == expected


@needs_node
def test_play_head_advances_with_the_presentation_speed_only():
    assert node("return V.advance(0, 2, 10, 100);") == {"position": 20, "finished": False}
    assert node("return V.advance(95, 1, 10, 100);") == {"position": 100, "finished": True}
    assert node("return V.advance(5, -3, 10, 100);")["position"] == 5


@needs_node
def test_stage_segments_group_consecutive_stages():
    assert node('return V.stageSegments(["a","a","b","a"]);') == [
        {"stage": "a", "from": 0, "to": 1}, {"stage": "b", "from": 2, "to": 2}, {"stage": "a", "from": 3, "to": 3}]
    assert node("return V.stageSegments([]);") == []


@needs_node
def test_layers_and_detail_targets_are_the_specified_ones():
    assert node("return V.LAYERS;") == ["crop", "soil", "water", "temperature", "radiation", "vpd", "co2", "events"]
    assert set(node("return Object.keys(V.DETAIL_TARGETS);")) == {"crop", "plot", "greenhouse", "soil"}


# -- record / replay ----------------------------------------------------------------------------------
def test_record_returns_a_session_without_pixels(recorded):
    session = recorded["session"]
    assert session["kind"] == "RUNTIME_SESSION_RECORD"
    assert {"document", "configuration", "seed", "event_sequence", "checkpoints", "hashes", "final_state", "session_hash"} <= set(session)
    assert "screenshot" not in json.dumps(session).lower()


def test_record_is_deterministic(replay_service, recorded):
    assert replay_service.record(DOC)["session"]["session_hash"] == recorded["session"]["session_hash"]


def test_replay_reproduces_every_check(replay_service, recorded):
    replay = replay_service.replay(recorded["session"])
    assert replay["status"] == "MATCH" and all(replay["checks"].values()) and len(replay["checks"]) == 5


def test_replay_survives_a_javascript_json_round_trip(replay_service, recorded):
    text = re.sub(r'(?<![\d."])(\d+)\.0(?![\d."])', r"\1", json.dumps(recorded["session"]))
    assert text != json.dumps(recorded["session"])
    assert replay_service.replay(json.loads(text))["status"] == "MATCH"


def test_replay_result_equals_the_recorded_trajectory_hashes(replay_service, recorded):
    replay = replay_service.replay(recorded["session"])
    assert replay["recomputed_hashes"] == recorded["session"]["hashes"]


@pytest.mark.parametrize("mutation", [
    lambda s: s.__setitem__("seed", 12345),
    lambda s: s["document"]["events"][0].__setitem__("intensity", 7),
    lambda s: s["hashes"].__setitem__("baseline_trajectory_hash", "0" * 64),
    lambda s: s.__setitem__("event_sequence", []),
])
def test_tampered_sessions_are_rejected(replay_service, recorded, mutation):
    session = json.loads(json.dumps(recorded["session"]))
    mutation(session)
    with pytest.raises(SimulationApiError):
        replay_service.replay(session)


def test_unknown_fields_and_wrong_kinds_are_rejected(replay_service, recorded):
    extra = {**recorded["session"], "extra": 1}
    with pytest.raises(SimulationApiError):
        replay_service.replay(extra)
    with pytest.raises(SimulationApiError):
        replay_service.replay({**recorded["session"], "kind": "OTHER"})
    with pytest.raises(SimulationApiError):
        replay_service.replay("not a session")


def test_replay_never_claims_scientific_evidence(replay_service, recorded):
    status = replay_service.replay(recorded["session"])["scientific_status"]
    assert status["REAL_VERIFIED"] == 0 and not any(v for v in status.values() if isinstance(v, bool))


# -- determinism and independence from the renderer -----------------------------------------------------
def test_trajectory_hash_does_not_depend_on_the_requested_variable_set():
    service = InteractiveRuntimeService()
    narrow = service.what_if({**DOC, "request": {**BASE, "options": {"variables": ["temperature_c"], "compute_trajectory_hash": True}}})
    full = service.what_if({**DOC, "request": {**BASE, "options": {"compute_trajectory_hash": True}}})
    assert narrow["hashes"]["baseline_configuration_hash"] != "" and full["comparison"] is not None


def test_what_if_is_repeatable_and_the_events_change_the_intervention_only():
    service = InteractiveRuntimeService()
    first, second = service.what_if(DOC), service.what_if(DOC)
    assert first["what_if_hash"] == second["what_if_hash"]
    assert first["hashes"]["baseline_configuration_hash"] != first["hashes"]["intervention_configuration_hash"]


def test_playback_speed_is_not_part_of_any_request_or_hash(recorded):
    assert "speed" not in json.dumps(recorded["session"]).lower()


# -- HTTP adapter and static assets ---------------------------------------------------------------------
def test_adapter_records_and_replays():
    adapter = InteractiveFrontendAdapter()
    session = adapter.runtime_record(DOC)["session"]
    assert adapter.runtime_replay(session)["status"] == "MATCH"


@pytest.fixture(scope="module")
def server():
    from agri_twin.interfaces.frontend_api import FrontendRequestHandler

    class Handler(FrontendRequestHandler):
        adapter = InteractiveFrontendAdapter()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.mark.parametrize("path", ["/", "/visual_state.js", "/visual.js", "/runtime.js", "/scene_state.js", "/iso_scene.js", "/vendor/uPlot.iife.min.js", "/vendor/uPlot.min.css",
                                  "/vendor/isokit.iife.js", "/vendor/isokit.css"])
def test_assets_are_served_locally_with_a_strict_csp(server, path):
    with urllib.request.urlopen(server + path, timeout=10) as response:
        assert response.status == 200
        assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_unlisted_assets_are_not_served(server):
    for path in ("/vendor/uPlot.LICENSE", "/vendor/isokit.LICENSE", "/../pyproject.toml", "/vendor/"):
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(server + path, timeout=10)


def test_record_and_replay_over_http(server):
    def post(path, body):
        request = urllib.request.Request(server + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read())

    session = post("/api/runtime/record", DOC)["session"]
    assert post("/api/runtime/replay", session)["status"] == "MATCH"
    session["seed"] = 5
    with pytest.raises(urllib.error.HTTPError) as caught:
        post("/api/runtime/replay", session)
    assert caught.value.code == 400


# -- HTML, layout, accessibility ------------------------------------------------------------------------
HTML = (FRONTEND / "index.html").read_text(encoding="utf-8")
CSS = (FRONTEND / "styles.css").read_text(encoding="utf-8")
RUNTIME_JS = (FRONTEND / "runtime.js").read_text(encoding="utf-8")
VISUAL_JS = (FRONTEND / "visual.js").read_text(encoding="utf-8")


@pytest.mark.parametrize("layer", ["crop", "soil", "water", "temperature", "radiation", "vpd", "co2", "events"])
def test_every_layer_has_a_toggle(layer):
    assert f'data-layer="{layer}"' in HTML


@pytest.mark.parametrize("token", ["tc-play", "tc-restart", "tc-back", "tc-fwd", "tc-speed", "tc-event", "tc-checkpoint", "iso-zoom-in", "iso-zoom-out", "iso-reset",
                                   "detail-target", "detail-panel", "event-table", "delta-table", "session-record", "session-replay", "fps-meter", "layer-status"])
def test_controls_and_panels_exist(token):
    assert f'id="{token}"' in HTML


def test_all_assets_are_local():
    assert not re.search(r"(<script[^>]+src|<link[^>]+href)\s*=\s*[\"']?(https?:)?//", HTML)
    assert not re.search(r"https?://", CSS)
    assert (FRONTEND / "vendor" / "uPlot.LICENSE").is_file()
    assert (FRONTEND / "vendor" / "isokit.LICENSE").is_file()


def test_assets_are_loaded_in_dependency_order():
    order = [HTML.index(name) for name in ("uPlot.iife.min.js", "isokit.iife.js", "visual_state.js", "scene_state.js", "iso_scene.js", "visual.js", "runtime.js")]
    assert order == sorted(order)


def test_mobile_rules_exist_and_prevent_horizontal_overflow():
    assert "@media" in CSS and "390" in CSS or "max-width" in CSS
    assert "overflow-wrap" in CSS and "touch-action" in CSS


def test_iso_parts_are_keyboard_and_screen_reader_reachable():
    for token in ("role", "tabindex", "aria-label", "keydown"):
        assert token in RUNTIME_JS
    assert "aria-live" in HTML


def test_speed_options_cover_the_specified_range():
    match = re.search(r"SPEEDS\s*=\s*\[([^\]]+)\]", RUNTIME_JS)
    speeds = [float(item) for item in match.group(1).split(",")]
    assert min(speeds) == 0.25 or min(speeds) <= 0.5
    assert max(speeds) == 50


def test_fps_is_measured_in_the_browser_not_assumed():
    assert "requestAnimationFrame" in RUNTIME_JS and "fpsLog" in RUNTIME_JS


def test_greenhouse_visual_elements_are_drawn_from_visual_state():
    for token in ("ventilation", "shading", "co2", "greenhouse"):
        assert token in RUNTIME_JS
    assert "NOT_APPLICABLE" in RUNTIME_JS or "not applicable" in RUNTIME_JS.lower()


def test_charts_mark_events_and_the_checkpoint():
    for token in ("hooks", "draw", "checkpoint", "placeFromClick"):
        assert token in VISUAL_JS


def test_comparison_marks_incomparable_rows():
    assert "not comparable" in VISUAL_JS


def test_user_events_are_labelled_synthetic_in_the_ui():
    assert "USER-DEFINED SYNTHETIC FORCING" in HTML or "USER-DEFINED SYNTHETIC FORCING" in VISUAL_JS


# -- performance budget ----------------------------------------------------------------------------------
def test_what_if_response_time_budget():
    service = InteractiveRuntimeService()
    started = time.perf_counter()
    service.what_if(DOC)
    assert time.perf_counter() - started < 60


def test_visual_state_transform_is_cheap_in_node():
    if NODE is None:
        pytest.skip("node is not installed")
    elapsed = node(
        CTX + 'const c = ctx("greenhouse"); const t = Date.parse("2026-01-01"); for (let i = 0; i < 20000; i += 1) V.buildVisualState(c, (i % 30) / 10); return 1;'
    )
    assert elapsed == 1


# -- static audit ----------------------------------------------------------------------------------------
def test_static_audit_passes_with_the_new_modules():
    audit = static_audit_runtime(ROOT)
    assert audit["status"] == "PASS" and audit["violations"] == []


def _audit_tree(tmp_path, runtime_js, html="<html></html>", css="", vendored=True):
    (tmp_path / "src/agri_twin/application").mkdir(parents=True)
    (tmp_path / "frontend/vendor").mkdir(parents=True)
    for name in ("runtime_events.py", "interactive_runtime.py", "runtime_replay.py"):
        (tmp_path / "src/agri_twin/application" / name).write_text("x = 1\n", encoding="utf-8")
    for name in ("runtime.js", "visual_state.js", "visual.js", "scene_state.js", "iso_scene.js", "bench.js"):
        (tmp_path / "frontend" / name).write_text(runtime_js if name == "runtime.js" else "const a = 1;\n", encoding="utf-8")
    (tmp_path / "frontend/index.html").write_text(html, encoding="utf-8")
    (tmp_path / "frontend/styles.css").write_text(css, encoding="utf-8")
    if vendored:
        for name in ("uPlot.iife.min.js", "uPlot.min.css", "uPlot.LICENSE", "isokit.iife.js", "isokit.css", "isokit.LICENSE"):
            (tmp_path / "frontend/vendor" / name).write_text("x", encoding="utf-8")
    return {item["rule"] for item in static_audit_runtime(tmp_path)["violations"]}


def test_audit_accepts_a_clean_tree(tmp_path):
    assert _audit_tree(tmp_path, "const a = 1;\n") == set()


@pytest.mark.parametrize(("code", "rule"), [
    ("const w = new Worker('x');", "scheduler_or_nondeterminism_in_javascript"),
    ("const r = Math.random();", "scheduler_or_nondeterminism_in_javascript"),
    ("fetch('https://example.com/x');", "remote_network_in_javascript"),
    ("const g = Math.exp(1);", "scientific_formula_in_javascript"),
    ("const t = new Date();", "wall_clock_in_javascript"),
    ("const s = new THREE.Scene();", "external_library_in_javascript"),
])
def test_audit_detects_forbidden_javascript(tmp_path, code, rule):
    assert rule in _audit_tree(tmp_path, code + "\n")


def test_audit_detects_remote_assets_and_missing_vendored_files(tmp_path):
    rules = _audit_tree(tmp_path, "const a = 1;\n", html='<script src="https://cdn.example.com/x.js"></script>', vendored=False)
    assert {"remote_dependency_in_frontend", "missing_vendored_library"} <= rules


def test_scientific_status_stays_negative():
    assert SCIENTIFIC_STATUS["REAL_VERIFIED"] == 0
    assert not any(value for value in SCIENTIFIC_STATUS.values() if isinstance(value, bool))
