"""Reproducible runtime sessions: RECORD and REPLAY (Phase 5.40).

A session stores what is needed to reproduce a what-if exactly (configuration, seed, event
sequence, checkpoint digests and result hashes), never screenshots or rendered frames.
REPLAY re-executes the same document through the existing ``InteractiveRuntimeService`` and
verifies events, checkpoint, trajectory hashes and final state. No new engine, clock or
scheduler exists here: a replay is the canonical what-if executed again.
"""

from __future__ import annotations

from typing import Any, Mapping

from agri_twin.application.interactive_runtime import InteractiveRuntimeService
from agri_twin.application.interactive_simulation import (
    SCIENTIFIC_STATUS,
    ErrorCode,
    _fail,
    _hash,
    canonicalize_request,
)

VERSION = "5.40.0"
SESSION_KIND = "RUNTIME_SESSION_RECORD"
SESSION_FIELDS = ("kind", "version", "document", "configuration", "seed", "event_sequence", "event_sequence_hash", "checkpoints", "hashes", "final_state",
                  "scientific_status", "session_hash")


def _norm(value: Any) -> Any:
    # JSON round trips through JavaScript turn 20.0 into 20; hash a form that is stable under that.
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, Mapping):
        return {key: _norm(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_norm(item) for item in value]
    return value


def _session_hash(body: Any) -> str:
    return _hash(_norm(body))


def _session_body(document: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    intervention = result["branches"]["intervention"]
    final_state = intervention["response"]["result"]["final_state"]
    point = result["branch_point"]
    return {
        "kind": SESSION_KIND,
        "version": VERSION,
        "document": {"request": dict(document["request"]), "checkpoint_time": document["checkpoint_time"], "events": [dict(item) for item in document["events"]]},
        "configuration": {"baseline_configuration_hash": result["hashes"]["baseline_configuration_hash"],
                          "intervention_configuration_hash": result["hashes"]["intervention_configuration_hash"]},
        "seed": canonicalize_request(document["request"]).seed,
        "event_sequence": [{key: event[key] for key in ("event_id", "event_type", "start_simulation_time", "end_simulation_time", "duration_hours") if key in event}
                           for event in result["events"]],
        "event_sequence_hash": result["hashes"]["event_sequence_hash"],
        "checkpoints": [{"role": "branch_point", "simulation_time": point["simulation_time"], "sha256": point["checkpoint_sha256"],
                         "resume_hash": point["resume_hash"], "steps_completed": point["steps_completed"]}],
        "hashes": {"prefix_trajectory_hash": result["hashes"]["prefix_trajectory_hash"], "baseline_trajectory_hash": result["hashes"]["baseline_trajectory_hash"],
                   "intervention_trajectory_hash": result["hashes"]["intervention_trajectory_hash"], "what_if_hash": result["what_if_hash"]},
        "final_state": {"simulation_time": intervention["response"]["result"]["end"], "intervention_final_state_hash": _hash(final_state)},
        "scientific_status": dict(SCIENTIFIC_STATUS),
    }


class RuntimeReplayService:
    """RECORD a what-if as a reproducible session and REPLAY it with verification."""

    def __init__(self, runtime: InteractiveRuntimeService | None = None) -> None:
        self.runtime = runtime or InteractiveRuntimeService()

    def record(self, document: Any) -> dict[str, Any]:
        result = self.runtime.what_if(document)
        body = _session_body(document, result)
        session = {**body, "session_hash": _session_hash(body)}
        return {"session": session, "result": result}

    def replay(self, session: Any) -> dict[str, Any]:
        recorded = self._validate(session)
        result = self.runtime.what_if(recorded["document"])
        fresh = _session_body(recorded["document"], result)
        checks = {
            "events_reproduced": fresh["event_sequence"] == recorded["event_sequence"] and fresh["event_sequence_hash"] == recorded["event_sequence_hash"],
            "configuration_reproduced": fresh["configuration"] == recorded["configuration"] and fresh["seed"] == recorded["seed"],
            "checkpoints_reproduced": fresh["checkpoints"] == recorded["checkpoints"],
            "trajectory_hashes_reproduced": fresh["hashes"] == recorded["hashes"],
            "final_state_reproduced": fresh["final_state"] == recorded["final_state"],
        }
        return {"kind": "RUNTIME_SESSION_REPLAY", "version": VERSION, "status": "MATCH" if all(checks.values()) else "MISMATCH", "checks": checks,
                "session_hash": recorded["session_hash"], "recomputed_hashes": fresh["hashes"], "scientific_status": dict(SCIENTIFIC_STATUS), "result": result}

    @staticmethod
    def _validate(session: Any) -> dict[str, Any]:
        if not isinstance(session, Mapping):
            raise _fail(ErrorCode.INVALID_REQUEST, f"session must be a mapping, got {type(session).__name__}", "session")
        unknown = sorted(set(session) - set(SESSION_FIELDS))
        missing = [name for name in SESSION_FIELDS if name not in session]
        if unknown or missing:
            raise _fail(ErrorCode.INVALID_REQUEST, f"session fields mismatch (unknown: {', '.join(unknown) or 'none'}; missing: {', '.join(missing) or 'none'})", unknown[0] if unknown else missing[0])
        if session["kind"] != SESSION_KIND or session["version"] != VERSION:
            raise _fail(ErrorCode.INVALID_REQUEST, f"unsupported session kind/version {session['kind']}/{session['version']}; expected {SESSION_KIND}/{VERSION}", "kind")
        body = {key: value for key, value in session.items() if key != "session_hash"}
        if _session_hash(body) != session["session_hash"]:
            raise _fail(ErrorCode.INVALID_REQUEST, "session_hash does not match the session content: the record was modified", "session_hash")
        return dict(session)
