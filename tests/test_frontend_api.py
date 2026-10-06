from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from agri_twin.application.interactive_simulation import (
    ErrorCode,
    InteractiveSimulationService,
    SimulationApiError,
    canonicalize_request,
    contract_description,
)
from agri_twin.interfaces.frontend_api import (
    FrontendRequestHandler,
    InteractiveFrontendAdapter,
    serve,
)

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
SHORT_RUN = {
    "crop": "tomato",
    "environment": "outdoor",
    "end_time": "2026-02-16T00:00:00+00:00",
}


def wait_for_terminal(adapter: InteractiveFrontendAdapter, simulation_id: str) -> dict:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        response = adapter.get(simulation_id)
        if response["execution_status"] not in {"CREATED", "RUNNING"}:
            return response
        time.sleep(0.02)
    raise AssertionError(f"simulation {simulation_id} did not finish within 15 seconds")


@pytest.mark.parametrize("asset", ["index.html", "styles.css", "app.js"])
def test_frontend_assets_exist(asset: str) -> None:
    assert (FRONTEND / asset).is_file()


@pytest.mark.parametrize("crop", contract_description()["crops"])
def test_capabilities_expose_canonical_crop_defaults(crop: str) -> None:
    capabilities = InteractiveFrontendAdapter().capabilities()
    defaults = capabilities["crop_defaults"][crop]
    canonical = canonicalize_request({"crop": crop})
    assert defaults["variety"] == canonical.variety
    assert defaults["plot"] == canonical.plot
    assert defaults["default_environment"] == canonical.environment
    assert defaults["start_time"] == canonical.start_time.isoformat()
    assert defaults["end_time"] == canonical.end_time.isoformat()


def test_capabilities_expose_configured_plot_details_and_coordinates() -> None:
    details = InteractiveFrontendAdapter().capabilities()["plot_details"]["tomato"]
    assert details == {
        "plot_id": "plot_12010",
        "name": "i.12010_R0120-TomateRaf_12010",
        "farm_name": "EL_MIRADOR",
        "plot_code": "T01-T04-GH",
        "crop_key": "tomato",
        "variety": "RAF",
        "area_ha": 3.25,
        "current_stage": "vegetative_growth",
        "irrigation_type": "drip_hydroponic",
        "soil_type": "sandy_loam",
        "station_id": "ST-TOM-02",
        "coordinates": {
            "latitude": 37.89215,
            "longitude": -0.87123,
            "elevation_m": None,
        },
        "metadata_status": "CONFIGURED",
        "metadata_source": "src/farm_config.json",
    }


def test_capabilities_mark_unconfigured_plot_details_without_coordinates() -> None:
    details = InteractiveFrontendAdapter().capabilities()["plot_details"]["apple"]
    assert details["metadata_status"] == "NO_FARM_METADATA_CONFIGURED"
    assert details["metadata_source"] is None
    assert details["coordinates"] is None


def test_plot_details_ui_uses_optional_external_map_link() -> None:
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    script = (FRONTEND / "app.js").read_text(encoding="utf-8")
    assert 'href="https://www.openstreetmap.org/' not in html
    assert 'rel="noopener noreferrer"' in html
    assert "https://www.openstreetmap.org/?mlat=" in script
    assert "Number.isFinite(coordinates.latitude)" in script
    assert "selected coordinates are sent to OpenStreetMap only if you open the map" in html


@pytest.mark.parametrize(
    ("crop", "environment", "expected"),
    [
        ("tomato", "outdoor", True),
        ("tomato", "greenhouse", True),
        ("lettuce", "outdoor", True),
        ("lettuce", "greenhouse", True),
        ("pepper", "outdoor", True),
        ("pepper", "greenhouse", True),
        ("grape", "greenhouse", False),
        ("peach", "greenhouse", False),
        ("plum", "greenhouse", False),
        ("apple", "greenhouse", False),
    ],
)
def test_capabilities_only_offer_backend_supported_environments(crop: str, environment: str, expected: bool) -> None:
    capabilities = InteractiveFrontendAdapter().capabilities()
    assert (environment in capabilities["crop_environments"][crop]) is expected


def test_capabilities_are_projected_from_the_phase_537_contract() -> None:
    capabilities = InteractiveFrontendAdapter().capabilities()
    contract = contract_description()
    assert capabilities["api_version"] == contract["api_version"]
    assert capabilities["crops"] == contract["crops"]
    assert capabilities["scenarios"] == contract["scenarios"]
    assert capabilities["chilling_models"] == contract["chilling_models"]
    assert capabilities["modes"] == contract["modes"]


def test_capabilities_label_every_scenario_as_synthetic_for_ui() -> None:
    capabilities = InteractiveFrontendAdapter().capabilities()
    assert "SYNTHETIC_SEASONAL" in capabilities["weather_sources"]
    assert capabilities["scientific_status"]["REAL_VERIFIED"] == 0
    assert capabilities["execution_adapter"].startswith("SYNCHRONOUS_IN_PROCESS_THREAD")


def test_plan_returns_backend_canonical_request_and_advisory_mode() -> None:
    planned = InteractiveFrontendAdapter().plan(SHORT_RUN)
    canonical = canonicalize_request(SHORT_RUN)
    assert planned["request"] == canonical.to_dict()
    assert planned["request_hash"] == canonical.request_hash
    assert planned["plan"]["mode"] == "INTERACTIVE"
    assert planned["plan"]["estimated_seconds"] >= 0


def test_plan_classifies_full_season_with_progress() -> None:
    planned = InteractiveFrontendAdapter().plan({"crop": "tomato", "environment": "outdoor"})
    assert planned["plan"]["mode"] == "INTERACTIVE_WITH_PROGRESS"
    assert planned["plan"]["total_steps"] > 1000


@pytest.mark.parametrize(
    ("req_document", "code", "path"),
    [
        ({"crop": "banana"}, ErrorCode.UNSUPPORTED_CROP, "crop"),
        ({"crop": "tomato", "environment": "vertical_farm"}, ErrorCode.UNSUPPORTED_ENVIRONMENT, "environment"),
        ({"crop": "peach", "environment": "greenhouse"}, ErrorCode.UNSUPPORTED_ENVIRONMENT, "environment"),
        ({"crop": "tomato", "scenario": "MONSOON"}, ErrorCode.INVALID_SCENARIO, "scenario"),
        ({"crop": "tomato", "end_time": "2026-01-01T00:00:00+00:00"}, ErrorCode.INVALID_TIME_RANGE, "end_time"),
        ({"crop": "tomato", "variety": "unconfigured"}, ErrorCode.INVALID_CONFIGURATION, "variety"),
        ({"crop": "tomato", "plot": "../private"}, ErrorCode.INVALID_CONFIGURATION, "plot"),
        ({"crop": "tomato", "start_time": "2026-02-16T00:00:00+00:00"}, ErrorCode.INVALID_TIME_RANGE, "start_time"),
        ({"crop": "tomato", "options": {"code": "print(1)"}}, ErrorCode.INVALID_REQUEST, "options.code"),
        ({"crop": "tomato", "end_time": "2026-02-16T00:30:00+00:00"}, ErrorCode.INVALID_TIME_RANGE, "end_time"),
    ],
)
def test_invalid_plan_requests_keep_structured_backend_errors(req_document: dict, code: ErrorCode, path: str) -> None:
    with pytest.raises(SimulationApiError) as caught:
        InteractiveFrontendAdapter().plan(req_document)
    assert caught.value.errors[0].code is code
    assert caught.value.errors[0].path == path


def test_create_returns_created_state_and_canonical_hashes() -> None:
    adapter = InteractiveFrontendAdapter()
    response = adapter.create(SHORT_RUN)
    assert response["execution_status"] == "CREATED"
    assert response["request"] == canonicalize_request(SHORT_RUN).to_dict()
    assert response["hashes"]["request_hash"] == canonicalize_request(SHORT_RUN).request_hash
    assert response["plan"]["mode"] == "INTERACTIVE"


def test_start_runs_without_blocking_the_calling_thread_and_completes() -> None:
    adapter = InteractiveFrontendAdapter()
    created = adapter.create(SHORT_RUN)
    started_at = time.perf_counter()
    adapter.start(created["simulation_id"])
    assert time.perf_counter() - started_at < 0.5
    final = wait_for_terminal(adapter, created["simulation_id"])
    assert final["execution_status"] == "COMPLETED"
    assert final["result"]["complete"] is True


def test_start_is_idempotent_after_execution_has_started() -> None:
    adapter = InteractiveFrontendAdapter()
    created = adapter.create({"crop": "tomato", "environment": "outdoor"})
    first = adapter.start(created["simulation_id"])
    second = adapter.start(created["simulation_id"])
    assert first["simulation_id"] == second["simulation_id"]
    final = wait_for_terminal(adapter, created["simulation_id"])
    assert final["execution_status"] == "COMPLETED"


def test_progress_endpoint_projects_operational_progress() -> None:
    adapter = InteractiveFrontendAdapter()
    created = adapter.create(SHORT_RUN)
    adapter.start(created["simulation_id"])
    final = wait_for_terminal(adapter, created["simulation_id"])
    progress = adapter.progress(created["simulation_id"])
    assert progress["status"] == "COMPLETED"
    assert progress["completed_steps"] == progress["total_steps"]
    assert progress["fraction"] == 1.0
    assert final["progress"]["kind"] == "OPERATIONAL_PROGRESS_NOT_SCIENTIFIC_EVIDENCE"


def test_result_endpoint_returns_api_result_contract() -> None:
    adapter = InteractiveFrontendAdapter()
    created = adapter.create(SHORT_RUN)
    adapter.start(created["simulation_id"])
    final = wait_for_terminal(adapter, created["simulation_id"])
    result = adapter.result(created["simulation_id"])
    assert result == final["result"]
    assert result["start"] == final["request"]["start_time"]
    assert result["trajectory"]["time"][0] > result["start"]


def test_cancel_before_start_is_cancelled_and_keeps_backend_checkpoint_contract() -> None:
    adapter = InteractiveFrontendAdapter()
    created = adapter.create(SHORT_RUN)
    cancelled = adapter.cancel(created["simulation_id"])
    assert cancelled["execution_status"] == "CANCELLED"
    assert cancelled["execution_status"] != "FAILED"
    assert cancelled["checkpoint"] is None
    assert cancelled["errors"][0]["code"] == "CANCELLATION_REQUESTED"


def test_result_catalogue_preserves_not_applicable_and_not_supported() -> None:
    adapter = InteractiveFrontendAdapter()
    created = adapter.create(SHORT_RUN)
    adapter.start(created["simulation_id"])
    result = wait_for_terminal(adapter, created["simulation_id"])["result"]
    states = {item["name"]: item["availability"] for item in result["variables"]}
    assert states["temperature_c"] == "AVAILABLE"
    assert states["co2_ppm"] == "NOT_APPLICABLE"
    assert states["canopy_temperature_c"] == "NOT_SUPPORTED"


def test_hash_opt_out_is_passed_to_the_backend_without_frontend_recomputation() -> None:
    adapter = InteractiveFrontendAdapter()
    request = {**SHORT_RUN, "options": {"compute_trajectory_hash": False}}
    created = adapter.create(request)
    adapter.start(created["simulation_id"])
    final = wait_for_terminal(adapter, created["simulation_id"])
    assert final["request"]["options"]["compute_trajectory_hash"] is False
    assert final["hashes"]["trajectory_hash"] is None
    assert final["hashes"]["configuration_hash"]


@pytest.mark.parametrize(
    ("crop", "environment", "end_time", "dormancy"),
    [
        ("tomato", "outdoor", "2026-02-16T00:00:00+00:00", None),
        ("tomato", "greenhouse", "2026-02-16T00:00:00+00:00", None),
        ("lettuce", "outdoor", None, None),
        ("peach", "outdoor", "2026-02-22T00:00:00+00:00", None),
        (
            "peach",
            "outdoor",
            "2026-02-22T00:00:00+00:00",
            {"start_policy": "DORMANCY_STATE", "chilling_model": "DYNAMIC", "fallback_policy": "STRICT"},
        ),
    ],
)
def test_end_to_end_adapter_runs_canonical_simulation_cases(
    crop: str, environment: str, end_time: str | None, dormancy: dict | None
) -> None:
    request = {"crop": crop, "environment": environment}
    if end_time:
        request["end_time"] = end_time
    if dormancy:
        request["dormancy"] = dormancy
    adapter = InteractiveFrontendAdapter()
    created = adapter.create(request)
    adapter.start(created["simulation_id"])
    final = wait_for_terminal(adapter, created["simulation_id"])
    assert final["execution_status"] == "COMPLETED"
    assert final["result"]["complete"] is True
    assert final["result"]["trajectory"]["time"]
    if dormancy:
        effective = final["effective_configuration"]["dormancy"]
        assert effective["requested_chilling_model"] == "DYNAMIC"
        assert effective["effective_chilling_model"] == "CHILLING_HOURS"
        assert effective["fallback_applied"] is True


def test_end_to_end_checkpoint_resume_matches_uninterrupted_backend_trajectory() -> None:
    adapter = InteractiveFrontendAdapter()
    partial = adapter.service.run_simulation(SHORT_RUN)
    full_end = canonicalize_request({"crop": "tomato"}).end_time.isoformat()
    resume_request = {
        **partial.request,
        "end_time": full_end,
        "checkpoint": partial.checkpoint.to_dict(),
    }
    del resume_request["start_time"]
    resumed_created = adapter.service.resume_simulation(resume_request)
    adapter.start(resumed_created.simulation_id)
    resumed = wait_for_terminal(adapter, resumed_created.simulation_id)
    uninterrupted = InteractiveSimulationService().run_simulation(
        {"crop": "tomato", "environment": "outdoor"}
    )
    first_series = partial.result.trajectory
    second_series = resumed["result"]["trajectory"]
    full_series = uninterrupted.result.trajectory
    assert set(first_series) == set(second_series) == set(full_series)
    assert all(full_series[name] == first_series[name] + second_series[name] for name in full_series)
    assert resumed["checkpoint"]["payload"] == uninterrupted.checkpoint.payload


def test_repeat_simulations_keep_request_configuration_and_trajectory_hashes() -> None:
    first = InteractiveSimulationService().run_simulation(SHORT_RUN)
    second = InteractiveSimulationService().run_simulation(dict(SHORT_RUN))
    assert first.hashes["request_hash"] == second.hashes["request_hash"]
    assert first.hashes["configuration_hash"] == second.hashes["configuration_hash"]
    assert first.hashes["trajectory_hash"] == second.hashes["trajectory_hash"]
    assert first.result.to_dict() == second.result.to_dict()


@pytest.mark.parametrize(
    "forbidden",
    [
        "WeatherEngine",
        "PhenologyEngine",
        "ScenarioRunner",
        "ParameterRegistry",
        "TwinState",
        "SimulationClock",
        "SimulationScheduler",
        "def compute_vpd",
    ],
)
def test_frontend_sources_do_not_duplicate_science_or_simulation_infrastructure(forbidden: str) -> None:
    sources = "\n".join(path.read_text(encoding="utf-8") for path in FRONTEND.iterdir() if path.is_file())
    assert forbidden not in sources


def test_html_exposes_labeled_keyboard_accessible_controls_and_live_states() -> None:
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    app = (FRONTEND / "app.js").read_text(encoding="utf-8")
    for required in ('for="crop"', 'for="environment"', 'for="scenario"', 'for="horizon"', 'role="alert"', "aria-live"):
        assert required in html
    assert "role" in app and "aria-label" in app


def test_setup_panel_has_no_misleading_step_number() -> None:
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert 'class="step-tag"' not in html
    assert ">01</span>" not in html


def test_variety_help_stays_with_its_field_in_desktop_and_mobile_grid() -> None:
    styles = (FRONTEND / "styles.css").read_text(encoding="utf-8")
    assert ".form-grid #variety-help { grid-column: 2; }" in styles
    assert ".form-grid #variety-help { grid-column: 1; }" in styles


def test_charts_have_simulated_time_ticks_and_numeric_value_graduations() -> None:
    app = (FRONTEND / "app.js").read_text(encoding="utf-8")
    styles = (FRONTEND / "styles.css").read_text(encoding="utf-8")
    assert "new uPlot(" in app
    assert '"Simulated time' in app
    assert '"Simulated day' in app
    assert "formatAxisValue" in app
    assert ".uplot-chart" in styles


def test_phenological_stages_have_shared_chart_bands_and_compact_colored_legend() -> None:
    app = (FRONTEND / "app.js").read_text(encoding="utf-8")
    styles = (FRONTEND / "styles.css").read_text(encoding="utf-8")
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert "getStageSegments(trajectory)" in app
    assert "chartPlot(title, trajectory[name], trajectory.time || [], variable.unit, stageSegments)" in app
    assert "drawClear" in app and "band" in app
    assert "formatTimestampRange(segment.start, segment.end)" in app
    assert 'timeZone: "UTC"' in app
    assert "--stage-border" in styles
    assert "Colors match the subtle chart bands." in html


def test_phenological_stage_colors_are_keyed_to_plant_stage_meaning() -> None:
    app = (FRONTEND / "app.js").read_text(encoding="utf-8")
    assert 'establishment: { band: "#f2e7ce", border: "#a77a35", card: "#faf5e9" }' in app
    assert 'vegetative_growth: { band: "#dcefe3", border: "#4d8757", card: "#eff7f0" }' in app
    assert 'yield_maturation: { band: "#f8e7b8", border: "#bd7922", card: "#fff7e7" }' in app
    assert 'post_harvest_dormancy: { band: "#e3e7eb", border: "#727d88", card: "#f3f5f6" }' in app
    assert "color: STAGE_COLORS[previous] || UNKNOWN_STAGE_COLOR" in app


def test_frontend_preserves_structured_error_codes_and_paths_as_text() -> None:
    app = (FRONTEND / "app.js").read_text(encoding="utf-8")
    assert "item.code" in app
    assert "item.path" in app
    assert "textContent" in app
    assert "innerHTML" not in app


def test_svg_trajectory_path_disables_default_black_fill_explicitly() -> None:
    app = (FRONTEND / "app.js").read_text(encoding="utf-8")
    assert "<svg" not in app.split("function chartPlot")[1].split("function ")[0]


def test_frontend_requests_hash_by_default_and_does_not_calculate_hashes() -> None:
    app = (FRONTEND / "app.js").read_text(encoding="utf-8")
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert 'id="trajectory-hash" type="checkbox" checked' in html
    assert "compute_trajectory_hash: $(\"#trajectory-hash\").checked" in app
    assert "crypto.subtle" not in app


def test_frontend_supports_responsive_layout_and_reduced_motion() -> None:
    css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
    assert "@media (max-width: 900px)" in css
    assert "@media (max-width: 620px)" in css
    assert "prefers-reduced-motion" in css


def test_frontend_has_textual_scientific_status_and_greenhouse_limitation() -> None:
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert "Real agricultural data verified" in html
    assert "Calibration performed" in html
    assert "Experimental validation performed" in html
    assert "Actuated greenhouse operation is not exposed" in html


def test_http_e2e_serves_ui_calls_adapter_and_returns_a_completed_result() -> None:
    adapter = InteractiveFrontendAdapter()

    class TestHandler(FrontendRequestHandler):
        pass

    TestHandler.adapter = adapter
    server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urllib.request.urlopen(f"{base}/") as response:
            assert response.status == 200
            assert b"Simulation workspace" in response.read()
        with urllib.request.urlopen(f"{base}/api/capabilities") as response:
            capabilities = json.loads(response.read())
        assert "tomato" in capabilities["crops"]
        request = urllib.request.Request(
            f"{base}/api/simulations",
            data=json.dumps(SHORT_RUN).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            created = json.loads(response.read())
        start = urllib.request.Request(
            f"{base}/api/simulations/{created['simulation_id']}/start",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(start) as response:
            json.loads(response.read())
        final = None
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with urllib.request.urlopen(f"{base}/api/simulations/{created['simulation_id']}") as response:
                final = json.loads(response.read())
            if final["execution_status"] not in {"CREATED", "RUNNING"}:
                break
            time.sleep(0.02)
        assert final["execution_status"] == "COMPLETED"
        assert final["result"]["trajectory"]["temperature_c"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_http_api_rejects_malformed_json_with_structured_error() -> None:
    class TestHandler(FrontendRequestHandler):
        pass

    TestHandler.adapter = InteractiveFrontendAdapter()
    server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/simulations",
            data=b"{",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        payload = json.loads(caught.value.read())
        assert caught.value.code == 400
        assert payload["errors"][0]["code"] == "INVALID_REQUEST"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_server_does_not_serve_arbitrary_file_paths() -> None:
    class TestHandler(FrontendRequestHandler):
        pass

    TestHandler.adapter = InteractiveFrontendAdapter()
    server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        path = "%2e%2e/%2e%2e/src/agri_twin/interfaces/frontend_api.py"
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/{path}")
        assert caught.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    with pytest.raises(ValueError, match="loopback"):
        serve("0.0.0.0", 8765)


def test_operational_performance_fields_are_separated_from_scientific_hashes() -> None:
    result = InteractiveSimulationService(timer=time.perf_counter).run_simulation(SHORT_RUN)
    assert result.operational["timings_seconds"]["simulation_seconds"] >= 0
    assert "simulation_seconds" not in result.deterministic_dict()
    assert "trajectory_hash" in result.hashes
