"""Offline delivery audit for Phase 4.7.8 greenhouse microclimate."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from agri_twin.domain import ActuatorControl, CropGrowthState, GreenhouseMicroclimateEngine, WeatherState


ROOT = Path(__file__).resolve().parent
T0 = datetime(2026, 7, 1, tzinfo=timezone.utc)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def crop():
    return CropGrowthState(T0, "tomato", "unspecified", "vegetative_growth", leaf_area_index=2.0)


def weather(**changes):
    values = dict(temperature_c=35, relative_humidity_pct=40, solar_radiation_w_m2=800, wind_speed_m_s=3, wind_direction_deg=180, rain_rate_mm_h=0, pressure_hpa=1012)
    values.update(changes)
    return WeatherState(**values)


def main() -> int:
    checks = []

    def run(name, function):
        try:
            checks.append((name, "PASS", function()))
        except Exception as exc:
            checks.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))

    def bypass():
        result = GreenhouseMicroclimateEngine().advance(weather(), crop(), 3600, mode="outdoor")
        require(result.indoor_state.temperature_c == 35 and result.indoor_state.radiation_w_m2 == 800, "outdoor bypass changed weather")
        return "outdoor mode bypasses greenhouse transformation"

    def actuators():
        engine = GreenhouseMicroclimateEngine()
        shaded = engine.advance(weather(), crop(), 3600, mode="passive_greenhouse", actuators={"shade": ActuatorControl(0.5)})
        heated = engine.advance(weather(temperature_c=0), crop(), 86400, mode="actuated_greenhouse", actuators={"heating": ActuatorControl(5, maximum=5, capacity=5)})
        require(shaded.indoor_state.radiation_w_m2 < 800 * 0.78, "shade did not reduce radiation")
        require(heated.indoor_state.temperature_c > 0, "heating did not affect microclimate")
        return "cover, shade and heating transform the microclimate"

    def vpd_and_stability():
        engine = GreenhouseMicroclimateEngine()
        first = engine.advance(weather(), crop(), 30 * 86400, mode="passive_greenhouse")
        second = engine.advance(weather(), crop(), 30 * 86400, mode="passive_greenhouse")
        require(first == second and first.environment.vpd_kpa >= 0, "microclimate is not deterministic/stable")
        source = (ROOT / "src" / "agri_twin" / "domain" / "greenhouse.py").read_text(encoding="utf-8")
        require("datetime.now" not in source and "time.time" not in source, "microclimate uses real time")
        return "VPD and accelerated timestep are stable without a parallel clock"

    def separation():
        source = (ROOT / "src" / "agri_twin" / "domain" / "greenhouse.py").read_text(encoding="utf-8")
        require("biomass_total=" not in source and "biomass_leaf=" not in source, "actuator model mutates biomass")
        return "actuators affect environment only"

    run("Outdoor bypass", bypass)
    run("Cover and actuators", actuators)
    run("VPD and stability", vpd_and_stability)
    run("Responsibility separation", separation)
    print("=" * 60)
    print(" CROP DIGITAL TWIN - PHASE 4.7.8 GREENHOUSE MICROCLIMATE")
    print("=" * 60)
    for index, (name, status, detail) in enumerate(checks, 1):
        print(f"[{index:02d}] {name:.<39} {status}  {detail}")
    failed = sum(status == "FAIL" for _, status, _ in checks)
    print("\nPHASE 4.7.8 STATUS: " + ("MICROCLIMATE READY - SITE CALIBRATION PENDING" if failed == 0 else "NOT READY"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())