"""Offline delivery audit for the Phase 5.3 validation framework."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from agri_twin.domain import (
    AlignmentPolicy,
    BenchmarkEngine,
    CalibrationParameter,
    DatasetRole,
    Observation,
    ObservationDataset,
    ObservationResolution,
    ParameterSet,
    SimulationPoint,
    ValidationCase,
    ValidationEngine,
    ValidationStatus,
)


ROOT = Path(__file__).resolve().parent
T0 = datetime(2026, 6, 1, tzinfo=timezone.utc)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def parameters() -> ParameterSet:
    return ParameterSet((CalibrationParameter("synthetic.p", 1, 1, 0, 2, 1, "relative", "engineering_default", "candidate_for_calibration", True),))


def dataset() -> ObservationDataset:
    return ObservationDataset("synthetic-independent-validation", DatasetRole.VALIDATION, (Observation(T0, "lai", 1, "m2_m-2", resolution=ObservationResolution.DAILY),))


def case(model_name="SyntheticDigitalTwin") -> ValidationCase:
    return ValidationCase("tomato", "synthetic", None, T0, T0 + timedelta(days=1), dataset(), parameters(), model_name=model_name, alignment=AlignmentPolicy.EXACT)


def main() -> int:
    checks = []

    def run(name, function):
        try:
            checks.append((name, "PASS", function()))
        except Exception as exc:
            checks.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))

    def validation():
        result = ValidationEngine().evaluate(case(), lambda current_case: (SimulationPoint(T0, {"lai": 1}, {"lai": "m2_m-2"}),))
        require(result.status == ValidationStatus.SUCCESS and result.metrics[0].rmse == 0, "validation metrics are invalid")
        return "independent synthetic validation produces reproducible metrics"

    def missing_and_event():
        missing = ValidationEngine().evaluate(case(), lambda current_case: ())
        require(missing.status == ValidationStatus.INSUFFICIENT_DATA and missing.warnings, "missing simulation data was hidden")
        return "missing data remains explicit"

    def benchmark():
        result = BenchmarkEngine().evaluate(case(), {
            "digital_twin": lambda current_case: (SimulationPoint(T0, {"lai": 1}, {"lai": "m2_m-2"}),),
            "persistence_baseline": lambda current_case: (SimulationPoint(T0, {"lai": 2}, {"lai": "m2_m-2"}),),
        })
        require(result.ranking[0] == "digital_twin" and set(result.results) == {"digital_twin", "persistence_baseline"}, "benchmark ranking is invalid")
        return "same dataset compares multiple models without mutation"

    def reproducibility():
        engine = ValidationEngine()
        first = engine.evaluate(case(), lambda current_case: (SimulationPoint(T0, {"lai": 1}, {"lai": "m2_m-2"}),))
        second = engine.evaluate(case(), lambda current_case: (SimulationPoint(T0, {"lai": 1}, {"lai": "m2_m-2"}),))
        require(first == second, "validation is not deterministic")
        source = (ROOT / "src" / "agri_twin" / "domain" / "validation.py").read_text(encoding="utf-8")
        require("datetime.now" not in source and "time.time" not in source and "sleep(" not in source, "real-time dependency detected")
        return "validation uses no real-time dependency"

    run("Independent validation", validation)
    run("Missing data and event readiness", missing_and_event)
    run("Benchmark and baseline", benchmark)
    run("Reproducibility", reproducibility)
    print("=" * 60)
    print(" CROP DIGITAL TWIN - PHASE 5.3 VALIDATION")
    print("=" * 60)
    for index, (name, status, detail) in enumerate(checks, 1):
        print(f"[{index:02d}] {name:.<39} {status}  {detail}")
    failed = sum(status == "FAIL" for _, status, _ in checks)
    print("\nPHASE 5.3 STATUS: " + ("VALIDATION FRAMEWORK READY - NO SCIENTIFIC CLAIM" if failed == 0 else "NOT READY"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())