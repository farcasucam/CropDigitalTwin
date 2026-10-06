"""Offline Phase 5.40 delivery check: interactive visual simulation, record/replay and presentation audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from agri_twin.application.interactive_runtime import static_audit_runtime
from agri_twin.application.interactive_simulation import SCIENTIFIC_STATUS
from agri_twin.application.runtime_replay import RuntimeReplayService

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "data" / "frontend"
DOC = {
    "request": {"crop": "tomato", "environment": "greenhouse", "end_time": "2026-03-15T00:00:00+00:00"},
    "checkpoint_time": "2026-02-20T00:00:00+00:00",
    "events": [{"event_type": "HEAT_WAVE", "start_simulation_time": "2026-02-21T00:00:00+00:00", "duration_hours": 24, "intensity": 6.0}],
}
NO_FLAGS = (
    "REAL_VERIFIED = 0",
    "CALIBRATION_PERFORMED = false",
    "EXPERIMENTAL_VALIDATION_PERFORMED = false",
    "BIOLOGICAL_VALIDITY_CLAIMED = false",
    "FIELD_ACCURACY_CLAIMED = false",
    "DATA_ASSIMILATION_IMPLEMENTED = false",
)
FPS_DESKTOP_MIN = 30.0
FPS_MOBILE_MIN = 20.0


def _sha(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _write_artifacts(report: dict[str, Any]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "visual_simulation_report.json").write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    software = report["SOFTWARE_RESULT"]
    performance = report["PERFORMANCE_RESULT"]
    readme = f"""# Phase 5.40 interactive visual simulation report

Status: **{report["status"]}**

Produced by `manual_phase5_40_visual_simulation_test.py`. The deterministic hash covers the software
checks only; browser measurements are machine-dependent and excluded from it.

## SOFTWARE_RESULT
- Visual simulation tests: {software["visual_tests"]}
- Static audit: {software["static_audit"]}
- Record/replay: {software["replay_status"]}
- Full regression: {software["full_regression_status"]} (passed={software["full_regression_passed"]}, skipped={software["full_regression_skipped"]})
- Browser smoke: {software["browser_smoke_status"]}

## PERFORMANCE_RESULT (measured in the browser, not inferred)
- Desktop FPS: {performance["desktop_fps"]} (target >= {FPS_DESKTOP_MIN})
- Narrow viewport (390 px, desktop Chromium, not a physical phone) FPS: {performance["narrow_viewport_fps"]} (target >= {FPS_MOBILE_MIN})
- Horizontal overflow at 1280/768/390: {performance["overflow_checks"]}

## SCIENTIFIC_EVIDENCE
None. The visual layer only displays API output; user events are USER-DEFINED SYNTHETIC FORCING.

Scientific status flags: {"; ".join(NO_FLAGS)}.
"""
    (OUTPUT / "visual_simulation_README.md").write_text(readme, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-regression-status", choices=("PASS", "FAIL", "NOT_RUN"), default="NOT_RUN")
    parser.add_argument("--full-regression-passed", type=int)
    parser.add_argument("--full-regression-skipped", type=int)
    parser.add_argument("--browser-smoke-status", choices=("PASS", "FAIL", "NOT_RUN"), default="NOT_RUN")
    parser.add_argument("--desktop-fps", type=float)
    parser.add_argument("--narrow-fps", type=float)
    parser.add_argument("--overflow-free", choices=("yes", "no", "not_run"), default="not_run")
    arguments = parser.parse_args()

    print("Phase 5.40 visual simulation tests")
    status = pytest.main(["-q", str(ROOT / "tests" / "test_visual_simulation.py")])
    audit = static_audit_runtime(ROOT)
    service = RuntimeReplayService()
    started = time.perf_counter()
    recorded = service.record(DOC)
    again = service.record(DOC)
    replay = service.replay(recorded["session"])
    elapsed = time.perf_counter() - started
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    checks = {
        "visual_tests_pass": status == 0,
        "static_audit_passes": audit.get("status") == "PASS",
        "record_deterministic": recorded["session"]["session_hash"] == again["session"]["session_hash"],
        "replay_matches": replay["status"] == "MATCH" and all(replay["checks"].values()),
        "layers_present": all(f'data-layer="{layer}"' in html for layer in ("crop", "soil", "water", "temperature", "radiation", "vpd", "co2", "events")),
        "assets_local": "http://" not in html and "https://" not in html,
        "scientific_status_has_no_positive_claims": SCIENTIFIC_STATUS["REAL_VERIFIED"] == 0
        and not any(v for v in SCIENTIFIC_STATUS.values() if isinstance(v, bool)),
    }
    failed = [name for name, ok in checks.items() if not ok]
    desktop_ok = arguments.desktop_fps is not None and arguments.desktop_fps >= FPS_DESKTOP_MIN
    narrow_ok = arguments.narrow_fps is not None and arguments.narrow_fps >= FPS_MOBILE_MIN
    report: dict[str, Any] = {
        "phase": "5.40",
        "status": "PASS" if not failed else "FAIL",
        "failed_checks": failed,
        "checks": checks,
        "renderer": "SVG isometric + vendored uPlot (MIT, offline)",
        "session_hash": recorded["session"]["session_hash"],
        "SOFTWARE_RESULT": {
            "visual_tests": "PASS" if status == 0 else "FAIL",
            "static_audit": audit.get("status"),
            "replay_status": replay["status"],
            "full_regression_status": arguments.full_regression_status,
            "full_regression_passed": arguments.full_regression_passed,
            "full_regression_skipped": arguments.full_regression_skipped,
            "browser_smoke_status": arguments.browser_smoke_status,
        },
        "SCIENTIFIC_EVIDENCE": {"produced": False, "scientific_status": dict(SCIENTIFIC_STATUS), "flags": list(NO_FLAGS)},
    }
    report["deterministic_hash"] = _sha(report)
    report["PERFORMANCE_RESULT"] = {
        "desktop_fps": arguments.desktop_fps,
        "narrow_viewport_fps": arguments.narrow_fps,
        "overflow_checks": arguments.overflow_free,
        "record_and_replay_seconds": round(elapsed, 3),
        "note": "machine-dependent, excluded from deterministic_hash",
    }
    _write_artifacts(report)

    print(json.dumps({"status": report["status"], "failed": failed, "hash": report["deterministic_hash"]}, indent=2))
    complete = (
        report["status"] == "PASS"
        and arguments.full_regression_status == "PASS"
        and arguments.browser_smoke_status == "PASS"
        and desktop_ok
        and narrow_ok
        and arguments.overflow_free == "yes"
    )
    if complete:
        print("PHASE 5.40 COMPLETE")
        for flag in NO_FLAGS:
            print(f"  NO: {flag}")
    else:
        print("PHASE 5.40 INCOMPLETE: pending failed checks, full regression, browser smoke, FPS or overflow evidence")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
