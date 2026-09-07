from datetime import datetime, timezone

import pytest

from agri_twin.application import SimulationClock, SimulationScheduler
from agri_twin.domain import (
    CropMicroclimateFeedback,
    GreenhouseActuatorState,
    GreenhouseConfiguration,
    GreenhousePhysicalModel,
    MicroclimateState,
    WeatherState,
)
from agri_twin.infrastructure.energyplus_greenhouse import (
    ENERGYPLUS_VARIABLES,
    EnergyPlusAvailability,
    EnergyPlusBackendError,
    EnergyPlusGreenhouseModel,
    EnergyPlusStatus,
    EnergyPlusVariableUnavailable,
    EnergyPlusExecutionResult,
    detect_energyplus,
)


WEATHER = WeatherState(25, 60, 500, 2, 180, 0, 1012)
CONFIGURATION = GreenhouseConfiguration()
ACTUATORS = GreenhouseActuatorState(ventilation_ach=2, shading_fraction=0.25)
FEEDBACK = CropMicroclimateFeedback()


def variables(**changes):
    values = {
        "air_temperature_c": 26.0,
        "relative_humidity_pct": 55.0,
        "solar_radiation_w_m2": 350.0,
        "ventilation_ach": 2.0,
        "heating_energy_j": 720000.0,
        "cooling_energy_j": 360000.0,
        "co2_ppm": 430.0,
    }
    values.update(changes)
    return values


class FakeRunner:
    def __init__(self, result=None, error=None):
        self.calls = []
        self.result = result or EnergyPlusExecutionResult(variables())
        self.error = error

    def run(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


def test_detection_is_explicit_and_does_not_require_energyplus():
    assert detect_energyplus().status in set(EnergyPlusStatus)


def test_availability_has_diagnostics_for_every_state():
    availability = EnergyPlusAvailability(EnergyPlusStatus.UNAVAILABLE, detail="missing")
    assert availability.status is EnergyPlusStatus.UNAVAILABLE
    assert availability.detail == "missing"
    assert availability.python_api is False


@pytest.mark.parametrize("status", list(EnergyPlusStatus))
def test_all_availability_statuses_are_representable(status):
    assert EnergyPlusAvailability(status).status is status


def test_unavailable_backend_is_explicit_and_does_not_fallback():
    model = EnergyPlusGreenhouseModel(availability=EnergyPlusAvailability(EnergyPlusStatus.UNAVAILABLE, detail="not installed"))
    with pytest.raises(EnergyPlusBackendError, match="UNAVAILABLE"):
        model.step(WEATHER, CONFIGURATION, GreenhouseActuatorState(), FEEDBACK, 3600)


def test_backend_implements_common_contract():
    assert issubclass(EnergyPlusGreenhouseModel, GreenhousePhysicalModel)


def test_invalid_timestep_is_rejected():
    with pytest.raises(ValueError):
        EnergyPlusGreenhouseModel(timestep_seconds=0)
    model = EnergyPlusGreenhouseModel(runner=FakeRunner())
    with pytest.raises(ValueError):
        model.step(WEATHER, CONFIGURATION, GreenhouseActuatorState(), FEEDBACK, 0)


def test_runner_receives_weather_configuration_actuators_and_timestep():
    runner = FakeRunner()
    model = EnergyPlusGreenhouseModel(runner=runner, availability=EnergyPlusAvailability(EnergyPlusStatus.AVAILABLE))
    result = model.step(WEATHER, CONFIGURATION, ACTUATORS, FEEDBACK, 1800)
    assert isinstance(result, MicroclimateState)
    assert runner.calls[0]["weather"] == WEATHER
    assert runner.calls[0]["configuration"] == CONFIGURATION
    assert runner.calls[0]["actuators"] == ACTUATORS
    assert runner.calls[0]["dt_seconds"] == 1800


def test_real_energyplus_variables_convert_to_microclimate_state():
    model = EnergyPlusGreenhouseModel(runner=FakeRunner(), availability=EnergyPlusAvailability(EnergyPlusStatus.AVAILABLE))
    state = model.step(WEATHER, CONFIGURATION, ACTUATORS, FEEDBACK, 3600)
    assert state.temperature_c == 26.0
    assert state.relative_humidity_pct == 55.0
    assert state.solar_radiation_w_m2 == 350.0
    assert state.heating_kw == pytest.approx(0.2)
    assert state.cooling_kw == pytest.approx(0.1)
    assert state.shading_fraction == 0.25
    assert state.pressure_hpa == WEATHER.pressure_hpa


def test_missing_energyplus_variable_is_not_falsified():
    incomplete = variables()
    incomplete.pop("co2_ppm")
    model = EnergyPlusGreenhouseModel(
        runner=FakeRunner(EnergyPlusExecutionResult(incomplete)),
        availability=EnergyPlusAvailability(EnergyPlusStatus.AVAILABLE),
    )
    with pytest.raises(EnergyPlusVariableUnavailable, match="co2"):
        model.step(WEATHER, CONFIGURATION, GreenhouseActuatorState(), FEEDBACK, 3600)


def test_runner_errors_are_propagated():
    model = EnergyPlusGreenhouseModel(
        runner=FakeRunner(error=EnergyPlusBackendError("runtime failed")),
        availability=EnergyPlusAvailability(EnergyPlusStatus.AVAILABLE),
    )
    with pytest.raises(EnergyPlusBackendError, match="runtime failed"):
        model.step(WEATHER, CONFIGURATION, GreenhouseActuatorState(), FEEDBACK, 3600)


def test_determinism_and_state_reset():
    model = EnergyPlusGreenhouseModel(runner=FakeRunner(), availability=EnergyPlusAvailability(EnergyPlusStatus.AVAILABLE))
    first = model.step(WEATHER, CONFIGURATION, GreenhouseActuatorState(), FEEDBACK, 3600)
    second = model.step(WEATHER, CONFIGURATION, GreenhouseActuatorState(), FEEDBACK, 3600)
    assert first == second
    assert model.state() == second
    model.reset()
    with pytest.raises(EnergyPlusBackendError, match="no state"):
        model.state()


def test_variable_registry_contains_only_idf_declared_names():
    assert ENERGYPLUS_VARIABLES["air_temperature_c"] == "Zone Air Temperature"
    assert ENERGYPLUS_VARIABLES["solar_radiation_w_m2"] == "Surface Window Transmitted Solar Radiation Rate"


def test_simulation_clock_remains_external_to_backend():
    clock = SimulationClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    runner = FakeRunner()
    model = EnergyPlusGreenhouseModel(runner=runner, availability=EnergyPlusAvailability(EnergyPlusStatus.AVAILABLE))
    clock.advance(3600)
    model.step(WEATHER, CONFIGURATION, GreenhouseActuatorState(), FEEDBACK, 3600)
    assert runner.calls[0]["dt_seconds"] == 3600
    assert clock.now().hour == 1


def test_scheduler_can_schedule_backend_without_backend_advancing_clock():
    clock = SimulationClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    scheduler = SimulationScheduler(clock, timestep_seconds=60)
    runner = FakeRunner()
    model = EnergyPlusGreenhouseModel(runner=runner, availability=EnergyPlusAvailability(EnergyPlusStatus.AVAILABLE))
    scheduler.register("energyplus", 60, lambda moment: model.step(WEATHER, CONFIGURATION, GreenhouseActuatorState(), FEEDBACK, 60))
    scheduler.advance(60)
    assert len(runner.calls) == 1
    assert clock.now().minute == 1
