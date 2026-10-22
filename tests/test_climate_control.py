"""Phase 5.42: passive-first climate control, schedules and energy estimate (domain rules and the interactive-simulation integration)."""

from __future__ import annotations

import pytest

from agri_twin.application.climate_control import ClimateControlRequestError, parse_control, stage_setpoints
from agri_twin.application.interactive_simulation import InteractiveSimulationService, SimulationApiError, canonicalize_request
from agri_twin.domain.climate_control import (
    ClimateControlConfig,
    ClimateControlError,
    ControlDesign,
    ControlObservation,
    EquipmentSpec,
    RuleBasedClimateController,
    ScheduleProgram,
    StageSetpoints,
    commands_from_decision,
)

SETPOINTS = StageSetpoints("tomato", "yield_maturation", 12.0, 32.0, 35.0, 0.0, 850.0, 950.0, 30.0, 0.22, 0.30)
EQUIPMENT = {"vent_max_ach": 30, "extractor_max_ach": 20, "extractor_power_kw": 1.5, "cooling_capacity_kw": 40, "cooling_cop": 3, "heating_capacity_kw": 40, "heating_efficiency": 0.9, "irrigation_max_mm_step": 3}
ALL_AUTO = {name: "AUTO" for name in ("shade", "vents", "extractors", "cooling", "heating", "irrigation")}


def controller(actuators=None, equipment=None, schedules=()):
    return RuleBasedClimateController(ClimateControlConfig.from_mapping({"actuators": actuators or ALL_AUTO, "equipment": EQUIPMENT if equipment is None else equipment, "schedules": list(schedules)}))


def observation(indoor=25.0, outdoor=20.0, radiation=0.0, vwc=0.3, setpoints=SETPOINTS, hour=12, month=7, day=15, conductance=1100.0, previous_kw=0.0):
    return ControlObservation(month, day, hour, "yield_maturation", setpoints, indoor, 60.0, 1.0, outdoor, radiation, radiation * 0.78, vwc, conductance, 335.0, previous_kw)


def test_nothing_acts_inside_the_comfortable_range():
    decision = controller().decide(observation(indoor=25.0))
    assert (decision.vents, decision.extractors, decision.cooling, decision.heating, decision.shade) == (0.0, 0.0, 0.0, 0.0, 0.0)


def test_passive_is_exhausted_before_any_energy_is_spent():
    c = controller()
    # hot band of the stage: 32 .. 35 degC; vents full at 30 % of it (32.9), extractors at 60 % (33.8)
    first = c.decide(observation(indoor=32.5))
    assert 0 < first.vents < 1 and first.extractors == 0 and first.cooling == 0
    second = c.decide(observation(indoor=33.4))
    assert second.vents == 1.0 and 0 < second.extractors < 1 and second.cooling == 0
    third = c.decide(observation(indoor=34.5))
    assert third.vents == 1.0 and third.extractors == 1.0 and third.cooling > 0
    assert commands_from_decision(first, ControlDesignEquipment(), 3600).energy_kwh == 0.0  # passive only: no energy


def ControlDesignEquipment():
    return EquipmentSpec.from_mapping(EQUIPMENT)


def test_ventilation_is_held_back_when_the_outside_air_is_not_cooler():
    decision = controller().decide(observation(indoor=33.0, outdoor=38.0))
    assert decision.vents == 0 and decision.extractors == 0 and decision.cooling > 0
    assert any("held back" in reason for reason in decision.reasons)


def test_the_screen_follows_the_stage_radiation_thresholds_and_shading_reduction():
    c = controller()
    assert c.decide(observation(radiation=800.0)).shade == 0.0  # 800 * 0.78 = 624 W m-2 < optimal_max 850
    middle = c.decide(observation(radiation=1200.0)).shade  # 936 W m-2: inside [850, 950]
    full = c.decide(observation(radiation=1500.0)).shade
    assert 0 < middle < full == pytest.approx(0.30)  # shading_reduction_pct 30 from the catalogue


def test_heating_acts_only_below_the_stage_minimum_and_is_capacity_limited():
    c = controller()
    assert c.decide(observation(indoor=12.5, outdoor=5.0)).heating == 0.0
    mild, severe = c.decide(observation(indoor=11.0, outdoor=2.0)).heating, c.decide(observation(indoor=2.0, outdoor=-5.0)).heating
    assert 0 < mild < severe <= 1.0


def _closed_loop(kind, outdoor, steps=60, start=6.0):
    """Lumped greenhouse (1100 W/K, 2500 kJ/K) stepped hourly, as the simulation does, with the controller in the loop."""
    import math
    g, capacity, dt, tau = 1100.0, 2.5e6, 3600.0, 2.5e6 / 1100.0
    c, temperature, previous_kw, trace = controller(), start, 0.0, []
    for _ in range(steps):
        decision = c.decide(observation(indoor=temperature, outdoor=outdoor, conductance=g, previous_kw=previous_kw))
        kw = decision.heating * 40.0 - decision.cooling * 40.0
        equilibrium = outdoor + kw * 1000.0 / g
        temperature = equilibrium + (temperature - equilibrium) * math.exp(-dt / tau)
        previous_kw = kw
        trace.append(temperature)
    return trace


def test_the_hvac_loop_settles_on_the_stage_limit_without_oscillating_or_overshooting():
    cold = _closed_loop("heat", outdoor=5.0)
    assert max(cold[-10:]) - min(cold[-10:]) < 0.05 and abs(cold[-1] - SETPOINTS.min_temp_c) < 1.5 and max(cold) <= SETPOINTS.min_temp_c + 0.1
    # cooling target is where the passive tier ends (max_temp + 60 % of the hot band) because no passive equipment is in this loop's physics
    hot = _closed_loop("cool", outdoor=42.0, start=40.0)
    assert max(hot[-10:]) - min(hot[-10:]) < 0.05 and max(hot[-10:]) < 42.0


def test_a_missing_threshold_disables_only_the_rule_that_needs_it_and_says_so():
    bare = StageSetpoints("x", "stage")
    decision = controller().decide(observation(indoor=40.0, radiation=1500.0, setpoints=bare))
    assert decision.vents == decision.cooling == decision.shade == 0.0
    assert {decision.source[name] for name in ("vents", "extractors", "cooling", "shade", "irrigation")} == {"NO_THRESHOLD"}
    assert decision.reasons


def test_equipment_that_is_not_defined_is_unavailable_never_defaulted():
    decision = controller(equipment={}).decide(observation(indoor=40.0))
    assert decision.vents == decision.extractors == decision.cooling == 0.0
    assert decision.source["vents"] == decision.source["cooling"] == "UNAVAILABLE"


def test_energy_is_not_estimable_without_the_efficiency_it_needs():
    equipment = EquipmentSpec.from_mapping({**EQUIPMENT, "cooling_cop": None})
    decision = controller(equipment={**EQUIPMENT, "cooling_cop": None}).decide(observation(indoor=35.0))
    record = commands_from_decision(decision, equipment, 3600)
    assert record.cooling_kw > 0 and record.electric_kw is None and record.energy_kwh is None
    full = commands_from_decision(controller().decide(observation(indoor=35.0)), EquipmentSpec.from_mapping(EQUIPMENT), 1800)
    assert full.energy_kwh == pytest.approx(full.electric_kw / 2)
    assert full.layer == "ACTIVE"


def test_schedules_are_daily_windows_in_a_date_range_and_wrap_midnight_and_year_end():
    program = ScheduleProgram("shade", "06-15", "09-15", 11, 17, 0.6)
    assert program.active(7, 1, 11) and program.active(7, 1, 16) and not program.active(7, 1, 17) and not program.active(5, 1, 12) and not program.active(7, 1, 10)
    night = ScheduleProgram("heating", "11-01", "02-28", 22, 6, 1.0)
    assert night.active(12, 5, 23) and night.active(1, 5, 3) and not night.active(1, 5, 12) and not night.active(6, 5, 23)
    c = controller(actuators={"shade": "SCHEDULE"}, schedules=[program.to_dict()])
    assert c.decide(observation(month=7, hour=12)).shade == 0.6 and c.decide(observation(month=7, hour=20)).shade == 0.0


@pytest.mark.parametrize("bad", [
    {"actuators": {"toaster": "AUTO"}}, {"actuators": {"shade": "SOMETIMES"}}, {"equipment": {"vent_max_ach": -1}}, {"equipment": {"cooling_cop": 0}},
    {"equipment": {"warp_drive": 1}}, {"schedules": [{"actuator": "shade", "from_day": "13-45", "to_day": "09-15", "start_hour": 1, "end_hour": 2, "value": 1}]},
    {"schedules": [{"actuator": "shade", "from_day": "06-15", "to_day": "09-15", "start_hour": 5, "end_hour": 5, "value": 1}]}, {"schedules": [{"actuator": "shade"}]}, {"unknown": 1},
])
def test_invalid_control_documents_are_rejected(bad):
    with pytest.raises(ClimateControlError):
        ClimateControlConfig.from_mapping(bad)


def test_the_design_gain_must_be_a_fraction():
    for gain in (0.0, 1.5, -0.2):
        with pytest.raises(ClimateControlError):
            ControlDesign(hvac_gain=gain)


def test_setpoints_come_from_the_crop_catalogue_and_are_not_invented():
    tomato = stage_setpoints("tomato", "yield_maturation")
    assert (tomato.max_temp_c, tomato.critical_heat_c, tomato.shading_reduction_pct) == (32.0, 35.0, 30.0)
    unknown = stage_setpoints("tomato", "no_such_stage")
    assert unknown.max_temp_c is None and unknown.optimal_max_w_m2 is None


def test_a_decision_depends_only_on_the_observation():
    c = controller()
    assert c.decide(observation(indoor=34.0)) == c.decide(observation(indoor=34.0))


# ---- integration with the interactive simulation ----------------------------------------------------------------------------
BASE = {"crop": "tomato", "environment": "greenhouse", "scenario": "BASE_SEASON", "end_time": "2026-05-10T00:00:00+00:00", "options": {"include_trajectory": True, "compute_trajectory_hash": True}}
# sized for the default greenhouse (864 m2, about 4600 m3): the domain tests above use small round numbers, the simulation needs equipment that can move this much air and heat
GH_EQUIPMENT = {"vent_max_ach": 30, "extractor_max_ach": 20, "extractor_power_kw": 25, "cooling_capacity_kw": 400, "cooling_cop": 3, "heating_capacity_kw": 150, "heating_efficiency": 0.9, "irrigation_max_mm_step": 3}
CONTROL = {"actuators": ALL_AUTO, "equipment": GH_EQUIPMENT}


@pytest.fixture(scope="module")
def runs():
    service = InteractiveSimulationService()
    return {"plain": service.run_simulation(BASE), "control": service.run_simulation({**BASE, "control": CONTROL}), "again": service.run_simulation({**BASE, "control": CONTROL})}


def test_no_control_block_leaves_the_request_and_result_unchanged(runs):
    assert "control" not in canonicalize_request(BASE).to_dict()
    assert "control_layer" in {item["name"] for item in runs["plain"].result.variables}
    availability = {item["name"]: item["availability"] for item in runs["plain"].result.variables}
    assert availability["control_energy_kwh"] == "NOT_APPLICABLE" and "control_energy_kwh" not in runs["plain"].result.trajectory


def test_a_controlled_run_is_deterministic_and_reports_what_the_controller_did(runs):
    a, b = runs["control"], runs["again"]
    assert a.result.trajectory_hash == b.result.trajectory_hash != runs["plain"].result.trajectory_hash
    trajectory = a.result.trajectory
    assert set(trajectory["control_layer"]) <= {"NONE", "PASSIVE", "ACTIVE"}
    cumulative = trajectory["control_energy_kwh_cumulative"]
    assert cumulative[-1] == pytest.approx(sum(trajectory["control_energy_kwh"]))
    assert all(y >= x for x, y in zip(cumulative, cumulative[1:]))


def test_control_keeps_the_greenhouse_inside_the_stage_range_at_least_as_well_as_the_default_operation(runs):
    plain, controlled = runs["plain"].result.trajectory, runs["control"].result.trajectory
    assert max(controlled["temperature_c"]) < max(plain["temperature_c"]) and max(controlled["heat_stress"]) <= max(plain["heat_stress"])
    assert max(controlled["cold_stress"]) <= max(plain["cold_stress"]) + 0.05


def test_the_controller_does_not_flip_the_vents_between_fully_open_and_shut_from_one_hour_to_the_next(runs):
    vents = runs["control"].result.trajectory["control_vent_opening"]
    assert sum(1 for a, b in zip(vents, vents[1:]) if abs(a - b) > 0.8) <= 6  # it asks the greenhouse model what each action would do, so it does not chase the past


def test_the_controller_never_writes_a_state_it_only_changes_actuators(runs):
    trajectory = runs["control"].result.trajectory
    assert max(trajectory["greenhouse_heating_kw"]) > 0  # visible as the actuator the physical model received
    assert all(h == 0 or c == 0 for h, c in zip(trajectory["greenhouse_heating_kw"], trajectory["greenhouse_cooling_kw"]))


def test_control_is_part_of_the_resume_identity():
    plain, controlled = canonicalize_request(BASE), canonicalize_request({**BASE, "control": CONTROL})
    assert plain.resume_hash != controlled.resume_hash and plain.request_hash != controlled.request_hash


def test_all_actuators_off_is_the_same_as_no_control():
    assert parse_control({"actuators": {}}, "greenhouse") is None
    assert canonicalize_request({**BASE, "control": {"actuators": {"shade": "OFF"}}}).request_hash == canonicalize_request(BASE).request_hash


def test_climate_actuators_need_a_greenhouse_but_irrigation_does_not():
    with pytest.raises(ClimateControlRequestError) as caught:
        parse_control({"actuators": {"vents": "AUTO"}, "equipment": EQUIPMENT}, "outdoor")
    assert caught.value.path == "control.actuators.vents"
    assert parse_control({"actuators": {"irrigation": "AUTO"}}, "outdoor") is not None


def test_energyplus_takes_a_controller_in_lock_step_except_for_the_shade_screen():
    assert parse_control({"actuators": {"vents": "AUTO", "cooling": "AUTO"}, "equipment": EQUIPMENT}, "greenhouse", backend="ENERGYPLUS") is not None
    with pytest.raises(ClimateControlRequestError) as caught:
        parse_control({"actuators": {"shade": "AUTO"}, "equipment": EQUIPMENT}, "greenhouse", backend="ENERGYPLUS")
    assert caught.value.path == "control.actuators.shade"


def test_an_invalid_control_block_is_a_structured_api_error():
    with pytest.raises(SimulationApiError) as caught:
        canonicalize_request({**BASE, "control": {"actuators": {"toaster": "AUTO"}}})
    assert "toaster" in str(caught.value.to_dict())


def test_a_manual_event_on_an_actuator_replaces_the_controller_for_it():
    service = InteractiveSimulationService()
    event = {"event_type": "SHADING", "start_simulation_time": "2026-02-20T00:00:00+00:00", "duration_hours": 48, "intensity": 1.0}
    request = {**BASE, "end_time": "2026-02-25T00:00:00+00:00", "control": {"actuators": {"shade": "AUTO"}}, "runtime_events": [event]}
    shade = service.run_simulation(request).result.trajectory["greenhouse_shading_fraction"]
    assert max(shade) > 0 and shade[0] == 0.0
