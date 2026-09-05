"""Offline delivery audit for Phase 4.7.3 deterministic phenology."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from agri_twin.application import SimulationClock
from agri_twin.domain import CropGrowthState, PhenologyEngine, WeatherState


ROOT = Path(__file__).resolve().parent
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
ANNUALS = {"tomato", "lettuce", "pepper"}
PERENNIALS = {"grape", "peach", "plum", "apple"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def state(crop_key: str, *, dormant: bool = False) -> CropGrowthState:
    return CropGrowthState(T0, crop_key, "unspecified", "establishment", dormancy_released=not dormant)


def weather(temperature_c: float) -> WeatherState:
    return WeatherState(temperature_c, 60, 300, 1, 180, 0, 1012)


def main() -> int:
    checks: list[tuple[str, str, str]] = []

    def run(name: str, function) -> None:
        try:
            checks.append((name, "PASS", str(function() or "verified")))
        except Exception as exc:
            checks.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))

    def coverage() -> str:
        engine = PhenologyEngine()
        require({engine.profile_for(crop).crop_key for crop in ANNUALS | PERENNIALS} == ANNUALS | PERENNIALS, "profile coverage is incomplete")
        return "seven crop profiles are available"

    def annual_gdd() -> str:
        engine = PhenologyEngine()
        initial = state("tomato")
        current_time = T0 + timedelta(days=20)
        result = engine.advance(initial, weather(25), current_time, 20 * 86400)
        require(result.gdd_accumulated == 300, "GDD clipping or accumulation is incorrect")
        require(result.current_stage != initial.current_stage, "annual stage did not transition")
        return "explicit GDD advance clips temperature and changes phase"

    def dormancy() -> str:
        engine = PhenologyEngine()
        initial = state("plum", dormant=True)
        current_time = T0 + timedelta(hours=24)
        result = engine.advance(initial, weather(5), current_time, 24 * 3600)
        require(result.chilling_hours == 24 and result.gdd_accumulated == 0, "dormancy must accumulate chilling before forcing")
        return "perennial dormancy gates forcing until chilling release"

    def deterministic_clock() -> str:
        clock = SimulationClock(T0)
        initial = state("lettuce")
        dt = clock.advance(48 * 3600)
        engine = PhenologyEngine()
        first = engine.advance(initial, weather(20), clock.now(), dt.total_seconds())
        second = engine.advance(initial, weather(20), clock.now(), dt.total_seconds())
        require(first == second, "same state, weather and dt must be deterministic")
        source = (ROOT / "src" / "agri_twin" / "domain" / "phenology.py").read_text(encoding="utf-8")
        require("datetime.now" not in source and "time.time" not in source, "phenology uses real time")
        return "SimulationClock delta is replayable and no parallel clock exists"

    run("Seven-crop coverage", coverage)
    run("Annual GDD and phase transition", annual_gdd)
    run("Perennial chilling and dormancy", dormancy)
    run("Clock integration and determinism", deterministic_clock)
    print("=" * 60)
    print(" CROP DIGITAL TWIN - PHASE 4.7.3 PHENOLOGY")
    print("=" * 60)
    for index, (name, status, detail) in enumerate(checks, 1):
        print(f"[{index:02d}] {name:.<39} {status}  {detail}")
    failed = sum(status == "FAIL" for _, status, _ in checks)
    print("\nPHASE 4.7.3 STATUS: " + ("ENGINE READY - CALIBRATION PENDING" if failed == 0 else "NOT READY"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())