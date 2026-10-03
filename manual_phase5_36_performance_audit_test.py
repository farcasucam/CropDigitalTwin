"""Offline delivery verification for Phase 5.36: performance, latency and scalability audit.

Runs the canonical benchmark matrix, prints timing summaries and the dominant
bottlenecks, compares optimized and reference outputs, verifies deterministic replay
and the absence of parameter / TwinState mutation, writes the artifact and ends with
PASS or FAIL. Timings are measurements on this machine; no improvement is assumed:
before/after ratios are printed as measured, including workloads that did not change.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from agri_twin.application.performance_audit import PerformanceAuditSuite, write_report

ROOT = Path(__file__).resolve().parent
BASELINE = ROOT / "data" / "performance" / "performance_baseline_reference.json"


def main() -> int:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else None
    suite = PerformanceAuditSuite(ROOT, repeats=2)
    report = suite.build_report(baseline=baseline)
    payload = report.to_dict()
    perf, optimization = payload["performance_measurement"], payload["optimization_result"]

    print("== Benchmark matrix (simulation only; min of 2 sequential runs)")
    for row in perf["benchmark_matrix"]:
        m = row["performance_measurement"]
        print(f"  {row['workload']['workload_id']:<46} steps={row['steps_executed']:>6} {m['elapsed_seconds']:7.3f} s  {m['milliseconds_per_step']:6.3f} ms/step  {m['seconds_per_simulated_day']:.4f} s/day")
    answer = perf["cost_separation"]["answer"]
    print(f"== Twin simulation (tomato outdoor full season): {answer['twin_simulation_seconds']:.3f} s")
    print(f"== Validation/reporting infrastructure on the same campaign: {answer['validation_and_reporting_infrastructure_seconds']:.3f} s")
    for key, value in perf["cost_separation"]["seconds"].items():
        print(f"     {key:<40} {value:8.3f} s")
    print("== Dominant bottlenecks (>= 3 % of profiled workload)")
    for row in perf["bottlenecks"]:
        print(f"  [{row['workload']}] {row['percentage_of_workload']:5.1f}% {row['classification']:<18} {row['component']}:{row['function']} calls={row['call_count']}")
    print("== Scaling")
    for axis, value in perf["scaling"].items():
        if isinstance(value, dict) and "measured_scaling" in value:
            print(f"  {axis:<22} {value['measured_scaling']:<12} R^2={value['r_squared']:.4f} slope={value['slope_seconds_per_unit']:.4f} s/unit")
    grid = perf["scaling"]["time_x_plots_grid"]
    print(f"  time x plots grid: consistent_with_O(TxP)={grid['consistent_with_O_T_x_P']} cv={grid['seconds_per_plot_day_cv']:.3f}")
    print("== Frontend classification (advisory, simulation only)")
    for name, value in perf["frontend"]["cases"].items():
        print(f"  {name:<46} {value['seconds']:7.2f} s  {value['classification']}")
    print("== Optimizations (equivalence and measured effect)")
    for item in optimization["equivalence"]:
        print(f"  {item['optimization']}: {item['status']} byte_identical={item['rows_byte_identical']} seconds={json.dumps({k: round(v, 3) for k, v in item['seconds'].items() if v is not None})}")
    before_after = optimization["before_after"]
    if before_after is not None:
        ratios = [row["ratio_after_over_before"] for row in before_after["rows"]]
        print(f"  simulation matrix vs pre-optimization baseline: outputs identical={before_after['all_outputs_identical']}, after/before ratio median={sorted(ratios)[len(ratios) // 2]:.3f} (simulation code unchanged; ~1.0 expected)")
        for key, row in before_after["cost_separation"]["rows"].items():
            print(f"     {key:<40} before={row['seconds_before']:8.3f} s after={row['seconds_after']:8.3f} s ratio={row['ratio_after_over_before']:.3f}")

    replay = {row.workload.workload_id: (row.steps_executed, row.output_hash) for row in suite.run_matrix_outputs()}
    recorded = {row["workload"]["workload_id"]: (row["steps_executed"], row["output_hash"]) for row in perf["benchmark_matrix"]}
    checks = [
        ("benchmark matrix executed completely", len(perf["benchmark_matrix"]) == 23 and all(row["steps_executed"] == row["workload"]["simulation_steps"] for row in perf["benchmark_matrix"])),
        ("deterministic replay (in report and independent replay)", payload["software_result"]["determinism_checks"]["status"] == "PASS" and replay == recorded),
        ("optimized outputs identical to references", all(item["status"] == "PASS" for item in optimization["equivalence"]) and (before_after is None or before_after["all_outputs_identical"])),
        ("no parameter mutation", payload["software_result"]["mutation_checks"]["status"] == "PASS"),
        ("no TwinState mutation", payload["software_result"]["mutation_checks"]["before"]["initial_twin_state"] == payload["software_result"]["mutation_checks"]["after"]["initial_twin_state"]),
        ("no scientific evidence produced", payload["scientific_evidence"] == []),
    ]
    report_path, readme_path = write_report(report, ROOT / "data" / "performance")
    print(f"artifact={report_path.relative_to(ROOT).as_posix()} readme={readme_path.relative_to(ROOT).as_posix()} deterministic_hash={payload['deterministic_hash']}")
    for label, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'}: {label}")
    ok = payload["status"] == "PASS" and all(passed for _, passed in checks)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
