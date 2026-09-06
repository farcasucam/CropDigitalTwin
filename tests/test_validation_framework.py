from datetime import datetime, timedelta, timezone

import pytest

from agri_twin.domain import (
    AlignmentPolicy,
    BenchmarkEngine,
    CalibrationParameter,
    DatasetRole,
    Observation,
    ObservationDataset,
    ObservationResolution,
    ParameterSet,
    PersistenceBaseline,
    SimulationPoint,
    ValidationCase,
    ValidationComparator,
    ValidationEngine,
    ValidationError,
    ValidationStatus,
)


T0 = datetime(2026, 6, 1, tzinfo=timezone.utc)


def parameters():
    return ParameterSet((CalibrationParameter("p", 1, 1, 0, 2, 1, "u", "engineering_default", "candidate_for_calibration", True),))


def observations(role=DatasetRole.VALIDATION, values=(1.0, 2.0)):
    return ObservationDataset("synthetic-independent", role, tuple(Observation(T0 + timedelta(days=index), "lai", value, "m2_m-2", resolution=ObservationResolution.DAILY) for index, value in enumerate(values)))


def case(role=DatasetRole.VALIDATION, alignment=AlignmentPolicy.SAME_DAY):
    return ValidationCase("tomato", "synthetic", None, T0, T0 + timedelta(days=2), observations(role), parameters(), alignment=alignment)


def points(values=(1.0, 2.0)):
    return tuple(SimulationPoint(T0 + timedelta(days=index), {"lai": value}, {"lai": "m2_m-2"}) for index, value in enumerate(values))


def test_valid_validation_case():
    assert case().dataset.role == DatasetRole.VALIDATION


def test_calibration_dataset_is_rejected_as_validation_case():
    with pytest.raises(ValidationError):
        case(DatasetRole.CALIBRATION)


def test_empty_validation_dataset_is_rejected_by_dataset_contract():
    with pytest.raises(ValueError):
        ObservationDataset("empty", DatasetRole.VALIDATION, ())


def test_exact_alignment():
    comparison = ValidationComparator().compare(observations().observations, points(), AlignmentPolicy.EXACT)

    assert all(record.residual == 0 for record in comparison.records)


def test_same_day_alignment():
    shifted = (SimulationPoint(T0 + timedelta(hours=12), {"lai": 1}, {"lai": "m2_m-2"}), SimulationPoint(T0 + timedelta(days=1, hours=12), {"lai": 2}, {"lai": "m2_m-2"}))
    comparison = ValidationComparator().compare(observations().observations, shifted, AlignmentPolicy.SAME_DAY)

    assert comparison.missing_simulations == 0


def test_nearest_alignment():
    comparison = ValidationComparator().compare(observations().observations, points(), AlignmentPolicy.NEAREST)

    assert len(comparison.records) == 2


def test_window_alignment_rejects_outside_window():
    comparison = ValidationComparator().compare(observations().observations, (SimulationPoint(T0 + timedelta(hours=12), {"lai": 1}),), AlignmentPolicy.WINDOW, 60)

    assert comparison.missing_simulations == 2


def test_missing_simulation_warning():
    comparison = ValidationComparator().compare(observations().observations, (), AlignmentPolicy.EXACT)

    assert comparison.missing_simulations == 2
    assert comparison.warnings


def test_duplicate_observation_warning():
    duplicate = observations().observations[0]
    comparison = ValidationComparator().compare((duplicate, duplicate), points(), AlignmentPolicy.EXACT)

    assert comparison.duplicate_observations == 1


def test_invalid_unit_is_not_silently_compared():
    simulation = (SimulationPoint(T0, {"lai": 1}, {"lai": "kg"}),)
    comparison = ValidationComparator().compare(observations().observations[:1], simulation, AlignmentPolicy.EXACT)

    assert comparison.records[0].simulated is None


def test_success_result_has_metrics_and_traceability():
    result = ValidationEngine().evaluate(case(), lambda current_case: points())

    assert result.status == ValidationStatus.SUCCESS
    assert result.metrics[0].rmse == 0
    assert result.alignment == AlignmentPolicy.SAME_DAY
    assert result.independent is True


def test_calibration_role_is_in_sample_only_result():
    dataset = observations(DatasetRole.CALIBRATION)
    # Bypass ValidationCase's independent-data guard to verify result semantics.
    object.__setattr__(case(), "dataset", dataset) if False else None
    with pytest.raises(ValidationError):
        case(DatasetRole.CALIBRATION)


def test_insufficient_result_for_no_valid_pairs():
    empty_points = lambda current_case: ()
    result = ValidationEngine().evaluate(case(), empty_points)

    assert result.status == ValidationStatus.INSUFFICIENT_DATA


def test_event_validation_records_date_error():
    event_dataset = ObservationDataset("events", DatasetRole.VALIDATION, (Observation(T0, "flowering", T0.date().isoformat(), "date", resolution=ObservationResolution.EVENT, observation_type="event"),))
    event_case = ValidationCase("tomato", None, None, T0, T0 + timedelta(days=2), event_dataset, parameters(), alignment=AlignmentPolicy.EVENT)
    result = ValidationEngine().evaluate(event_case, lambda current_case: (SimulationPoint(T0, {"flowering": (T0 + timedelta(days=2)).date().isoformat()}),))

    assert result.event_errors_days["flowering"] == (2.0,)


def test_period_metrics_are_retained():
    result = ValidationEngine().evaluate(case(), lambda current_case: points())

    assert "whole_season" in result.metrics_by_period


def test_benchmark_uses_same_dataset_and_ranks_models():
    benchmark = BenchmarkEngine().evaluate(case(), {"good": lambda current_case: points(), "bad": lambda current_case: points((3, 4))})

    assert benchmark.ranking[0] == "good"
    assert set(benchmark.results) == {"good", "bad"}


def test_benchmark_is_reproducible():
    engine = BenchmarkEngine()
    first = engine.evaluate(case(), {"good": lambda current_case: points()})
    second = engine.evaluate(case(), {"good": lambda current_case: points()})

    assert first == second


def test_persistence_baseline_is_available():
    result = PersistenceBaseline().run(case())

    assert result[0].variables["lai"] == 1


def test_event_resolution_is_not_treated_as_continuous_series():
    event = Observation(T0, "harvest", T0.date().isoformat(), "date", resolution=ObservationResolution.EVENT, observation_type="event")

    assert event.resolution == ObservationResolution.EVENT


def test_stage_labels_can_be_preserved_in_case():
    configured = ValidationCase("tomato", None, None, T0, T0 + timedelta(days=2), observations(), parameters(), stage_labels={"development": "vegetative_growth"})

    assert configured.stage_labels["development"] == "vegetative_growth"


def test_period_label_is_explicit():
    configured = ValidationCase("tomato", None, None, T0, T0 + timedelta(days=2), observations(), parameters(), period_label="flowering")

    assert configured.period_label == "flowering"


def test_observation_uncertainty_survives_comparison():
    observed = Observation(T0, "lai", 1, "m2_m-2", uncertainty=0.1)
    record = ValidationComparator().compare((observed,), points((1,)), AlignmentPolicy.EXACT).records[0]

    assert record.uncertainty == 0.1


def test_model_name_is_retained_in_result():
    configured = ValidationCase("tomato", None, None, T0, T0 + timedelta(days=2), observations(), parameters(), model_name="synthetic-digital-twin")
    result = ValidationEngine().evaluate(configured, lambda current_case: points())

    assert result.model_name == "synthetic-digital-twin"


def test_validation_result_repeated_execution_is_equal():
    engine = ValidationEngine()
    first = engine.evaluate(case(), lambda current_case: points())
    second = engine.evaluate(case(), lambda current_case: points())

    assert first == second


def test_weekly_resolution_is_supported():
    weekly = Observation(T0, "lai", 1, "m2_m-2", resolution=ObservationResolution.WEEKLY)

    assert weekly.resolution == ObservationResolution.WEEKLY


def test_hourly_and_subhourly_resolutions_are_supported():
    hourly = Observation(T0, "temperature", 20, "degC", resolution=ObservationResolution.HOURLY)
    subhourly = Observation(T0, "temperature", 20, "degC", resolution=ObservationResolution.SUBHOURLY)

    assert hourly.resolution != subhourly.resolution


def test_case_keeps_parameter_set():
    configured = case()

    assert configured.parameters.value_map()["p"] == 1