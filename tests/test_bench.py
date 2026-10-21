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
