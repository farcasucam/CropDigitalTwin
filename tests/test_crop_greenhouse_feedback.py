from datetime import datetime, timezone

import pytest

from agri_twin.application import SimulationClock, SimulationScheduler
from agri_twin.domain import (
    CropGreenhouseFeedbackConfiguration,
    CropGreenhouseFeedbackLoop,
    CropGrowthEngine,
    CropGrowthInput,
    CropGrowthState,
    CropPhysicalExchangeModel,
    GreenhouseActuatorState,
    GreenhouseConfiguration,
    MicroclimateState,
    SimplifiedGreenhouseModel,
    SoilState,
    WeatherState,
)
from agri_twin.infrastructure.energyplus_greenhouse import (
    EnergyPlusAvailability,
    EnergyPlusExecutionResult,
    EnergyPlusGreenhouseModel,
    EnergyPlusStatus,
)


T0 = datetime(2026, 7, 1, tzinfo=timezone.utc)


def weather(**changes):
    values = dict(temperature_c=28, relative_humidity_pct=60, solar_radiation_w_m2=700, wind_speed_m_s=2, wind_direction_deg=180, rain_rate_mm_h=0, pressure_hpa=1012)
    values.update(changes)
    return WeatherState(**values)


def crop(**changes):
    values = dict(simulation_time=T0, crop_key="tomato", variety="RAF", current_stage="vegetative_growth", biomass_total=50, biomass_leaf=50, leaf_area_index=2.0, root_depth_m=0.5, soil_water_vwc=0.25)
    values.update(changes)
    return CropGrowthState(**values)


def soil():
    return SoilState(0.25, 22, 0.35, 0.10, 20, 75)


def growth_for(state, micro=None, dt=3600):
    micro = micro or MicroclimateState(28, 60, 0.0, co2_ppm=420, pressure_hpa=1012, solar_radiation_w_m2=700, par_umol_m2_s=1400)
    return CropGrowthEngine().advance(state, CropGrowthInput(weather(temperature_c=micro.temperature_c, relative_humidity_pct=micro.relative_humidity_pct, solar_radiation_w_m2=micro.solar_radiation_w_m2), dt))


def test_transpiration_has_units_origin_and_responds_to_vpd():
    state = crop()
    model = CropPhysicalExchangeModel()
    low_vpd = MicroclimateState(25, 90, 0.0, co2_ppm=420, vpd_kpa=0.3, pressure_hpa=1012, solar_radiation_w_m2=500, par_umol_m2_s=1000)
    high_vpd = MicroclimateState(35, 20, 0.0, co2_ppm=420, vpd_kpa=2.5, pressure_hpa=1012, solar_radiation_w_m2=500, par_umol_m2_s=1000)
    low = model.calculate(state, growth_for(state, low_vpd), low_vpd, weather(), 3600, soil())
    high = model.calculate(state, growth_for(state, high_vpd), high_vpd, weather(), 3600, soil())
    assert high.transpiration_rate.value > low.transpiration_rate.value
    assert high.transpiration_rate.unit == "mm h-1"
    assert high.transpiration_rate.origin


def test_latent_heat_units_follow_water_vaporization():
    exchange = CropPhysicalExchangeModel().calculate(crop(), growth_for(crop()), MicroclimateState(28, 60, 0.0, co2_ppm=420, pressure_hpa=1012, solar_radiation_w_m2=700, par_umol_m2_s=1400), weather(), 3600, soil())
    assert exchange.latent_heat_flux.value == pytest.approx(exchange.transpiration_rate.value * 2_450_000 / 3600)
    assert exchange.latent_heat_flux.unit == "W m-2"


def test_sensible_heat_is_bounded_and_increases_with_lai():
    model = CropPhysicalExchangeModel()
    micro = MicroclimateState(28, 60, 0.0, co2_ppm=420, pressure_hpa=1012, solar_radiation_w_m2=700, par_umol_m2_s=1400)
    low = model.calculate(crop(leaf_area_index=0.5), growth_for(crop(leaf_area_index=0.5), micro), micro, weather(), 3600)
    high = model.calculate(crop(leaf_area_index=3), growth_for(crop(leaf_area_index=3), micro), micro, weather(), 3600)
    assert high.sensible_heat_flux.value >= low.sensible_heat_flux.value
    assert high.sensible_heat_flux.unit == "W m-2"


def test_co2_exchange_depends_on_growth_not_fixed_value():
    state = crop()
    model = CropPhysicalExchangeModel()
    micro = MicroclimateState(28, 60, 0.0, co2_ppm=420, pressure_hpa=1012, solar_radiation_w_m2=700, par_umol_m2_s=1400)
    growth = growth_for(state, micro)
    exchange = model.calculate(state, growth, micro, weather(), 3600)
    assert exchange.co2_uptake.value > 0
    assert exchange.co2_uptake.origin != "fixed"
    assert model.calculate(state, growth_for(state, micro, 0.0), micro, weather(), 3600).co2_uptake.value == 0


def test_feedback_loop_converges_with_simplified_model_and_returns_feedback():
    loop = CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel())
    result = loop.step(crop(), weather(), GreenhouseConfiguration(), GreenhouseActuatorState(), 3600, soil())
    assert result.convergence.converged
    assert result.convergence.iterations <= 8
    assert result.feedback.transpiration_mm_h >= 0
    assert isinstance(result.microclimate, MicroclimateState)
    assert result.crop.biomass_total >= 50


def test_higher_radiation_increases_growth_potential_and_interception():
    loop = CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel())
    low = loop.step(crop(), weather(solar_radiation_w_m2=200), GreenhouseConfiguration(), GreenhouseActuatorState(), 3600)
    high = loop.step(crop(), weather(solar_radiation_w_m2=900), GreenhouseConfiguration(), GreenhouseActuatorState(), 3600)
    assert high.crop_growth.potential_growth_g_m2 > low.crop_growth.potential_growth_g_m2
    assert high.feedback.intercepted_radiation_w_m2 > low.feedback.intercepted_radiation_w_m2


def test_shading_and_ventilation_change_the_feedback_path():
    loop = CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel())
    shaded = loop.step(crop(), weather(), GreenhouseConfiguration(), GreenhouseActuatorState(shading_fraction=0.7), 3600)
    ventilated = loop.step(crop(), weather(temperature_c=35), GreenhouseConfiguration(), GreenhouseActuatorState(ventilation_ach=12), 3600)
    baseline = loop.step(crop(), weather(), GreenhouseConfiguration(), GreenhouseActuatorState(), 3600)
    assert shaded.microclimate.solar_radiation_w_m2 < baseline.microclimate.solar_radiation_w_m2
    assert ventilated.microclimate.temperature_c != baseline.microclimate.temperature_c


def test_non_convergence_is_explicit_and_reports_last_state():
    configuration = CropGreenhouseFeedbackConfiguration(max_iterations=1, tolerance_temperature_c=1e-12, tolerance_relative_humidity_pct=1e-12, tolerance_co2_ppm=1e-12)
    result = CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel(), configuration=configuration).step(crop(), weather(), GreenhouseConfiguration(), GreenhouseActuatorState(), 3600)
    assert not result.convergence.converged
    assert result.convergence.iterations == 1
    assert result.convergence.reason == "maximum iterations reached"
    assert result.convergence.final_error > 1
    assert result.microclimate.temperature_c >= 0


def test_relaxation_is_configurable_and_deterministic():
    unrelaxed = CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel(), configuration=CropGreenhouseFeedbackConfiguration(max_iterations=1, relaxation_alpha=1.0)).step(crop(), weather(), GreenhouseConfiguration(), GreenhouseActuatorState(), 3600)
    relaxed = CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel(), configuration=CropGreenhouseFeedbackConfiguration(max_iterations=1, relaxation_alpha=0.5)).step(crop(), weather(), GreenhouseConfiguration(), GreenhouseActuatorState(), 3600)
    assert relaxed.microclimate.temperature_c != unrelaxed.microclimate.temperature_c
    assert relaxed == CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel(), configuration=CropGreenhouseFeedbackConfiguration(max_iterations=1, relaxation_alpha=0.5)).step(crop(), weather(), GreenhouseConfiguration(), GreenhouseActuatorState(), 3600)


@pytest.mark.parametrize("alpha", [0, -0.1, 1.1])
def test_relaxation_bounds(alpha):
    with pytest.raises(ValueError):
        CropGreenhouseFeedbackConfiguration(relaxation_alpha=alpha)


def test_clock_and_scheduler_control_external_timestep_only():
    clock = SimulationClock(T0)
    scheduler = SimulationScheduler(clock, 3600)
    loop = CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel())
    results = []
    scheduler.register("feedback", 3600, lambda timestamp: results.append(loop.step(crop(simulation_time=timestamp), weather(), GreenhouseConfiguration(), GreenhouseActuatorState(), 3600)))
    scheduler.advance(3600)
    assert len(results) == 1
    assert clock.now() == T0.replace(hour=1)
    assert results[0].crop.simulation_time == T0.replace(hour=1)


def test_feedback_state_has_no_nan_or_invalid_humidity_co2():
    result = CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel()).step(crop(), weather(temperature_c=40, relative_humidity_pct=10), GreenhouseConfiguration(), GreenhouseActuatorState(), 3600)
    assert 0 <= result.microclimate.relative_humidity_pct <= 100
    assert result.microclimate.co2_ppm >= 0
    assert all(value == value and abs(value) != float("inf") for value in (result.microclimate.temperature_c, result.feedback.transpiration_mm_h, result.feedback.latent_heat_w_m2, result.feedback.co2_uptake_ppm))


def test_same_loop_contract_is_compatible_with_energyplus_backend_boundary():
    values = {"air_temperature_c": 27, "relative_humidity_pct": 60, "solar_radiation_w_m2": 500, "ventilation_ach": 2, "heating_energy_j": 0, "cooling_energy_j": 0, "co2_ppm": 420}

    class Runner:
        def run(self, **kwargs):
            return EnergyPlusExecutionResult(values)

    backend = EnergyPlusGreenhouseModel(Runner(), EnergyPlusAvailability(EnergyPlusStatus.AVAILABLE))
    result = CropGreenhouseFeedbackLoop(backend).step(crop(), weather(), GreenhouseConfiguration(), GreenhouseActuatorState(), 3600)
    assert result.microclimate.temperature_c == 27
    assert result.convergence.iterations <= 8
