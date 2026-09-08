"""Compact, synthetic scientific architecture audit for Phases 5.1-5.7.4."""

from datetime import datetime, timezone
from pathlib import Path

from agri_twin.domain import (
    CropGreenhouseFeedbackLoop,
    CropGrowthState,
    GreenhouseActuatorState,
    GreenhouseConfiguration,
    ParameterRegistry,
    SimplifiedGreenhouseModel,
    SoilState,
    WeatherState,
)


ROOT = Path(__file__).resolve().parent
T0 = datetime(2026, 7, 1, tzinfo=timezone.utc)


def main() -> int:
    registry = ParameterRegistry.from_repository(ROOT)
    audit = registry.audit()
    crop = CropGrowthState(
        simulation_time=T0,
        crop_key="tomato",
        variety="RAF",
        current_stage="vegetative_growth",
        biomass_total=50.0,
        biomass_leaf=50.0,
        leaf_area_index=2.0,
        root_depth_m=0.5,
        soil_water_vwc=0.25,
    )
    weather = WeatherState(28.0, 60.0, 700.0, 2.0, 180.0, 0.0, 1012.0)
    soil = SoilState(0.25, 22.0, 0.35, 0.10, 20.0, 75.0)
    result = CropGreenhouseFeedbackLoop(SimplifiedGreenhouseModel()).step(
        crop,
        weather,
        GreenhouseConfiguration(),
        GreenhouseActuatorState(),
        3600.0,
        soil,
    )
    print("temporal_chain=SimulationClock -> Scheduler -> WeatherState -> Greenhouse -> Microclimate -> CropGrowth -> Feedback")
    print(f"parameters=records:{len(registry.records)} audit_errors:{len(audit.validate())} engineering_defaults:{audit.summary['engineering_defaults']}")
    print(f"greenhouse_backend=SimplifiedGreenhouseModel energyplus=optional_not_required")
    print(f"temperature_c={result.microclimate.temperature_c:.6f} radiation_w_m2={result.microclimate.solar_radiation_w_m2:.6f} humidity_pct={result.microclimate.relative_humidity_pct:.6f} vpd_kpa={result.microclimate.vpd_kpa:.6f}")
    print(f"apar_mj_m2={result.crop_growth.apar_mj_m2:.6f} actual_growth_g_m2={result.crop_growth.actual_growth_g_m2:.6f} lai={result.crop.leaf_area_index:.6f}")
    print(f"transpiration_mm_h={result.exchange.transpiration_rate.value:.6f} latent_heat_w_m2={result.exchange.latent_heat_flux.value:.6f} sensible_heat_w_m2={result.exchange.sensible_heat_flux.value:.6f}")
    print(f"co2_uptake_ppm_timestep={result.exchange.co2_uptake.value:.6f} co2_final_ppm={result.microclimate.co2_ppm:.6f}")
    print(f"fixed_point_iterations={result.convergence.iterations} converged={result.convergence.converged} error={result.convergence.final_error:.6f}")
    print("calibration_status=framework_ready_insufficient_real_observations")
    print("validation_status=not_experimentally_validated")
    print("scientific_status=MECHANISTIC SIMPLIFIED MODEL - NOT CALIBRATED / NOT EXPERIMENTALLY VALIDATED")
    print("note=all displayed values are synthetic model outputs, never observations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
