"""Phase 5.36 performance, latency and scalability audit.

No test asserts an absolute runtime: timings are machine dependent. Tests check
benchmark completeness, deterministic inputs/outputs, step counts, scaling and
profiling schemas, no mutation and the equivalence of every optimization.
"""

from __future__ import annotations

import ast
import json
import math
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from agri_twin.application.integrated_synthetic_validation import snapshot_numbers
from agri_twin.application.performance_audit import (
    BOTTLENECK_CLASSES,
    FRONTEND_BANDS,
    OPTIMIZATIONS,
    PerformanceAuditSuite,
    _hoisted_difference,
    _reference_restart_difference,
    band,
    campaign_scenario,
    classify,
    fit_linear,
    run_campaign,
    truncated,
    write_report,
)
from agri_twin.application.scenarios import ScenarioRunner
from agri_twin.application.seasonal_synthetic_campaign import KNOWN_CROPS, build_campaign, seasonal_weather_factory

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def suite():
    return PerformanceAuditSuite(ROOT, repeats=1, quick=True)


@pytest.fixture(scope="module")
def report(suite):
    return suite.build_report()


@pytest.fixture(scope="module")
def payload(report):
    return report.to_dict()


def _keys(value, found=None):
    found = set() if found is None else found
    if isinstance(value, dict):
        for key, item in value.items():
            found.add(key)
            _keys(item, found)
    elif isinstance(value, list):
        for item in value:
            _keys(item, found)
    return found


# --- matrix completeness and determinism of inputs -------------------------------------------


def test_full_benchmark_matrix_is_complete():
    ids = [workload.workload_id for workload, _ in PerformanceAuditSuite(ROOT, quick=False).benchmark_matrix()]
    assert "small_tomato_outdoor_7d" in ids and "medium_tomato_outdoor_full_season" in ids
    for scenario in ("hot_season", "cold_season", "dry_season", "humid_season", "heat_wave", "cold_wave", "heat_wave_with_dryness"):
        assert f"scenario_tomato_outdoor_{scenario}" in ids
    assert {f"crop_{crop}_outdoor_full_season" for crop in KNOWN_CROPS if crop != "tomato"} <= set(ids)
    assert {"greenhouse_tomato_full_season", "greenhouse_lettuce_full_season", "greenhouse_pepper_full_season"} <= set(ids)
    assert {"multi_plot_7_crops_outdoor", "multi_cycle_lettuce_outdoor_x3"} <= set(ids)
    assert sum(1 for item in ids if item.startswith("chilling_")) == 3 and len(ids) == len(set(ids))


def test_workload_descriptions_are_deterministic():
    first = [workload.to_dict() for workload, _ in PerformanceAuditSuite(ROOT, quick=False).benchmark_matrix()]
    second = [workload.to_dict() for workload, _ in PerformanceAuditSuite(ROOT, quick=False).benchmark_matrix()]
    assert first == second and all(len(item["model_configuration_hash"]) == 64 for item in first)


def test_full_season_workloads_use_the_unmodified_campaign():
    workloads = {workload.workload_id: workload for workload, _ in PerformanceAuditSuite(ROOT, quick=False).benchmark_matrix()}
    scenario = build_campaign("tomato", "outdoor", "BASE_SEASON", seed=532).scenario
    assert workloads["medium_tomato_outdoor_full_season"].model_configuration_hash == scenario.config_hash()
    assert workloads["medium_tomato_outdoor_full_season"].days == (scenario.end - scenario.start).days


def test_step_counts_match_workload_metadata(payload):
    for row in payload["performance_measurement"]["benchmark_matrix"]:
        assert row["steps_executed"] == row["workload"]["simulation_steps"] > 0


def test_benchmark_outputs_replay_identically(suite, payload):
    replay = {row.workload.workload_id: (row.steps_executed, row.output_hash) for row in suite.run_matrix_outputs()}
    recorded = {row["workload"]["workload_id"]: (row["steps_executed"], row["output_hash"]) for row in payload["performance_measurement"]["benchmark_matrix"]}
    assert replay == recorded and payload["software_result"]["determinism_checks"]["status"] == "PASS"


def test_truncated_scenario_clips_events_and_keeps_everything_else():
    scenario = build_campaign("tomato", "outdoor", "HEAT_WAVE", seed=532).scenario
    short = truncated(scenario, 10.0)
    assert short.end == scenario.start + timedelta(days=10) and all(event.end <= short.end for event in short.events)
    assert (short.initial_crop, short.initial_soil, short.seed, short.resolution_seconds) == (scenario.initial_crop, scenario.initial_soil, scenario.seed, scenario.resolution_seconds)
    assert run_campaign(short)[0] == 240 and truncated(scenario, 10_000.0) is scenario


# --- metrics, scaling, profiling schemas ---------------------------------------------------------------


def test_measurement_schema(payload):
    for row in payload["performance_measurement"]["benchmark_matrix"]:
        assert {"scenario", "crop", "environment", "days", "simulation_steps", "plots", "cycles", "model_configuration_hash"} <= set(row["workload"])
        assert {"elapsed_seconds", "seconds_per_simulated_day", "milliseconds_per_step", "min_seconds", "median_seconds", "repeats"} <= set(row["performance_measurement"])


def test_scaling_metadata(payload):
    scaling = payload["performance_measurement"]["scaling"]
    assert {"simulation_days", "number_of_plots", "number_of_crops", "number_of_scenarios", "number_of_cycles", "time_x_plots_grid", "theoretical_structure"} <= set(scaling)
    for axis in ("simulation_days", "number_of_plots", "number_of_crops", "number_of_scenarios", "number_of_cycles"):
        assert scaling[axis]["measured_scaling"] in {"LINEAR", "SUBLINEAR", "SUPERLINEAR", "INCONCLUSIVE"}
        steps = [row["steps"] for row in scaling[axis]["rows"]]
        assert steps == sorted(steps) and steps[0] > 0


@pytest.mark.parametrize("sizes,seconds,expected", [
    ([1, 2, 4, 8], [1.0, 2.0, 4.0, 8.0], "LINEAR"),
    ([1, 2, 4, 8], [1.0, 4.0, 16.0, 64.0], "SUPERLINEAR"),
    ([1, 2, 4, 8], [1.0, 1.0, 1.0, 1.0], "SUBLINEAR"),
])
def test_scaling_classifier(sizes, seconds, expected):
    assert fit_linear(sizes, seconds)["measured_scaling"] == expected


def test_profiling_schema(payload):
    profiling = payload["performance_measurement"]["profiling_summary"]
    for key in ("simulation", "validation"):
        section = profiling[key]
        assert section["total_calls"] > 0 and section["top_by_tottime"] and section["top_by_cumtime"]
        for item in section["top_by_tottime"]:
            assert {"function", "calls", "tottime_seconds", "cumtime_seconds", "seconds_per_call", "percentage_of_workload", "classification"} <= set(item)
            assert item["classification"] in BOTTLENECK_CLASSES
        assert abs(sum(value["percentage"] for value in section["time_by_classification"].values()) - 100.0) < 1e-6
        assert section["deterministic_call_counts"]


def test_profiler_call_counts_are_deterministic(suite, payload):
    again = suite.profiling()
    assert again["simulation"]["deterministic_call_counts"] == payload["performance_measurement"]["profiling_summary"]["simulation"]["deterministic_call_counts"]


@pytest.mark.parametrize("module,name,expected", [
    ("dataclasses.py", "_replace", "STATE_MANAGEMENT"),
    ("agri_twin/domain/models.py", "__post_init__", "VALIDATION"),
    ("~", "<built-in method math.exp>", "MODEL_COMPUTATION"),
    ("~", "<built-in method builtins.getattr>", "PYTHON_OVERHEAD"),
    ("agri_twin/application/integrated_synthetic_validation.py", "_numeric_fields", "DIAGNOSTICS"),
    ("agri_twin/domain/greenhouse.py", "advance", "MODEL_COMPUTATION"),
    ("agri_twin/application/twin_state.py", "save_snapshot", "PERSISTENCE"),
    ("json/encoder.py", "encode", "SERIALIZATION"),
])
def test_bottleneck_classification_rules(module, name, expected):
    assert classify(module, name) == expected


def test_bottlenecks_are_classified_and_documented(payload):
    for row in payload["performance_measurement"]["bottlenecks"]:
        assert row["classification"] in BOTTLENECK_CLASSES and row["percentage_of_workload"] >= 3.0
        assert {"component", "function", "total_time_seconds", "call_count", "time_per_call_seconds"} <= set(row)


def test_simulation_cost_is_separated_from_validation(payload):
    separation = payload["performance_measurement"]["cost_separation"]
    assert set(separation["answer"]) == {"twin_simulation_seconds", "validation_and_reporting_infrastructure_seconds"}
    assert separation["workload"]["steps"] == 168


def test_frontend_classification_schema(payload):
    names = {name for name, _ in FRONTEND_BANDS}
    for value in payload["performance_measurement"]["frontend"]["cases"].values():
        assert value["classification"] in names and value["classification"] == band(value["seconds"])
    assert band(0.5) == "INTERACTIVE" and band(5.0) == "INTERACTIVE_WITH_PROGRESS" and band(60.0) == "BACKGROUND_TASK" and band(500.0) == "BATCH_ONLY"


# --- optimizations ----------------------------------------------------------------------------------------


def test_every_optimization_is_equivalent(payload):
    equivalence = payload["optimization_result"]["equivalence"]
    assert {item["optimization"] for item in equivalence} == {"O1_RESTART_SNAPSHOT_FLATTENING", "O2_POLICY_MATRIX_WEATHER_REPLAY"}
    assert all(item["status"] == "PASS" and item["rows_byte_identical"] for item in equivalence)
    assert {item["id"] for item in OPTIMIZATIONS} == {"O1_RESTART_SNAPSHOT_FLATTENING", "O2_POLICY_MATRIX_WEATHER_REPLAY", "O3_READINESS_TEST_SHARED_EVALUATION"}
    assert all(item["scientific_risk"].startswith("NONE") for item in OPTIMIZATIONS)


def test_o1_hoisted_difference_equals_reference_on_non_zero_differences():
    runner = ScenarioRunner(seasonal_weather_factory)
    base = runner.run(campaign_scenario("tomato", "outdoor", "BASE_SEASON", 2.0)).snapshots
    hot = runner.run(campaign_scenario("tomato", "outdoor", "HOT_SEASON", 2.0)).snapshots
    reference = _reference_restart_difference(hot, base)
    hoisted = max(_hoisted_difference(a, b) for a, b in zip(hot, base))
    assert reference == hoisted > 0.0
    pairwise = [max(abs(v - snapshot_numbers(b)[k]) for k, v in snapshot_numbers(a).items()) for a, b in zip(hot, base)]
    assert pairwise == [_hoisted_difference(a, b) for a, b in zip(hot, base)]


def test_optimizations_do_not_change_simulation_outputs(payload):
    baseline = json.loads((ROOT / "data" / "performance" / "performance_baseline_reference.json").read_text(encoding="utf-8"))
    reference = {row["workload"]["workload_id"]: row["output_hash"] for row in baseline["performance_measurement"]["benchmark_matrix"]}
    full = PerformanceAuditSuite(ROOT, repeats=1, quick=False)
    for workload_id in ("small_tomato_outdoor_7d", "greenhouse_lettuce_full_season"):
        function = next(function for workload, function in full.benchmark_matrix() if workload.workload_id == workload_id)
        assert function()[1] == reference[workload_id]


# --- integrity, schema, audit -------------------------------------------------------------------------------


def test_no_parameter_or_twin_state_mutation(payload):
    mutation = payload["software_result"]["mutation_checks"]
    assert mutation["status"] == "PASS" and mutation["before"] == mutation["after"]
    assert {"parameter_registry", "parameter_sets", "phenology_profiles", "initial_twin_state"} <= set(mutation["before"])


def test_report_schema_and_separation(payload):
    assert {"software_result", "performance_measurement", "optimization_result", "scientific_evidence", "deterministic_hash", "limitations",
            "duplicated_work_audit", "open_performance_architecture"} <= set(payload)
    assert payload["scientific_evidence"] == [] and payload["status"] == "PASS"
    assert {"baseline", "environment", "benchmark_matrix", "profiling_summary", "bottlenecks", "scaling", "frontend"} <= set(payload["performance_measurement"])
    for flag in ("real_agricultural_data_verified", "calibration_performed", "experimental_validation_performed", "biological_validity_claimed", "field_accuracy_claimed", "data_assimilation_implemented"):
        assert payload[flag] is False


def test_timings_never_enter_the_deterministic_hash(report):
    view = report.deterministic_view()
    counts = view.pop("profiling_call_counts")  # keys are function identifiers, values integer call counts
    assert all(isinstance(value, int) for section in counts.values() for value in section.values())
    keys = _keys(view)
    assert not any("seconds" in key or "elapsed" in key or key in {"durations", "speedup"} for key in keys)


def test_written_artifact_round_trips(report, tmp_path):
    report_path, readme_path = write_report(report, tmp_path)
    assert json.loads(report_path.read_text(encoding="utf-8"))["deterministic_hash"] == report.to_dict()["deterministic_hash"]
    assert "Twin simulation vs validation/reporting" in readme_path.read_text(encoding="utf-8")


def test_timing_instrumentation_stays_out_of_the_model():
    source_root = ROOT / "src" / "agri_twin"
    allowed = {"application/performance_audit.py", "application/sensitivity.py", "application/integrated_synthetic_validation.py", "application/seasonal_synthetic_campaign.py"}
    offenders = []
    for path in sorted(source_root.rglob("*.py")):
        relative = path.relative_to(source_root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        uses = any(isinstance(node, ast.Attribute) and node.attr in {"perf_counter", "process_time"} for node in ast.walk(tree)) \
            or any(isinstance(node, (ast.Import, ast.ImportFrom)) and any(alias.name in {"cProfile", "profile", "pstats"} for alias in node.names) for node in ast.walk(tree))
        if uses and relative not in allowed:
            offenders.append(relative)
    assert offenders == []
    importers = [path.relative_to(source_root).as_posix() for path in source_root.rglob("*.py") if "performance_audit" in path.read_text(encoding="utf-8") and path.name not in {"performance_audit.py", "__init__.py"}]
    assert importers == []


def test_performance_module_has_no_global_mutable_cache_or_concurrency():
    tree = ast.parse((ROOT / "src" / "agri_twin" / "application" / "performance_audit.py").read_text(encoding="utf-8"))
    imports = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names} | \
              {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert not imports & {"threading", "multiprocessing", "concurrent", "asyncio", "random", "requests", "urllib", "socket", "functools"}
    module_level = [node for node in tree.body if isinstance(node, ast.Assign) and not any(getattr(target, "id", "") == "__all__" for target in node.targets)]
    assert all(not isinstance(node.value, (ast.Dict, ast.List, ast.Set)) for node in module_level)
