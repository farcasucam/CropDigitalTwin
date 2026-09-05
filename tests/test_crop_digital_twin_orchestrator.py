from datetime import datetime, timezone

import pytest

from agri_twin.application import CropDigitalTwinOrchestrator, SimulationClock, SimulationScheduler, WeatherEngine
from agri_twin.domain import CropGrowthState, FertilizationRequest, IrrigationRequest, SoilState, WeatherState, ActuatorControl
from agri_twin.domain.weather import WeatherConfiguration


T0 = datetime(2026, 5, 1, tzinfo=timezone.utc)


class FixedWeatherProvider:
    def __init__(self, state):
        self.state = state

    def get(self, timestamp):
        return self.state


def build(weather, mode="outdoor", available_n=200.0, vwc=0.25):
    clock = SimulationClock(T0)
    weather_engine = WeatherEngine(WeatherConfiguration(), provider=FixedWeatherProvider(weather))
    crop = CropGrowthState(T0, "tomato", "RAF", "establishment", leaf_area_index=1.0, nutrient_reserve_kg_ha=200, nutrient_available_kg_ha=available_n)
    soil = SoilState(vwc, 20, 0.32, 0.10, 20, 0)
    return CropDigitalTwinOrchestrator(clock, weather_engine, crop, soil, mode)


def normal_weather(**changes):
    values = dict(temperature_c=24, relative_humidity_pct=70, solar_radiation_w_m2=500, wind_speed_m_s=2, wind_direction_deg=180, rain_rate_mm_h=0, pressure_hpa=1012)
    values.update(changes)
    return WeatherState(**values)


def test_outdoor_normal_growth_is_deterministic_and_persistent():
    first = build(normal_weather())
    second = build(normal_weather())
    result_a = first.step(3600)
    result_b = second.step(3600)

    assert result_a == result_b
    assert result_a.crop.simulation_time == first.clock.now()
    assert result_a.crop.biomass_total > 0
    assert result_a.crop.leaf_area_index >= 1.0


def test_clock_scheduler_and_accelerated_timesteps():
    orchestrator = build(normal_weather())
    scheduler = SimulationScheduler(orchestrator.clock, 3600)
    calls = []
    orchestrator.register_scheduler_task(scheduler)
    scheduler.register("observe", 86400, lambda timestamp: calls.append(timestamp))
    scheduler.advance(7 * 86400)

    assert orchestrator.clock.now() == T0.replace(day=8)
    assert len(calls) == 7
    assert orchestrator.last_snapshot is not None


def test_drought_then_irrigation_recovery():
    orchestrator = build(normal_weather(), vwc=0.12)
    dry = orchestrator.step(7 * 86400)
    recovered = orchestrator.step(3600, irrigation=IrrigationRequest("manual", 100))

    assert dry.crop.water_stress > 0
    assert recovered.soil.vwc_m3_m3 > dry.soil.vwc_m3_m3
    assert recovered.crop.water_stress < dry.crop.water_stress


def test_heatwave_and_frost_accumulate_damage():
    heat = build(normal_weather(temperature_c=38, relative_humidity_pct=20))
    hot = heat.step(3 * 86400)
    frost = build(normal_weather(temperature_c=-5))
    cold = frost.step(12 * 3600)

    assert hot.crop.heat_damage > 0
    assert cold.crop.frost_damage > 0
    assert hot.growth_factor < 1


def test_greenhouse_hvac_and_shading_reduce_adverse_environment():
    outdoor = build(normal_weather(temperature_c=38, solar_radiation_w_m2=1000), "outdoor").step(86400)
    greenhouse = build(normal_weather(temperature_c=38, solar_radiation_w_m2=1000), "actuated_greenhouse").step(86400, actuators={"cooling": ActuatorControl(5, maximum=5, capacity=5), "shade": ActuatorControl(0.5)})

    assert greenhouse.microclimate.indoor_state.temperature_c < outdoor.microclimate.indoor_state.temperature_c
    assert greenhouse.microclimate.indoor_state.radiation_w_m2 < outdoor.microclimate.indoor_state.radiation_w_m2
    assert greenhouse.crop.heat_damage <= outdoor.crop.heat_damage


def test_nutrient_deficit_reduces_growth_and_fertilization_recovers_factor():
    deficit = build(normal_weather(), available_n=0)
    low = deficit.step(86400)
    recovered = deficit.step(86400, fertilization=FertilizationRequest(200, 1, "manual"))

    assert low.crop.nutrient_status == 0
    assert recovered.crop.nutrient_status > low.crop.nutrient_status
    assert recovered.actual_growth_g_m2 >= low.actual_growth_g_m2


def test_state_serialization_round_trip_shape_is_available():
    result = build(normal_weather()).step(3600)
    payload = result.crop.to_dict()

    assert payload["simulation_time"] == result.crop.simulation_time.isoformat()
    assert payload["biomass_total"] == result.crop.biomass_total
    assert "harvest_ready" in payload


def test_small_hourly_and_long_month_steps_remain_finite():
    hourly = build(normal_weather())
    for _ in range(24):
        hourly.step(3600)
    monthly = build(normal_weather()).step(30 * 86400)

    for result in (hourly.last_snapshot, monthly):
        assert result is not None
        assert result.crop.biomass_total >= 0
        assert 0 <= result.crop.maturity_index <= 1
        assert 0 <= result.crop.nutrient_status <= 1


def test_accelerated_lifecycle_reaches_explicit_harvest_state():
    orchestrator = build(normal_weather())
    result = orchestrator.step(100 * 86400)

    assert result.crop.current_stage == "post_harvest_dormancy"
    assert result.crop.maturity_index == 1.0
    assert result.harvest_ready is True