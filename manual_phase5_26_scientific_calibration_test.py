"""Offline delivery verification for Phase 5.26."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from agri_twin.application.scientific_calibration import (
    CalibrationExecutionStatus,
    CalibrationReadiness,
    ScientificCalibrationSuite,
)
from agri_twin.domain.calibration import (
    CalibrationCase,
    CalibrationObjective,
    CalibrationParameter,
    DatasetRole,
    FunctionSimulationRunner,
    Observation,
    ObservationDataset,
    ParameterSet,
    SimulationPoint,
)

ROOT = Path(__file__).resolve().parent
START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 1, 2, tzinfo=timezone.utc)


def main() -> None:
    suite = ScientificCalibrationSuite(ROOT)
    sources = suite.audit_sources()
    assert not any(source.classification.value == "REAL_VERIFIED" for source in sources)

    observation = Observation(
        START,
        "biomass",
        2.0,
        "g_m-2",
        source="SYNTHETIC_SOFTWARE_TEST",
        source_type="synthetic_test_data",
        dataset_id="phase5_26_fixture",
        crop="tomato",
        variety="RAF",
        plot_id="plot_12010",
    )
    dataset = ObservationDataset("phase5_26_fixture", DatasetRole.CALIBRATION, (observation,), source="SYNTHETIC_SOFTWARE_TEST", source_type="synthetic_test_data")
    parameter = CalibrationParameter("fixture.scale", 1.0, 1.0, 0.0, 2.0, 1.0, "dimensionless", "engineering_default", "candidate_for_calibration", True)
    case = CalibrationCase("tomato", "RAF", "plot_12010", START, END, dataset, ParameterSet((parameter,), "fixture"))

    def runner(_case, parameters, _dataset):
        return (SimulationPoint(START, {"biomass": parameters.value_map()["fixture.scale"]}, {"biomass": "g_m-2"}),)

    rejected = suite.calibrate(case, runner=FunctionSimulationRunner(runner), objective=CalibrationObjective({"biomass": 1.0}))
    assert rejected.status is CalibrationExecutionStatus.NOT_PERFORMED
    assert rejected.readiness is CalibrationReadiness.INSUFFICIENT_DATA
    assert rejected.calibrated_parameters is None

    software_first = suite.software_fixture_calibration(case, runner=FunctionSimulationRunner(runner), objective=CalibrationObjective({"biomass": 1.0}), max_evaluations=3)
    software_second = suite.software_fixture_calibration(case, runner=FunctionSimulationRunner(runner), objective=CalibrationObjective({"biomass": 1.0}), max_evaluations=3)
    assert software_first == software_second
    assert case.parameters.value_map() == {"fixture.scale": 1.0}

    report = suite.build_report(rejected)
    paths = suite.write_report(report)
    assert all(path.exists() for path in paths)
    assert report.calibration_performed is False
    assert report.parameters_calibrated == ()

    print("=" * 80)
    print("PHASE 5.26 COMPLETE")
    print("CALIBRATION PIPELINE READY")
    print("CALIBRATION NOT PERFORMED - INSUFFICIENT REAL DATA")
    print("SYNTHETIC CALIBRATION TESTS QUALIFIED AS SOFTWARE TESTS ONLY")
    print("REAL AGRONOMIC DATA NOT VERIFIED")
    print("EXPERIMENTAL VALIDATION NOT CLAIMED")
    print("DATA ASSIMILATION NOT IMPLEMENTED")
    print("transactional_safety=PASS determinism=PASS")
    print("PASS")
    print("=" * 80)


if __name__ == "__main__":
    main()
