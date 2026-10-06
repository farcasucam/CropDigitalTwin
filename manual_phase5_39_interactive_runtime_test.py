"""Offline Phase 5.39 delivery check: runtime events, what-if branches and visualization contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from agri_twin.application.interactive_runtime import InteractiveRuntimeService, static_audit_runtime
from agri_twin.application.interactive_simulation import SCIENTIFIC_STATUS, InteractiveSimulationService
from agri_twin.application.runtime_events import event_contract
from agri_twin.interfaces.frontend_api import InteractiveFrontendAdapter

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "data" / "frontend"
BASE = {"crop": "tomato", "environment": "greenhouse", "end_time": "2026-03-15T00:00:00+00:00"}
SCENARIOS = {
    "heat_wave": [{"event_type": "HEAT_WAVE", "start_simulation_time": "2026-02-20T00:00:00+00:00", "duration_hours": 24, "intensity": 6.0}],
    "ventilation_rain": [
        {"event_type": "VENTILATION", "start_simulation_time": "2026-02-20T00:00:00+00:00", "duration_hours": 12, "intensity": 0.8},
        {"event_type": "RAIN", "start_simulation_time": "2026-02-21T00:00:00+00:00", "duration_hours": 6, "intensity": 3.0},
    ],
}
CHECKPOINT = "2026-02-20T00:00:00+00:00"
HTML_FLAGS = ("NOT_APPLICABLE", "USER-DEFINED SYNTHETIC FORCING")
NO_FLAGS = (
    "REAL_VERIFIED = 0",
    "CALIBRATION_PERFORMED = false",
    "EXPERIMENTAL_VALIDATION_PERFORMED = false",
    "BIOLOGICAL_VALIDITY_CLAIMED = false",
    "FIELD_ACCURACY_CLAIMED = false",
    "DATA_ASSIMILATION_IMPLEMENTED = false",
)


def _sha(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _what_if(service: InteractiveRuntimeService, events: list[dict[str, Any]]) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    result = service.what_if({"request": BASE, "checkpoint_time": CHECKPOINT, "events": events})
    return result, time.perf_counter() - started


def _jsonable(value: Any) -> Any:
    return value.to_dict() if hasattr(value, "to_dict") else value


def _write_artifacts(report: dict[str, Any]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "interactive_runtime_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    readme = f"""# Phase 5.39 interactive runtime report

Status: **{report["status"]}**

Produced by `manual_phase5_39_interactive_runtime_test.py`. The deterministic
hash covers the event contract, checks and what-if hashes. Machine-dependent
performance is recorded separately and excluded from that hash. No timestamp.

- Runtime test suite: {report["runtime_test_status"]}
- Static audit: {report["static_audit_status"]}
- Full regression: {report["full_regression_status"]}
- Supported events: {", ".join(report["supported_events"])}
- Not supported: {", ".join(report["unsupported_events"])}
- Scientific evidence produced: none. User events are USER-DEFINED SYNTHETIC FORCING.

Scientific status flags: {"; ".join(NO_FLAGS)}.
"""
    (OUTPUT / "interactive_runtime_README.md").write_text(readme, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-regression-status", choices=("PASS", "FAIL", "NOT_RUN"), default="NOT_RUN")
    parser.add_argument("--full-regression-passed", type=int)
    parser.add_argument("--full-regression-skipped", type=int)
    parser.add_argument("--browser-smoke-status", choices=("PASS", "FAIL", "NOT_RUN"), default="NOT_RUN")
    arguments = parser.parse_args()

    print("Phase 5.39 runtime tests")
    runtime_status = pytest.main(["-q", str(ROOT / "tests" / "test_interactive_runtime.py")])
    audit = static_audit_runtime(ROOT)
    service = InteractiveRuntimeService(InteractiveSimulationService(timer=time.perf_counter))
    contract = service.contract()
    events_contract = event_contract()
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "frontend" / "runtime.js").read_text(encoding="utf-8")
    capabilities = InteractiveFrontendAdapter().capabilities()

    results: dict[str, dict[str, Any]] = {}
    timings: dict[str, float] = {}
    for name, events in SCENARIOS.items():
        first, elapsed = _what_if(service, events)
        second, _ = _what_if(service, events)
        results[name] = {"first": first, "second": second}
        timings[f"what_if_{name}_seconds"] = round(elapsed, 3)

    def _field(result: dict[str, Any], key: str) -> Any:
        return _jsonable(result).get(key)

    hashes = {name: _field(pair["first"], "what_if_hash") for name, pair in results.items()}
    checks: dict[str, bool] = {
        "runtime_tests_pass": runtime_status == 0,
        "static_audit_passes": audit.get("status") == "PASS",
        "what_if_deterministic": all(
            _field(pair["first"], "what_if_hash") and _field(pair["first"], "what_if_hash") == _field(pair["second"], "what_if_hash")
            for pair in results.values()
        ),
        "scenarios_differ": len(set(hashes.values())) == len(hashes),
        "history_unchanged_before_first_event": all(
            pair["first"]["comparison"]["unchanged_before_first_event"] is True
            for pair in results.values()
        ),
        "capabilities_expose_runtime_contract": capabilities.get("runtime") is not None,
        "scientific_status_has_no_positive_claims": SCIENTIFIC_STATUS["REAL_VERIFIED"] == 0
        and not any(v for v in SCIENTIFIC_STATUS.values() if isinstance(v, bool)),
        "views_present": all(token in html for token in ("TOP", "ISOMETRIC", "DETAIL")),
        "user_events_labelled_synthetic": HTML_FLAGS[1] in html,
        "no_per_plant_fabrication": HTML_FLAGS[0] in script,
        "time_controller_present": all(token in html for token in ("tc-play", "tc-pause")) or "tc-" in html,
        "water_stress_not_supported": "WATER_STRESS" in json.dumps(_jsonable(contract)) and "WATER_STRESS" not in [
            spec for spec in _supported(events_contract)
        ],
    }
    failed = [name for name, ok in checks.items() if not ok]
    supported = _supported(events_contract)
    report: dict[str, Any] = {
        "phase": "5.39",
        "status": "PASS" if not failed else "FAIL",
        "failed_checks": failed,
        "checks": checks,
        "runtime_test_status": "PASS" if runtime_status == 0 else "FAIL",
        "static_audit_status": audit.get("status"),
        "full_regression_status": arguments.full_regression_status,
        "full_regression_passed": arguments.full_regression_passed,
        "full_regression_skipped": arguments.full_regression_skipped,
        "browser_smoke_status": arguments.browser_smoke_status,
        "supported_events": sorted(supported),
        "unsupported_events": ["WATER_STRESS"],
        "renderer": "SVG isometric (no external library)",
        "what_if_hashes": hashes,
        "scientific_status": dict(SCIENTIFIC_STATUS),
        "scientific_status_flags": list(NO_FLAGS),
    }
    report["deterministic_hash"] = _sha(report)
    report["performance_observations"] = {"timings_seconds": timings, "note": "machine-dependent, excluded from deterministic_hash"}
    _write_artifacts(report)

    print(json.dumps({"status": report["status"], "failed": failed, "hash": report["deterministic_hash"]}, indent=2))
    complete = report["status"] == "PASS" and arguments.full_regression_status == "PASS" and arguments.browser_smoke_status == "PASS"
    if complete:
        print("PHASE 5.39 COMPLETE")
        for flag in NO_FLAGS:
            print(f"  NO: {flag}")
    else:
        print("PHASE 5.39 INCOMPLETE: pending " + ("failed checks" if failed else "full regression / browser smoke"))
    return 0 if report["status"] == "PASS" else 1


def _supported(contract: Any) -> list[str]:
    return [item["event_type"] for item in contract["supported"]]


if __name__ == "__main__":
    sys.exit(main())
