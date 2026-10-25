"""The crop and greenhouse twin as a host of ``tsxai``: an implementation of its ``SimulatorPort``.

``tsxai`` (https://github.com/farcasucam/tsxai) is an independent framework for explaining multivariate time series; it knows nothing of this project. This module is the only place where the two meet:
it turns the interactive simulation service into a deterministic simulator the framework's causal benchmark can run with and without an intervention.

* **Variables and roles:** ``src/xai_variable_roles.json`` (provisional design convention) with the units of the twin's variable catalogue.
* **Interventions:** the runtime events of the twin (heat and cold waves, radiation, rain, dryness, wind, irrigation, ventilation, shading, CO2), with their technical bounds, and the sampling ranges and probe
  levels of ``src/xai_benchmark_design.json`` (sampling conventions of the benchmark, not agronomic values).
* **Contexts:** every crop outdoors and, for the annual crops, in the greenhouse with and without the climate controller (illustrative equipment, not a real installation) and with the controller plus the
  crop's feedback on the greenhouse air (``feedback=on``). Variants of one crop in one season share a split group, so they can never straddle the dev/test split.
* **Frames (phase 6.1):** ``twin_series_source()`` is a ``tsxai`` ``SeriesSource`` over this simulator; the exogenous weather and the rain are labelled ``FORCING`` and everything the twin computes ``SYNTHETIC``.
  A scenario may also carry its own ``greenhouse`` request (for example EnergyPlus, where installed) in ``options``.
* **Timing:** a window sample ``k`` is the hour ending ``campaign_start + window_start + k`` hours; an intervention that starts at window index ``s`` acts on samples ``s+1 .. s+n``, which is how the twin
  applies a runtime event of ``n`` hours.

The truth of a benchmark built here is the truth of the SIMULATED twin, whose crop model is not calibrated.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from tsxai.bench import BenchmarkDesign
from tsxai.core import ContextSpec, FactorSpec, Intervention, RunResult, ScenarioDescriptor, SimulatorSeriesSource, VariableCatalogue, VariableSpec, content_hash

from agri_twin.application.greenhouse_backend import layout_floor_area_m2
from agri_twin.application.interactive_simulation import VARIABLES, InteractiveSimulationService
from agri_twin.application.runtime_events import SPEC_INDEX
from agri_twin.application.scientific_benchmark import KNOWN_CROPS
from agri_twin.application.seasonal_synthetic_campaign import ANNUAL_GREENHOUSE_CROPS, campaign_cycle

ROLES_FILE = Path(__file__).resolve().parents[2] / "xai_variable_roles.json"
DESIGN_FILE = Path(__file__).resolve().parents[2] / "xai_benchmark_design.json"
NAME = "agri-twin-interactive/1"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def benchmark_design(path: Path | str | None = None) -> BenchmarkDesign:
    """The generic part of the twin's design file as a ``tsxai`` ``BenchmarkDesign``."""
    d = _load(Path(path or DESIGN_FILE))
    return BenchmarkDesign(
        seasons=d["seasons"], window_days=(d["window"]["days_min"], d["window"]["days_max"]), warmup_days_min=d["window"]["warmup_days_min"],
        interventions_per_scenario=(d["events"]["per_scenario_min"], d["events"]["per_scenario_max"]), duration_hours=(d["events"]["duration_hours_min"], d["events"]["duration_hours_max"]),
        probe_horizon_hours=d["probes"]["horizon_hours"], probe_cutoff_after_hours=d["probes"]["cutoff_after_hours"], observation_levels=d["observation"]["levels"],
        level_order=tuple(d["observation"]["level_order"]), floor_sigma=d["observation"]["floor_sigma"], split_salt=d["split"]["salt"], split_test_share=d["split"]["test_share"])


class TwinSimulator:
    """``tsxai.core.SimulatorPort`` for the twin. Pure: a run depends only on its arguments."""

    name = NAME

    def __init__(self, service: InteractiveSimulationService | None = None, design_path: Path | str | None = None, roles_path: Path | str | None = None) -> None:
        self._service = service or InteractiveSimulationService()
        self._design = _load(Path(design_path or DESIGN_FILE))
        self._roles = _load(Path(roles_path or ROLES_FILE))
        self._units = {variable.name: (variable.unit, variable.scope) for variable in VARIABLES}

    # -- the port ---------------------------------------------------------------------------------------------------------------------------------
    def catalogue(self) -> VariableCatalogue:
        """Roles of every variable the twin can produce (variables the twin does not represent are not part of its world)."""
        variables = {name: VariableSpec(self._units[name][0], entry["role"], entry["why"], entry.get("activation", {}).get("fraction")) for name, entry in self._roles["variables"].items() if self._units.get(name, ("", "NONE"))[1] != "NONE"}
        return VariableCatalogue(variables, tuple(self._roles["default_targets"]))

    def catalogue_for(self, scenario: ScenarioDescriptor) -> VariableCatalogue:
        """The catalogue with the rated power of the scenario's installation: a device's ON threshold is a fraction of the equipment the scenario runs with (none without the controller: no device, no threshold)."""
        equipment = (scenario.options.get("control") or {}).get("equipment", {})
        nominal = {name: float(equipment[entry["activation"]["nominal_from"]]) for name, entry in self._roles["variables"].items() if "activation" in entry and name in self.catalogue().variables and entry["activation"]["nominal_from"] in equipment}
        return self.catalogue().with_nominal(nominal)

    def factors(self) -> Mapping[str, FactorSpec]:
        cfg, probes = self._design["factors"], self._design["probes"]
        in_probes = set(probes["outdoor"]) | set(probes["greenhouse"])
        out: dict[str, FactorSpec] = {}
        for name, entry in cfg.items():
            spec = SPEC_INDEX[name]
            has_level = entry["intensity_min"] is not None
            out[name] = FactorSpec(name, entry["unit"], spec.minimum if has_level else None, spec.maximum if has_level else None,
                                   (entry["intensity_min"], entry["intensity_max"]) if has_level else None, probes["levels"].get(name) if has_level else None, name in in_probes,
                                   (("environment", "greenhouse"),) if "outdoor" not in entry["environments"] else ())
        return out

    def contexts(self) -> Sequence[ContextSpec]:
        warmup = self._design["window"]["warmup_days_min"] * 24
        cells = []
        for crop in KNOWN_CROPS:
            _, start, end = campaign_cycle(crop)
            hours = int((end - start).total_seconds() // 3600)
            variants = [{"environment": "outdoor", "control": "off"}]
            if crop in ANNUAL_GREENHOUSE_CROPS:
                variants += [{"environment": "greenhouse", "control": "off"}, {"environment": "greenhouse", "control": "on"}, {"environment": "greenhouse", "control": "on", "feedback": "on"}]
            cells += [ContextSpec({"crop": crop, **variant}, hours, warmup, ("crop",)) for variant in variants]
        return cells

    def scenario_options(self, labels: Mapping[str, str], season: int) -> Mapping[str, Any]:
        options: dict[str, Any] = {}
        if labels.get("feedback") == "on":
            options["greenhouse"] = {"backend": "SIMPLIFIED", "crop_exchange": True}
        if labels.get("control") == "on":
            control = self._design["control"]
            area = layout_floor_area_m2(None)
            equipment = {**control["equipment_fixed"], **{key: round(value * area, 3) for key, value in control["equipment_per_m2"].items()}}
            options["control"] = {"actuators": dict(control["actuators"]), "equipment": equipment}
        return options

    def run(self, scenario: ScenarioDescriptor, interventions: Sequence[Intervention] = ()) -> RunResult:
        crop, environment = scenario.labels["crop"], scenario.labels["environment"]
        _, origin, _ = campaign_cycle(crop)
        w0, w1 = scenario.window_start, scenario.window_start + scenario.window_hours
        request: dict[str, Any] = {"crop": crop, "environment": environment, "seed": scenario.season, "end_time": (origin + timedelta(hours=w1)).isoformat(),
                                   "options": {"include_trajectory": True, "compute_trajectory_hash": True}}
        if interventions:
            request["runtime_events"] = [{"event_type": item.factor, "start_simulation_time": (origin + timedelta(hours=w0 + item.start)).isoformat(), "duration_hours": item.duration,
                                          **({"intensity": item.level} if item.level is not None else {})} for item in interventions]
        if scenario.options.get("greenhouse"):
            request["greenhouse"] = dict(scenario.options["greenhouse"])
        control = scenario.options.get("control")
        if control:
            request["control"] = {"actuators": dict(control["actuators"]), "equipment": dict(control["equipment"])}
        response = self._service.run_simulation(request)
        if response.execution_status.value != "COMPLETED":
            raise RuntimeError(f"the twin did not complete the run: {[error.message for error in response.errors]}")
        trajectory = response.result.trajectory
        a, b = w0 - 1, w1 - 1  # the trajectory starts at the first step after the campaign start: sample j is the hour ending origin + (j + 1) h
        series = {name: list(values[a:b]) for name, values in trajectory.items() if name != "time" and None not in values[a:b]}
        run_hash = content_hash({"request": response.hashes["request_hash"], "trajectory": response.result.trajectory_hash, "window": [w0, w1]})
        return RunResult(series, list(trajectory["time"][a:b]), run_hash)


CONTROLLER_DRIVEN = ("past_only_covariate", "set by the climate controller in this scenario (control on): an output of the controller reacting to the state, so not a plan; its future values are never given to a forecaster")
FACTOR_PLAN = {"IRRIGATION": ("irrigation_mm",), "SHADING": ("greenhouse_shading_fraction",), "VENTILATION": ("control_vent_opening",)}  # the decision variable an intervention itself sets (a stated plan)


def controller_role_overrides(simulator: TwinSimulator):
    """With the controller on, the decision-role variables (vent opening, extractor, shading, irrigation) are the controller's own outputs: they react to the indoor state, so their future values would hand a
    forecaster the controller's reaction to the very target it predicts. In those scenarios they become past-only covariates; with the controller off they stay decisions (a person's plan)."""
    decisions = simulator.catalogue().with_role("decision_covariate")

    def overrides(scenario):
        return {name: CONTROLLER_DRIVEN for name in decisions} if scenario.labels.get("control") == "on" else {}

    return overrides


def intervention_plan_variables(intervention) -> tuple[str, ...]:
    """The variables an intervention directly sets, to be stated as a plan in a what-if (empty for a weather or process factor)."""
    return FACTOR_PLAN.get(intervention.factor, ())


def twin_series_source(simulator: TwinSimulator | None = None) -> SimulatorSeriesSource:
    """Frames of the twin: the exogenous weather and the rain are forcing, everything the twin computes is synthetic (no ``REAL_VERIFIED`` data exists). With the controller on, its outputs are past-only covariates."""
    simulator = simulator or TwinSimulator()
    forcing = {name: "FORCING" for name in simulator.catalogue().with_role("known_future_covariate")}
    return SimulatorSeriesSource(simulator, "SYNTHETIC", forcing, role_overrides=controller_role_overrides(simulator))
