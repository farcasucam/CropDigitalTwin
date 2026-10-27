"""Recording and replaying the climate controller's commands, for the effects engine of ``tsxai``.

An effect "with reactive policy" lets the controller answer the perturbation; an effect "with replayed actuation" imposes the commands the controller issued in another run (by default the run without the
perturbation), step by step, so the controller no longer reacts. These two contrasts are different quantities and their difference is reported as such; it is not called a direct or an indirect effect.

What is replayed is the **command trajectory**: the fractions of equipment capacity the rule-based controller emits before any manual override (shade, vents, extractors, cooling, heating, irrigation). What stays
live while replaying: manual events still override the controller for their actuators (a perturbation that is itself an actuation, such as a ventilation event, still acts), the equipment translates fractions
into physical commands with its own capacities, and every protection of the physical model remains in force. A saturated actuator therefore saturates under replay too; the report of the run says so only through
its outputs, not through a flag.

The controller is stateless (it maps the observation of a step to commands; the state it reads, such as the previous HVAC power, lives in the twin), so replaying its decisions needs no hidden state. Decision ``n`` is
made at the start of step ``n`` and acts on trajectory sample ``n``.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Mapping, Sequence

from agri_twin.domain.climate_control import ControlDecision, ControlObservation

TRACE_FIELDS = ("shade", "vents", "extractors", "cooling", "heating", "irrigation_mm", "irrigation_target_vwc")
NO_TARGET = -1.0  # a refill-to-target irrigation has a target moisture in [0, 1]; the trace stores "no target" as this sentinel


class RecordingController:
    """Wraps a controller and keeps every decision it emits, in step order."""

    name = "recording"

    def __init__(self, inner) -> None:
        self.inner = inner
        self.decisions: list[ControlDecision] = []

    def decide(self, observation: ControlObservation) -> ControlDecision:
        decision = self.inner.decide(observation)
        self.decisions.append(decision)
        return decision


class ReplayController:
    """Wraps a controller; from step ``first_step`` for ``len(trace)`` steps the fields present in ``trace`` replace the wrapped controller's decision, every other field and step stays the wrapped one."""

    name = "replay"

    def __init__(self, inner, trace: Mapping[str, Sequence[float]], first_step: int) -> None:
        unknown = set(trace) - set(TRACE_FIELDS)
        if unknown:
            raise ValueError(f"not a controller command: {sorted(unknown)}")
        lengths = {len(v) for v in trace.values()}
        if len(lengths) > 1:
            raise ValueError("every replayed command needs the same number of steps")
        self.inner, self.trace, self.first_step = inner, trace, first_step
        self.length = lengths.pop() if lengths else 0
        self.calls = 0
        self.replayed_steps = 0

    def decide(self, observation: ControlObservation) -> ControlDecision:
        step, self.calls = self.calls, self.calls + 1
        decision = self.inner.decide(observation)  # always evaluated: the rules stay live outside the replayed fields and steps
        k = step - self.first_step
        if not 0 <= k < self.length:
            return decision
        self.replayed_steps += 1
        changes = {name: (None if values[k] == NO_TARGET else float(values[k])) if name == "irrigation_target_vwc" else float(values[k]) for name, values in self.trace.items()}
        return replace(decision, **changes)


def trace_of(decisions: Sequence[ControlDecision], first: int, count: int) -> dict[str, list[float]]:
    """The command trajectory of steps ``first .. first+count-1`` (one value per step and command)."""
    chosen = decisions[first:first + count]
    if len(chosen) != count:
        raise ValueError(f"the run made {len(decisions)} decisions: steps {first}..{first + count - 1} are not all there")
    return {name: [NO_TARGET if getattr(d, name) is None else float(getattr(d, name)) for d in chosen] for name in TRACE_FIELDS}
