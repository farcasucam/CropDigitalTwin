"""Tennessee Eastman process as a host of the effect queries (SimulatorPort plus run_traced), through the third-party Python backend `tep` (Braatz group Fortran port by Downs and Vogel, via jkitchin/tennessee-eastman-profbraatz).

The package is NOT a dependency of this repository: its source directory is given by the argument `tep_src` or the environment variable `TEP_SRC` and is added to sys.path when the host is built.
Its licence is the University of Illinois notice (the pyproject says BSD-3); that notice must travel with any redistribution.

Conventions (checked by tests/test_tennessee_eastman.py and manual_phase7_pt10a_tennessee.py):
* one sample per simulated SECOND (the process step), the window is `window_hours` samples of one second (the field name belongs to the port; here the unit is the sample);
* sample `a` (absolute, from the start of the run) is the measurement of the state after the step `a` (the package's own measurement is one step late: `_advance` refreshes it); an intervention at window index `s` lasting `n` changes the steps `first+s+1 .. first+s+n`, so the samples `s+1 .. s+n`;
* the season is the seed of the process noise (`season + 1`); the closed loop is the plant's own decentralised control (`DecentralizedController`), run from the steady state up to the window;
* the pre-window state is saved once per (season, window start) by a deep copy of the simulator and reused (the check in the manual script shows this reproduces the uninterrupted run);
* factors `IDV1 .. IDV20` are the plant's disturbances (on or off, no level);
* actuation trace: the twelve manipulated variables `mv_01 .. mv_12` as applied at each sample; replaying overrides the named ones from the window start (the others stay under the closed loop).
"""

from __future__ import annotations

import copy
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from tsxai.core.catalogue import PAST_ONLY, TARGET, VariableCatalogue, VariableSpec
from tsxai.core.errors import PortError
from tsxai.core.hashing import content_hash
from tsxai.core.simulator import ContextSpec, FactorSpec, Intervention, RunResult, ScenarioDescriptor
from tsxai.effects import InviableRun

NAME = "tennessee-eastman-python/1"
TOTAL_SAMPLES = 8 * 3600
N_XMEAS, N_MV, N_IDV = 41, 12, 20
TARGETS = (7, 8, 9, 12, 15)  # reactor pressure, reactor level, reactor temperature, separator level, stripper level


def _load_tep(tep_src: str | Path | None):
    source = tep_src or os.environ.get("TEP_SRC")
    if not source:
        raise PortError("give the source directory of the tep package (argument tep_src or environment variable TEP_SRC)")
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    import tep  # noqa: PLC0415

    return tep


class _Override:
    """Wraps the plant's controller: after it computes the manipulated variables of a step, the named ones are replaced by the traced values."""

    def __init__(self, inner: Any, values: Mapping[int, Sequence[float]], first: int) -> None:
        self.inner, self.values, self.first = inner, values, first

    def calculate(self, xmeas: Any, xmv: Any, step: int) -> Any:
        out = self.inner.calculate(xmeas, xmv, step).copy()
        k = step - self.first
        for index, series in self.values.items():
            if 0 <= k < len(series):
                out[index] = series[k]
        return out


class TennesseeEastman:
    name = NAME

    def __init__(self, tep_src: str | Path | None = None) -> None:
        self._tep = _load_tep(tep_src)
        self._snapshots: dict[tuple[int, int], Any] = {}
        self.snapshot_hits = 0

    def catalogue(self) -> VariableCatalogue:
        v = VariableSpec
        variables = {f"xmeas_{i:02d}": v("process units (see the process description)", TARGET if i in TARGETS else PAST_ONLY, "measurement of the plant" + (": a controlled or safety-relevant quantity" if i in TARGETS else "")) for i in range(1, N_XMEAS + 1)}
        variables.update({f"mv_{i:02d}": v("percent", PAST_ONLY, "manipulated variable as applied by the plant's closed loop (an output of the controller)") for i in range(1, N_MV + 1)})
        return VariableCatalogue(variables, tuple(f"xmeas_{i:02d}" for i in TARGETS))

    def factors(self) -> Mapping[str, FactorSpec]:
        return {f"IDV{i}": FactorSpec(f"IDV{i}", "on/off") for i in range(1, N_IDV + 1)}

    def contexts(self) -> Sequence[ContextSpec]:
        return [ContextSpec({"plant": "tennessee_eastman_base_case"}, TOTAL_SAMPLES, 0)]

    def scenario_options(self, labels: Mapping[str, str], season: int) -> Mapping[str, Any]:
        return {}

    # -- runs ------------------------------------------------------------------------------------------------------------------------------------
    def _simulator(self, season: int, first: int) -> Any:
        key = (season, first)
        if key not in self._snapshots:
            sim = self._tep.TEPSimulator(random_seed=season + 1, control_mode=self._tep.ControlMode.CLOSED_LOOP, backend="python")
            sim.initialize()
            for _ in range(first):
                if not self._advance(sim):
                    raise InviableRun(f"the plant shut down before the window ({first} s)")
            self._snapshots[key] = sim
        else:
            self.snapshot_hits += 1
        return copy.deepcopy(self._snapshots[key])

    @staticmethod
    def _advance(sim: Any) -> bool:
        """One second: the plant's step, then the measurements of the NEW state (the package reads them at the start of the next step, one step late, which would show an intervention one sample after the contract says)."""
        ok = sim.step()
        if ok:
            sim.process.evaluate(sim.time, sim.process.state.yy)
        return ok

    def run(self, scenario: ScenarioDescriptor, interventions: Sequence[Intervention] = ()) -> RunResult:
        return self.run_traced(scenario, interventions)[0]

    def run_traced(self, scenario: ScenarioDescriptor, interventions: Sequence[Intervention] = (), replay: Mapping[str, Sequence[float]] | None = None) -> tuple[RunResult, dict[str, list[float]]]:
        first, count = scenario.window_start, scenario.window_hours
        for item in interventions:
            if not item.factor.startswith("IDV") or not 1 <= int(item.factor[3:]) <= N_IDV:
                raise PortError(f"unknown factor {item.factor}")
        sim = self._simulator(scenario.season, first)
        if replay:
            values = {int(name.split("_")[1]) - 1: [float(x) for x in series] for name, series in replay.items()}
            sim.controller = _Override(sim.controller, values, first)
        used = sorted({int(item.factor[3:]) for item in interventions})
        rows: dict[str, list[float]] = {name: [] for name in self.catalogue().variables}
        for k in range(count):
            for idv in used:
                active = any(int(item.factor[3:]) == idv and item.start + 1 <= k <= item.start + item.duration for item in interventions)
                sim.set_disturbance(idv, 1 if active else 0)
            if not self._advance(sim) or sim.is_shutdown():
                raise InviableRun(f"the plant shut down at second {first + k}")
            for i, x in enumerate(sim.get_measurements(), 1):
                rows[f"xmeas_{i:02d}"].append(float(x))
            for i, x in enumerate(sim.get_manipulated_vars(), 1):
                rows[f"mv_{i:02d}"].append(float(x))
        inputs = {"simulator": NAME, "labels": dict(scenario.labels), "season": scenario.season, "window": [first, count], "options": dict(scenario.options),
                  "interventions": [item.to_dict() for item in interventions], "replay": None if not replay else {k: list(v) for k, v in replay.items()}}
        trace = {name: list(series) for name, series in rows.items() if name.startswith("mv_")}
        return RunResult(rows, [f"s{first + i}" for i in range(count)], content_hash({"inputs": inputs, "series": rows})), trace
