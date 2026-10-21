"""Phase 5.41: greenhouse layout catalogue, scene state transform and the integrated spatial view."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from agri_twin.application.greenhouse_catalogue import build_greenhouse_catalogue
from agri_twin.application.interactive_runtime import static_audit_runtime
from agri_twin.domain.greenhouse_modularity import CATALOGUE_RULES
from agri_twin.domain.greenhouse_typology import GreenhouseTypology
from agri_twin.interfaces.frontend_api import InteractiveFrontendAdapter

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")
HTML = (FRONTEND / "index.html").read_text(encoding="utf-8")
RUNTIME_JS = (FRONTEND / "runtime.js").read_text(encoding="utf-8")


def node(script: str):
    program = (
        f"const V = require({json.dumps(str(FRONTEND / 'visual_state.js'))});\n"
        f"const S = require({json.dumps(str(FRONTEND / 'scene_state.js'))});\n"
        f"console.log(JSON.stringify((() => {{ {script} }})()));"
    )
    done = subprocess.run([NODE, "-e", program], capture_output=True, text=True, timeout=60, check=True)
    return json.loads(done.stdout)


CTX = """
const times = ["2026-03-01T00:00:00+00:00", "2026-03-01T01:00:00+00:00", "2026-03-01T02:00:00+00:00"];
const spec = (name, availability = "AVAILABLE", unit = "u") => ({name, availability, unit, reason: availability === "AVAILABLE" ? null : "r"});
const catalogue = V.catalogue([spec("temperature_c"), spec("outdoor_temperature_c"), spec("relative_humidity_pct"), spec("radiation_w_m2"), spec("leaf_area_index"),
  spec("precipitation_mm"), spec("irrigation_mm"), spec("water_stress"), spec("heat_stress"), spec("cold_stress"), spec("vpd_stress"), spec("accumulated_stress"),
  spec("frost_damage"), spec("biomass_total_g_m2"), spec("biomass_fruit_g_m2"), spec("maturity_index"), spec("soil_water_vwc_m3_m3"), spec("vpd_kpa"),
  spec("greenhouse_ventilation_fraction"), spec("greenhouse_shading_fraction"), spec("greenhouse_heating_kw"), spec("greenhouse_cooling_kw"),
  spec("co2_ppm", "NOT_APPLICABLE"), spec("crop_stage")]);
const series = {temperature_c: [20, 24, 28], outdoor_temperature_c: [10, 12, 14], relative_humidity_pct: [60, 62, 64], radiation_w_m2: [0, 100, 400],
  leaf_area_index: [1, 2, 3], precipitation_mm: [0, 2, 1], irrigation_mm: [0, 0, 0.4], water_stress: [0, 0.2, 0.4], heat_stress: [0, 0, 1], cold_stress: [0, 0, 0],
  vpd_stress: [0, 0.1, 0.2], accumulated_stress: [0, 2, 4], frost_damage: [0, 0.25, 0.5], biomass_total_g_m2: [100, 200, 400], biomass_fruit_g_m2: [0, 20, 100],
  maturity_index: [0, 0.3, 0.6], soil_water_vwc_m3_m3: [0.2, 0.3, 0.4], vpd_kpa: [0.5, 1, 1.5], greenhouse_ventilation_fraction: [0, 0.5, 0.9],
  greenhouse_shading_fraction: [0, 0, 0.5], greenhouse_heating_kw: [1, 0, 0], greenhouse_cooling_kw: [0, 0, 2], crop_stage: ["a", "a", "b"]};
const ctx = (environment) => V.buildContext({series, catalogue, times, events: [], environment, branch: "intervention"});
const scene = (environment, position) => { const c = ctx(environment); return S.fromVisual(V.buildVisualState(c, position), c, position); };
"""


# -- catalogue ------------------------------------------------------------------------------------------
def test_catalogue_covers_every_typology_with_profiles_and_provenance():
    catalogue = build_greenhouse_catalogue()
    assert set(catalogue["typologies"]) == {t.value for t in GreenhouseTypology}
    assert catalogue["geometry_provenance"] == "PARAMETRIC_SCHEMATIC"
    assert "not a manufacturer drawing" in catalogue["statement"]
    for name, entry in catalogue["typologies"].items():
        assert entry["profiles"], name
        default = entry["default"]
        assert f"{default['span']:g}|{default['rise']:g}" in entry["profiles"], name
        for profile in entry["profiles"].values():
            ys = [point[0] for point in profile["profile"]]
            assert ys[0] == pytest.approx(0.0, abs=1e-9) and ys == sorted(ys)
            assert all(point[1] >= -1e-9 for point in profile["profile"])  # relative to the gutter line: never below it


def test_catalogue_is_deterministic_and_open_field_is_provisional_without_energyplus():
    assert json.dumps(build_greenhouse_catalogue(), sort_keys=True) == json.dumps(build_greenhouse_catalogue(), sort_keys=True)
    field = build_greenhouse_catalogue()["open_field"]
    assert field["evidence"] == "PROVISIONAL_DEFAULT" and field["uses_energyplus"] is False


def test_catalogue_offers_only_manufacturer_listed_options_where_published():
    catalogue = build_greenhouse_catalogue()["typologies"]
    assert catalogue["MULTITUNEL_CAPILLA"]["options"]["span"] == [8.0, 9.6]
    assert catalogue["MULTITUNEL_GRANDE_LUX"]["options"]["span"] == [12.8, 14.4, 16.0]
    assert catalogue["MULTITUNEL_TROPICAL_ASIMETRICO"]["listed"]["rise"] is False  # ridge rise is not published
    assert set(catalogue["TUNEL"]["options"]["rise"]) == set(CATALOGUE_RULES[GreenhouseTypology.TUNEL].ridge_rise_m.values)


@needs_node
def test_profile_keys_match_the_javascript_number_formatting():
    catalogue = build_greenhouse_catalogue()["typologies"]
    pairs = [[name, span, rise] for name, entry in catalogue.items() for span in entry["options"]["span"] for rise in entry["options"]["rise"]]
    program = f"const keys = {json.dumps(pairs)}.map(([n, s, r]) => [n, `${{s}}|${{r}}`]); console.log(JSON.stringify(keys));"
    done = subprocess.run([NODE, "-e", program], capture_output=True, text=True, timeout=30, check=True)
    for name, key in json.loads(done.stdout):
        assert key in catalogue[name]["profiles"], (name, key)


@pytest.fixture(scope="module")
def server():
    class Handler(__import__("agri_twin.interfaces.frontend_api", fromlist=["FrontendRequestHandler"]).FrontendRequestHandler):
        adapter = InteractiveFrontendAdapter()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_catalogue_endpoint_serves_the_domain_catalogue(server):
    with urllib.request.urlopen(server + "/api/greenhouse/catalogue", timeout=30) as response:
        assert response.status == 200
        payload = json.loads(response.read())
    assert payload == json.loads(json.dumps(build_greenhouse_catalogue()))


# -- scene state (pure JS) --------------------------------------------------------------------------------
@needs_node
def test_scene_state_is_a_pure_function_of_the_series():
    assert node(CTX + 'return scene("greenhouse", 1.5);') == node(CTX + 'return scene("greenhouse", 1.5);')


@needs_node
def test_greenhouse_scene_state_carries_actuators_indoor_and_outdoor_values():
    state = node(CTX + 'return scene("greenhouse", 2);')
    assert state["outdoor"]["temp_c"] == 14 and state["indoor"]["temp_c"] == 28
    assert state["actuators"] == {"vent_opening": 0.9, "screen_deployed": 0.5, "heating_kw": 0, "cooling_kw": 2, "extractor_level": None}
    assert state["indoor"]["co2_ppm"] is None  # NOT_APPLICABLE stays unavailable, never zero


@needs_node
def test_open_field_state_has_no_indoor_or_actuators_and_uses_the_crop_environment_as_outdoor():
    state = node(CTX + 'return scene("outdoor", 2);')
    assert state["indoor"] is None and state["actuators"] is None
    assert state["outdoor"]["temp_c"] == 28 and state["outdoor"]["rh_pct"] == 64


@needs_node
def test_wind_is_never_invented_and_rain_is_converted_to_an_hourly_rate():
    state = node(CTX + 'return scene("outdoor", 1);')
    assert state["outdoor"]["wind_m_s"] is None and state["outdoor"]["wind_dir_deg"] is None
    assert state["outdoor"]["rain_mm_h"] == pytest.approx(2.0)  # 2 mm in a 1 h step


@needs_node
def test_crop_state_reads_the_returned_series_only():
    crop = node(CTX + 'return scene("greenhouse", 2).crop;')
    assert crop["lai"] == 3 and crop["loss_fraction"] == 0.5 and crop["water_stress"] == 0.4 and crop["heat_stress"] == 1
    assert crop["fruit_fraction"] == pytest.approx(0.25) and crop["accumulated"] == pytest.approx(1.0)
    assert crop["growth"] == pytest.approx(0.75)  # LAI 3 against the fixed drawing reference of 4


@needs_node
def test_a_young_crop_is_drawn_small_and_an_unstressed_run_stays_green():
    young = node(CTX + 'series.leaf_area_index = [0.1, 0.1, 0.1]; series.accumulated_stress = [0, 0, 0]; return scene("greenhouse", 1).crop;')
    assert young["growth"] == pytest.approx(0.025) and young["accumulated"] == 0
    mild = node(CTX + 'series.accumulated_stress = [0, 0.2, 0.2]; return scene("greenhouse", 1).crop;')
    assert mild["accumulated"] == pytest.approx(0.2)  # relative to max(1, run maximum), not stretched to the run extent


@needs_node
def test_unrequested_or_unavailable_variables_become_null_not_zero():
    state = node(CTX + 'delete series.frost_damage; delete series.biomass_fruit_g_m2; return scene("greenhouse", 1).crop;')
    assert state["loss_fraction"] is None and state["fruit_fraction"] is None


@needs_node
def test_fractional_positions_blend_values_and_are_flagged():
    state = node(CTX + 'return scene("greenhouse", 1.5);')
    assert state["interpolated"] is True and state["indoor"]["temp_c"] == pytest.approx(26)


@needs_node
def test_hour_of_day_comes_from_the_timestamp_text():
    assert node('return S.hourOfDay("2026-03-01T13:30:00+00:00");') == 13.5
    assert node('return S.hourOfDay("garbage");') == 12


@needs_node
def test_crop_silhouettes_are_schematic_with_a_default():
    assert node('return [S.silhouetteFor("tomato"), S.silhouetteFor("lettuce"), S.silhouetteFor("unknown-crop")];') == ["vine", "rosette", "bush"]


# -- integration markers ------------------------------------------------------------------------------------
def test_spatial_view_uses_the_scene_modules_and_the_layout_panel():
    for token in ("layout-panel", "layout-typology", "layout-span", "layout-rise", "layout-gutter", "layout-pillar", "layout-spans", "layout-bays", "layout-note"):
        assert f'id="{token}"' in HTML
    for token in ("IsoScene.create", "SceneState.fromVisual", "/api/greenhouse/catalogue", "data-part", "aria-label"):
        assert token in RUNTIME_JS


def test_the_old_flat_drawing_code_is_gone():
    assert "function projection" not in RUNTIME_JS and "function poly(" not in RUNTIME_JS


def test_static_audit_still_passes_with_the_scene_modules():
    audit = static_audit_runtime(ROOT)
    assert audit["status"] == "PASS" and audit["violations"] == []
    assert "frontend/iso_scene.js" in audit["javascript_files"] and "frontend/scene_state.js" in audit["javascript_files"]
    assert "frontend/vendor/isokit.iife.js" in audit["vendored_libraries"]
