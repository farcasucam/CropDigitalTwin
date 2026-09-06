"""Offline delivery audit for the Phase 5.2 calibration framework."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from agri_twin.application import SimulationClock
from agri_twin.domain import (
    CalibrationCase,
    CalibrationObjective,
    CalibrationStatus,
    CalibrationParameter,
    ClockSimulationRunner,
    DatasetRole,
    FunctionSimulationRunner,
    GridSearchCalibrator,
    Observation,
    ObservationDataset,
    ObservationResolution,
    ParameterSet,
    SimulationPoint,
)


ROOT = Path(__file__).resolve().parent
T0 = datetime(2026, 5, 1, tzinfo=timezone.utc)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def parameter_set() -> ParameterSet:
    return ParameterSet((CalibrationParameter("synthetic.growth", 1.0, 1.0, 0.0, 2.0, 0.5, "relative", "engineering_default", "candidate_for_calibration", True),))


def dataset(role: DatasetRole = DatasetRole.CALIBRATION) -> ObservationDataset:
    return ObservationDataset("synthetic", role, (Observation(T0, "biomass", 1.0, "g_m-2", resolution=ObservationResolution.DAILY),))


def main() -> int:
    checks = []

    def run(name, function):
        try:
            checks.append((name, "PASS", function()))
        except Exception as exc:
            checks.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))

    def contracts():
        case = CalibrationCase("tomato", "synthetic", None, T0, T0 + timedelta(days=1), dataset(), parameter_set(), validation_dataset=dataset(DatasetRole.VALIDATION))
        require(case.calibration_dataset.role == DatasetRole.CALIBRATION, "calibration role missing")
        require(case.validation_dataset.role == DatasetRole.VALIDATION, "validation role missing")
        return "CalibrationCase, Observation and separate datasets validate"

    def grid_search():
        def simulate(case, parameters, observations):
            value = parameters.value_map()["synthetic.growth"]
            return (SimulationPoint(T0, {"biomass": value}, {"biomass": "g_m-2"}),)

        case = CalibrationCase("tomato", "synthetic", None, T0, T0 + timedelta(days=1), dataset(), parameter_set())
        result = GridSearchCalibrator(FunctionSimulationRunner(simulate), CalibrationObjective({"biomass": 1}, {"biomass": 1}), 20).fit(case)
        require(result.status == CalibrationStatus.SUCCESS and result.calibrated_parameters.value_map()["synthetic.growth"] == 1, "synthetic grid search failed")
        return f"Grid Search recovered synthetic value in {result.evaluations} evaluations"

    def clock_runner():
        clock = SimulationClock(T0)
        runner = ClockSimulationRunner(clock, 3600, lambda timestamp, parameters: {"temperature": 20.0})
        points = runner.run(CalibrationCase("tomato", None, None, T0, T0 + timedelta(hours=2), dataset(), parameter_set()), parameter_set(), dataset())
        require(len(points) == 3 and clock.now() == T0 + timedelta(hours=2), "SimulationClock runner failed")
        return "runner uses simulated time only"

    def insufficient():
        case = CalibrationCase("tomato", None, None, T0, T0 + timedelta(days=1), dataset(), ParameterSet(()))
        result = GridSearchCalibrator(FunctionSimulationRunner(lambda *_: ()), CalibrationObjective({"biomass": 1}), 5).fit(case)
        require(result.status == CalibrationStatus.INSUFFICIENT_DATA, "insufficient data/status was not explicit")
        return "insufficient calibration data is reported without invented results"

    run("Contracts and dataset roles", contracts)
    run("Synthetic Grid Search", grid_search)
    run("SimulationClock runner", clock_runner)
    run("Insufficient data", insufficient)
    print("=" * 60)
    print(" CROP DIGITAL TWIN - PHASE 5.2 CALIBRATION")
    print("=" * 60)
    for index, (name, status, detail) in enumerate(checks, 1):
        print(f"[{index:02d}] {name:.<39} {status}  {detail}")
    failed = sum(status == "FAIL" for _, status, _ in checks)
    print("\nPHASE 5.2 STATUS: " + ("FRAMEWORK READY - NO SCIENTIFIC CALIBRATION CLAIM" if failed == 0 else "NOT READY"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())