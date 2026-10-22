"""Phase 5.44: the simplified greenhouse is a lumped model of the SAME greenhouse EnergyPlus simulates (geometry, envelope, default operation)."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from agri_twin.application.consistent_greenhouse import GeometryGreenhouseEngine, reduced_configuration, reduced_model_constants
from agri_twin.application.greenhouse_backend import layout_spec, parse_greenhouse_backend, simplified_configuration
from agri_twin.application.interactive_runtime import InteractiveRuntimeService
from agri_twin.application.interactive_simulation import InteractiveSimulationService
from agri_twin.domain.greenhouse import (
    ActuatorControl,
    GreenhouseConfiguration,
    GreenhouseMicroclimateState,
    MicroclimateState,
    SimplifiedGreenhouseModel,
    _two_node_step,
)
from agri_twin.domain.greenhouse_typology import GreenhouseTypology, default_geometry, floor_area_m2, volume_m3
from agri_twin.domain.models import WeatherState
from agri_twin.infrastructure.greenhouse_idf import FLOOR_MATERIAL, EnvelopeSpec, ThermalSpec, build_greenhouse_idf, cover_area_m2

WEATHER = WeatherState(8.0, 60.0, 0.0, 2.0, 180.0, 0.0, 1013.0)
service = InteractiveSimulationService()


def lumped(**overrides) -> GreenhouseConfiguration:
    return replace(reduced_configuration(default_geometry(GreenhouseTypology.MULTITUNEL_CAPILLA))[0], **overrides)


def step(config: GreenhouseConfiguration, weather=WEATHER, prior=None, actuators=None, dt=3600.0) -> MicroclimateState:
    return SimplifiedGreenhouseModel(configuration=config).step(weather, config, actuators or {}, None, dt, prior=prior)


# ---- the numerics -------------------------------------------------------------------------------------------------------------------------
def test_the_two_node_step_is_the_exact_solution_of_its_equations():
    args = dict(g_out=9000.0, t_out=8.0, g_floor=3500.0, g_ground=6000.0, t_ground=15.0, c_air=5.6e6, c_floor=2.5e8, q_air=2000.0, q_floor=90000.0)
    air, floor = 12.0, 14.0

    def derivative(a, f):
        return ((args["g_out"] * (args["t_out"] - a) + args["g_floor"] * (f - a) + args["q_air"]) / args["c_air"],
                (args["g_floor"] * (a - f) + args["g_ground"] * (args["t_ground"] - f) + args["q_floor"]) / args["c_floor"])

    a, f, dt = air, floor, 1.0
    for _ in range(3600):  # independent check: classical RK4 with one-second steps
        k1 = derivative(a, f)
        k2 = derivative(a + dt / 2 * k1[0], f + dt / 2 * k1[1])
        k3 = derivative(a + dt / 2 * k2[0], f + dt / 2 * k2[1])
        k4 = derivative(a + dt * k3[0], f + dt * k3[1])
        a, f = a + dt / 6 * (k1[0] + 2 * k2[0] + 2 * k3[0] + k4[0]), f + dt / 6 * (k1[1] + 2 * k2[1] + 2 * k3[1] + k4[1])
    exact = _two_node_step(air, floor, **args, dt_seconds=3600.0)
    assert exact[0] == pytest.approx(a, abs=1e-6) and exact[1] == pytest.approx(f, abs=1e-6)


def test_the_two_node_step_settles_on_the_analytic_equilibrium_and_conserves_the_energy_balance():
    args = dict(g_out=9000.0, t_out=8.0, g_floor=3500.0, g_ground=6000.0, t_ground=15.0, c_air=5.6e6, c_floor=2.5e8, q_air=2000.0, q_floor=90000.0)
    air, floor = _two_node_step(0.0, 0.0, **args, dt_seconds=1e9)
    out = args["g_out"] * (args["t_out"] - air) + args["g_floor"] * (floor - air) + args["q_air"]
    ground = args["g_ground"] * (args["t_ground"] - floor) + args["g_floor"] * (air - floor) + args["q_floor"]
    assert out == pytest.approx(0.0, abs=1e-3) and ground == pytest.approx(0.0, abs=1e-3)  # no net heat anywhere at equilibrium


def test_the_historical_model_is_bit_for_bit_unchanged_when_no_extension_is_configured():
    legacy = GreenhouseConfiguration()
    state = step(legacy, WeatherState(20.0, 50.0, 600.0, 2.0, 180.0, 0.0, 1013.0))
    assert state.floor_temperature_c is None and "floor_temperature_c" not in state.to_dict()  # checkpoints of historical runs keep their payload


# ---- the physics of the default operation ----------------------------------------------------------------------------------------------------
def test_the_thermostat_holds_the_setpoint_when_the_heater_can_and_never_exceeds_its_capacity_when_it_cannot():
    prior = GreenhouseMicroclimateState(temperature_c=12.0, relative_humidity_pct=60.0, floor_temperature_c=14.0)
    strong = lumped()
    held = step(strong, replace(WEATHER, temperature_c=6.0), prior=prior)  # a loss the 86 kW heater can cover
    assert held.air_temperature_c == pytest.approx(strong.thermostat_setpoint_c, abs=1e-6) and 0.0 < held.heating_kw <= strong.heater_capacity_kw
    assert step(strong, replace(WEATHER, temperature_c=-2.0), prior=prior).heating_kw == pytest.approx(strong.heater_capacity_kw)  # colder than it can hold: full power, and no more
    weak = lumped(heater_capacity_kw=5.0)
    limited = step(weak, replace(WEATHER, temperature_c=6.0), prior=prior)
    assert limited.heating_kw == pytest.approx(5.0) and limited.air_temperature_c < weak.thermostat_setpoint_c


def test_the_vents_open_by_themselves_above_their_temperature_and_only_when_the_outdoor_air_is_cooler():
    config = lumped()
    sunny = WeatherState(20.0, 50.0, 900.0, 2.0, 180.0, 0.0, 1013.0)
    warm_prior = GreenhouseMicroclimateState(temperature_c=26.0, relative_humidity_pct=50.0, floor_temperature_c=30.0)
    opened = step(config, sunny, prior=warm_prior)
    assert opened.ventilation_fraction > 0.9  # the opening, as EnergyPlus reports it
    hot_night = WeatherState(38.0, 30.0, 0.0, 2.0, 180.0, 0.0, 1013.0)  # warmer outside than the greenhouse would be: venting would only bring heat in
    assert step(config, hot_night, prior=GreenhouseMicroclimateState(temperature_c=30.0, relative_humidity_pct=50.0, floor_temperature_c=30.0)).ventilation_fraction == 0.0
    assert step(replace(config, passive_vent_open_above_c=None), sunny, prior=warm_prior).ventilation_fraction == 0.0


def test_a_controller_driving_a_function_makes_the_default_for_that_function_stand_down():
    config = lumped()
    cold = replace(WEATHER, temperature_c=-2.0)
    prior = GreenhouseMicroclimateState(temperature_c=12.0, relative_humidity_pct=60.0, floor_temperature_c=14.0)
    engine = GeometryGreenhouseEngine(config)
    crop = type("Crop", (), {"leaf_area_index": 1.0})()
    default = engine.advance(cold, crop, 3600.0, "passive_greenhouse", {}, prior).indoor_state
    commanded = engine.advance(cold, crop, 3600.0, "passive_greenhouse", {"heating": ActuatorControl(0.0, maximum=1.0, capacity=1.0)}, prior).indoor_state
    assert default.heating_kw > 10.0 and commanded.heating_kw == 0.0  # heating under a controller: no hidden thermostat on top


def test_a_ventilation_command_is_a_fraction_of_the_vent_capacity_and_ventilation_ach_is_physical():
    config, crop = lumped(), type("Crop", (), {"leaf_area_index": 1.0})()
    engine = GeometryGreenhouseEngine(config)
    prior = GreenhouseMicroclimateState(temperature_c=18.0, relative_humidity_pct=60.0, floor_temperature_c=15.0)
    cool = replace(WEATHER, temperature_c=10.0)
    fraction = engine.advance(cool, crop, 3600.0, "passive_greenhouse", {"ventilation": ActuatorControl(0.5, maximum=1.0, capacity=1.0)}, prior).indoor_state
    physical = engine.advance(cool, crop, 3600.0, "passive_greenhouse", {"ventilation_ach": ActuatorControl(15.0, maximum=15.0, capacity=15.0)}, prior).indoor_state
    assert fraction.ventilation_fraction == pytest.approx(0.5, abs=0.02) and physical.ventilation_fraction == pytest.approx(0.5, abs=0.02)


def test_the_floor_temperature_travels_in_the_state_and_restores_exactly():
    state = step(lumped())
    assert state.floor_temperature_c is not None
    again = GreenhouseMicroclimateState(**state.to_dict())
    assert again.floor_temperature_c == state.floor_temperature_c


# ---- one greenhouse for both models ---------------------------------------------------------------------------------------------------------
def test_the_lumped_model_reads_its_numbers_from_the_geometry_and_envelope_of_the_energyplus_model():
    spec = default_geometry(GreenhouseTypology.MULTITUNEL_CAPILLA)
    config, description = reduced_configuration(spec)
    built = build_greenhouse_idf(spec)
    assert config.thermal_exchange_area_m2 == pytest.approx(built.floor_area_m2) == pytest.approx(floor_area_m2(spec))
    assert config.volume_m3 == pytest.approx(built.volume_m3) == pytest.approx(volume_m3(spec))
    assert config.heat_loss_w_k == pytest.approx(cover_area_m2(spec) * EnvelopeSpec().cover_u_w_m2k.value)
    thermal = ThermalSpec()
    assert (config.ventilation_ach, config.passive_vent_ach, config.passive_vent_open_above_c, config.thermostat_setpoint_c, config.ground_temperature_c) == (
        thermal.infiltration_ach.value, thermal.max_ventilation_ach.value, thermal.vent_open_above_c.value, thermal.heating_setpoint_c.value, thermal.ground_temperature_c.value)
    assert config.heater_capacity_kw == pytest.approx(thermal.heater_capacity_w_m2.value * floor_area_m2(spec) / 1000.0)
    assert "PROVISIONAL" in description["sources"] and "NOT_VALIDATED" in description["sources"]
    line = f"Material, Floor Soil, MediumSmooth, {FLOOR_MATERIAL['thickness_m']:.2f}, {FLOOR_MATERIAL['conductivity_w_mk']:.2f}, {FLOOR_MATERIAL['density_kg_m3']:.0f}, {FLOOR_MATERIAL['specific_heat_j_kgk']:.0f}"
    assert line in built.text  # the floor layer both models use is one and the same


def test_every_typology_gets_a_valid_configuration_and_the_cover_is_larger_than_the_floor():
    for typology in GreenhouseTypology:
        config = reduced_configuration(default_geometry(typology))[0]
        assert config.thermal_exchange_area_m2 > 0 and config.heat_loss_w_k > config.thermal_exchange_area_m2 and 0.0 < config.solar_transmission <= 1.0


def test_the_layout_changes_the_simplified_results_which_it_never_did_before():
    base = {"crop": "tomato", "environment": "greenhouse", "end_time": "2026-02-24T00:00:00+00:00", "options": {"include_trajectory": True, "compute_trajectory_hash": True}}
    one = service.run_simulation(base)
    other = service.run_simulation({**base, "greenhouse": {"backend": "SIMPLIFIED", "layout": {"typology": "TUNEL"}}})
    assert one.result.trajectory_hash != other.result.trajectory_hash
    assert one.effective_configuration["greenhouse_backend"]["floor_area_m2"] != other.effective_configuration["greenhouse_backend"]["floor_area_m2"]


def test_a_greenhouse_run_is_deterministic_and_what_if_equals_the_continuous_run_with_the_floor_state():
    base = {"crop": "tomato", "environment": "greenhouse", "end_time": "2026-03-10T00:00:00+00:00", "options": {"include_trajectory": True, "compute_trajectory_hash": True}}
    plain = service.run_simulation(base)
    assert plain.result.trajectory_hash == service.run_simulation(base).result.trajectory_hash
    event = {"event_type": "SHADING", "start_simulation_time": "2026-03-01T00:00:00+00:00", "duration_hours": 24, "intensity": 0.5}
    result = InteractiveRuntimeService().what_if({"request": {k: v for k, v in base.items() if k != "options"}, "checkpoint_time": "2026-02-25T00:00:00+00:00", "events": [event]})
    prefix, baseline = result["prefix"]["result"]["trajectory"], result["branches"]["baseline"]["response"]["result"]["trajectory"]
    keep = [index for index, time in enumerate(baseline["time"]) if time > prefix["time"][-1]]
    for name in ("time", "temperature_c", "relative_humidity_pct", "greenhouse_heating_kw", "biomass_total_g_m2"):
        assert prefix[name] + [baseline[name][index] for index in keep] == plain.result.trajectory[name], name  # exact, including the hidden floor node


def test_the_constants_the_lumped_model_needs_are_declared_provisional_and_bounded():
    constants = reduced_model_constants()
    assert constants["evidence_status"] == "CONSISTENCY_WITH_ENERGYPLUS_NOT_VALIDATED"
    assert 0.0 < constants["incidence_factor"] <= 1.0 and 0.0 <= constants["solar_to_air_fraction"] <= 1.0 and constants["floor_film_coefficient_w_m2k"] > 0


def test_open_field_runs_have_no_greenhouse_block():
    assert parse_greenhouse_backend(None, "outdoor") is None
    assert layout_spec(parse_greenhouse_backend(None, "greenhouse")).typology is GreenhouseTypology.MULTITUNEL_CAPILLA
    assert simplified_configuration(parse_greenhouse_backend({"backend": "SIMPLIFIED", "layout": {"n_spans": 2}}, "greenhouse"))[0].thermal_exchange_area_m2 < \
        simplified_configuration(parse_greenhouse_backend(None, "greenhouse"))[0].thermal_exchange_area_m2
