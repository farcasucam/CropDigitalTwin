from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from agri_twin.application.real_validation import DataSourceClassification
from agri_twin.application.scientific_calibration import (
    CalibrationExecutionStatus,
    CalibrationReadiness,
    ScientificCalibrationSuite,
)
from agri_twin.domain.calibration import (
    CalibrationCase,
    CalibrationError,
    CalibrationObjective,
    CalibrationParameter,
    DatasetRole,
    FunctionSimulationRunner,
    Observation,
    ObservationDataset,
    ParameterSet,
    SimulationPoint,
)

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 1, 2, tzinfo=timezone.utc)


def fixture_dataset(name: str = "synthetic_calibration_fixture") -> ObservationDataset:
    observation = Observation(
        START,
        "biomass",
        2.0,
        "g_m-2",
        source="SYNTHETIC_SOFTWARE_TEST",
        source_type="synthetic_test_data",
        dataset_id=name,
        crop="tomato",
        variety="RAF",
        plot_id="plot_12010",
        cycle_id="cycle_1",
    )
    return ObservationDataset(name, DatasetRole.CALIBRATION, (observation,), source="SYNTHETIC_SOFTWARE_TEST", source_type="synthetic_test_data")


def fixture_parameter(value: float = 1.0, minimum: float = 0.0, maximum: float = 2.0, *, allowed: bool = True) -> CalibrationParameter:
    return CalibrationParameter("fixture.scale", value, value, minimum, maximum, 1.0, "dimensionless", "engineering_default", "candidate_for_calibration", allowed)


def fixture_case() -> CalibrationCase:
    dataset = fixture_dataset()
    return CalibrationCase("tomato", "RAF", "plot_12010", START, END, dataset, ParameterSet((fixture_parameter(),), "fixture"))


def fixture_runner(case, parameters, dataset):
    value = parameters.value_map()["fixture.scale"]
    return (SimulationPoint(START, {"biomass": value}, {"biomass": "g_m-2"}),)


def test_no_real_verified_data_rejects_scientific_calibration_without_mutation():
    suite = ScientificCalibrationSuite(ROOT)
    case = fixture_case()
    before_registry = tuple(record.to_dict() for record in suite.registry.records)
    result = suite.calibrate(case, runner=FunctionSimulationRunner(fixture_runner), objective=CalibrationObjective({"biomass": 1.0}), holdout=None)

    assert result.status is CalibrationExecutionStatus.NOT_PERFORMED
    assert result.readiness is CalibrationReadiness.INSUFFICIENT_DATA
    assert result.calibration_performed is False
    assert result.calibrated_parameters is None
    assert tuple(record.to_dict() for record in suite.registry.records) == before_registry
    assert case.parameters.value_map() == {"fixture.scale": 1.0}


def test_synthetic_and_substitute_sources_are_not_real_verified():
    suite = ScientificCalibrationSuite(ROOT)
    sources = suite.audit_sources()
    assert not any(source.classification is DataSourceClassification.REAL_VERIFIED for source in sources)
    assert any(source.classification is DataSourceClassification.SYNTHETIC for source in sources)
    assert any(source.classification is DataSourceClassification.SIMULATED_REAL_DATA_SUBSTITUTE for source in sources)


def test_parameter_audit_excludes_unallowed_unbounded_and_non_identifiable_parameters():
    suite = ScientificCalibrationSuite(ROOT)
    audits = suite.audit_parameters(fixture_dataset())
    rue = next(item for item in audits if item.parameter_id == "radiation.rue")
    assert rue.accepted is False
    assert rue.identifiability in {"INSUFFICIENT_DATA", "CONFOUNDED"}
    assert any("identifiability=" in reason for reason in rue.reasons)


def test_split_has_no_overlap_and_requires_independent_holdout():
    suite = ScientificCalibrationSuite(ROOT)
    calibration = fixture_dataset("calibration")
    holdout = ObservationDataset("holdout", DatasetRole.VALIDATION, (calibration.observations[0],), source_type="synthetic_test_data")
    split = suite.build_split(calibration, holdout)
    assert split.overlap
    assert split.independent is False
    assert suite.readiness(observations=calibration, holdout=holdout) is CalibrationReadiness.INSUFFICIENT_DATA


def test_existing_grid_search_is_available_only_as_synthetic_software_test():
    suite = ScientificCalibrationSuite(ROOT)
    case = fixture_case()
    result = suite.software_fixture_calibration(case, runner=FunctionSimulationRunner(fixture_runner), objective=CalibrationObjective({"biomass": 1.0}), max_evaluations=3)
    assert result.status.value == "SUCCESS"
    assert result.calibrated_parameters is not None
    assert result.calibrated_parameters.values[0].minimum <= result.calibrated_parameters.values[0].value <= result.calibrated_parameters.values[0].maximum
    assert result.dataset == "synthetic_calibration_fixture"


def test_software_fixture_grid_search_is_deterministic_and_transactional():
    suite = ScientificCalibrationSuite(ROOT)
    case = fixture_case()
    runner = FunctionSimulationRunner(fixture_runner)
    objective = CalibrationObjective({"biomass": 1.0})
    first = suite.software_fixture_calibration(case, runner=runner, objective=objective, max_evaluations=3)
    second = suite.software_fixture_calibration(case, runner=runner, objective=objective, max_evaluations=3)
    assert first == second
    assert case.parameters.value_map() == {"fixture.scale": 1.0}


def test_bounds_and_calibration_allowed_are_enforced_by_existing_contract():
    with pytest.raises(CalibrationError):
        fixture_parameter(value=3.0)
    with pytest.raises(CalibrationError):
        fixture_parameter(allowed=False)


def test_report_has_no_calibrated_parameters_or_validation_claim():
    suite = ScientificCalibrationSuite(ROOT)
    report = suite.build_report()
    payload = report.to_dict()
    assert payload["calibration_performed"] is False
    assert payload["parameters_calibrated"] == []
    assert payload["calibration_status"] == "INSUFFICIENT_DATA"
    assert "VALIDATED" not in report.to_json()
    assert "SCIENTIFICALLY_VALIDATED" not in report.to_json()
    assert report.to_json() == suite.build_report().to_json()
