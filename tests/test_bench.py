"""Phase 5.41: the experiment bench page (routes, markup consistency, backend availability in the capabilities)."""

from __future__ import annotations

import re
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import agri_twin.interfaces.frontend_api as frontend_api
from agri_twin.infrastructure.energyplus_timeline import EnergyPlusInstall
from agri_twin.interfaces.frontend_api import FrontendRequestHandler, InteractiveFrontendAdapter

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
HTML = (FRONTEND / "bench.html").read_text(encoding="utf-8")
JS = (FRONTEND / "bench.js").read_text(encoding="utf-8")
CSS = (FRONTEND / "bench.css").read_text(encoding="utf-8")
CLASSIC = (FRONTEND / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def server():
    class Handler(FrontendRequestHandler):
        adapter = InteractiveFrontendAdapter()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.mark.parametrize("path", ["/bench", "/bench.js", "/bench.css"])
def test_bench_assets_are_served_locally_with_a_strict_csp(server, path):
    with urllib.request.urlopen(server + path, timeout=15) as response:
        assert response.status == 200
        assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_every_element_id_used_by_the_script_exists_in_the_markup():
    static_ids = set(re.findall(r'\$\("#([A-Za-z0-9_-]+)"', JS))
    dynamic_ids = {f"{prefix}-{branch}" for prefix in ("svg", "read", "chip") for branch in ("baseline", "intervention")}
    dynamic_ids |= {f"layout-{name}" for name in ("span", "rise", "gutter", "pillar", "spans", "bays")}
    dynamic_ids |= {f"{name}" for name in ("scenes", "transport", "charts", "delta", "info")}
    declared = set(re.findall(r'id="([A-Za-z0-9_-]+)"', HTML))
    missing = sorted((static_ids | dynamic_ids) - declared)
    assert not missing, f"ids used by bench.js but absent from bench.html: {missing}"


def test_scripts_load_in_dependency_order_and_everything_is_local():
    order = [HTML.index(name) for name in ("uPlot.iife.min.js", "isokit.iife.js", "visual_state.js", "scene_state.js", "iso_scene.js", "bench.js")]
    assert order == sorted(order)
    assert not re.search(r"(<script[^>]+src|<link[^>]+href)\s*=\s*[\"']?(https?:)?//", HTML)
    assert "https://" not in CSS and "http://" not in CSS


def test_the_two_pages_link_to_each_other():
    assert 'href="/"' in HTML and 'href="/bench"' in CLASSIC


def test_the_bench_states_its_scientific_limits_and_never_hides_unavailable_values():
    assert "synthetic" in HTML.lower() and "synthetic" in JS.lower()
    assert '"n/a"' in JS and "not a causal or validated effect" in JS
    assert "Scientific status" in JS


def test_presets_respect_the_backend_limits():
    assert 'preset.type === "CO2"' in JS and "ENERGYPLUS" in JS


def test_capabilities_report_both_backends_and_a_reason_when_energyplus_is_missing(monkeypatch):
    monkeypatch.setattr(frontend_api, "find_energyplus", lambda: None)
    backends = {item["id"]: item for item in InteractiveFrontendAdapter.greenhouse_backends()}
    assert backends["SIMPLIFIED"]["available"] is True
    assert backends["ENERGYPLUS"]["available"] is False and "not found" in backends["ENERGYPLUS"]["reason"]


def test_an_energyplus_version_the_model_was_not_written_for_is_not_offered(monkeypatch):
    monkeypatch.setattr(frontend_api, "find_energyplus", lambda: EnergyPlusInstall(Path("energyplus"), "25.2.0", "test"))
    energyplus = next(item for item in InteractiveFrontendAdapter.greenhouse_backends() if item["id"] == "ENERGYPLUS")
    assert energyplus["available"] is False and "25.2.0" in energyplus["reason"]


def test_capabilities_expose_the_backends(server):
    import json

    with urllib.request.urlopen(server + "/api/capabilities", timeout=60) as response:
        payload = json.loads(response.read())
    assert [item["id"] for item in payload["greenhouse_backends"]] == ["SIMPLIFIED", "ENERGYPLUS"]


def test_capabilities_expose_climate_control_with_thresholds_from_the_crop_catalogue(server):
    import json

    with urllib.request.urlopen(server + "/api/capabilities", timeout=60) as response:
        control = json.loads(response.read())["climate_control"]
    assert [item["id"] for item in control["actuators"]] == ["shade", "vents", "extractors", "cooling", "heating", "irrigation"]
    assert {item["id"]: item["layer"] for item in control["actuators"]} == {"shade": "PASSIVE", "vents": "PASSIVE", "extractors": "ACTIVE", "cooling": "ACTIVE", "heating": "ACTIVE", "irrigation": "PASSIVE"}
    assert control["stage_thresholds"]["tomato"]["yield_maturation"]["max_temp_c"] == 32.0
    assert "USER_DEFINED" in control["equipment_status"] and "NOT_VALIDATED" in control["design_status"]


def test_the_bench_offers_climate_control_without_assuming_any_equipment():
    assert "Climate control" in HTML and "(not sourced)" in HTML and "Passive first" in HTML
    assert "Nothing is assumed" in HTML and "illustrativeEquipment" in JS
    assert 'placeholder = "not defined"' in JS  # an empty equipment field stays undefined; the request only carries numbers the user typed
    assert 'bench.config.backend === "ENERGYPLUS"' in JS  # the controller cannot act on a precomputed EnergyPlus timeline


SCENE_JS = (FRONTEND / "iso_scene.js").read_text(encoding="utf-8")


def test_related_events_come_as_bundles_that_stay_individually_editable():
    assert "const BUNDLES" in JS and "storm" in JS and "parts.forEach((part) => addEvent(part, false)" in JS
    assert "bundle" in CSS


def test_event_plausibility_is_relative_to_the_runs_own_weather_and_never_blocks():
    assert "function plausibility" in JS and "run's OWN weather" in JS
    assert "unusual for the season" in JS and "hint, never a block" in JS


def test_the_scene_draws_phenology_stress_and_temperature_from_the_crop_catalogue_range():
    for token in ("lifeStage", "dormancy", "flowers", "senescence", "leafPath", "tempTint(t, comfort)", "critical_heat_c", "critical_frost_c", "scene-climate", "Stress:"):
        assert token in SCENE_JS, token
    assert "state.comfort" in JS and "stage_thresholds" in JS  # the colour range is the stage's own, never a number of the page's


def test_bars_have_a_tooltip_and_the_chart_bands_follow_them_in_the_same_colour():
    assert 'id="tl-tip"' in HTML and "function showTip" in JS and "Duration" in JS and "scheduleBandRedraw()" in JS
    assert "bench.events.map((event) => ({ from: eventStartMs(event)" in JS and "hueFor(event.type)" in JS.split("function drawBands")[1].split("function redrawCharts")[0] or "band.hue" in JS


def test_the_scene_background_no_longer_follows_the_hour_of_the_day():
    assert "lerp(228, 205" not in SCENE_JS and 'skyRect.setAttribute("fill"' not in SCENE_JS  # constant warm paper; day and night is the sun marker only


def test_the_bench_offers_real_weather_with_a_planting_date_and_states_what_it_is():
    for token in ("weather-source", "planting-date", "planting-year", "weather-note"):
        assert f'id="{token}"' in HTML, token
    for token in ('"LOCAL_ARCHIVE"', "campaign_start", "const localMode", "function ensurePlanting", "not station data", "approximate growing area"):
        assert token in JS, token


def test_capabilities_list_the_local_weather_each_crop_can_use(server):
    import json

    with urllib.request.urlopen(server + "/api/capabilities", timeout=60) as response:
        datasets = json.loads(response.read())["weather_datasets"]
    assert datasets["source"] == "LOCAL_ARCHIVE" and datasets["classification"] == "FORCING" and "never REAL_VERIFIED" in datasets["note"]
    assert set(datasets["crops"]) >= {"tomato", "lettuce", "peach"} and datasets["crops"]["lettuce"]["cycle_days"] == 42


def test_event_plausibility_uses_the_climate_of_the_date_when_real_weather_is_selected():
    for token in ("/api/weather/climatology", "function loadClimate", "climate.p05", "climate.p95", "unusual for the season", "const runKey"):
        assert token in JS, token
    assert "tertile" in JS.lower() or "warmest third" in JS  # the run-relative hint stays as the fallback without real weather


def test_the_scene_has_a_hand_inked_look_built_once_and_never_redrawn_per_frame():
    for token in ('INK = "#231e16"', "PAPER", "scene-cast-shadow", "scene-tone", "scene-ink", "feDisplacementMap", "toneBand", "hull2", "halo: false"):
        assert token in SCENE_JS, token
    update = SCENE_JS.split("function update(s, layers, calm)")[1].split("return {\n      update,")[0]
    for static_only in ("feDisplacementMap", "feTurbulence", "hull2(", "toneBand(", "K.solidSvg("):
        assert static_only not in update, f"{static_only} must be built in configure, not in update"


def test_the_run_button_turns_red_when_the_data_no_longer_match_the_settings():
    for token in ('id="stale-note"', 'id="run-label"', 'data-stale="false"'):
        assert token in HTML, token
    for token in ("function runSignature", "function staleReasons", "function updateStale", "function stable(", "data.signature = signature", "Run again", "changed: "):
        assert token in JS, token
    assert 'button.primary[data-stale="true"]' in CSS and "#c0392b" in CSS
    # only what changes the request counts: the view, the layers and the chart choice or order are not part of the signature
    signature = JS.split("function runSignature()")[1].split("const SETTING_NAMES")[0]
    assert "buildRequest()" in signature and "eventDocuments()" in signature and "layers" not in signature and "view" not in signature and "charts" not in signature


def test_charts_can_be_reordered_by_drag_or_buttons_and_laid_out_in_columns():
    for token in ("function chartTools", "function moveChart", "function syncChartOrder", "function applyChartColumns", "dragstart", "dragover", "Move earlier", "Move later", "Drag to reorder"):
        assert token in JS, token
    assert 'id="chart-cols"' in HTML and "var(--cols" in CSS and ".chart-card.dragging" in CSS


def test_a_chart_has_a_close_button_and_the_oval_button_always_says_whether_it_is_shown():
    for token in ("chart-close", "function setChart", "function refreshChartChips", "chip.dataset.name = name", "chartsInit"):
        assert token in JS, token
    # the chip, the x and a rebuild all go through setChart / buildCharts, which re-syncs every chip
    assert "close.addEventListener(\"click\", () => setChart(name, false))" in JS
    assert "chip.addEventListener(\"click\", () => setChart(name, !bench.config.charts.includes(name)))" in JS
    assert "refreshChartChips();" in JS.split("function buildCharts")[1].split("// Reordering")[0]
    assert ".chart-close" in CSS


def test_the_first_visit_shows_the_3d_scene_and_the_charts_without_data():
    for token in ("function previewState", "function renderPreview", "No data yet", "Preview · no data yet", "function chartCatalogue", "renderPreview();"):
        assert token in JS, token
    assert "preview without data" in HTML and ".chart-empty" in CSS
    assert "growth: 0.3" in JS.split("function previewState")[1].split("function renderPreview")[0]  # a drawing placeholder; every number stays n/a


def test_the_bench_prices_the_estimated_energy_with_the_users_own_tariff_after_the_run():
    for element in ("tariff-flat", "tariff-yearly", "tariff-bands", "tariff-currency"):
        assert element in HTML
    assert "/api/energy/cost" in JS and "attachCost" in JS and "Nothing is assumed: with no price the cost stays empty" in HTML
    assert "tariff" not in JS[JS.index("function buildRequest"):JS.index("function buildRequest") + 700]  # the tariff is not part of the simulation request


def test_the_bench_offers_optional_energyplus_hvac_cooling_without_assuming_values():
    assert "hvac-setpoint" in HTML and "hvac-capacity" in HTML and "nothing is assumed" in HTML.lower()
    assert "cooling_setpoint_c" in JS and "cooling_capacity_w_m2" in JS and 'bench.config.backend === "ENERGYPLUS" && isNumber(hvac.setpoint)' in JS


def test_the_bench_offers_the_optional_crop_feedback_of_the_simplified_model():
    assert "crop-exchange" in HTML and "Off by default" in HTML
    assert "request.greenhouse.crop_exchange = true" in JS and 'bench.config.backend === "SIMPLIFIED" && bench.config.cropExchange' in JS


def test_the_bench_offers_the_penman_monteith_option_and_sends_it_only_when_chosen():
    assert "et0-method" in HTML and "indoor-wind" in HTML
    assert 'bench.config.et0Method === "PENMAN_MONTEITH_FAO56"' in JS and "request.model_options" in JS


def test_the_bench_offers_the_cited_co2_growth_response_and_sends_it_only_when_chosen():
    assert "co2-response" in HTML and "co2-gain" in HTML
    assert 'bench.config.co2Response === "LOG_RELATIVE_GAIN"' in JS and "co2_gain_per_doubling" in JS


def test_the_bench_lets_the_controller_drive_energyplus_except_the_shade_screen():
    assert 'bench.config.backend === "ENERGYPLUS" && actuator === "shade"' in JS and "lock-step" in JS
    assert "cannot react to a controller" not in JS
