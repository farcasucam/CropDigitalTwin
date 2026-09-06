"""Independent scientific validation and benchmark contracts."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Iterable, Mapping, Protocol, Sequence

from agri_twin.domain.calibration import (
    CalibrationError,
    DatasetRole,
    Observation,
    ObservationComparator,
    ObservationDataset,
    ObservationResolution,
    ParameterSet,
    SimulationPoint,
    VariableMetrics,
    calculate_metrics,
)


class ValidationError(ValueError):
    """Raised when a validation case or policy is invalid."""


class ValidationStatus(StrEnum):
    SUCCESS = "SUCCESS"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    IN_SAMPLE_ONLY = "IN_SAMPLE_ONLY"
    FAILED = "FAILED"


class AlignmentPolicy(StrEnum):
    EXACT = "exact"
    SAME_DAY = "same_day"
    NEAREST = "nearest"
    WINDOW = "aggregation_window"
    EVENT = "event"


@dataclass(frozen=True, slots=True)
class ValidationCase:
    crop: str
    variety: str | None
    plot: str | None
    start: datetime
    end: datetime
    dataset: ObservationDataset
    parameters: ParameterSet
    model_name: str = "CropDigitalTwin"
    model_version: str = "1.0"
    variables: tuple[str, ...] = ()
    resolution: ObservationResolution | None = None
    alignment: AlignmentPolicy = AlignmentPolicy.EXACT
    period_label: str = "whole_season"
    stage_labels: Mapping[str, str] = field(default_factory=dict)
    experiment_id: str = "validation"

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None or self.end <= self.start:
            raise ValidationError("validation period must be ordered and timezone-aware")
        if not self.dataset.observations:
            raise ValidationError("validation dataset cannot be empty")
        if self.dataset.role == DatasetRole.CALIBRATION:
            raise ValidationError("validation requires independent validation/test data")


@dataclass(frozen=True, slots=True)
class ValidationComparison:
    records: tuple
    policy: AlignmentPolicy
    missing_observations: int
    missing_simulations: int
    duplicate_observations: int
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ValidationResult:
    status: ValidationStatus
    case: ValidationCase
    dataset: str
    model_name: str
    parameter_set: ParameterSet
    observation_count: int
    period: tuple[datetime, datetime]
    metrics: tuple[VariableMetrics, ...]
    metrics_by_period: Mapping[str, tuple[VariableMetrics, ...]]
    metrics_by_stage: Mapping[str, tuple[VariableMetrics, ...]]
    event_errors_days: Mapping[str, tuple[float, ...]]
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]
    alignment: AlignmentPolicy
    independent: bool


def _match_points(observation: Observation, points: Sequence[SimulationPoint], policy: AlignmentPolicy, window_seconds: float) -> tuple[SimulationPoint, ...]:
    if policy == AlignmentPolicy.EXACT:
        return tuple(point for point in points if point.timestamp == observation.timestamp)
    if policy == AlignmentPolicy.SAME_DAY:
        return tuple(point for point in points if point.timestamp.date() == observation.timestamp.date())
    if policy == AlignmentPolicy.EVENT:
        return tuple(points)
    if policy == AlignmentPolicy.WINDOW:
        return tuple(point for point in points if abs((point.timestamp - observation.timestamp).total_seconds()) <= window_seconds)
    return tuple(points)


class ValidationComparator:
    def compare(self, observations: Iterable[Observation], simulated: Iterable[SimulationPoint], policy: AlignmentPolicy = AlignmentPolicy.EXACT, window_seconds: float = 0.0) -> ValidationComparison:
        observations = tuple(observations)
        points = tuple(sorted(simulated, key=lambda point: point.timestamp))
        duplicates = len(observations) - len({(item.timestamp, item.variable) for item in observations})
        records = []
        missing_observations = missing_simulations = 0
        warnings: list[str] = []
        for observation in observations:
            candidates = _match_points(observation, points, policy, window_seconds)
            if policy == AlignmentPolicy.EVENT or observation.resolution == ObservationResolution.EVENT:
                candidate = candidates[0] if candidates else None
            elif policy == AlignmentPolicy.WINDOW:
                candidate = candidates[0] if candidates else None
            else:
                candidate = min(candidates, key=lambda point: abs(point.timestamp - observation.timestamp)) if candidates else None
            if candidate is None:
                missing_simulations += 1
                missing_observations += 1
            records.extend(ObservationComparator().compare((observation,), (candidate,) if candidate else ()))
        if duplicates:
            warnings.append(f"duplicate observations: {duplicates}")
        if missing_simulations:
            warnings.append(f"missing simulation matches: {missing_simulations}")
        return ValidationComparison(tuple(records), policy, missing_observations, missing_simulations, duplicates, tuple(warnings))


class ValidationRunner(Protocol):
    def run(self, case: ValidationCase) -> tuple[SimulationPoint, ...]: ...


def _run_validation(runner: ValidationRunner | callable, case: ValidationCase) -> tuple[SimulationPoint, ...]:
    if callable(runner) and not hasattr(runner, "run"):
        return tuple(runner(case))
    return tuple(runner.run(case))


def _event_errors(comparison: ValidationComparison) -> dict[str, tuple[float, ...]]:
    errors: dict[str, list[float]] = {}
    for record in comparison.records:
        if record.variable and record.residual is None and record.absolute_error is not None:
            errors.setdefault(record.variable, []).append(float(record.absolute_error))
    return {key: tuple(values) for key, values in sorted(errors.items())}


class ValidationEngine:
    def evaluate(self, case: ValidationCase, runner: ValidationRunner) -> ValidationResult:
        if case.dataset.role == DatasetRole.CALIBRATION:
            return ValidationResult(ValidationStatus.IN_SAMPLE_ONLY, case, case.dataset.name, case.model_name, case.parameters, len(case.dataset.observations), (case.start, case.end), (), {}, {}, {}, ("calibration dataset is not independent",), ("in-sample evaluation cannot establish validation",), case.alignment, False)
        if not case.dataset.observations:
            return ValidationResult(ValidationStatus.INSUFFICIENT_DATA, case, case.dataset.name, case.model_name, case.parameters, 0, (case.start, case.end), (), {}, {}, {}, ("no observations",), ("independent observations are required",), case.alignment, True)
        points = _run_validation(runner, case)
        comparison = ValidationComparator().compare(case.dataset.observations, points, case.alignment)
        metrics = calculate_metrics(comparison.records)
        warnings = list(comparison.warnings)
        if not any(metric.count for metric in metrics):
            warnings.append("no valid observation/simulation pairs")
            status = ValidationStatus.INSUFFICIENT_DATA
        else:
            status = ValidationStatus.SUCCESS
        by_period = {case.period_label: metrics}
        return ValidationResult(status, case, case.dataset.name, case.model_name, case.parameters, len(case.dataset.observations), (case.start, case.end), metrics, by_period, {}, _event_errors(comparison), tuple(warnings), ("synthetic or independent observations required for scientific claims",), case.alignment, True)


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    dataset: str
    results: Mapping[str, ValidationResult]
    ranking: tuple[str, ...]


class BenchmarkEngine:
    def evaluate(self, case: ValidationCase, models: Mapping[str, ValidationRunner]) -> BenchmarkResult:
        results = {name: ValidationEngine().evaluate(replace_case(case, model_name=name), runner) for name, runner in sorted(models.items())}
        ranked = tuple(sorted(results, key=lambda name: _result_score(results[name])))
        return BenchmarkResult(case.dataset.name, results, ranked)


def replace_case(case: ValidationCase, **changes) -> ValidationCase:
    from dataclasses import replace
    return replace(case, **changes)


def _result_score(result: ValidationResult) -> float:
    values = [metric.rmse for metric in result.metrics if metric.rmse is not None]
    return sum(values) / len(values) if values else math.inf


class PersistenceBaseline:
    """Simple baseline adapter: repeat the first known value."""

    def run(self, case: ValidationCase) -> tuple[SimulationPoint, ...]:
        first = case.dataset.observations[0]
        return (SimulationPoint(case.start, {first.variable: first.value}, {first.variable: first.unit}),)