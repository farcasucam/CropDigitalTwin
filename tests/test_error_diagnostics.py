from datetime import datetime, timezone

import pytest

from agri_twin.application import (
    AlignmentResult,
    AlignmentStatus,
    ComparisonDataset,
    ComparisonResult,
    CycleResolution,
    diagnose,
)
from agri_twin.domain.validation import AlignmentPolicy

T0 = datetime(2026, 5, 1, 10, tzinfo=timezone.utc)


def result(observed, simulated, *, plot="plot-a", crop="tomato", variety="RAF", cycle="cycle-a", variable="lai", stage="flowering", environment="GREENHOUSE", status=AlignmentStatus.MATCHED, quality="VALID", observation_id="obs"):
    alignment = AlignmentResult(status, observation_id, plot, cycle, T0, T0 if status is AlignmentStatus.MATCHED else None, 0.0 if status is AlignmentStatus.MATCHED else None, AlignmentPolicy.EXACT, CycleResolution.EXPLICIT, "matched" if status is AlignmentStatus.MATCHED else "invalid", status is AlignmentStatus.MATCHED)
    residual = simulated - observed if status is AlignmentStatus.MATCHED else None
    return ComparisonResult(alignment, variable, crop, variety, observed, "m2_m-2", simulated if status is AlignmentStatus.MATCHED else None, "m2_m-2" if status is AlignmentStatus.MATCHED else None, residual, abs(residual) if residual is not None else None, 0.2, quality, "technician", "SIMULATION", stage, environment)


def dataset(*items):
    matched = sum(item.alignment.status is AlignmentStatus.MATCHED for item in items)
    ambiguous = sum(item.alignment.status is AlignmentStatus.AMBIGUOUS for item in items)
    invalid = sum(item.alignment.status in {AlignmentStatus.INVALID_OBSERVATION, AlignmentStatus.UNIT_ERROR, AlignmentStatus.MISSING_SIMULATION_VARIABLE} for item in items)
    return ComparisonDataset(tuple(items), matched, len(items) - matched - ambiguous - invalid, ambiguous, invalid)


def test_global_metrics_reuse_existing_definitions():
    diagnostics = diagnose(dataset(result(1, 2), result(2, 2), result(3, 4)))
    summary = diagnostics.global_summary()
    assert summary.n == 3
    assert summary.mae == pytest.approx(2 / 3)
    assert summary.rmse == pytest.approx((2 / 3) ** 0.5)
    assert summary.bias == pytest.approx(2 / 3)
    assert summary.r2 is not None
    assert summary.coverage_ratio == 1


def test_multilevel_grouping_keeps_context_separate():
    diagnostics = diagnose(dataset(
        result(1, 2, plot="plot-a", cycle="lettuce-1", crop="lettuce", variety="", environment="GREENHOUSE"),
        result(1, 4, plot="plot-a", cycle="lettuce-2", crop="lettuce", variety="", environment="GREENHOUSE"),
        result(1, 3, plot="plot-b", cycle="pepper-1", crop="pepper", variety="Lamuyo", environment="OUTDOOR"),
    ))
    assert {item.group_key for item in diagnostics.by_plot()} == {"plot-a", "plot-b"}
    assert {item.group_key for item in diagnostics.by_cycle()} == {"plot-a:lettuce-1", "plot-a:lettuce-2", "plot-b:pepper-1"}
    assert {item.group_key for item in diagnostics.by_crop()} == {"lettuce", "pepper"}
    assert {item.group_key for item in diagnostics.by_environment()} == {"GREENHOUSE", "OUTDOOR"}
    assert len(diagnostics.by_stage()) == 1


def test_quality_coverage_and_outlier_are_reported_without_removal():
    diagnostics = diagnose(dataset(
        result(1, 2),
        result(1, 9, observation_id="outlier"),
        result(1, None, status=AlignmentStatus.INVALID_OBSERVATION, quality="INVALID", observation_id="invalid"),
        result(1, None, status=AlignmentStatus.NO_MATCH, quality="VALID", observation_id="unmatched"),
        result(1, 2, quality="ESTIMATED", observation_id="estimated"),
    ), outlier_threshold=5)
    summary = diagnostics.global_summary()
    assert summary.invalid_count == 1
    assert summary.unmatched_count == 1
    assert summary.quality.estimated_count == 1
    assert len(diagnostics.outliers()) == 1
    assert len(diagnostics.comparison.results) == 5


def test_empty_constant_and_json_determinism():
    empty = diagnose(ComparisonDataset((), 0, 0, 0, 0))
    assert empty.global_summary().status == "NO_DATA"
    assert empty.global_summary().mae is None
    constant = diagnose(dataset(result(2, 2), result(2, 3))).global_summary()
    assert constant.r2 is None
    assert diagnose(dataset(result(1, 2))).to_dict() == diagnose(dataset(result(1, 2))).to_dict()


def test_baseline_improvement_and_no_mutation():
    current = dataset(result(1, 2), result(2, 3))
    baseline = dataset(result(1, 4), result(2, 5))
    diagnostics = diagnose(current, baseline=baseline)
    assert diagnostics.baseline_summary().rmse > diagnostics.global_summary().rmse
    assert diagnostics.relative_rmse_improvement() > 0
    assert current == dataset(result(1, 2), result(2, 3))
