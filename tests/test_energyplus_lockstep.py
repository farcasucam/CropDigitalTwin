"""EnergyPlus driven in lock-step by a climate controller (phase 5.46). Needs EnergyPlus 26.1 except where stated."""

from __future__ import annotations

import pytest

import agri_twin.application.greenhouse_backend as backend_module
from agri_twin.application.greenhouse_backend import _hourly_forcing, layout_spec
from agri_twin.application.interactive_runtime import InteractiveRuntimeService
from agri_twin.application.interactive_simulation import InteractiveSimulationService, SimulationApiError, canonicalize_request
from agri_twin.domain.greenhouse import ActuatorControl
from agri_twin.infrastructure.energyplus_lockstep import (
    SETPOINT_OFF_COOL_C,
    SETPOINT_OFF_HEAT_C,
    LockstepCommands,
    LockstepSession,
    commands_from_actuators,
)
from agri_twin.infrastructure.energyplus_timeline import TimelineInputs, find_energyplus, run_timeline

INSTALL = find_energyplus()
needs_energyplus = pytest.mark.skipif(INSTALL is None or not INSTALL.version.startswith("26.1"), reason="EnergyPlus 26.1 not installed (external dependency)")
EQUIPMENT = {"vent_max_ach": 30, "extractor_max_ach": 20, "extractor_power_kw": 20, "cooling_capacity_kw": 400, "cooling_cop": 3, "heating_capacity_kw": 150, "heating_efficiency": 0.9}
CONTROL = {"actuators": {"vents": "AUTO", "extractors": "AUTO", "cooling": "AUTO", "heating": "AUTO"}, "equipment": EQUIPMENT}
BASE = {"crop": "tomato", "environment": "greenhouse", "end_time": "2026-02-20T00:00:00+00:00", "greenhouse": {"backend": "ENERGYPLUS"}, "control": CONTROL,
        "options": {"include_trajectory": True, "compute_trajectory_hash": True}}
service = InteractiveSimulationService()


def run(**extra):
    response = service.run_simulation({**BASE, **extra})
    assert response.execution_status.value == "COMPLETED", response.errors
    return response


@pytest.fixture
def energyplus_present(monkeypatch):
    monkeypatch.setattr(backend_module, "require_energyplus", lambda: object())


# ---- no EnergyPlus needed ---------------------------------------------------------------------------------------------------------------------
def test_actuators_become_commands_and_each_driven_function_makes_the_default_stand_down():
    plain = commands_from_actuators({})
    assert plain == LockstepCommands() and plain.auto_vent and plain.heating_setpoint_c is None and plain.cooling_setpoint_c is None
    controller = commands_from_actuators({"ventilation_ach": ActuatorControl(18.0, maximum=18.0, capacity=18.0), "heating": ActuatorControl(40.0, maximum=40.0, capacity=40.0)})
    assert not controller.auto_vent and controller.controller_air_changes == 18.0 and controller.controller_heat_kw == 40.0
    assert controller.heating_setpoint_c == SETPOINT_OFF_HEAT_C and controller.cooling_setpoint_c is None
    cooling = commands_from_actuators({"cooling": ActuatorControl(60.0, maximum=60.0, capacity=60.0), "heating": ActuatorControl(0.0, maximum=1.0, capacity=1.0)})
    assert cooling.controller_heat_kw == -60.0 and cooling.cooling_setpoint_c == SETPOINT_OFF_COOL_C and cooling.heating_setpoint_c == SETPOINT_OFF_HEAT_C
    manual = commands_from_actuators({"ventilation": ActuatorControl(0.6, maximum=1.0, capacity=1.0)})
    assert manual.auto_vent and manual.forced_vent_fraction == 0.6  # a manual event adds to the default venting, as in the open-loop model


def test_the_shade_screen_cannot_be_driven_in_lock_step(energyplus_present):
    with pytest.raises(SimulationApiError) as caught:
        canonicalize_request({**BASE, "control": {"actuators": {"shade": "AUTO"}, "equipment": {}}})
    assert caught.value.errors[0].path == "control.actuators.shade" and "lock-step" in caught.value.errors[0].message
    assert canonicalize_request({**BASE, "control": {"actuators": {"vents": "AUTO"}, "equipment": {"vent_max_ach": 30}}}).control is not None  # everything else is allowed now


def test_a_greenhouse_request_without_a_controller_still_uses_the_open_loop_timeline(energyplus_present):
    assert canonicalize_request({k: v for k, v in BASE.items() if k != "control"}).control is None


# ---- the session ------------------------------------------------------------------------------------------------------------------------------
@needs_energyplus
def test_lock_step_with_default_commands_reproduces_the_open_loop_timeline():
    from agri_twin.application.interactive_simulation import _weather_factory

    request = canonicalize_request({**BASE, "end_time": "2026-02-18T00:00:00+00:00"})
    scenario = service._prepare(request)[1]  # noqa: SLF001
    series, forced, shading = _hourly_forcing(scenario, _weather_factory(request), request.end_time)
    location = backend_module._location(request.plot)  # noqa: SLF001
    spec = layout_spec(request.greenhouse)
    timeline = run_timeline(TimelineInputs(location, tuple(series), tuple(forced), tuple(shading), spec, thermal=backend_module.thermal_spec(request.greenhouse)))
    with LockstepSession(spec, series, shading, location, thermal=backend_module.thermal_spec(request.greenhouse)) as session:
        for stamp, _ in series[:96]:
            value, reference = session.advance(stamp, LockstepCommands()), timeline.values[stamp]
            assert value.air_temperature_c == pytest.approx(reference.air_temperature_c, abs=1e-9)
            assert value.relative_humidity_pct == pytest.approx(reference.relative_humidity_pct, abs=1e-9)
            assert value.radiation_w_m2 == pytest.approx(reference.radiation_w_m2, abs=1e-9)
            assert value.heating_w / 1000.0 == pytest.approx(reference.heating_kw, abs=1e-9)
            assert min(1.0, value.ventilation_ach / session.max_ventilation_ach) == pytest.approx(reference.ventilation_fraction, abs=1e-9)


@needs_energyplus
def test_every_actuator_does_what_it_should_and_the_thermostat_stands_down_when_told():
    from agri_twin.application.interactive_simulation import _weather_factory

    request = canonicalize_request({**BASE, "end_time": "2026-02-18T00:00:00+00:00"})
    scenario = service._prepare(request)[1]  # noqa: SLF001
    series, _, shading = _hourly_forcing(scenario, _weather_factory(request), request.end_time)
    location, spec = backend_module._location(request.plot), layout_spec(request.greenhouse)  # noqa: SLF001
    off = dict(heating_setpoint_c=SETPOINT_OFF_HEAT_C, cooling_setpoint_c=SETPOINT_OFF_COOL_C)
    cases = {"free": LockstepCommands(auto_vent=False, **off), "heat": LockstepCommands(auto_vent=False, controller_heat_kw=50.0, **off), "cool": LockstepCommands(auto_vent=False, controller_heat_kw=-50.0, **off),
             "air": LockstepCommands(auto_vent=False, controller_air_changes=20.0, **off), "forced": LockstepCommands(auto_vent=False, forced_vent_fraction=1.0, **off), "default": LockstepCommands()}
    result = {}
    for name, commands in cases.items():
        with LockstepSession(spec, series, shading, location) as session:
            rows = [session.advance(stamp, commands) for stamp, _ in series[:48]]
        result[name] = (sum(r.air_temperature_c for r in rows) / 48, sum(r.ventilation_ach for r in rows) / 48, sum(r.heating_w for r in rows) / 48000)
    assert result["heat"][0] > result["free"][0] + 3.0 > result["cool"][0] + 6.0 and result["air"][0] < result["free"][0] - 2.0
    assert result["air"][1] == pytest.approx(20.0, abs=1.0) and result["forced"][1] > 29.0 and result["free"][1] < 0.01
    assert result["free"][2] == 0.0 and result["default"][2] > 1.0  # the thermostat only stands down on command


@needs_energyplus
def test_hours_must_be_requested_in_order_and_closing_ends_the_process():
    from agri_twin.application.interactive_simulation import _weather_factory

    request = canonicalize_request({**BASE, "end_time": "2026-02-17T00:00:00+00:00"})
    scenario = service._prepare(request)[1]  # noqa: SLF001
    series, _, shading = _hourly_forcing(scenario, _weather_factory(request), request.end_time)
    session = LockstepSession(layout_spec(request.greenhouse), series, shading, backend_module._location(request.plot))  # noqa: SLF001
    try:
        session.advance(series[0][0], LockstepCommands())
        from agri_twin.infrastructure.energyplus_timeline import EnergyPlusTimelineError

        with pytest.raises(EnergyPlusTimelineError):
            session.advance(series[5][0], LockstepCommands())  # skipping hours is refused
        process = session._process  # noqa: SLF001
    finally:
        session.close()
    assert process.poll() is not None  # the child process is gone


# ---- the run ----------------------------------------------------------------------------------------------------------------------------------
@needs_energyplus
def test_a_controller_runs_on_energyplus_deterministically_and_keeps_the_crop_air_in_range():
    first, second = run(), run()
    assert first.result.trajectory_hash == second.result.trajectory_hash
    trajectory = first.result.trajectory
    assert first.diagnostics["greenhouse_backend"]["mode"] == "LOCK_STEP" and first.diagnostics["greenhouse_backend"]["backend"] == "ENERGYPLUS"
    assert "control_energy_kwh_cumulative" in trajectory and max(trajectory["control_vent_opening"]) > 0.0
    open_loop = service.run_simulation({k: v for k, v in BASE.items() if k != "control"})
    assert trajectory["greenhouse_ventilation_fraction"] != open_loop.result.trajectory["greenhouse_ventilation_fraction"]  # the controller, not the default venting, is acting
    assert min(trajectory["temperature_c"]) > -5.0


@needs_energyplus
def test_what_if_equals_the_continuous_run_with_a_controller_on_energyplus():
    plain = run(end_time="2026-02-22T00:00:00+00:00")
    event = {"event_type": "VENTILATION", "start_simulation_time": "2026-02-20T00:00:00+00:00", "duration_hours": 12, "intensity": 1.0}
    request = {k: v for k, v in {**BASE, "end_time": "2026-02-22T00:00:00+00:00"}.items() if k != "options"}
    result = InteractiveRuntimeService().what_if({"request": request, "checkpoint_time": "2026-02-19T00:00:00+00:00", "events": [event]})
    prefix, baseline = result["prefix"]["result"]["trajectory"], result["branches"]["baseline"]["response"]["result"]["trajectory"]
    keep = [index for index, time in enumerate(baseline["time"]) if time > prefix["time"][-1]]
    for name in ("temperature_c", "relative_humidity_pct", "greenhouse_cooling_kw", "control_vent_opening", "biomass_total_g_m2"):
        assert prefix[name] + [baseline[name][index] for index in keep] == plain.result.trajectory[name], name  # the resume replayed the prefix and continued on the same session
    intervention = result["branches"]["intervention"]["response"]["result"]["trajectory"]
    assert intervention["greenhouse_ventilation_fraction"] != baseline["greenhouse_ventilation_fraction"]


@needs_energyplus
def test_a_checkpoint_from_another_controller_is_refused_by_the_replay():
    producer = run(end_time="2026-02-18T00:00:00+00:00")
    other = {"actuators": {"vents": "AUTO", "heating": "AUTO"}, "equipment": {"vent_max_ach": 30, "heating_capacity_kw": 150, "heating_efficiency": 0.9}}
    with pytest.raises(SimulationApiError):  # the resume identity includes the control configuration
        service.run_simulation({**{k: v for k, v in BASE.items() if k != "options"}, "control": other, "checkpoint": producer.checkpoint.to_dict()})
