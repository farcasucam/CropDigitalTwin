"""Explanation of a what-if of the web bench: every runtime event is a player, the branches are re-simulated from the SAME checkpoint, and the deterministic narrative (`tsxai.report.effects_narrative`) says what the
events did, how the effect divides and what the division hides. No language model; every number in the text is a number of the effects report, and the text is re-read by `check_narrative` before it is returned.

The document is the one of `/api/runtime/what-if` plus an optional `language` ("en" or "es"). The query it builds: players = the events (at most `MAX_EVENTS`, because the cost doubles with each: 2^n branch runs),
reference = the baseline branch, outcomes = those of `OUTCOMES` the run produces, policy = the run's own (the greenhouse controller, when there is one, acts in every branch; replaying its actuation is not offered here).
The smallest effect that matters per outcome is declared in `OUTCOMES` (a presentation convention, not agronomic knowledge); the models are reported as uncalibrated.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from tsxai.core import Intervention, RunResult, ScenarioDescriptor, content_hash
from tsxai.effects import EffectQuery, Outcome, Player, Policy, ResimulationEngine
from tsxai.report import Glossary, check_narrative, narrate_effects

from agri_twin.application.interactive_runtime import InteractiveRuntimeService, _fail, _parse
from agri_twin.application.interactive_simulation import ErrorCode, canonicalize_request
from agri_twin.application.runtime_events import RuntimeEvent

NAME = "agri-twin-whatif/1"
MAX_EVENTS = 4
LANGUAGES = ("en", "es")
# name, variable, aggregate, unit, smallest effect that matters, English and Spanish label
OUTCOMES = (
    ("biomass_total_end", "biomass_total_g_m2", "max", "g/m2", 1.0, "the final total biomass", "la biomasa total final"),
    ("temperature_mean", "temperature_c", "mean", "degC", 0.1, "the mean air temperature experienced by the crop", "la temperatura media del aire que percibe el cultivo"),
    ("water_stress_mean", "water_stress", "mean", "fraction", 0.01, "the mean water stress", "el estrés hídrico medio"),
    ("nutrient_status_mean", "nutrient_status", "mean", "fraction", 0.01, "the mean nutrient status", "el estado nutricional medio"),
)


class WhatIfHost:
    """A host whose factors are the events of one what-if (`E0`, `E1`, ...) and whose runs resume from the shared checkpoint."""

    name = NAME

    def __init__(self, runtime: InteractiveRuntimeService, resume: Mapping[str, Any], events: Sequence[RuntimeEvent]) -> None:
        self._runtime, self._resume, self._events = runtime, dict(resume), list(events)

    def run(self, scenario: ScenarioDescriptor, interventions: Sequence[Intervention] = ()) -> RunResult:
        chosen = sorted({int(item.factor[1:]) for item in interventions})
        request = self._resume | ({"runtime_events": [self._events[i].request_dict() for i in chosen]} if chosen else {})
        response = self._runtime._completed(self._runtime.service.run_simulation(request), "branch")
        trajectory = response.result.trajectory
        series = {name: list(values) for name, values in trajectory.items() if name != "time" and None not in values}
        return RunResult(series, list(trajectory["time"]), content_hash({"request": response.hashes["request_hash"], "trajectory": response.result.trajectory_hash, "events": chosen}))


def _event_label(event: RuntimeEvent, language: str) -> str:
    spec = event.spec
    what = event.event_type.lower().replace("_", " ")
    words = spec.unit.split()
    unit = (words[0] + ("/ha" if words[1:2] == ["ha-1"] else "")) if words else ""
    amount = f"{event.intensity:g} {unit}".strip() if spec.primary_parameter else ""
    start = event.start.strftime("%Y-%m-%d %H:%M")
    if language == "es":
        return f"{what} ({amount + ', ' if amount else ''}{event.duration_hours:g} h desde {start})"
    return f"{what} ({amount + ', ' if amount else ''}{event.duration_hours:g} h from {start})"


def explain_what_if(runtime: InteractiveRuntimeService, document: Any) -> dict[str, Any]:
    if not isinstance(document, Mapping):
        raise _fail(ErrorCode.INVALID_REQUEST, f"explain request must be a mapping, got {type(document).__name__}")
    language = document.get("language", "en")
    if language not in LANGUAGES:
        raise _fail(ErrorCode.INVALID_REQUEST, f"language must be one of {', '.join(LANGUAGES)}", "language")
    base, branch_point, events = runtime._document({key: value for key, value in document.items() if key != "language"})
    canonical = canonicalize_request(base)
    parsed = _parse(canonical, branch_point, events)
    if str((base.get("greenhouse") or {}).get("backend", "")).upper() == "ENERGYPLUS":
        raise _fail(ErrorCode.INVALID_REQUEST, "the explanation re-simulates every combination of events, which takes minutes per branch with EnergyPlus; use the simplified backend", "request")
    if len(parsed) > MAX_EVENTS:
        raise _fail(ErrorCode.INVALID_REQUEST, f"at most {MAX_EVENTS} events can be explained together (the cost doubles with each one)", "events")
    prefix = runtime._completed(runtime.service.run_simulation({**base, "end_time": branch_point.isoformat()}), "prefix")
    resume = {key: value for key, value in base.items() if key not in {"start_time", "end_time"}} | {"checkpoint": prefix.checkpoint.to_dict(), "end_time": canonical.end_time.isoformat()}  # type: ignore[union-attr]
    host = WhatIfHost(runtime, resume, parsed)
    reference = host.run(ScenarioDescriptor({}, 0, 0, 1))
    steps = len(reference.time)
    produced = [o for o in OUTCOMES if o[1] in reference.series]
    if not produced:
        raise _fail(ErrorCode.INVALID_REQUEST, "the run returns none of the outcome variables; request at least biomass_total_g_m2 in options.variables", "request")
    descriptor = ScenarioDescriptor({"crop": canonical.crop, "environment": canonical.environment}, int(canonical.seed or 0), 0, steps)
    players = tuple(Player(event.event_id, (Intervention(f"E{i}", 0, 1),)) for i, event in enumerate(parsed))
    outcomes = tuple(Outcome(name, variable, aggregate, unit) for name, variable, aggregate, unit, _, _, _ in produced)
    engine = ResimulationEngine(host)
    report = engine.evaluate(EffectQuery(descriptor, outcomes, players, policy=Policy("reactive")))
    report["simulator"] = NAME
    glossary = Glossary({event.event_id: {lang: _event_label(event, lang) for lang in LANGUAGES} for event in parsed},
                        {name: {"en": en, "es": es} for name, _, _, _, _, en, es in produced})
    material = {name: floor for name, _, _, _, floor, _, _ in produced}
    narrative = narrate_effects(report, language, glossary, outcomes=[o.name for o in outcomes], material=material)
    return {"kind": "WHAT_IF_EFFECT_EXPLANATION", "language": language, "text": narrative.text, "claims": [{"id": c.claim_id, "kind": c.kind, "text": c.text, "numbers": dict(c.numbers)} for c in narrative.claims],
            "problems": check_narrative(narrative, glossary, report), "narrative_hash": narrative.narrative_hash, "source_report_hash": narrative.source_report_hash, "query_hash": report["query_hash"],
            "players": [{"id": e.event_id, "label": _event_label(e, language)} for e in parsed], "branch_runs": engine.runs,
            "effects": {name: {"unit": o["unit"], "reference": o["reference"], "factual": o["factual"], "total_effect": o["total_effect"], "shapley": o["shapley"], "interaction_gap": o["interaction_gap"]} for name, o in report["outcomes"].items()},
            "statement": "Deterministic text from re-simulation of the branches of this what-if; no language model; effects are exact inside the simulator and not validated against a real system."}
