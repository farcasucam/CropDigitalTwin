"""Offline delivery verification for Phase 5.37: interactive simulation API and execution contract.

Walks the frontend-facing flow through the public API only (request -> canonical
form -> short run -> deterministic rerun -> season with progress -> checkpoint ->
resume -> comparison -> immutability -> scientific status -> structured errors),
then builds the qualification report, writes the artifact under data/simulation/
and ends with PASS or FAIL. Synthetic forcing only: no real data, calibration or
experimental validation is performed or claimed.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from agri_twin.application.interactive_simulation import (
    SCIENTIFIC_STATUS,
    ErrorCode,
    ExecutionMode,
    ExecutionStatus,
    InteractiveSimulationApiSuite,
    InteractiveSimulationService,
    SimulationApiError,
    canonicalize_request,
    configuration_fingerprint,
    plan_execution,
    write_report,
)

ROOT = Path(__file__).resolve().parent


def main() -> int:
    checks: list[tuple[str, bool]] = []

    def check(label: str, passed: bool) -> None:
        checks.append((label, passed))
        print(f"  {'PASS' if passed else 'FAIL'}: {label}")

    before = configuration_fingerprint(ROOT)
    service = InteractiveSimulationService(timer=time.perf_counter)  # operational timings only; the API reads no clock

    print("1-2. create and canonicalize a request")
    document = {"crop": "Tomato", "environment": "outdoor", "end_time": "2026-02-22T00:00:00+00:00"}
    request = canonicalize_request(document)
    print(f"     canonical: {request.canonical_json()[:160]}...")
    check("canonical JSON is stable and round-trips", canonicalize_request(json.loads(request.canonical_json())).canonical_json() == request.canonical_json())
    check("short horizon is INTERACTIVE (from configuration, nothing executed)", plan_execution(request).mode is ExecutionMode.INTERACTIVE)

    print("3-5. run a short simulation, check result and hashes")
    short = service.run_simulation(request)
    result = short.result
    print(f"     status={short.execution_status.value} steps={result.steps} final stage={result.final_state['phenological_stage']} "
          f"biomass={result.final_state['biomass_g_m2']:.3f} g/m2 trajectory_hash={short.hashes['trajectory_hash'][:16]}")
    check("short run completed with every step", short.execution_status is ExecutionStatus.COMPLETED and result.steps == request.total_steps)
    check("result series have one value per step", all(len(values) == result.steps for values in result.trajectory.values()))

    print("6-7. run again and compare")
    again = InteractiveSimulationService().run_simulation(document)
    check("same request hash, configuration hash, trajectory hash and serialized response",
          short.deterministic_dict() == again.deterministic_dict() and short.response_hash == again.response_hash)

    print("8-9. full season with progress")
    events = []
    season = service.run_simulation({"crop": "tomato", "environment": "outdoor"}, events.append)
    print(f"     mode={season.plan['mode']} steps={season.progress.completed_steps} progress events={len(events)} "
          f"simulation={season.operational['timings_seconds']['simulation_seconds']:.3f} s (operational)")
    check("season is INTERACTIVE_WITH_PROGRESS and completed", season.plan["mode"] == ExecutionMode.INTERACTIVE_WITH_PROGRESS.value and season.execution_status is ExecutionStatus.COMPLETED)
    check("progress fractions increase to 1.0 with simulated time", [e.fraction for e in events] == sorted(e.fraction for e in events) and events[-1].fraction == 1.0)

    print("10-12. checkpoint, resume and compare with the continuous run")
    partial = service.run_simulation({"crop": "tomato", "environment": "outdoor", "end_time": "2026-04-10T00:00:00+00:00"})
    resumed = service.resume_simulation({"crop": "tomato", "environment": "outdoor", "checkpoint": partial.checkpoint.to_dict()})
    resumed = service.start_simulation(resumed.simulation_id)
    full, first, second = season.result.trajectory, partial.result.trajectory, resumed.result.trajectory
    print(f"     checkpoint {partial.checkpoint.simulation_time.isoformat()} sha256={partial.checkpoint.sha256[:16]} "
          f"steps {partial.progress.completed_steps}+{resumed.progress.completed_steps}={season.progress.completed_steps}")
    check("full run == partial run + checkpoint + resume (every series)", all(full[key] == first[key] + second[key] for key in full))
    check("final state and final checkpoint identical", season.result.final_state == resumed.result.final_state and season.checkpoint.payload == resumed.checkpoint.payload)

    print("13. immutability")
    check("parameter registry, parameter sets, profiles and configuration unchanged", configuration_fingerprint(ROOT) == before)

    print("14. scientific status")
    status = season.deterministic_dict()["scientific_status"]
    print(f"     {json.dumps({key: status[key] for key in ('REAL_VERIFIED', 'CALIBRATION_PERFORMED', 'EXPERIMENTAL_VALIDATION_PERFORMED')})}")
    check("REAL_VERIFIED = 0, no calibration, no experimental validation", status == dict(SCIENTIFIC_STATUS) and status["REAL_VERIFIED"] == 0
          and status["CALIBRATION_PERFORMED"] is False and status["EXPERIMENTAL_VALIDATION_PERFORMED"] is False)

    print("15. structured errors")
    for document, code, path in (({"crop": "banana"}, ErrorCode.UNSUPPORTED_CROP, "crop"), ({"crop": "peach", "environment": "greenhouse"}, ErrorCode.UNSUPPORTED_ENVIRONMENT, "environment"),
                                 ({"crop": "tomato", "end_time": "2026-01-01T00:00:00+00:00"}, ErrorCode.INVALID_TIME_RANGE, "end_time"),
                                 ({"crop": "tomato", "scenario": "MONSOON"}, ErrorCode.INVALID_SCENARIO, "scenario")):
        try:
            canonicalize_request(document)
            observed = None
        except SimulationApiError as exc:
            observed = exc.errors[0]
            print(f"     {observed.code.value} at {observed.path}: {observed.message}")
        check(f"{code.value} reported at {path}", observed is not None and observed.code is code and observed.path == path)

    print("== qualification report (contract, determinism, checkpoint, cancellation, errors, results, audit, performance)")
    report = InteractiveSimulationApiSuite(ROOT, repeats=3, timer=time.perf_counter).build_report()
    payload = report.to_dict()
    for name, section in payload["software_result"].items():
        print(f"  {name:<20} {section['status']}")
    for row in payload["performance_measurement"]["rows"]:
        print(f"  perf {row['case']:<32} direct={row['direct_execution_seconds']:.3f} s api_sim={row['SIMULATION_TIME']:.3f} s "
              f"overhead={100 * row['API_OVERHEAD']['relative_to_direct']:.1f}% (+trajectory hash {100 * row['OPTIONAL_TRAJECTORY_HASH']['relative_to_direct']:.1f}%) "
              f"to_json={row['SERIALIZATION_TIME']['to_json_seconds']:.3f} s")
    check("qualification report PASS", payload["status"] == "PASS")
    check("repeated report build has the same deterministic hash", InteractiveSimulationApiSuite(ROOT, repeats=1).build_report(include_performance=False).deterministic_hash == payload["deterministic_hash"])
    check("no scientific evidence produced", payload["scientific_evidence"] == [])
    report_path, readme_path = write_report(report, ROOT / "data" / "simulation")
    print(f"artifact={report_path.relative_to(ROOT).as_posix()} readme={readme_path.relative_to(ROOT).as_posix()} deterministic_hash={payload['deterministic_hash']}")
    ok = all(passed for _, passed in checks)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
