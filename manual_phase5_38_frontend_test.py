"""Offline Phase 5.38 delivery check and reproducible frontend report."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from agri_twin.application.interactive_simulation import (
    SCIENTIFIC_STATUS,
    InteractiveSimulationService,
    canonicalize_request,
    configuration_fingerprint,
    contract_description,
)
from agri_twin.interfaces.frontend_api import FrontendRequestHandler, InteractiveFrontendAdapter

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "data" / "frontend"
SHORT_TOMATO = {
    "crop": "tomato",
    "environment": "outdoor",
    "end_time": "2026-02-16T00:00:00+00:00",
}


def _wait(adapter: InteractiveFrontendAdapter, simulation_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        response = adapter.get(simulation_id)
        if response["execution_status"] not in {"CREATED", "RUNNING"}:
            return response
        time.sleep(0.02)
    raise TimeoutError(f"simulation {simulation_id} did not finish in 20 seconds")


def _run_adapter(adapter: InteractiveFrontendAdapter, request: dict[str, Any]) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    created = adapter.create(request)
    adapter.start(created["simulation_id"])
    response = _wait(adapter, created["simulation_id"])
    return response, time.perf_counter() - started


def _http_run(request: dict[str, Any]) -> tuple[dict[str, Any], float, float, float]:
    adapter = InteractiveFrontendAdapter(timer=time.perf_counter)

    class ReportHandler(FrontendRequestHandler):
        pass

    ReportHandler.adapter = adapter
    server = ThreadingHTTPServer(("127.0.0.1", 0), ReportHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    started = time.perf_counter()
    api_request_seconds = 0.0
    try:
        create = urllib.request.Request(
            f"{base}/api/simulations",
            data=json.dumps(request).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        request_started = time.perf_counter()
        with urllib.request.urlopen(create, timeout=20) as result:
            created = json.loads(result.read())
        api_request_seconds += time.perf_counter() - request_started
        start = urllib.request.Request(
            f"{base}/api/simulations/{created['simulation_id']}/start",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        request_started = time.perf_counter()
        with urllib.request.urlopen(start, timeout=20):
            pass
        api_request_seconds += time.perf_counter() - request_started
        final = None
        while time.perf_counter() - started < 20:
            request_started = time.perf_counter()
            with urllib.request.urlopen(f"{base}/api/simulations/{created['simulation_id']}", timeout=20) as result:
                final = json.loads(result.read())
                serialization_seconds = float(result.headers.get("X-Serialization-Seconds", "0"))
            api_request_seconds += time.perf_counter() - request_started
            if final["execution_status"] not in {"CREATED", "RUNNING"}:
                return final, time.perf_counter() - started, serialization_seconds, api_request_seconds
            time.sleep(0.02)
        raise TimeoutError("HTTP frontend-to-adapter execution did not finish in 20 seconds")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _write_artifacts(report: dict[str, Any]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "interactive_frontend_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    readme = f"""# Phase 5.38 frontend report

Status: **{report["status"]}**

This report is produced by `manual_phase5_38_frontend_test.py`. Its deterministic
hash covers contract, software checks and their outcomes. Machine-dependent
performance observations are recorded separately and excluded from that hash.
No timestamp is added to the report.

- Frontend test suite: {report["frontend_test_status"]}
- Frontend build: {report["frontend_build_status"]}
- Full regression: {report["full_regression_status"]}
- Browser UI smoke: {report["browser_smoke_status"]}
- API contract: {report["api_contract_version"]}
- Supported crops: {", ".join(report["supported_crops"])}
- E2E checks: {report["end_to_end_status"]}
- Responsive/accessibility static checks: {report["accessibility_status"]}
- Deterministic execution: {report["determinism_status"]}
- Scientific evidence produced: none

Performance observations: see `interactive_frontend_report.json`. All durations
are operational measurements, not evidence of scientific validity.

To regenerate after running the browser smoke test and `pytest -q`:

```powershell
python manual_phase5_38_frontend_test.py --frontend-render-ms <short-ms> --full-season-render-ms <season-ms> --browser-smoke-status PASS --full-regression-status PASS --full-regression-passed 1224 --full-regression-skipped 12
```
"""
    (OUTPUT / "interactive_frontend_README.md").write_text(readme, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontend-render-ms", type=float)
    parser.add_argument("--full-season-render-ms", type=float)
    parser.add_argument("--full-regression-status", choices=("PASS", "FAIL", "NOT_RUN"), default="NOT_RUN")
    parser.add_argument("--full-regression-passed", type=int)
    parser.add_argument("--full-regression-skipped", type=int)
    parser.add_argument("--browser-smoke-status", choices=("PASS", "FAIL", "NOT_RUN"), default="NOT_RUN")
    arguments = parser.parse_args()

    print("Phase 5.38 frontend tests")
    pytest_status = pytest.main(["-q", str(ROOT / "tests" / "test_frontend_api.py")])
    capabilities = InteractiveFrontendAdapter().capabilities()
    before = configuration_fingerprint(ROOT)
    checks: dict[str, bool] = {
        "static_assets_present": all((ROOT / "frontend" / name).is_file() for name in ("index.html", "app.js", "styles.css")),
        "contract_capabilities_available": capabilities["api_version"] == contract_description()["api_version"],
        "supported_crop_set": set(capabilities["crops"]) == {"tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple"},
        "scientific_status_is_unqualified": capabilities["scientific_status"] == dict(SCIENTIFIC_STATUS),
    }
    adapter = InteractiveFrontendAdapter(timer=time.perf_counter)
    e2e_cases = [
        ("tomato_outdoor_short", SHORT_TOMATO),
        ("lettuce_full_season", {"crop": "lettuce", "environment": "outdoor"}),
        ("tomato_greenhouse", {"crop": "tomato", "environment": "greenhouse", "end_time": "2026-02-16T00:00:00+00:00"}),
        ("peach_dormancy", {"crop": "peach", "environment": "outdoor", "end_time": "2026-02-22T00:00:00+00:00"}),
        (
            "dynamic_strict_fallback",
            {
                "crop": "peach",
                "environment": "outdoor",
                "end_time": "2026-02-22T00:00:00+00:00",
                "dormancy": {"start_policy": "DORMANCY_STATE", "chilling_model": "DYNAMIC", "fallback_policy": "STRICT"},
            },
        ),
    ]
    e2e_results: dict[str, str] = {}
    measured_adapter_seconds = None
    measured_adapter_model_seconds = None
    for case, request in e2e_cases:
        response, elapsed = _run_adapter(adapter, request)
        e2e_results[case] = response["execution_status"]
        checks[f"e2e_{case}"] = response["execution_status"] == "COMPLETED" and bool(response["result"])
        if case == "tomato_outdoor_short":
            measured_adapter_seconds = elapsed
            measured_adapter_model_seconds = response["operational"]["timings_seconds"].get("simulation_seconds")
        if case == "dynamic_strict_fallback":
            effective = response["effective_configuration"]["dormancy"]
            checks["fallback_is_visible"] = (
                effective["requested_chilling_model"] == "DYNAMIC"
                and effective["effective_chilling_model"] == "CHILLING_HOURS"
                and effective["fallback_applied"] is True
            )

    partial = adapter.service.run_simulation(SHORT_TOMATO)
    full_request = canonicalize_request({"crop": "tomato", "environment": "outdoor"})
    resume_request = {
        **partial.request,
        "end_time": full_request.end_time.isoformat(),
        "checkpoint": partial.checkpoint.to_dict(),
    }
    resume_request.pop("start_time", None)
    resumed_created = adapter.service.resume_simulation(resume_request)
    adapter.start(resumed_created.simulation_id)
    resumed = _wait(adapter, resumed_created.simulation_id)
    uninterrupted = InteractiveSimulationService().run_simulation(
        {"crop": "tomato", "environment": "outdoor"}
    )
    checks["checkpoint_resume_matches_full_run"] = all(
        uninterrupted.result.trajectory[name]
        == partial.result.trajectory[name] + resumed["result"]["trajectory"][name]
        for name in uninterrupted.result.trajectory
    )
    checks["resumed_checkpoint_is_backend_checkpoint"] = (
        resumed["checkpoint"]["payload"] == uninterrupted.checkpoint.payload
    )
    checks["deterministic_response_and_hashes"] = (
        InteractiveSimulationService().run_simulation(SHORT_TOMATO).deterministic_dict()
        == InteractiveSimulationService().run_simulation(SHORT_TOMATO).deterministic_dict()
    )
    checks["configuration_immutability"] = configuration_fingerprint(ROOT) == before

    frontend_sources = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "frontend").iterdir() if path.is_file()
    )
    forbidden = ("WeatherEngine", "PhenologyEngine", "ScenarioRunner", "TwinState", "ParameterRegistry", "SimulationClock")
    checks["static_domain_audit"] = all(value not in frontend_sources for value in forbidden)
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    checks["accessibility_and_responsive_basics"] = (
        all(value in html for value in ('for="crop"', 'role="alert"', "aria-live", "aria-label"))
        and "@media (max-width: 620px)" in css
        and "prefers-reduced-motion" in css
    )

    direct_service = InteractiveSimulationService(timer=time.perf_counter)
    direct_short_started = time.perf_counter()
    direct_short = direct_service.run_simulation(SHORT_TOMATO)
    direct_short_wall = time.perf_counter() - direct_short_started
    direct_full_started = time.perf_counter()
    direct_full = InteractiveSimulationService(timer=time.perf_counter).run_simulation(
        {"crop": "tomato", "environment": "outdoor"}
    )
    direct_full_wall = time.perf_counter() - direct_full_started
    http_response, http_wall, http_serialization, http_api_time = _http_run(SHORT_TOMATO)
    checks["http_end_to_end_completed"] = http_response["execution_status"] == "COMPLETED"
    encoded = json.dumps(http_response, sort_keys=True, separators=(",", ":"), allow_nan=False)
    serialization_started = time.perf_counter()
    json.dumps(http_response, sort_keys=True, separators=(",", ":"), allow_nan=False)
    serialization_local = time.perf_counter() - serialization_started
    deserialization_started = time.perf_counter()
    json.loads(encoded)
    deserialization_local = time.perf_counter() - deserialization_started

    performance = {
        "classification": "OPERATIONAL_SOFTWARE_MEASUREMENT_NOT_SCIENTIFIC_EVIDENCE",
        "MODEL_TIME": {
            "direct_short_seconds": direct_short.operational["timings_seconds"]["simulation_seconds"],
            "direct_full_season_seconds": direct_full.operational["timings_seconds"]["simulation_seconds"],
            "http_short_seconds": http_response["operational"]["timings_seconds"].get("simulation_seconds"),
            "adapter_short_seconds": measured_adapter_model_seconds,
        },
        "API_TIME": {
            "adapter_short_end_to_end_seconds": measured_adapter_seconds,
            "http_short_total_request_round_trips_seconds": http_api_time,
            "http_short_end_to_end_seconds_including_model_and_polling": http_wall,
        },
        "SERIALIZATION_TIME": {
            "http_response_seconds": http_serialization,
            "local_json_seconds": serialization_local,
            "local_json_deserialization_seconds": deserialization_local,
            "serialized_response_bytes": len(encoded.encode("utf-8")),
        },
        "FRONTEND_RENDER_TIME": {
            "measurement_status": "MEASURED_IN_BROWSER"
            if arguments.frontend_render_ms is not None and arguments.full_season_render_ms is not None
            else "NOT_CAPTURED",
            "short_run_milliseconds": arguments.frontend_render_ms,
            "full_season_milliseconds": arguments.full_season_render_ms,
        },
    }
    stable = {
        "api_contract_version": capabilities["api_version"],
        "supported_crops": capabilities["crops"],
        "supported_environments": capabilities["environments"],
        "supported_scenarios": capabilities["scenarios"],
        "supported_execution_modes": capabilities["modes"],
        "e2e_cases": e2e_results,
        "checks": checks,
        "frontend_test_status": "PASS" if pytest_status == pytest.ExitCode.OK else "FAIL",
        "frontend_build_status": "PASS (static assets; no build pipeline required)"
        if checks["static_assets_present"]
        else "FAIL",
        "full_regression": {
            "status": arguments.full_regression_status,
            "passed": arguments.full_regression_passed,
            "skipped": arguments.full_regression_skipped,
        },
        "browser_smoke_status": arguments.browser_smoke_status,
        "scientific_status": dict(SCIENTIFIC_STATUS),
        "responsive_viewports_smoke_tested": [1440, 768, 390] if arguments.browser_smoke_status == "PASS" else [],
    }
    stable_hash = hashlib.sha256(
        json.dumps(stable, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    passed = all(checks.values()) and pytest_status == pytest.ExitCode.OK
    report_status = (
        passed
        and arguments.full_regression_status == "PASS"
        and arguments.frontend_render_ms is not None
        and arguments.full_season_render_ms is not None
        and arguments.browser_smoke_status == "PASS"
    )
    report = {
        **stable,
        "status": "PASS" if report_status else "INCOMPLETE",
        "deterministic_hash": stable_hash,
        "frontend_test_status": "PASS" if pytest_status == pytest.ExitCode.OK else "FAIL",
        "frontend_build_status": "PASS (static assets; no build pipeline required)"
        if checks["static_assets_present"]
        else "FAIL",
        "full_regression_status": arguments.full_regression_status,
        "full_regression_summary": (
            f"{arguments.full_regression_passed} passed, {arguments.full_regression_skipped} skipped, 0 failed"
            if arguments.full_regression_status == "PASS"
            and arguments.full_regression_passed is not None
            and arguments.full_regression_skipped is not None
            else arguments.full_regression_status
        ),
        "browser_smoke_status": arguments.browser_smoke_status,
        "end_to_end_status": "PASS" if all(value == "COMPLETED" for value in e2e_results.values()) and checks["http_end_to_end_completed"] else "FAIL",
        "determinism_status": "PASS" if checks["deterministic_response_and_hashes"] and checks["checkpoint_resume_matches_full_run"] else "FAIL",
        "accessibility_status": "PASS" if checks["accessibility_and_responsive_basics"] else "FAIL",
        "responsive_status": "PASS" if arguments.browser_smoke_status == "PASS" else "NOT_RUN",
        "performance_observations": performance,
        "scientific_evidence": [],
    }
    _write_artifacts(report)
    for name, passed_check in checks.items():
        print(f"  {'PASS' if passed_check else 'FAIL'}: {name}")
    print(f"artifact={OUTPUT.relative_to(ROOT).as_posix()}/interactive_frontend_report.json")
    print(f"status={report['status']} deterministic_hash={stable_hash}")
    return 0 if report_status else 1


if __name__ == "__main__":
    sys.exit(main())
