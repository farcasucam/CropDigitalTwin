"""Reproducible manual Phase 5.7.4 feedback scenarios."""

from datetime import datetime, timezone

from agri_twin.domain import (
    CropGreenhouseFeedbackConfiguration,
    CropGreenhouseFeedbackLoop,
    CropMicroclimateFeedback,
    CropGrowthState,
    GreenhouseActuatorState,
    GreenhouseConfiguration,
    SimplifiedGreenhouseModel,
    SoilState,
    WeatherState,
)


T0 = datetime(2026, 7, 1, tzinfo=timezone.utc)


def run_case(name: str, weather: WeatherState, actuators: GreenhouseActuatorState) -> None:
    crop = CropGrowthState(
        simulation_time=T0,
        crop_key="tomato",
        variety="RAF",
        current_stage="vegetative_growth",
        biomass_total=50,
        biomass_leaf=50,
        leaf_area_index=2.0,
        root_depth_m=0.5,
        soil_water_vwc=0.25,
    )
    soil = SoilState(0.25, 22, 0.35, 0.10, 20, 75)
    loop = CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel())
    initial = loop.greenhouse.step(weather, GreenhouseConfiguration(), actuators, CropMicroclimateFeedback(), 3600)
    result = loop.step(crop, weather, GreenhouseConfiguration(), actuators, 3600, soil)
    print(f"[{name}]")
    print(f"initial_temperature_c={initial.temperature_c:.3f} initial_vpd_kpa={initial.vpd_kpa:.3f} initial_co2_ppm={initial.co2_ppm:.3f}")
    print(f"co2_supply_ppm={actuators.co2_supply_ppm:.3f}")
    print(f"temperature_without_feedback_c={initial.temperature_c:.3f} temperature_with_feedback_c={result.microclimate.temperature_c:.3f}")
    print(f"iterations={result.convergence.iterations} converged={result.convergence.converged} error={result.convergence.final_error:.6f}")
    print(f"transpiration_mm_h={result.feedback.transpiration_mm_h:.6f} latent_heat_w_m2={result.feedback.latent_heat_w_m2:.6f} sensible_heat_w_m2={result.feedback.sensible_heat_w_m2:.6f} co2_uptake_ppm={result.feedback.co2_uptake_ppm:.6f}")
    print(f"final_temperature_c={result.microclimate.temperature_c:.3f} final_vpd_kpa={result.microclimate.vpd_kpa:.3f} final_co2_ppm={result.microclimate.co2_ppm:.3f}")


def main() -> int:
    common = dict(temperature_c=28, relative_humidity_pct=60, wind_speed_m_s=2, wind_direction_deg=180, rain_rate_mm_h=0, pressure_hpa=1012)
    run_case("radiation", WeatherState(solar_radiation_w_m2=800, **common), GreenhouseActuatorState())
    run_case("shaded", WeatherState(solar_radiation_w_m2=800, **common), GreenhouseActuatorState(shading_fraction=0.7))
    run_case("high_vpd", WeatherState(solar_radiation_w_m2=800, relative_humidity_pct=25, **{key: value for key, value in common.items() if key != "relative_humidity_pct"}), GreenhouseActuatorState())
    model = SimplifiedGreenhouseModel()
    configuration = GreenhouseConfiguration(co2_ppm_baseline=450)
    no_uptake = model.step(WeatherState(solar_radiation_w_m2=800, **common), configuration, GreenhouseActuatorState(), CropMicroclimateFeedback(), 3600)
    uptake = model.step(WeatherState(solar_radiation_w_m2=800, **common), configuration, GreenhouseActuatorState(), CropMicroclimateFeedback(co2_uptake_ppm=10), 3600, prior=no_uptake)
    print("[co2_and_thermal_audit]")
    print(f"co2_previous_ppm={no_uptake.co2_ppm:.3f} co2_supply_ppm=0.000 co2_uptake_ppm=10.000 co2_final_ppm={uptake.co2_ppm:.3f}")
    neutral = model.step(WeatherState(solar_radiation_w_m2=800, **common), configuration, GreenhouseActuatorState(), CropMicroclimateFeedback(), 3600)
    latent = model.step(WeatherState(solar_radiation_w_m2=800, **common), configuration, GreenhouseActuatorState(), CropMicroclimateFeedback(latent_heat_w_m2=200), 3600, prior=neutral)
    sensible = model.step(WeatherState(solar_radiation_w_m2=800, **common), configuration, GreenhouseActuatorState(), CropMicroclimateFeedback(sensible_heat_w_m2=20), 3600, prior=neutral)
    print(f"temperature_neutral_c={neutral.temperature_c:.3f} temperature_latent_c={latent.temperature_c:.3f} temperature_sensible_c={sensible.temperature_c:.3f}")
    repeat_a = CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel()).step(CropGrowthState(simulation_time=T0, crop_key="tomato", variety="RAF", current_stage="vegetative_growth", biomass_total=50, biomass_leaf=50, leaf_area_index=2.0, root_depth_m=0.5, soil_water_vwc=0.25), WeatherState(solar_radiation_w_m2=800, **common), GreenhouseConfiguration(), GreenhouseActuatorState(), 3600)
    repeat_b = CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel()).step(CropGrowthState(simulation_time=T0, crop_key="tomato", variety="RAF", current_stage="vegetative_growth", biomass_total=50, biomass_leaf=50, leaf_area_index=2.0, root_depth_m=0.5, soil_water_vwc=0.25), WeatherState(solar_radiation_w_m2=800, **common), GreenhouseConfiguration(), GreenhouseActuatorState(), 3600)
    non_converged = CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel(), configuration=CropGreenhouseFeedbackConfiguration(max_iterations=1, tolerance_temperature_c=1e-12, tolerance_relative_humidity_pct=1e-12, tolerance_co2_ppm=1e-12)).step(CropGrowthState(simulation_time=T0, crop_key="tomato", variety="RAF", current_stage="vegetative_growth", biomass_total=50, biomass_leaf=50, leaf_area_index=2.0, root_depth_m=0.5, soil_water_vwc=0.25), WeatherState(solar_radiation_w_m2=800, **common), GreenhouseConfiguration(), GreenhouseActuatorState(), 3600)
    print(f"same_timestep_deterministic={repeat_a == repeat_b} non_converged={not non_converged.convergence.converged} non_convergence_error={non_converged.convergence.final_error:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
