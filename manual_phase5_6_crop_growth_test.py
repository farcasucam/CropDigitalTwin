"""Offline delivery demonstration for Phase 5.6 crop growth."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from agri_twin.domain import CropGrowthEngine, CropGrowthInput, CropGrowthState, WeatherState


ROOT = Path(__file__).resolve().parent
T0 = datetime(2026, 6, 1, tzinfo=timezone.utc)


def state() -> CropGrowthState:
    return CropGrowthState(T0, "tomato", "RAF", "vegetative_growth", biomass_total=50, biomass_leaf=50, leaf_area_index=1.0, root_depth_m=0.5)


def weather(**changes) -> WeatherState:
    values = dict(temperature_c=24, relative_humidity_pct=70, solar_radiation_w_m2=500, wind_speed_m_s=2, wind_direction_deg=180, rain_rate_mm_h=0, pressure_hpa=1012)
    values.update(changes)
    return WeatherState(**values)


def main() -> int:
    engine = CropGrowthEngine()
    initial = state()
    favorable = engine.advance(initial, CropGrowthInput(weather(), 86400))
    heat = engine.advance(favorable.state, CropGrowthInput(weather(temperature_c=40), 86400))
    drought = engine.advance(heat.state, CropGrowthInput(weather(), 86400, water_factor=0.1))
    recovery = engine.advance(drought.state, CropGrowthInput(weather(), 86400, water_factor=1.0))
    radiation = engine.advance(recovery.state, CropGrowthInput(weather(solar_radiation_w_m2=1000), 86400))
    repeat = engine.advance(initial, CropGrowthInput(weather(), 86400))
    print("=" * 60)
    print(" CROP DIGITAL TWIN - PHASE 5.6 CROP GROWTH")
    print("=" * 60)
    for label, result in (("initial", None), ("favorable", favorable), ("heat", heat), ("drought", drought), ("recovery", recovery), ("high_radiation", radiation)):
        if result is None:
            print(f"{label:15} biomass={initial.biomass_total:.3f} LAI={initial.leaf_area_index:.3f}")
        else:
            print(f"{label:15} biomass={result.state.biomass_total:.3f} LAI={result.state.leaf_area_index:.3f} growth={result.actual_growth_g_m2:.3f} maturity={result.state.maturity_index:.3f} factors={result.temperature_factor:.2f}/{result.water_factor:.2f}/{result.vpd_factor:.2f}/{result.radiation_factor:.2f}")
    assert favorable.state.biomass_total >= initial.biomass_total
    assert repeat == favorable
    print("\nSYNTHETIC SCENARIO: NOT SCIENTIFICALLY CALIBRATED")
    print("PHASE 5.6 STATUS: MECHANISTIC SIMPLIFIED MODEL - CALIBRATION READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())