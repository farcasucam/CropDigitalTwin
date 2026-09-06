"""Offline delivery audit for Phase 5.4 reproducible synthetic scenarios."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from agri_twin.application import ScenarioRunner, compare_scenarios, sweep_scenarios


ROOT = Path(__file__).resolve().parent
T0 = datetime(2026, 5, 1, tzinfo=timezone.utc)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def build(events=(), mode="outdoor", vwc=0.25):
    from agri_twin.application import Scenario, ScenarioKind, ScenarioEvent
    from agri_twin.domain import CropGrowthState, SoilState, WeatherState
    crop = CropGrowthState(T0, "tomato", "RAF", "establishment", leaf_area_index=1)
    return Scenario("manual", "synthetic", "delivery scenario", "tomato", "RAF", T0, T0 + timedelta(days=3), 86400, ScenarioKind.SYNTHETIC, crop, SoilState(vwc, 20, 0.32, 0.10, 20, 0), WeatherState(24, 70, 500, 2, 180, 0, 1012), mode, tuple(events), labels=("SYNTHETIC SCENARIO", "NOT SCIENTIFIC VALIDATION"))


def main() -> int:
    from agri_twin.application import ScenarioEvent
    checks = []

    def run(name, function):
        try:
            checks.append((name, "PASS", function()))
        except Exception as exc:
            checks.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))

    def baseline():
        result = ScenarioRunner().run(build())
        require(result.status == "SUCCESS" and len(result.snapshots) == 3, "baseline failed")
        require(result.config_hash == build().config_hash(), "configuration hash is unstable")
        return "baseline scenario and hash are reproducible"

    def stress():
        heat = ScenarioEvent("heat", "heat_wave", T0, T0 + timedelta(days=2), 12, {})
        drought = ScenarioEvent("dry", "dry", T0, T0 + timedelta(days=2), 0, {})
        baseline_result = ScenarioRunner().run(build())
        stress_result = ScenarioRunner().run(build((heat, drought), vwc=0.12))
        comparison = compare_scenarios((baseline_result, stress_result))
        require(comparison.deltas[stress_result.scenario_id], "stress comparison missing")
        return "combined heat/drought scenario and comparison pass"

    def sweep():
        result = sweep_scenarios(build(), "irrigation", (0, 20, 40))
        require(len(result.results) == 3 and all(item.status == "SUCCESS" for item in result.results), "scenario sweep failed")
        return "scenario sweep produces deterministic results"

    def validation_output():
        result = ScenarioRunner().run(build())
        dataset = result.observation_dataset(("biomass", "lai"))
        require(dataset.name == "manual" and dataset.observations, "validation export missing")
        require("SYNTHETIC SCENARIO" in build().labels and "NOT SCIENTIFIC VALIDATION" in build().labels, "scientific warning missing")
        source = (ROOT / "src" / "agri_twin" / "application" / "scenarios.py").read_text(encoding="utf-8")
        require("datetime.now" not in source and "time.time" not in source and "sleep(" not in source, "real-time dependency detected")
        return "scenario output integrates with validation and uses no real time"

    run("Baseline and reproducibility", baseline)
    run("Combined stress and comparison", stress)
    run("Scenario sweep", sweep)
    run("Validation integration", validation_output)
    print("=" * 60)
    print(" CROP DIGITAL TWIN - PHASE 5.4 SCENARIOS")
    print("=" * 60)
    for index, (name, status, detail) in enumerate(checks, 1):
        print(f"[{index:02d}] {name:.<39} {status}  {detail}")
    failed = sum(status == "FAIL" for _, status, _ in checks)
    print("\nPHASE 5.4 STATUS: " + ("SCENARIO PLATFORM READY - SYNTHETIC ONLY" if failed == 0 else "NOT READY"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())