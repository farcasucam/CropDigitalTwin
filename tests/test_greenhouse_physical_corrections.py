"""Phase 5.30 physical-consistency corrections of the greenhouse-crop chain."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agri_twin.application.clock import SimulationClock
from agri_twin.application.integrated_synthetic_validation import SINGLETON_CLASSES, static_audit
from agri_twin.application.orchestrator import CropDigitalTwinOrchestrator
from agri_twin.application.scenarios import Scenario, ScenarioEvent, ScenarioKind, ScenarioRunner
from agri_twin.application.twin_state import TwinState
from agri_twin.application.weather import WeatherEngine
from agri_twin.domain import (
    ActuatorControl,
    CropGreenhouseFeedbackLoop,
    CropGrowthEngine,
    CropGrowthError,
    CropGrowthInput,
    CropGrowthState,
    CropMicroclimateFeedback,
    CropPhysicalExchangeModel,
    GreenhouseActuatorState,
    GreenhouseConfiguration,
    MicroclimateState,
    ParameterRegistry,
    PhenologyEngine,
    RadiationGrowthEngine,
    SimplifiedGreenhouseModel,
    SoilState,
    WaterBalanceEngine,
    WeatherConfiguration,
    WeatherState,
)
from agri_twin.domain.greenhouse import (
    AIR_DENSITY_KG_M3,
    AIR_SPECIFIC_HEAT_J_KG_K,
    saturation_vapour_density_kg_m3,
    vapour_density_kg_m3,
    vapour_pressure_deficit_kpa,
)

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 7, 1, tzinfo=timezone.utc)


def weather(**changes):
    values = dict(temperature_c=20.0, relative_humidity_pct=50.0, solar_radiation_w_m2=0.0, wind_speed_m_s=2.0, wind_direction_deg=180.0, rain_rate_mm_h=0.0, pressure_hpa=1013.0)
    values.update(changes)
    return WeatherState(**values)


def micro(temperature=20.0, humidity=50.0, co2=420.0, radiation=0.0):
    return MicroclimateState(air_temperature_c=temperature, relative_humidity_pct=humidity, vpd_kpa=vapour_pressure_deficit_kpa(temperature, humidity), pressure_hpa=1013.0, solar_radiation_w_m2=radiation, par_umol_m2_s=radiation * 2.04, co2_ppm=co2)


def crop(**changes):
    values = dict(simulation_time=T0, crop_key="tomato", variety="RAF", current_stage="vegetative_growth", biomass_total=100.0, biomass_leaf=60.0, biomass_stem=20.0, biomass_root=20.0, leaf_area_index=1.2, root_depth_m=0.6, soil_water_vwc=0.3, phenology_model="TEST")
    values.update(changes)
    return CropGrowthState(**values)


def soil():
    return SoilState(0.30, 18.0, 0.35, 0.10, 0.0, 120.0)


def closed(**changes):
    return GreenhouseConfiguration(ventilation_ach=0.0, **changes)


def step(prior, outdoor, configuration, actuators=None, feedback=None, dt=3600.0):
    return SimplifiedGreenhouseModel().step(outdoor, configuration, actuators or GreenhouseActuatorState(), feedback or CropMicroclimateFeedback(), dt, prior=prior)


def growth(state, microclimate, dt=3600.0):
    return CropGrowthEngine().advance(state, CropGrowthInput(weather(temperature_c=microclimate.temperature_c, relative_humidity_pct=microclimate.relative_humidity_pct, solar_radiation_w_m2=microclimate.solar_radiation_w_m2), dt))


# --- Defect 1: saturation and latent flux -------------------------------------


def test_saturated_air_blocks_transpiration_and_latent_flux():
    saturated = micro(24.0, 100.0, radiation=600.0)
    assert saturated.vpd_kpa == 0.0
    model = CropPhysicalExchangeModel()
    state = crop()
    for soil_state in (soil(), None):
        exchange = model.calculate(state, growth(state, saturated), saturated, weather(), 3600.0, soil_state)
        assert exchange.transpiration_rate.value == 0.0
        assert exchange.latent_heat_flux.value == 0.0


def test_positive_vpd_keeps_the_water_balance_demand_from_indoor_air():
    indoor = micro(28.0, 50.0, radiation=600.0)
    state = crop()
    exchange = CropPhysicalExchangeModel().calculate(state, growth(state, indoor), indoor, weather(temperature_c=15.0, solar_radiation_w_m2=900.0), 3600.0, soil())
    indoor_weather = WeatherState(28.0, 50.0, 600.0, 2.0, 180.0, 0.0, 1013.0)
    expected = WaterBalanceEngine().advance(soil(), indoor_weather, 3600.0, state).transpiration_mm
    assert exchange.transpiration_rate.value == pytest.approx(expected)
    assert "indoor microclimate" in exchange.transpiration_rate.origin


def test_high_humidity_limits_transpiration_to_the_vapour_deficit():
    humid = micro(28.0, 99.99, radiation=700.0)
    state = crop()
    model = CropPhysicalExchangeModel()
    limited = model.calculate(state, growth(state, humid), humid, weather(), 3600.0, soil())
    demand = WaterBalanceEngine().advance(soil(), WeatherState(28.0, 99.99, 700.0, 2.0, 180.0, 0.0, 1013.0), 3600.0, state).transpiration_mm
    capacity = humid.vpd_kpa * 1000.0 / (461.5 * (28.0 + 273.15)) * model.configuration.air_volume_m3
    assert capacity < demand
    assert limited.transpiration_rate.value == pytest.approx(capacity)


def test_closed_greenhouse_never_exceeds_saturation_or_evaporates_into_saturated_air():
    loop = CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel())
    state = crop()
    for hour in range(96):
        now = T0 + timedelta(hours=hour + 1)
        outdoor = weather(temperature_c=18.0 + 8.0 * math.sin(2 * math.pi * (hour - 8) / 24), relative_humidity_pct=85.0, solar_radiation_w_m2=max(0.0, 800.0 * math.sin(2 * math.pi * (hour - 6) / 24)))
        result = loop.step(state, outdoor, closed(), GreenhouseActuatorState(), 3600.0, soil(), simulation_time=now)
        indoor = result.microclimate
        assert indoor.relative_humidity_pct <= 100.0
        if indoor.vpd_kpa <= 1e-12:
            assert result.exchange.latent_heat_flux.value == 0.0
        state = result.crop.advance(now, 3600.0)


# --- Defect 2: ventilation ----------------------------------------------------


@pytest.mark.parametrize("quantity", ["temperature", "vapour", "co2"])
def test_ventilation_ach_moves_indoor_air_toward_outdoor(quantity):
    prior = micro(35.0, 90.0, co2=900.0)
    outdoor = weather(temperature_c=20.0, relative_humidity_pct=40.0)
    gaps = []
    for ach in (0.0, 1.0, 5.0):
        state = step(prior, outdoor, GreenhouseConfiguration(ventilation_ach=ach, heat_loss_w_k=0.0))
        gaps.append({
            "temperature": abs(state.temperature_c - outdoor.temperature_c),
            "vapour": abs(vapour_density_kg_m3(state.temperature_c, state.relative_humidity_pct) - vapour_density_kg_m3(20.0, 40.0)),
            "co2": abs(state.co2_ppm - 420.0),
        }[quantity])
    assert gaps[0] > gaps[1] > gaps[2] > 0


def test_zero_ventilation_and_no_conduction_is_a_closed_box():
    prior = micro(30.0, 60.0, co2=700.0)
    state = step(prior, weather(temperature_c=10.0, relative_humidity_pct=30.0), closed(heat_loss_w_k=0.0))
    assert state.ventilation_fraction == 0.0
    assert state.temperature_c == pytest.approx(30.0)
    assert state.co2_ppm == pytest.approx(700.0)
    assert vapour_density_kg_m3(state.temperature_c, state.relative_humidity_pct) == pytest.approx(vapour_density_kg_m3(30.0, 60.0))


def test_exchanged_fraction_is_the_exact_first_order_air_exchange():
    configuration = GreenhouseConfiguration(ventilation_ach=2.0)
    state = step(micro(), weather(), configuration, GreenhouseActuatorState(ventilation_ach=1.0), dt=1800.0)
    assert state.ventilation_fraction == pytest.approx(1.0 - math.exp(-3.0 * 0.5))


def test_configured_ventilation_is_used_by_the_model():
    prior = micro(35.0, 60.0, co2=900.0)
    outdoor = weather(temperature_c=20.0)
    ventilated = step(prior, outdoor, GreenhouseConfiguration(ventilation_ach=3.0))
    sealed = step(prior, outdoor, closed())
    assert ventilated.co2_ppm < sealed.co2_ppm
    assert ventilated.temperature_c < sealed.temperature_c


# --- Defect 3: thermal balance --------------------------------------------------


def test_equal_indoor_and_outdoor_temperature_gives_no_external_exchange():
    state = step(micro(22.0), weather(temperature_c=22.0), GreenhouseConfiguration())
    assert state.temperature_c == pytest.approx(22.0)


def test_indoor_hotter_than_outdoor_loses_heat_through_the_cover_when_closed():
    state = step(micro(30.0), weather(temperature_c=10.0), closed())
    conductance, capacity = 80.0, 2_500_000.0
    assert state.temperature_c == pytest.approx(10.0 + 20.0 * math.exp(-conductance / capacity * 3600.0))
    assert 10.0 < state.temperature_c < 30.0


def test_indoor_colder_than_outdoor_gains_heat():
    state = step(micro(5.0), weather(temperature_c=25.0), GreenhouseConfiguration())
    assert 5.0 < state.temperature_c < 25.0


def test_heat_exchange_depends_on_the_indoor_outdoor_difference_not_a_fixed_reference():
    cold = step(micro(8.0), weather(temperature_c=5.0), GreenhouseConfiguration())
    warm = step(micro(33.0), weather(temperature_c=30.0), GreenhouseConfiguration())
    assert cold.temperature_c - 5.0 == pytest.approx(warm.temperature_c - 30.0)


def test_exact_integration_is_stable_and_bounded_for_very_large_steps():
    configuration = GreenhouseConfiguration()
    solar = 700.0 * configuration.solar_transmission * configuration.thermal_exchange_area_m2
    conductance = configuration.heat_loss_w_k + AIR_DENSITY_KG_M3 * AIR_SPECIFIC_HEAT_J_KG_K * configuration.volume_m3 * configuration.ventilation_ach / 3600.0
    state = step(micro(40.0), weather(temperature_c=20.0, solar_radiation_w_m2=700.0), configuration, dt=30 * 86400.0)
    assert state.temperature_c == pytest.approx(20.0 + solar / conductance)


def test_outdoor_heat_raises_indoor_temperature():
    prior = micro(22.0)
    mild = step(prior, weather(temperature_c=22.0), GreenhouseConfiguration())
    hot = step(prior, weather(temperature_c=38.0), GreenhouseConfiguration())
    assert hot.temperature_c > mild.temperature_c


# --- Humidity / VPD -----------------------------------------------------------------


def test_misting_humidifies_and_cools_the_air():
    prior = micro(30.0, 30.0)
    dry = step(prior, weather(temperature_c=30.0, relative_humidity_pct=30.0), closed())
    misted = step(prior, weather(temperature_c=30.0, relative_humidity_pct=30.0), closed(), GreenhouseActuatorState(misting_mm_h=0.5))
    assert misted.relative_humidity_pct > dry.relative_humidity_pct
    assert misted.temperature_c < dry.temperature_c


def test_outdoor_bypass_reports_the_physical_vpd():
    outdoor = weather(temperature_c=30.0, relative_humidity_pct=40.0)
    state = SimplifiedGreenhouseModel().step(outdoor, GreenhouseConfiguration(mode="outdoor"), GreenhouseActuatorState(), CropMicroclimateFeedback(), 3600.0)
    assert state.vpd_kpa == pytest.approx(vapour_pressure_deficit_kpa(30.0, 40.0)) and state.vpd_kpa > 2.0


def test_vapour_state_is_bounded_by_saturation_after_cooling():
    prior = micro(30.0, 95.0)
    cooled = step(prior, weather(temperature_c=5.0, relative_humidity_pct=95.0), closed(), dt=12 * 3600.0)
    assert cooled.relative_humidity_pct == pytest.approx(100.0)
    assert vapour_density_kg_m3(cooled.temperature_c, cooled.relative_humidity_pct) <= saturation_vapour_density_kg_m3(cooled.temperature_c) + 1e-12


# --- Defect 4: the crop consumes the microclimate -------------------------------------


def orchestrator(mode="passive_greenhouse", **weather_changes):
    engine = WeatherEngine(WeatherConfiguration(), provider=type("Constant", (), {"get": staticmethod(lambda _t: weather(**weather_changes))})())
    return CropDigitalTwinOrchestrator(SimulationClock(T0), engine, crop(), soil(), mode)


def test_crop_receives_indoor_temperature_not_outdoor():
    twin = orchestrator(temperature_c=5.0, solar_radiation_w_m2=0.0)
    heating = {"heating": ActuatorControl(20.0, maximum=20.0, capacity=20.0)}
    snapshot = twin.step(3600.0, heating)
    indoor = snapshot.microclimate.indoor_state.temperature_c
    assert indoor > snapshot.outdoor_weather.temperature_c + 1.0
    assert snapshot.weather.temperature_c == indoor
    profile = PhenologyEngine().profile_for("tomato")
    assert snapshot.crop.gdd_accumulated == pytest.approx(PhenologyEngine.degree_days(indoor, profile, 3600.0))


def test_crop_receives_indoor_humidity_vpd_and_radiation():
    snapshot = orchestrator(temperature_c=28.0, relative_humidity_pct=40.0, solar_radiation_w_m2=800.0).step(3600.0, {"shade": ActuatorControl(0.5)})
    indoor = snapshot.microclimate.indoor_state
    assert snapshot.weather.relative_humidity_pct == indoor.relative_humidity_pct
    assert snapshot.weather.solar_radiation_w_m2 == indoor.solar_radiation_w_m2 < snapshot.outdoor_weather.solar_radiation_w_m2
    assert snapshot.environment.vpd_kpa == indoor.vpd_kpa


def test_no_rain_reaches_the_crop_inside_the_greenhouse():
    rainy = orchestrator(rain_rate_mm_h=10.0).step(3600.0)
    dry = orchestrator(rain_rate_mm_h=0.0).step(3600.0)
    assert rainy.weather.rain_rate_mm_h == 0.0
    assert rainy.soil == dry.soil
    outdoor = orchestrator("outdoor", rain_rate_mm_h=10.0).step(3600.0)
    assert outdoor.weather.rain_rate_mm_h == 10.0


def test_outdoor_mode_keeps_outdoor_weather_as_the_crop_environment():
    snapshot = orchestrator("outdoor", temperature_c=26.0, relative_humidity_pct=35.0, solar_radiation_w_m2=600.0).step(3600.0)
    assert snapshot.weather == snapshot.outdoor_weather
    assert snapshot.environment.vpd_kpa == pytest.approx(vapour_pressure_deficit_kpa(26.0, 35.0))


def test_orchestrator_greenhouse_state_is_persistent_between_steps():
    twin = orchestrator(temperature_c=10.0)
    first = twin.step(3600.0, {"co2": ActuatorControl(500.0, maximum=2000.0, capacity=2000.0)})
    second = twin.step(3600.0)
    assert second.microclimate.indoor_state.co2_ppm > 420.0
    assert second.microclimate.indoor_state.co2_ppm < first.microclimate.indoor_state.co2_ppm


# --- Defect 5: CO2 pathway -------------------------------------------------------


@pytest.mark.parametrize(("co2", "factor"), [(210.0, 0.5), (420.0, 1.0), (840.0, 1.0)])
def test_co2_response_levels(co2, factor):
    assert CropGrowthEngine.co2_response(co2) == pytest.approx(factor)


def test_co2_response_is_applied_exactly_once():
    indoor = micro(25.0, 60.0, radiation=700.0)
    state = crop()
    base = CropGrowthInput(weather(temperature_c=25.0, relative_humidity_pct=60.0, solar_radiation_w_m2=700.0), 3600.0)
    low = CropGrowthEngine().advance(state, replace(base, co2_ppm=210.0))
    ambient = CropGrowthEngine().advance(state, replace(base, co2_ppm=420.0))
    high = CropGrowthEngine().advance(state, replace(base, co2_ppm=840.0))
    explicit = CropGrowthEngine().advance(state, replace(base, co2_factor=0.5))
    assert low.actual_growth_g_m2 == pytest.approx(0.5 * ambient.actual_growth_g_m2)
    assert high.actual_growth_g_m2 == pytest.approx(ambient.actual_growth_g_m2)
    assert low.actual_growth_g_m2 == pytest.approx(explicit.actual_growth_g_m2)
    with pytest.raises(CropGrowthError):
        CropGrowthInput(base.weather, 3600.0, co2_factor=0.5, co2_ppm=210.0)
    assert indoor.co2_ppm == 420.0


def test_orchestrator_and_feedback_loop_share_the_same_co2_response():
    snapshot = orchestrator().step(3600.0, {"co2": ActuatorControl(300.0, maximum=2000.0, capacity=2000.0)})
    assert snapshot.co2_factor == CropGrowthEngine.co2_response(snapshot.microclimate.indoor_state.co2_ppm)
    depleted = micro(25.0, 60.0, co2=300.0, radiation=600.0)
    result = CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel())._grow(crop(), weather(), depleted, 3600.0, T0)
    assert result.co2_factor == CropGrowthEngine.co2_response(300.0)


# --- Defect 6: dormancy ----------------------------------------------------------


def test_endodormancy_blocks_active_growth_in_both_growth_engines():
    dormant = crop(current_stage="establishment", dormancy_released=False, crop_key="plum", variety="Suplum 26")
    sunny = weather(temperature_c=20.0, solar_radiation_w_m2=800.0)
    assert RadiationGrowthEngine().advance(dormant, sunny, 86400.0) == dormant
    result = CropGrowthEngine().advance(dormant, CropGrowthInput(sunny, 86400.0))
    assert result.actual_growth_g_m2 == 0.0
    assert result.state.biomass_total == dormant.biomass_total
    assert result.state.leaf_area_index == dormant.leaf_area_index
    assert result.state.maturity_index == dormant.maturity_index
    assert PhenologyEngine.growth_active(replace(dormant, dormancy_released=True)) is True


def test_perennial_chilling_release_forcing_and_budburst_transition():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    initial = crop(simulation_time=start, crop_key="peach", variety="UNSPECIFIED", current_stage="establishment", biomass_total=45.0, biomass_leaf=5.0, biomass_stem=20.0, biomass_root=20.0, leaf_area_index=0.1, dormancy_released=False)
    events = (
        ScenarioEvent("chill", "cold", start, start + timedelta(days=30), 4.0, {"temperature_c": 4.0}),
        ScenarioEvent("irrigation", "irrigation", start, start + timedelta(days=80), 0.4, {"amount_mm": 0.4}),
    )
    scenario = Scenario("p530_dormancy", "dormancy", "chilling then forcing", "peach", None, start, start + timedelta(days=80), 3600, ScenarioKind.SYNTHETIC, initial, soil(), weather(temperature_c=20.0, solar_radiation_w_m2=500.0), "outdoor", events)
    snapshots = ScenarioRunner().run(scenario).snapshots
    requirement = PhenologyEngine().profile_for("peach").chilling_requirement_hours
    release = next(index for index, snapshot in enumerate(snapshots) if snapshot.crop.dormancy_released)
    dormant = snapshots[:release]
    assert all(snapshot.crop.gdd_accumulated == 0.0 and snapshot.crop.biomass_total == 45.0 for snapshot in dormant)
    assert [snapshot.crop.chilling_hours for snapshot in dormant] == sorted(snapshot.crop.chilling_hours for snapshot in dormant)
    assert snapshots[release].crop.chilling_hours == pytest.approx(requirement)
    forcing = snapshots[release + 1:]
    # Forcing: GDD accumulate only above Tbase (4 C chilling air < peach Tbase 4.5 C).
    first_forcing = next(index for index, snapshot in enumerate(forcing) if snapshot.crop.gdd_accumulated > 0.0)
    assert forcing[first_forcing].simulation_time > start + timedelta(days=30)
    assert [snapshot.crop.gdd_accumulated for snapshot in forcing] == sorted(snapshot.crop.gdd_accumulated for snapshot in forcing)
    budburst = next(index for index, snapshot in enumerate(forcing) if snapshot.crop.current_stage == "vegetative_growth")
    assert budburst > 0 and forcing[-1].crop.biomass_total > 45.0
    assert all(snapshot.crop.current_stage == "establishment" for snapshot in snapshots[:release + 1])


# --- Feedback loop -----------------------------------------------------------------


def test_feedback_iterations_restart_from_the_same_start_of_step_state():
    start = micro(26.0, 55.0, radiation=650.0)
    outdoor = weather(temperature_c=24.0, relative_humidity_pct=60.0, solar_radiation_w_m2=800.0)
    first = CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel()).step(crop(), outdoor, GreenhouseConfiguration(), GreenhouseActuatorState(), 3600.0, soil(), prior=start)
    polluted_model = SimplifiedGreenhouseModel()
    polluted_model.step(weather(temperature_c=45.0), GreenhouseConfiguration(), GreenhouseActuatorState(), CropMicroclimateFeedback(), 3600.0)
    second = CropGreenhouseFeedbackLoop(polluted_model).step(crop(), outdoor, GreenhouseConfiguration(), GreenhouseActuatorState(), 3600.0, soil(), prior=start)
    assert first.microclimate.to_dict() == second.microclimate.to_dict()


def test_only_the_converged_state_is_carried_to_the_next_timestep():
    loop = CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel())
    result = loop.step(crop(), weather(solar_radiation_w_m2=700.0), GreenhouseConfiguration(), GreenhouseActuatorState(), 3600.0, soil())
    assert loop.last_converged is result.microclimate
    explicit = CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel()).step(crop(simulation_time=T0 + timedelta(hours=1)), weather(solar_radiation_w_m2=700.0), GreenhouseConfiguration(), GreenhouseActuatorState(), 3600.0, soil(), prior=result.microclimate)
    carried = loop.step(crop(simulation_time=T0 + timedelta(hours=1)), weather(solar_radiation_w_m2=700.0), GreenhouseConfiguration(), GreenhouseActuatorState(), 3600.0, soil())
    assert carried.microclimate.to_dict() == explicit.microclimate.to_dict()


@pytest.mark.parametrize("ach", [0.0, 0.3, 3.0])
def test_feedback_converges_after_corrections(ach):
    loop = CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel())
    state = crop()
    for hour in range(48):
        now = T0 + timedelta(hours=hour + 1)
        outdoor = weather(temperature_c=20.0 + 8.0 * math.sin(2 * math.pi * (hour - 9) / 24), relative_humidity_pct=60.0, solar_radiation_w_m2=max(0.0, 850.0 * math.sin(2 * math.pi * (hour - 6) / 24)))
        result = loop.step(state, outdoor, GreenhouseConfiguration(ventilation_ach=ach), GreenhouseActuatorState(), 3600.0, soil(), simulation_time=now)
        assert result.convergence.converged
        assert result.convergence.iterations <= loop.configuration.max_iterations
        state = result.crop.advance(now, 3600.0)


@pytest.mark.parametrize("outdoor", [
    dict(temperature_c=-15.0, relative_humidity_pct=95.0, solar_radiation_w_m2=0.0),
    dict(temperature_c=48.0, relative_humidity_pct=5.0, solar_radiation_w_m2=1300.0),
    dict(temperature_c=25.0, relative_humidity_pct=100.0, solar_radiation_w_m2=900.0),
])
def test_no_nan_or_inf_in_extreme_conditions(outdoor):
    for ach in (0.0, 30.0):
        result = CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel()).step(crop(), weather(**outdoor), GreenhouseConfiguration(ventilation_ach=ach), GreenhouseActuatorState(co2_supply_ppm=100.0, misting_mm_h=1.0), 3600.0, soil())
        values = [*result.microclimate.to_dict().values(), result.feedback.transpiration_mm_h, result.feedback.latent_heat_w_m2, result.crop_growth.actual_growth_g_m2]
        assert all(math.isfinite(value) for value in values)
        assert 0.0 <= result.microclimate.relative_humidity_pct <= 100.0


# --- Traceability, mutation, determinism, duplication ------------------------------


def test_new_constants_are_registered_and_physical_constants_are_not_calibratable():
    registry = ParameterRegistry.from_repository(ROOT)
    for parameter_id, value in (("physics.air_specific_heat", AIR_SPECIFIC_HEAT_J_KG_K), ("physics.water_vapour_gas_constant", 461.5)):
        record = registry.get(parameter_id)
        assert record.value == value and record.calibration_status == "fixed" and record.calibration_allowed is False and record.source_reference
    assert registry.get("crop.co2_response_reference").value == CropGrowthEngine.CO2_REFERENCE_PPM
    assert registry.get("greenhouse.outdoor_co2").value == 420.0


def test_greenhouse_runs_do_not_mutate_parameters():
    registry = ParameterRegistry.from_repository(ROOT)
    before = hashlib.sha256(json.dumps([record.to_dict() for record in registry.records], default=str).encode()).hexdigest()
    configuration = GreenhouseConfiguration()
    CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel()).step(crop(), weather(solar_radiation_w_m2=700.0), configuration, GreenhouseActuatorState(), 3600.0, soil())
    orchestrator().step(3600.0)
    after = hashlib.sha256(json.dumps([record.to_dict() for record in registry.records], default=str).encode()).hexdigest()
    assert before == after
    assert configuration == GreenhouseConfiguration()


def test_twin_state_projection_is_not_mutated_by_later_steps():
    twin = orchestrator(solar_radiation_w_m2=600.0)
    snapshot = twin.step(3600.0)
    state = TwinState(snapshot.simulation_time, "plot", "cycle", "tomato", "RAF", "ACTIVE", snapshot.crop.current_stage, lai=snapshot.crop.leaf_area_index, temperature_c=snapshot.microclimate.indoor_state.temperature_c)
    frozen = state.to_dict()
    twin.step(3600.0)
    assert state.to_dict() == frozen
    with pytest.raises(FrozenInstanceError):
        state.lai = 0.0  # type: ignore[misc]


def test_corrected_chain_is_deterministic():
    def run():
        twin = orchestrator(temperature_c=12.0, solar_radiation_w_m2=500.0)
        return [twin.step(3600.0, {"ventilation": ActuatorControl(2.0, maximum=5.0, capacity=5.0)}).crop.to_dict() for _ in range(24)]

    assert run() == run()


def test_no_parallel_physical_systems_exist():
    audit = static_audit(ROOT)
    assert audit["status"] == "PASS"
    assert audit["duplicate_core_classes"] == {} and audit["missing_core_classes"] == []
    assert {"GreenhousePhysicalModel", "CropGreenhouseFeedbackLoop", "WaterBalanceEngine", "ClimateStressEngine"} <= set(SINGLETON_CLASSES)
