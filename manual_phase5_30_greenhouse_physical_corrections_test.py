"""Offline delivery verification for Phase 5.30: greenhouse-crop physical corrections.

Controlled scenarios A-G of the phase specification. All values are synthetic
model outputs used to demonstrate internal physical consistency; they are never
observations and this script performs no calibration.
"""

from __future__ import annotations

import math
import sys
from datetime import datetime, timedelta, timezone

from agri_twin.application.clock import SimulationClock
from agri_twin.application.orchestrator import CropDigitalTwinOrchestrator
from agri_twin.application.scenarios import Scenario, ScenarioEvent, ScenarioKind, ScenarioRunner
from agri_twin.application.weather import WeatherEngine
from agri_twin.domain import (
    ActuatorControl,
    CropGreenhouseFeedbackLoop,
    CropGrowthEngine,
    CropGrowthInput,
    CropGrowthState,
    CropMicroclimateFeedback,
    CropPhysicalExchangeModel,
    GreenhouseActuatorState,
    GreenhouseConfiguration,
    MicroclimateState,
    SimplifiedGreenhouseModel,
    SoilState,
    WeatherConfiguration,
    WeatherState,
)
from agri_twin.domain.greenhouse import vapour_pressure_deficit_kpa

T0 = datetime(2026, 7, 1, tzinfo=timezone.utc)


def weather(temperature=20.0, humidity=50.0, radiation=0.0, rain=0.0) -> WeatherState:
    return WeatherState(temperature, humidity, radiation, 2.0, 180.0, rain, 1013.0)


def indoor(temperature=20.0, humidity=50.0, co2=420.0, radiation=0.0) -> MicroclimateState:
    return MicroclimateState(air_temperature_c=temperature, relative_humidity_pct=humidity, vpd_kpa=vapour_pressure_deficit_kpa(temperature, humidity), pressure_hpa=1013.0, solar_radiation_w_m2=radiation, par_umol_m2_s=radiation * 2.04, co2_ppm=co2)


def crop(**changes) -> CropGrowthState:
    values = dict(simulation_time=T0, crop_key="tomato", variety="RAF", current_stage="vegetative_growth", biomass_total=100.0, biomass_leaf=60.0, biomass_stem=20.0, biomass_root=20.0, leaf_area_index=1.2, root_depth_m=0.6, soil_water_vwc=0.3, phenology_model="MANUAL")
    values.update(changes)
    return CropGrowthState(**values)


def soil() -> SoilState:
    return SoilState(0.30, 18.0, 0.35, 0.10, 0.0, 120.0)


def diurnal(hour: int) -> WeatherState:
    return weather(20.0 + 8.0 * math.sin(2 * math.pi * (hour - 9) / 24), 65.0, max(0.0, 850.0 * math.sin(2 * math.pi * (hour - 6) / 24)))


def finite(*values: float) -> bool:
    return all(math.isfinite(value) for value in values)


def run_loop(ach: float, hours: int = 72) -> dict:
    loop = CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel())
    state = crop()
    converged, iterations, saturated_latent, deltas, ok = 0, [], 0, [], True
    for hour in range(hours):
        now = T0 + timedelta(hours=hour + 1)
        outdoor = diurnal(hour)
        result = loop.step(state, outdoor, GreenhouseConfiguration(ventilation_ach=ach), GreenhouseActuatorState(), 3600.0, soil(), simulation_time=now)
        micro = result.microclimate
        converged += int(result.convergence.converged)
        iterations.append(result.convergence.iterations)
        saturated_latent += int(micro.vpd_kpa <= 1e-12 and result.exchange.latent_heat_flux.value > 0)
        deltas.append(micro.temperature_c - outdoor.temperature_c)
        ok = ok and finite(*micro.to_dict().values(), result.feedback.latent_heat_w_m2, result.crop_growth.actual_growth_g_m2)
        state = result.crop.advance(now, 3600.0)
    return {"converged": converged, "steps": hours, "max_iterations": max(iterations), "saturated_latent": saturated_latent, "min_dT": min(deltas), "max_dT": max(deltas), "finite": ok}


def orchestrator(outdoor: WeatherState, mode: str = "passive_greenhouse") -> CropDigitalTwinOrchestrator:
    provider = type("Constant", (), {"get": staticmethod(lambda _t: outdoor)})()
    return CropDigitalTwinOrchestrator(SimulationClock(T0), WeatherEngine(WeatherConfiguration(), provider=provider), crop(), soil(), mode)


def main() -> int:
    model = SimplifiedGreenhouseModel

    # A. Closed greenhouse from a different initial indoor state.
    closed = run_loop(0.0)
    relax = model().step(weather(10.0), GreenhouseConfiguration(ventilation_ach=0.0), GreenhouseActuatorState(), CropMicroclimateFeedback(), 3600.0, prior=indoor(30.0))
    print(f"A closed: converged={closed['converged']}/{closed['steps']} max_iter={closed['max_iterations']} dT=[{closed['min_dT']:.2f},{closed['max_dT']:.2f}] latent_at_saturation={closed['saturated_latent']} relax_30C_to_10C_outdoor_1h={relax.temperature_c:.3f}")
    assert closed["converged"] == closed["steps"] and closed["saturated_latent"] == 0 and closed["finite"]
    assert 10.0 < relax.temperature_c < 30.0

    # B. Ventilated vs closed.
    ventilated = run_loop(3.0)
    print(f"B ventilated: converged={ventilated['converged']}/{ventilated['steps']} dT=[{ventilated['min_dT']:.2f},{ventilated['max_dT']:.2f}] vs closed dT=[{closed['min_dT']:.2f},{closed['max_dT']:.2f}]")
    assert ventilated["max_dT"] - ventilated["min_dT"] < closed["max_dT"] - closed["min_dT"]
    ach_gaps = [abs(model().step(weather(20.0), GreenhouseConfiguration(ventilation_ach=ach, heat_loss_w_k=0.0), GreenhouseActuatorState(), CropMicroclimateFeedback(), 3600.0, prior=indoor(35.0, 90.0, 900.0)).co2_ppm - 420.0) for ach in (0.0, 1.0, 5.0)]
    print(f"B co2 gap to outdoor after 1 h at ACH 0/1/5: {[round(g, 1) for g in ach_gaps]}")
    assert ach_gaps[0] > ach_gaps[1] > ach_gaps[2]

    # C. Saturation.
    saturated = indoor(24.0, 100.0, radiation=600.0)
    state = crop()
    growth = CropGrowthEngine().advance(state, CropGrowthInput(weather(24.0, 100.0, 600.0), 3600.0))
    exchange = CropPhysicalExchangeModel().calculate(state, growth, saturated, weather(), 3600.0, soil())
    print(f"C saturation: VPD={saturated.vpd_kpa} transpiration={exchange.transpiration_rate.value} latent={exchange.latent_heat_flux.value}")
    assert exchange.transpiration_rate.value == 0.0 and exchange.latent_heat_flux.value == 0.0

    # D. Outdoor heat and thermal transfer signs.
    mild = model().step(weather(22.0), GreenhouseConfiguration(), GreenhouseActuatorState(), CropMicroclimateFeedback(), 3600.0, prior=indoor(22.0))
    hot = model().step(weather(38.0), GreenhouseConfiguration(), GreenhouseActuatorState(), CropMicroclimateFeedback(), 3600.0, prior=indoor(22.0))
    colder = model().step(weather(25.0), GreenhouseConfiguration(), GreenhouseActuatorState(), CropMicroclimateFeedback(), 3600.0, prior=indoor(5.0))
    print(f"D thermal: equal={mild.temperature_c:.3f} (22) outdoor_38C={hot.temperature_c:.3f} indoor_5C_outdoor_25C={colder.temperature_c:.3f}")
    assert mild.temperature_c == 22.0 or abs(mild.temperature_c - 22.0) < 1e-9
    assert hot.temperature_c > mild.temperature_c and 5.0 < colder.temperature_c < 25.0

    # E. The crop consumes indoor temperature.
    twin = orchestrator(weather(5.0))
    snapshot = twin.step(3600.0, {"heating": ActuatorControl(20.0, maximum=20.0, capacity=20.0)})
    print(f"E crop temperature: outdoor={snapshot.outdoor_weather.temperature_c:.2f} indoor={snapshot.microclimate.indoor_state.temperature_c:.2f} crop_environment={snapshot.weather.temperature_c:.2f} gdd={snapshot.crop.gdd_accumulated:.4f}")
    assert snapshot.weather.temperature_c == snapshot.microclimate.indoor_state.temperature_c != snapshot.outdoor_weather.temperature_c

    # F. CO2 low / ambient / high with everything else constant.
    base = CropGrowthInput(weather(25.0, 60.0, 700.0), 3600.0)
    growth_by_co2 = {co2: CropGrowthEngine().advance(crop(), CropGrowthInput(base.weather, 3600.0, co2_ppm=co2)).actual_growth_g_m2 for co2 in (210.0, 420.0, 840.0)}
    print(f"F CO2 actual growth g m-2: {', '.join(f'{k:.0f} ppm={v:.4f}' for k, v in growth_by_co2.items())} (single response CropGrowthEngine.co2_response)")
    assert math.isclose(growth_by_co2[210.0], 0.5 * growth_by_co2[420.0]) and math.isclose(growth_by_co2[840.0], growth_by_co2[420.0])

    # G. Perennial dormancy -> chilling release -> forcing -> leaf-out stage.
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    dormant = crop(simulation_time=start, crop_key="peach", variety="UNSPECIFIED", current_stage="establishment", biomass_total=45.0, biomass_leaf=5.0, biomass_stem=20.0, biomass_root=20.0, leaf_area_index=0.1, dormancy_released=False)
    events = (ScenarioEvent("chill", "cold", start, start + timedelta(days=30), 4.0, {"temperature_c": 4.0}), ScenarioEvent("irrigation", "irrigation", start, start + timedelta(days=80), 0.4, {"amount_mm": 0.4}))
    snapshots = ScenarioRunner().run(Scenario("p530_manual_dormancy", "dormancy", "", "peach", None, start, start + timedelta(days=80), 3600, ScenarioKind.SYNTHETIC, dormant, soil(), weather(20.0, 60.0, 500.0), "outdoor", events)).snapshots
    release = next(i for i, s in enumerate(snapshots) if s.crop.dormancy_released)
    leaf_out = next(i for i, s in enumerate(snapshots) if s.crop.current_stage == "vegetative_growth")
    print(f"G dormancy: release_day={release // 24} chilling_h={snapshots[release].crop.chilling_hours:.0f} biomass_before_release={snapshots[release - 1].crop.biomass_total} vegetative_day={leaf_out // 24} final_biomass={snapshots[-1].crop.biomass_total:.1f}")
    assert all(s.crop.biomass_total == 45.0 and s.crop.gdd_accumulated == 0.0 for s in snapshots[:release])
    assert leaf_out > release and snapshots[-1].crop.biomass_total > 45.0

    print("PHASE 5.30 COMPLETE")
    print("GREENHOUSE PHYSICAL CONSISTENCY CORRECTED")
    print("NOTE: corrections restore internal physical consistency; they are not calibration and do not establish biological or experimental validity")
    print("REAL_VERIFIED = 0")
    print("CALIBRATION_PERFORMED = false")
    print("EXPERIMENTAL_VALIDATION_PERFORMED = false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
