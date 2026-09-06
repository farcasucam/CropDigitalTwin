from datetime import datetime, timedelta, timezone

import pytest

from agri_twin.application import SimulationClock
from agri_twin.domain import (
    CalibrationCase,
    CalibrationError,
    CalibrationObjective,
    CalibrationStatus,
    CalibrationParameter,
    ClockSimulationRunner,
    DatasetRole,
    FunctionSimulationRunner,
    GridSearchCalibrator,
    Observation,
    ObservationComparator,
    ObservationDataset,
    ObservationResolution,
    ParameterSet,
    ParameterRegistry,
    SimulationPoint,
    calculate_metrics,
)


T0 = datetime(2026, 5, 1, tzinfo=timezone.utc)


def parameter(value=1.0):
    return CalibrationParameter("synthetic.growth", value, value, 0.0, 2.0, 0.5, "relative", "engineering_default", "candidate_for_calibration", True)


def dataset(role=DatasetRole.CALIBRATION, value=1.0, resolution=ObservationResolution.DAILY):
    return ObservationDataset("synthetic", role, (Observation(T0, "biomass", value, "g_m-2", resolution=resolution),))


def case(parameter_set=None, validation=None):
    return CalibrationCase("tomato", "synthetic", None, T0, T0 + timedelta(days=1), dataset(), parameter_set or ParameterSet((parameter(),)), validation_dataset=validation)


def test_observations_require_timezone_and_support_events_and_resolution():
    observation = Observation(T0, "flowering", T0.date().isoformat(), "date", resolution=ObservationResolution.EVENT, observation_type="event")

    assert observation.resolution == ObservationResolution.EVENT
    with pytest.raises(CalibrationError):
        Observation(datetime(2026, 5, 1), "lai", 1, "m2_m-2")


def test_comparator_handles_daily_and_event_observations_and_metrics():
    observations = (
        Observation(T0, "biomass", 10.0, "g_m-2", resolution=ObservationResolution.DAILY),
        Observation(T0, "harvest", T0.date().isoformat(), "date", resolution=ObservationResolution.EVENT, observation_type="event"),
    )
    points = (SimulationPoint(T0 + timedelta(hours=12), {"biomass": 12.0, "harvest": T0.date().isoformat()}),)
    records = ObservationComparator().compare(observations, points)
    metrics = calculate_metrics(records)

    assert records[0].absolute_error == 2.0
    assert records[1].absolute_error == 0
    assert metrics[0].rmse == 2.0


def test_parameter_set_selects_only_registry_calibration_candidates():
    registry = ParameterRegistry((
        __import__("agri_twin.domain", fromlist=["ParameterRecord"]).ParameterRecord("p", "p", "p", "biological", "test", "tomato", None, None, "x", 1.0, 0.0, 2.0, "engineering_default", None, "test", "none", "low", "candidate_for_calibration", True, "data"),
    ))
    selected = ParameterSet.from_registry(registry, crop="tomato")

    assert [item.parameter_id for item in selected.values] == ["p"]


def test_grid_search_recovers_synthetic_parameter_deterministically():
    def simulate(case, parameters, dataset):
        value = parameters.value_map()["synthetic.growth"]
        return (SimulationPoint(T0, {"biomass": value}),)

    calibrator = GridSearchCalibrator(FunctionSimulationRunner(simulate), CalibrationObjective({"biomass": 1.0}), max_evaluations=20)
    result = calibrator.fit(case())

    assert result.status == CalibrationStatus.SUCCESS
    assert result.calibrated_parameters.value_map()["synthetic.growth"] == 1.0
    assert result == calibrator.fit(case())


def test_insufficient_data_result_is_explicit():
    empty_parameters = ParameterSet(())
    result = GridSearchCalibrator(FunctionSimulationRunner(lambda *_: ()), CalibrationObjective({"biomass": 1}), 5).fit(case(empty_parameters))

    assert result.status == CalibrationStatus.INSUFFICIENT_DATA


def test_validation_dataset_is_separate_from_calibration_dataset():
    validation = dataset(DatasetRole.VALIDATION)
    valid = case(validation=validation)

    assert valid.validation_dataset.role == DatasetRole.VALIDATION
    with pytest.raises(CalibrationError):
        case(validation=dataset(DatasetRole.CALIBRATION))


def test_clock_runner_advances_only_simulation_time():
    clock = SimulationClock(T0)
    runner = ClockSimulationRunner(clock, 3600, lambda timestamp, _: {"temperature": 20.0})
    points = runner.run(case(), ParameterSet((parameter(),)), dataset())

    assert len(points) == 25
    assert clock.now() == T0 + timedelta(days=1)


def test_observation_uncertainty_must_be_non_negative():
    with pytest.raises(CalibrationError):
        Observation(T0, "lai", 1, "m2_m-2", uncertainty=-1)


def test_event_requires_event_type():
    with pytest.raises(CalibrationError):
        Observation(T0, "flowering", T0.date().isoformat(), "date", resolution=ObservationResolution.EVENT)


def test_dataset_requires_observations():
    with pytest.raises(CalibrationError):
        ObservationDataset("empty", DatasetRole.CALIBRATION, ())


def test_dataset_requires_matching_case_role():
    with pytest.raises(CalibrationError):
        CalibrationCase("tomato", None, None, T0, T0 + timedelta(days=1), dataset(DatasetRole.VALIDATION), ParameterSet((parameter(),)))


def test_parameter_set_rejects_duplicate_ids():
    with pytest.raises(CalibrationError):
        ParameterSet((parameter(), parameter()))


def test_parameter_rejects_invalid_step_and_bounds():
    with pytest.raises(CalibrationError):
        CalibrationParameter("p", 1, 1, 2, 1, 1, "x", "unknown", "candidate_for_calibration", True)


def test_parameter_set_updates_only_requested_values():
    parameters = ParameterSet((parameter(), CalibrationParameter("other", 2, 2, 0, 2, 1, "x", "engineering_default", "candidate_for_calibration", True)))

    updated = parameters.with_values({"synthetic.growth": 0.5})

    assert updated.value_map() == {"synthetic.growth": 0.5, "other": 2}


def test_daily_matching_does_not_require_exact_hour():
    observation = Observation(T0, "biomass", 10, "g_m-2", resolution=ObservationResolution.DAILY)
    records = ObservationComparator().compare((observation,), (SimulationPoint(T0 + timedelta(hours=23), {"biomass": 10}),))

    assert records[0].residual == 0


def test_missing_simulation_is_reported_without_residual():
    records = ObservationComparator().compare((Observation(T0, "lai", 1, "m2_m-2"),), ())

    assert records[0].simulated is None and records[0].absolute_error is None


def test_unit_mismatch_is_not_compared():
    records = ObservationComparator().compare((Observation(T0, "lai", 1, "m2_m-2"),), (SimulationPoint(T0, {"lai": 1}, {"lai": "kg"}),))

    assert records[0].simulated is None


def test_metrics_compute_mae_rmse_bias_and_r2():
    records = ObservationComparator().compare((Observation(T0, "x", 1, "u"), Observation(T0 + timedelta(hours=1), "x", 3, "u")), (SimulationPoint(T0, {"x": 2}), SimulationPoint(T0 + timedelta(hours=1), {"x": 2})))
    metric = calculate_metrics(records)[0]

    assert metric.mae == 1 and metric.rmse == 1 and metric.bias == 0 and metric.r2 == 0


def test_event_metrics_are_not_continuous_metrics():
    observation = Observation(T0, "flowering", T0.date().isoformat(), "date", resolution=ObservationResolution.EVENT, observation_type="event")
    records = ObservationComparator().compare((observation,), (SimulationPoint(T0, {"flowering": (T0 + timedelta(days=3)).date().isoformat()}),))
    metric = calculate_metrics(records)[0]

    assert metric.rmse is None and metric.event_error_days == 3


def test_objective_normalizes_variables():
    objective = CalibrationObjective({"small": 1, "large": 1}, {"small": 1, "large": 100})
    from agri_twin.domain.calibration import VariableMetrics

    assert objective.score((VariableMetrics("small", 1, 1, 1, 0, None), VariableMetrics("large", 1, 100, 100, 0, None))) == 1


def test_objective_rejects_invalid_normalizer():
    with pytest.raises(CalibrationError):
        CalibrationObjective({"x": 1}, {"x": 0}).score((__import__("agri_twin.domain.calibration", fromlist=["VariableMetrics"]).VariableMetrics("x", 1, 1, 1, 0, None),))


def test_grid_search_respects_maximum_evaluations():
    calls = []
    runner = FunctionSimulationRunner(lambda case, parameters, data: (calls.append(parameters.value_map()) or SimulationPoint(T0, {"biomass": 0}),))
    calibrator = GridSearchCalibrator(runner, CalibrationObjective({"biomass": 1}), max_evaluations=2)

    result = calibrator.fit(case())

    assert result.evaluations == 2 and len(calls) == 2


def test_grid_search_target_score_stops_early():
    calibrator = GridSearchCalibrator(FunctionSimulationRunner(lambda *_: (SimulationPoint(T0, {"biomass": 1}),)), CalibrationObjective({"biomass": 1}), max_evaluations=20, target_score=0)

    result = calibrator.fit(case())

    assert result.evaluations == 1 and result.score == 0


def test_grid_search_failed_status_when_no_evaluation_can_run():
    calibrator = GridSearchCalibrator(FunctionSimulationRunner(lambda *_: ()), CalibrationObjective({"missing": 1}), max_evaluations=1)
    result = calibrator.fit(case())

    assert result.status == CalibrationStatus.FAILED


def test_parameter_registry_selection_can_be_empty_without_inventing_values():
    from agri_twin.domain import ParameterRegistry

    assert not ParameterSet.from_registry(ParameterRegistry(()), crop="tomato").values


def test_clock_runner_rejects_non_positive_step():
    with pytest.raises(CalibrationError):
        ClockSimulationRunner(SimulationClock(T0), 0, lambda *_: {})


def test_prediction_model_is_abstract():
    from agri_twin.domain import PredictionModel

    with pytest.raises(TypeError):
        PredictionModel()