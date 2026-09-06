"""Deterministic calibration framework independent from crop physics."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from itertools import product
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

from agri_twin.domain.parameter_audit import ParameterRecord, ParameterRegistry


class CalibrationError(ValueError):
    """Raised for invalid calibration contracts."""


class ObservationResolution(StrEnum):
    INSTANT = "instant"
    HOURLY = "hourly"
    SUBHOURLY = "subhourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    EVENT = "event"


class DatasetRole(StrEnum):
    CALIBRATION = "calibration"
    VALIDATION = "validation"
    TEST = "test"


class CalibrationStatus(StrEnum):
    SUCCESS = "SUCCESS"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class Observation:
    timestamp: datetime
    variable: str
    value: float | str
    unit: str
    uncertainty: float | None = None
    source: str = "unknown"
    quality: str = "unknown"
    resolution: ObservationResolution = ObservationResolution.INSTANT
    observation_type: str = "continuous"

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or not self.variable or not self.unit:
            raise CalibrationError("observation timestamp, variable and unit are required")
        if self.uncertainty is not None and (not math.isfinite(self.uncertainty) or self.uncertainty < 0):
            raise CalibrationError("observation uncertainty must be non-negative")
        if self.resolution == ObservationResolution.EVENT and self.observation_type != "event":
            raise CalibrationError("event resolution requires event observation_type")


@dataclass(frozen=True, slots=True)
class ObservationDataset:
    name: str
    role: DatasetRole
    observations: tuple[Observation, ...]

    def __post_init__(self) -> None:
        if not self.name or not self.observations:
            raise CalibrationError("dataset name and observations are required")


@dataclass(frozen=True, slots=True)
class CalibrationParameter:
    parameter_id: str
    value: float
    initial_value: float
    minimum: float
    maximum: float
    step: float
    unit: str
    source_type: str
    calibration_status: str
    calibration_allowed: bool

    def __post_init__(self) -> None:
        if self.minimum > self.maximum or self.step <= 0 or not self.minimum <= self.value <= self.maximum:
            raise CalibrationError(f"invalid calibration parameter range: {self.parameter_id}")
        if not self.calibration_allowed:
            raise CalibrationError(f"parameter is not calibrable: {self.parameter_id}")


@dataclass(frozen=True, slots=True)
class ParameterSet:
    values: tuple[CalibrationParameter, ...]
    name: str = "default"

    def __post_init__(self) -> None:
        ids = [parameter.parameter_id for parameter in self.values]
        if len(ids) != len(set(ids)):
            raise CalibrationError("duplicate parameters in parameter set")

    def value_map(self) -> dict[str, float]:
        return {parameter.parameter_id: parameter.value for parameter in self.values}

    def with_values(self, updates: Mapping[str, float]) -> "ParameterSet":
        return replace(self, values=tuple(replace(parameter, value=updates.get(parameter.parameter_id, parameter.value)) for parameter in self.values))

    @classmethod
    def from_registry(cls, registry: ParameterRegistry, *, crop: str | None = None, variety: str | None = None, stage: str | None = None, subsystem: str | None = None, include_unknown: bool = False) -> "ParameterSet":
        selected: list[CalibrationParameter] = []
        for record in registry.records:
            if crop is not None and record.crop not in {None, crop}:
                continue
            if variety is not None and record.variety not in {None, variety}:
                continue
            if stage is not None and record.phenological_stage not in {None, stage}:
                continue
            if subsystem is not None and record.subsystem != subsystem:
                continue
            if not record.calibration_allowed or record.minimum is None or record.maximum is None:
                continue
            if record.value is None and not include_unknown:
                continue
            value = float(record.value if record.value is not None else record.minimum)
            minimum, maximum = float(record.minimum), float(record.maximum)
            step = max((maximum - minimum) / 10.0, 1e-9)
            selected.append(CalibrationParameter(record.parameter_id, value, value, minimum, maximum, step, record.unit or "", record.source_type, record.calibration_status, True))
        return cls(tuple(selected), name=f"{crop or 'all'} calibration set")


@dataclass(frozen=True, slots=True)
class SimulationPoint:
    timestamp: datetime
    variables: Mapping[str, float | str]
    units: Mapping[str, str] = field(default_factory=dict)


class SimulationRunner(Protocol):
    def run(self, case: "CalibrationCase", parameters: ParameterSet, dataset: ObservationDataset) -> tuple[SimulationPoint, ...]: ...


class FunctionSimulationRunner:
    """Adapter for a deterministic simulation function or future orchestrator."""

    def __init__(self, function: Callable[["CalibrationCase", ParameterSet, ObservationDataset], tuple[SimulationPoint, ...]]) -> None:
        self._function = function

    def run(self, case: "CalibrationCase", parameters: ParameterSet, dataset: ObservationDataset) -> tuple[SimulationPoint, ...]:
        return tuple(self._function(case, parameters, dataset))


class ClockSimulationRunner:
    """Run a deterministic callback at simulated timestamps only."""

    def __init__(self, clock: Any, step_seconds: float, callback: Callable[[datetime, ParameterSet], Mapping[str, float | str]]) -> None:
        if not math.isfinite(step_seconds) or step_seconds <= 0:
            raise CalibrationError("step_seconds must be positive and finite")
        self._clock = clock
        self._step_seconds = step_seconds
        self._callback = callback

    def run(self, case: "CalibrationCase", parameters: ParameterSet, dataset: ObservationDataset) -> tuple[SimulationPoint, ...]:
        points = []
        current = case.start
        while current <= case.end:
            points.append(SimulationPoint(current, dict(self._callback(current, parameters))))
            if current == case.end:
                break
            delta = min(self._step_seconds, (case.end - current).total_seconds())
            self._clock.advance(delta)
            current += timedelta(seconds=delta)
        return tuple(points)


@dataclass(frozen=True, slots=True)
class CalibrationCase:
    crop: str
    variety: str | None
    plot: str | None
    start: datetime
    end: datetime
    calibration_dataset: ObservationDataset
    parameters: ParameterSet
    validation_dataset: ObservationDataset | None = None
    model_name: str = "CropDigitalTwin"
    configuration_version: str = "1.0"
    initial_state: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None or self.end <= self.start:
            raise CalibrationError("calibration period must be ordered and timezone-aware")
        if self.calibration_dataset.role != DatasetRole.CALIBRATION:
            raise CalibrationError("CalibrationCase requires a calibration dataset")
        if self.validation_dataset is not None and self.validation_dataset.role != DatasetRole.VALIDATION:
            raise CalibrationError("validation_dataset must be separate and marked validation")


@dataclass(frozen=True, slots=True)
class ComparisonRecord:
    timestamp: datetime
    variable: str
    observed: float | str
    simulated: float | str | None
    residual: float | None
    absolute_error: float | None
    uncertainty: float | None = None


def _nearest(points: Sequence[SimulationPoint], observation: Observation) -> SimulationPoint | None:
    if observation.resolution == ObservationResolution.EVENT:
        candidates = [point for point in points if point.timestamp.date() == observation.timestamp.date() or point.timestamp <= observation.timestamp]
    elif observation.resolution == ObservationResolution.DAILY:
        candidates = [point for point in points if point.timestamp.date() == observation.timestamp.date()]
    elif observation.resolution == ObservationResolution.WEEKLY:
        candidates = [point for point in points if abs((point.timestamp.date() - observation.timestamp.date()).days) <= 6]
    else:
        candidates = list(points)
    return min(candidates, key=lambda point: abs(point.timestamp - observation.timestamp)) if candidates else None


class ObservationComparator:
    def compare(self, observations: Iterable[Observation], simulated: Iterable[SimulationPoint]) -> tuple[ComparisonRecord, ...]:
        points = tuple(sorted(simulated, key=lambda point: point.timestamp))
        records = []
        for observation in observations:
            point = _nearest(points, observation)
            value = point.variables.get(observation.variable) if point else None
            compatible_unit = point is not None and (not point.units or point.units.get(observation.variable) == observation.unit)
            if not compatible_unit:
                value = None
            if isinstance(observation.value, (int, float)) and isinstance(value, (int, float)):
                residual = float(value) - float(observation.value)
                absolute = abs(residual)
            elif observation.resolution == ObservationResolution.EVENT and isinstance(value, str):
                residual = None
                absolute = abs((datetime.fromisoformat(value).date() - observation.timestamp.date()).days) if value else None
            else:
                residual = absolute = None
            records.append(ComparisonRecord(observation.timestamp, observation.variable, observation.value, value, residual, absolute, observation.uncertainty))
        return tuple(records)


@dataclass(frozen=True, slots=True)
class VariableMetrics:
    variable: str
    count: int
    mae: float | None
    rmse: float | None
    bias: float | None
    r2: float | None
    event_error_days: float | None = None


def calculate_metrics(records: Iterable[ComparisonRecord]) -> tuple[VariableMetrics, ...]:
    by_variable: dict[str, list[ComparisonRecord]] = {}
    for record in records:
        by_variable.setdefault(record.variable, []).append(record)
    output = []
    for variable, items in sorted(by_variable.items()):
        numeric = [item.residual for item in items if item.residual is not None]
        event_errors = [item.absolute_error for item in items if item.absolute_error is not None and item.residual is None]
        if not numeric:
            output.append(VariableMetrics(variable, len(event_errors), None, None, None, None, sum(event_errors) / len(event_errors) if event_errors else None))
            continue
        mean = sum(numeric) / len(numeric)
        observed = [float(item.observed) for item in items if item.residual is not None]
        total = sum((value - sum(observed) / len(observed)) ** 2 for value in observed)
        residual_sum = sum(value * value for value in numeric)
        output.append(VariableMetrics(variable, len(numeric), sum(abs(value) for value in numeric) / len(numeric), math.sqrt(residual_sum / len(numeric)), mean, 1 - residual_sum / total if total else None))
    return tuple(output)


@dataclass(frozen=True, slots=True)
class CalibrationObjective:
    weights: Mapping[str, float]
    normalizers: Mapping[str, float] = field(default_factory=dict)

    def score(self, metrics: Iterable[VariableMetrics]) -> float:
        by_variable = {metric.variable: metric for metric in metrics}
        total = weight_sum = 0.0
        for variable, weight in self.weights.items():
            metric = by_variable.get(variable)
            value = metric.rmse if metric and metric.rmse is not None else metric.event_error_days if metric else None
            if value is not None and weight >= 0:
                normalizer = self.normalizers.get(variable, 1.0)
                if normalizer <= 0 or not math.isfinite(normalizer):
                    raise CalibrationError(f"invalid objective normalizer: {variable}")
                total += weight * value / normalizer
                weight_sum += weight
        return total / weight_sum if weight_sum else math.inf


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    status: CalibrationStatus
    initial_parameters: ParameterSet
    calibrated_parameters: ParameterSet | None
    evaluations: int
    score: float | None
    metrics: tuple[VariableMetrics, ...]
    dataset: str
    model_name: str
    validation_metrics: tuple[VariableMetrics, ...] = ()
    message: str = ""


class GridSearchCalibrator:
    def __init__(self, runner: SimulationRunner, objective: CalibrationObjective, max_evaluations: int = 100, target_score: float | None = None) -> None:
        if max_evaluations <= 0:
            raise CalibrationError("max_evaluations must be positive")
        self.runner, self.objective, self.max_evaluations, self.target_score = runner, objective, max_evaluations, target_score

    def fit(self, case: CalibrationCase) -> CalibrationResult:
        if not case.parameters.values:
            return CalibrationResult(CalibrationStatus.INSUFFICIENT_DATA, case.parameters, None, 0, None, (), case.calibration_dataset.name, case.model_name, message="no selectable calibration parameters")
        best_score = math.inf
        best_parameters = None
        best_metrics: tuple[VariableMetrics, ...] = ()
        evaluations = 0
        grids = [tuple(self._grid(parameter)) for parameter in case.parameters.values]
        for values in product(*grids):
            if evaluations >= self.max_evaluations:
                break
            parameters = case.parameters.with_values({parameter.parameter_id: value for parameter, value in zip(case.parameters.values, values)})
            points = self.runner.run(case, parameters, case.calibration_dataset)
            records = ObservationComparator().compare(case.calibration_dataset.observations, points)
            metrics = calculate_metrics(records)
            score = self.objective.score(metrics)
            evaluations += 1
            if score < best_score:
                best_score, best_parameters, best_metrics = score, parameters, metrics
            if self.target_score is not None and score <= self.target_score:
                break
        if best_parameters is None:
            return CalibrationResult(CalibrationStatus.FAILED, case.parameters, None, evaluations, None, (), case.calibration_dataset.name, case.model_name, message="no evaluations completed")
        validation_metrics = self.evaluate(case, best_parameters, case.validation_dataset) if case.validation_dataset is not None else ()
        return CalibrationResult(CalibrationStatus.SUCCESS, case.parameters, best_parameters, evaluations, best_score, best_metrics, case.calibration_dataset.name, case.model_name, validation_metrics=validation_metrics)

    def evaluate(self, case: CalibrationCase, parameters: ParameterSet, dataset: ObservationDataset) -> tuple[VariableMetrics, ...]:
        if dataset.role == DatasetRole.CALIBRATION and case.validation_dataset is not None and dataset is case.calibration_dataset:
            raise CalibrationError("validation evaluation must not silently reuse calibration data")
        points = self.runner.run(case, parameters, dataset)
        return calculate_metrics(ObservationComparator().compare(dataset.observations, points))

    @staticmethod
    def _grid(parameter: CalibrationParameter) -> tuple[float, ...]:
        values = []
        current = parameter.minimum
        while current <= parameter.maximum + parameter.step * 1e-9:
            values.append(round(current, 12))
            current += parameter.step
        return tuple(values)


class PredictionModel(ABC):
    """Future forecasting contract; no external model is a runtime dependency."""

    @abstractmethod
    def fit(self, observations: ObservationDataset, target: str, past_covariates: Sequence[str] = (), future_covariates: Sequence[str] = ()) -> None: ...

    @abstractmethod
    def predict(self, start: datetime, horizon: int, frequency: str, covariates: Mapping[str, Sequence[float]] | None = None) -> tuple[SimulationPoint, ...]: ...

    @abstractmethod
    def evaluate(self, observations: ObservationDataset) -> tuple[VariableMetrics, ...]: ...