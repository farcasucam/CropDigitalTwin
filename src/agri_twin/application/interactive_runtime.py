"""Interactive runtime layer: event preview, what-if branching and branch comparison (Phase 5.39).

    frontend -> InteractiveRuntimeService -> InteractiveSimulationService (5.37)
             -> ScenarioRunner / orchestrator (existing engines)

The workflow is checkpoint based and never recomputes the season from the start:

    run to the branch point -> checkpoint -> validate runtime events
    -> resume the BASELINE branch (no events) and the INTERVENTION branch (events)
       from the same checkpoint -> compare the backend trajectories.

Runtime events are user-defined synthetic forcing, attached to simulation time and
accepted only at or after the checkpoint, so the simulated history is never modified.
This module adds no equation, engine, clock, scheduler, registry or weather generator:
the comparison only reports differences between values the backend already returned.
It reads no clock; operational timings exist only when the wrapped service has an
injected timer, and they never enter a hash.
"""

from __future__ import annotations

import ast
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from agri_twin.application.interactive_simulation import (
    SCIENTIFIC_STATUS,
    VARIABLE_INDEX,
    ErrorCode,
    ExecutionStatus,
    InteractiveSimulationService,
    SimulationResponse,
    API_FORBIDDEN_CALL_PREFIXES,
    API_FORBIDDEN_CALLS,
    API_FORBIDDEN_IMPORTS,
    CORE_CLASS_SUFFIXES,
    _dotted_name,
    _fail,
    _hash,
    _instant,
    canonicalize_request,
    variable_availability,
)
from agri_twin.application.integrated_synthetic_validation import static_audit
from agri_twin.application.runtime_events import (
    FORCING_CLASSIFICATION,
    PROVENANCE_CLASSES,
    SOURCE_USER_EVENT,
    RuntimeEventError,
    event_contract,
    event_sequence_hash,
    parse_runtime_events,
)
from agri_twin.application.seasonal_synthetic_campaign import build_campaign, campaign_cycle

VERSION = "5.39.0"
WHAT_IF_FIELDS = ("request", "checkpoint_time", "events")
CONSEQUENCE_NOTE = "NOT_PREDICTED: consequences exist only in the backend branch simulation; the interface never calculates them"


def _plain_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class InteractiveRuntimeService:
    """Event preview and what-if branching over the canonical interactive simulation service."""

    def __init__(self, service: InteractiveSimulationService | None = None) -> None:
        self.service = service or InteractiveSimulationService()

    @staticmethod
    def contract() -> dict[str, Any]:
        return event_contract()

    # -- document handling --------------------------------------------------------------

    @staticmethod
    def _document(document: Any) -> tuple[dict[str, Any], datetime, Any]:
        if not isinstance(document, Mapping):
            raise _fail(ErrorCode.INVALID_REQUEST, f"what-if request must be a mapping, got {type(document).__name__}")
        unknown = sorted(set(document) - set(WHAT_IF_FIELDS))
        if unknown:
            raise _fail(ErrorCode.INVALID_REQUEST, f"unknown fields: {', '.join(unknown)}; allowed: {', '.join(WHAT_IF_FIELDS)}", unknown[0])
        base = document.get("request")
        if not isinstance(base, Mapping):
            raise _fail(ErrorCode.INVALID_REQUEST, "request must be a simulation request mapping", "request")
        if base.get("checkpoint") is not None or base.get("runtime_events"):
            raise _fail(ErrorCode.INVALID_REQUEST, "the base request of a what-if must have neither a checkpoint nor runtime events: the branch point is created by the service", "request")
        canonical = canonicalize_request(base)
        if "checkpoint_time" not in document:
            raise _fail(ErrorCode.INVALID_REQUEST, "checkpoint_time is required (the simulation time at which the branch is created)", "checkpoint_time")
        branch_point = _instant(document["checkpoint_time"], "checkpoint_time")
        if not canonical.start_time < branch_point < canonical.end_time:
            raise _fail(ErrorCode.INVALID_TIME_RANGE, f"checkpoint_time {branch_point.isoformat()} must lie strictly inside the run ({canonical.start_time.isoformat()}, {canonical.end_time.isoformat()})", "checkpoint_time")
        if (branch_point - canonical.start_time).total_seconds() % 3600:
            raise _fail(ErrorCode.INVALID_TIME_RANGE, "checkpoint_time must lie on a whole simulation step (1 h)", "checkpoint_time")
        return dict(base), branch_point, document.get("events")

    # -- preview ------------------------------------------------------------------------

    def preview_events(self, document: Any) -> dict[str, Any]:
        """Validate an event sequence for a branch point and describe it; nothing is simulated."""
        base, branch_point, events = self._document(document)
        canonical = canonicalize_request(base)
        parsed = _parse(canonical, branch_point, events)
        rows = []
        for event in parsed:
            spec = event.spec
            affected = []
            for name in spec.affected_variables:
                availability = variable_availability(VARIABLE_INDEX[name], canonical.crop, canonical.environment, canonical.backend)
                affected.append({"variable": name, "unit": VARIABLE_INDEX[name].unit, "availability": availability.value})
            rows.append({**event.to_dict(), "supported": True, "support": "SUPPORTED", "provenance": SOURCE_USER_EVENT, "classification": FORCING_CLASSIFICATION,
                         "scenario_event_type": spec.scenario_type, "intensity_parameter": spec.primary_parameter, "intensity_unit": spec.unit,
                         "affected_variables": affected, "requires_checkpoint": True, "creates_new_branch": True, "consequences": CONSEQUENCE_NOTE})
        return {"kind": "EVENT_PREVIEW", "version": VERSION, "valid": True, "branch_point": branch_point.isoformat(), "events": rows,
                "event_sequence_hash": event_sequence_hash(parsed), "provenance": SOURCE_USER_EVENT, "classification": FORCING_CLASSIFICATION,
                "affects_only_future": True, "history_modified": False, "consequences": CONSEQUENCE_NOTE, "scientific_status": dict(SCIENTIFIC_STATUS)}

    # -- what-if ------------------------------------------------------------------------

    def what_if(self, document: Any) -> dict[str, Any]:
        """Run prefix -> checkpoint -> baseline and intervention branches resumed from it."""
        base, branch_point, events = self._document(document)
        canonical = canonicalize_request(base)
        parsed = _parse(canonical, branch_point, events)
        end_time = canonical.end_time.isoformat()
        prefix = self._completed(self.service.run_simulation({**base, "end_time": branch_point.isoformat()}), "prefix")
        checkpoint = prefix.checkpoint.to_dict()  # type: ignore[union-attr]
        resume = {key: value for key, value in base.items() if key not in {"start_time", "end_time"}} | {"checkpoint": checkpoint, "end_time": end_time}
        baseline = self._completed(self.service.run_simulation(resume), "baseline")
        intervention = self._completed(self.service.run_simulation(resume | {"runtime_events": [event.request_dict() for event in parsed]}), "intervention")
        comparison = compare_branches(baseline, intervention, first_event_start=min((event.start for event in parsed), default=None), branch_point=branch_point)
        sequence_hash = event_sequence_hash(parsed)
        empty_hash = event_sequence_hash(())
        branches = {
            "baseline": _branch("baseline", baseline, prefix, empty_hash),
            "intervention": _branch("intervention", intervention, prefix, sequence_hash),
        }
        deterministic = {
            "kind": "WHAT_IF_BRANCHING", "version": VERSION, "provenance_classes": list(PROVENANCE_CLASSES),
            "branch_point": {"simulation_time": branch_point.isoformat(), "checkpoint_sha256": checkpoint["sha256"], "resume_hash": checkpoint["resume_hash"],
                             "steps_completed": prefix.progress.completed_steps, "prefix_trajectory_hash": prefix.hashes["trajectory_hash"]},
            "events": [event.to_dict() | {"provenance": SOURCE_USER_EVENT, "classification": FORCING_CLASSIFICATION} for event in parsed],
            "comparison": comparison,
            "hashes": {"prefix_trajectory_hash": prefix.hashes["trajectory_hash"], "checkpoint_sha256": checkpoint["sha256"], "event_sequence_hash": sequence_hash,
                       "baseline_trajectory_hash": baseline.hashes["trajectory_hash"], "baseline_configuration_hash": baseline.hashes["configuration_hash"],
                       "baseline_event_sequence_hash": empty_hash,
                       "intervention_trajectory_hash": intervention.hashes["trajectory_hash"], "intervention_configuration_hash": intervention.hashes["configuration_hash"]},
            "scientific_status": dict(SCIENTIFIC_STATUS),
            "statement": "Baseline and intervention are independent branches of the same checkpoint; the intervention uses USER-DEFINED SYNTHETIC FORCING, never observed data.",
        }
        deterministic["what_if_hash"] = _hash(deterministic)
        return {**deterministic, "prefix": prefix.to_dict(), "branches": {name: {"provenance": branch["provenance"], "response": branch["response"]} for name, branch in branches.items()},
                "operational": {"timings_seconds": {name: dict(response.operational.get("timings_seconds", {})) for name, response in
                                                      (("prefix", prefix), ("baseline", baseline), ("intervention", intervention))},
                                "note": "PERFORMANCE_MEASUREMENT, machine-dependent, excluded from every hash"}}

    @staticmethod
    def _completed(response: SimulationResponse, role: str) -> SimulationResponse:
        if response.execution_status is not ExecutionStatus.COMPLETED or response.checkpoint is None:
            detail = "; ".join(error.message for error in response.errors) or response.execution_status.value
            raise _fail(ErrorCode.INTERNAL_EXECUTION_ERROR, f"what-if {role} segment did not complete: {detail}", role)
        return response


def _parse(canonical, branch_point: datetime, events: Any):
    if not isinstance(events, (list, tuple)) or not events:
        raise _fail(ErrorCode.INVALID_REQUEST, "events must be a non-empty list for a what-if intervention", "events")
    _, _, campaign_end = campaign_cycle(canonical.crop)
    base_ids = [event.event_id for event in build_campaign(canonical.crop, canonical.environment, canonical.scenario, seed=canonical.seed).scenario.events]
    try:
        return parse_runtime_events(events, environment=canonical.environment, earliest=branch_point, latest=campaign_end, reserved_ids=base_ids)
    except RuntimeEventError as exc:
        raise _fail(ErrorCode(exc.kind), exc.message, exc.path.replace("runtime_events", "events", 1)) from None


def _branch(name: str, response: SimulationResponse, prefix: SimulationResponse, sequence_hash: str) -> dict[str, Any]:
    return {"provenance": {"branch_id": name, "parent_checkpoint_sha256": prefix.checkpoint.sha256, "parent_simulation_time": prefix.checkpoint.simulation_time.isoformat(),  # type: ignore[union-attr]
                           "event_sequence_hash": sequence_hash, "request_hash": response.hashes["request_hash"], "configuration_hash": response.hashes["configuration_hash"],
                           "trajectory_hash": response.hashes["trajectory_hash"], "result_hash": response.hashes["result_hash"],
                           "forcing": "BASE_SCENARIO + SYNTHETIC_FORCING" if name == "baseline" else f"BASE_SCENARIO + SYNTHETIC_FORCING + {SOURCE_USER_EVENT}"},
            "response": response.to_dict()}


def compare_branches(baseline: SimulationResponse, intervention: SimulationResponse, *, first_event_start: datetime | None, branch_point: datetime) -> dict[str, Any]:
    """Report differences between two backend trajectories (no model calculation, no derived science)."""
    base, other = baseline.result.trajectory, intervention.result.trajectory  # type: ignore[union-attr]
    if base is None or other is None or base["time"] != other["time"]:
        raise _fail(ErrorCode.INTERNAL_EXECUTION_ERROR, "branches do not share a time axis; they cannot be compared")
    times = base["time"]
    rows: dict[str, Any] = {}
    changed_before_event = False
    for name, values in base.items():
        if name == "time" or name not in other:
            continue
        mine, theirs = values, other[name]
        first = next((index for index, (a, b) in enumerate(zip(mine, theirs)) if a != b), None)
        numeric = all(_plain_number(v) for v in mine) and all(_plain_number(v) for v in theirs)
        row: dict[str, Any] = {"final_baseline": mine[-1], "final_intervention": theirs[-1], "identical": first is None,
                               "first_difference_time": times[first] if first is not None else None}
        if numeric:
            row["delta_final"] = theirs[-1] - mine[-1]
            row["max_abs_delta"] = max(abs(a - b) for a, b in zip(mine, theirs))
            if not math.isfinite(row["delta_final"]):
                row["delta_final"] = None
        rows[name] = row
        if first is not None and first_event_start is not None and datetime.fromisoformat(times[first]) < first_event_start:
            changed_before_event = True
    differing = sorted(name for name, row in rows.items() if not row["identical"])
    return {"kind": "BACKEND_VALUE_COMPARISON", "note": "differences between values returned by the backend; no metric is derived here", "branch_point": branch_point.isoformat(),
            "first_event_start": first_event_start.isoformat() if first_event_start is not None else None, "steps": len(times),
            "unchanged_before_first_event": not changed_before_event, "variables_changed": differing, "variables": rows}


# ---------------------------------------------------------------------------
# Static audit and report
# ---------------------------------------------------------------------------

RUNTIME_AUDITED_PYTHON = ("src/agri_twin/application/runtime_events.py", "src/agri_twin/application/interactive_runtime.py", "src/agri_twin/application/runtime_replay.py")
RUNTIME_AUDITED_JS = ("frontend/runtime.js", "frontend/visual_state.js", "frontend/visual.js", "frontend/scene_state.js", "frontend/iso_scene.js", "frontend/bench.js")
VENDORED_LIBRARIES = ("frontend/vendor/uPlot.iife.min.js", "frontend/vendor/uPlot.min.css", "frontend/vendor/uPlot.LICENSE",
                      "frontend/vendor/isokit.iife.js", "frontend/vendor/isokit.css", "frontend/vendor/isokit.LICENSE")
REMOTE_ASSET = r"(<script[^>]+src|<link[^>]+href|@import\s+url\()\s*=?\s*[\x22\x27]?\s*(https?:)?//"
JS_FORBIDDEN = (
    (r"\bMath\.(exp|log|log10|log2|pow|sqrt|cbrt|tanh)\b|\*\*", "scientific_formula_in_javascript"),
    (r"\b(GDD|Tbase|growth_?rate|photosynthes\w*|evapotranspiration|chilling_?units?)\b", "model_term_in_javascript"),
    (r"\bDate\.now\s*\(|new Date\s*\(\s*\)", "wall_clock_in_javascript"),
    (r"\bimport\s|\brequire\s*\(|three(\.min)?\.js|THREE\.", "external_library_in_javascript"),
    (r"\bWebSocket\b|\bEventSource\b|\bXMLHttpRequest\b", "second_transport_in_javascript"),
    (r"\bnew\s+Worker\b|\bMath\.random\b", "scheduler_or_nondeterminism_in_javascript"),
    (r"fetch\s*\(\s*[\x22\x27`]https?:", "remote_network_in_javascript"),
)


def static_audit_runtime(root: str | Path) -> dict[str, Any]:
    """AST audit of the runtime modules plus a pattern audit of the runtime frontend script."""
    import re

    root = Path(root)
    violations: list[dict[str, Any]] = []
    for name in RUNTIME_AUDITED_PYTHON:
        path = root / name
        if not path.exists():
            violations.append({"file": name, "line": 0, "rule": "missing_file", "detail": name})
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                called = _dotted_name(node.func)
                if called in API_FORBIDDEN_CALLS or called.startswith(API_FORBIDDEN_CALL_PREFIXES):
                    violations.append({"file": name, "line": node.lineno, "rule": "wall_clock_sleep_or_global_random", "detail": called})
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                for module in modules:
                    if module.split(".")[0] in API_FORBIDDEN_IMPORTS:
                        violations.append({"file": name, "line": node.lineno, "rule": "forbidden_import", "detail": module})
            elif isinstance(node, ast.ClassDef) and node.name.endswith(CORE_CLASS_SUFFIXES + ("Provider", "Weather", "Phenology")):
                violations.append({"file": name, "line": node.lineno, "rule": "second_core_component", "detail": node.name})
    for name in RUNTIME_AUDITED_JS:
        path = root / name
        if not path.exists():
            violations.append({"file": name, "line": 0, "rule": "missing_file", "detail": name})
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            code = line.split("//", 1)[0]
            code = re.sub(r'"(?:[^"\\]|\\.)*"|`(?:[^`\\]|\\.)*`', '""', code)
            for pattern, rule in JS_FORBIDDEN:
                if re.search(pattern, code):
                    violations.append({"file": name, "line": number, "rule": rule, "detail": line.strip()[:80]})
    for name in ("frontend/index.html", "frontend/styles.css"):
        path = root / name
        if path.exists() and re.search(REMOTE_ASSET, path.read_text(encoding="utf-8"), re.IGNORECASE):
            violations.append({"file": name, "line": 0, "rule": "remote_dependency_in_frontend", "detail": "a script, stylesheet or import loads a remote asset"})
    for name in VENDORED_LIBRARIES:
        if not (root / name).is_file():
            violations.append({"file": name, "line": 0, "rule": "missing_vendored_library", "detail": name})
    has_project = (root / "src/agri_twin/application/integrated_synthetic_validation.py").exists()
    project = static_audit(root) if has_project else {"status": "NOT_RUN"}
    passed = not violations and project["status"] in {"PASS", "NOT_RUN"}
    return {"status": "PASS" if passed else "FAIL", "python_files": list(RUNTIME_AUDITED_PYTHON), "javascript_files": list(RUNTIME_AUDITED_JS),
            "violations": violations, "project_static_audit_status": project["status"],
            "renderer": "SVG isometric (no Three.js) drawn with the vendored isokit (MIT, local file); charts: vendored uPlot 1.6.32 (MIT, local file, presentation only)", "vendored_libraries": list(VENDORED_LIBRARIES),
            "rules": {"javascript": [rule for _, rule in JS_FORBIDDEN]}}
