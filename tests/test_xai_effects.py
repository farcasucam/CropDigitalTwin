"""Recording and replaying the climate controller's commands (``xai_effects``) and the effects engine of ``tsxai`` on the twin."""

from __future__ import annotations

import pytest

from tsxai.core import Intervention, ScenarioDescriptor
from tsxai.effects import EffectQuery, Outcome, Player, Policy, ResimulationEngine

from agri_twin.application.interactive_simulation import InteractiveSimulationService
from agri_twin.domain.climate_control import ControlDecision
from agri_twin.interfaces.xai_adapter import TwinSimulator
from agri_twin.interfaces.xai_effects import NO_TARGET, TRACE_FIELDS, RecordingController, ReplayController, trace_of


class Constant:
    name = "constant"

    def __init__(self, **fields) -> None:
        self.decision = ControlDecision(**fields)
        self.calls = 0

    def decide(self, observation):
        self.calls += 1
        return self.decision


# -- unit: no twin run ----------------------------------------------------------------------------------------------------------------------------
def test_a_replay_replaces_only_the_named_commands_inside_its_steps():
    inner = Constant(vents=0.2, heating=0.5, irrigation_target_vwc=0.3)
    replay = ReplayController(inner, {"vents": [0.9, 0.8], "irrigation_target_vwc": [NO_TARGET, 0.4]}, first_step=2)
    out = [replay.decide(None) for _ in range(5)]  # steps 0..4
    assert [d.vents for d in out] == [0.2, 0.2, 0.9, 0.8, 0.2]  # steps 2 and 3 are replayed
    assert [d.heating for d in out] == [0.5] * 5  # a command that is not in the trace stays the wrapped controller's
    assert [d.irrigation_target_vwc for d in out] == [0.3, 0.3, None, 0.4, 0.3]  # the sentinel is "no target"
    assert inner.calls == 5 and replay.replayed_steps == 2  # the rules stay live


def test_a_replay_refuses_what_is_not_a_command_or_has_ragged_lengths():
    with pytest.raises(ValueError):
        ReplayController(Constant(), {"temperature": [1.0]}, 0)
    with pytest.raises(ValueError):
        ReplayController(Constant(), {"vents": [0.1], "heating": [0.1, 0.2]}, 0)


def test_the_recorder_keeps_every_decision_and_the_trace_is_a_slice_of_them():
    recorder = RecordingController(Constant(vents=0.3))
    for _ in range(6):
        recorder.decide(None)
    trace = trace_of(recorder.decisions, 2, 3)
    assert set(trace) == set(TRACE_FIELDS) and trace["vents"] == [0.3, 0.3, 0.3] and trace["irrigation_target_vwc"] == [NO_TARGET] * 3
    with pytest.raises(ValueError):
        trace_of(recorder.decisions, 5, 3)


def test_the_default_service_has_no_controller_hook():
    assert InteractiveSimulationService()._controller_factory is None


# -- on the twin (about 1.5 s per run) ------------------------------------------------------------------------------------------------------------
LABELS = {"crop": "tomato", "environment": "greenhouse", "control": "on"}
HEAT = (Intervention("HEAT_WAVE", 12, 24, 8.0),)


@pytest.fixture(scope="module")
def twin():
    simulator = TwinSimulator()
    scenario = ScenarioDescriptor(LABELS, 0, 24 * 40, 48, simulator.scenario_options(LABELS, 0))
    return simulator, scenario


def test_recording_changes_no_run_and_replaying_a_runs_own_commands_reproduces_it(twin):
    simulator, scenario = twin
    plain = simulator.run(scenario, HEAT)
    recorded, trace = simulator.run_traced(scenario, HEAT, None)
    assert recorded.run_hash == plain.run_hash and recorded.series == plain.series  # the wrapper is transparent
    assert set(trace) == set(TRACE_FIELDS) and all(len(v) == 48 for v in trace.values())
    again, again_trace = simulator.run_traced(scenario, HEAT, trace)
    assert again.series == plain.series and again_trace == trace  # replaying the commands a run issued is that run


def test_under_replay_the_controller_no_longer_answers_the_perturbation(twin):
    simulator, scenario = twin
    reference, reference_trace = simulator.run_traced(scenario, (), None)
    reactive, reactive_trace = simulator.run_traced(scenario, HEAT, None)
    replayed, replayed_trace = simulator.run_traced(scenario, HEAT, reference_trace)
    assert reactive_trace != reference_trace  # the controller answers the heat wave
    assert replayed_trace == reference_trace  # and under replay it is held to the reference's commands
    assert replayed.series["temperature_c"] != reactive.series["temperature_c"]  # so the air does something else
    assert max(replayed.series["temperature_c"]) > max(reactive.series["temperature_c"])  # the heat wave is no longer cooled away


def test_a_scenario_without_the_controller_or_a_window_at_the_start_cannot_be_traced(twin):
    simulator, scenario = twin
    with pytest.raises(ValueError):
        simulator.run_traced(ScenarioDescriptor({**LABELS, "control": "off"}, 0, 24 * 40, 48, {}), (), None)
    with pytest.raises(ValueError):
        simulator.run_traced(ScenarioDescriptor(LABELS, 0, 0, 48, scenario.options), (), None)


def test_the_effects_engine_divides_a_twin_contrast_and_replayed_energy_is_fixed_by_construction(twin):
    simulator, scenario = twin
    players = (Player("heat_wave", HEAT), Player("high_radiation", (Intervention("HIGH_RADIATION", 12, 24, 1.3),)))
    outcomes = (Outcome("cooling_energy", "greenhouse_cooling_kw", "integral", "kWh"), Outcome("temperature_peak", "temperature_c", "max", "degC"))
    engine = ResimulationEngine(simulator)
    reactive = engine.evaluate(EffectQuery(scenario, outcomes, players))
    replayed = engine.evaluate(EffectQuery(scenario, outcomes, players, policy=Policy("replayed")))
    for report in (reactive, replayed):
        for outcome in report["outcomes"].values():
            assert abs(outcome["efficiency_residual"]) < 1e-9
    assert replayed["policy_check"]["reproduces_source_run"] is True
    assert replayed["outcomes"]["cooling_energy"]["total_effect"] == 0.0  # the commands are the reference's: nothing for the energy to change
    assert reactive["outcomes"]["cooling_energy"]["total_effect"] > 0.0  # ... while the reactive controller did spend energy
    assert reactive["report_hash"] == ResimulationEngine(simulator).evaluate(EffectQuery(scenario, outcomes, players))["report_hash"]


def test_a_cooling_capacity_intervention_caps_the_cooling_power_and_only_applies_to_the_whole_run(twin):
    simulator, scenario = twin
    rated = scenario.options["control"]["equipment"]["cooling_capacity_kw"]
    nominal = simulator.run(scenario, HEAT)
    reduced = simulator.run(scenario, HEAT + (Intervention("COOLING_CAPACITY", 0, scenario.window_hours, 0.05),))
    assert max(nominal.series["greenhouse_cooling_kw"]) > 0.05 * rated  # the nominal run needs more than the reduced installation can give
    assert max(reduced.series["greenhouse_cooling_kw"]) <= 0.05 * rated + 1e-9
    assert max(reduced.series["temperature_c"]) > max(nominal.series["temperature_c"])  # the installation can no longer hold the air
    with pytest.raises(ValueError):
        simulator.run(scenario, (Intervention("COOLING_CAPACITY", 5, scenario.window_hours - 5, 0.5),))  # a whole-run change only
    with pytest.raises(ValueError):
        simulator.run(ScenarioDescriptor({**LABELS, "control": "off"}, 0, 24 * 40, 48, {}), (Intervention("COOLING_CAPACITY", 0, 48, 0.5),))  # needs the controller
