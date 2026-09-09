"""Read-only multilevel diagnostics over Phase 5.12 comparisons."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime
from typing import Callable, Iterable, Mapping

from agri_twin.application.twin_alignment import AlignmentStatus, ComparisonDataset, ComparisonResult
from agri_twin.domain.calibration import ComparisonRecord, VariableMetrics, calculate_metrics


@dataclass(frozen=True, slots=True)
class QualityCounts:
    valid_count: int = 0
    invalid_count: int = 0
    missing_count: int = 0
    duplicate_count: int = 0
    unit_error_count: int = 0
    estimated_count: int = 0
    out_of_range_count: int = 0


@dataclass(frozen=True, slots=True)
class MetricSummary:
    grouping: str
    group_key: str
    variable: str | None
    n: int
    mae: float | None
    rmse: float | None
    bias: float | None
    r2: float | None
    matched_count: int
    unmatched_count: int
    ambiguous_count: int
    invalid_count: int
    coverage_ratio: float
    quality: QualityCounts
    alignment_methods: tuple[str, ...] = ()
    status: str = "OK"

    def to_dict(self) -> dict[str, object]:
        return {item.name: getattr(self, item.name) for item in fields(self)} | {"quality": {item.name: getattr(self.quality, item.name) for item in fields(self.quality)}}


@dataclass(frozen=True, slots=True)
class OutlierReport:
    observation_id: str | None
    plot_id: str | None
    cycle_id: str | None
    variable: str
    observation_time: datetime
    simulated_value: float | str | None
    observed_value: float | str | None
    residual: float | None
    absolute_error: float | None
    threshold: float

    def to_dict(self) -> dict[str, object]:
        return {item.name: (getattr(self, item.name).isoformat() if isinstance(getattr(self, item.name), datetime) else getattr(self, item.name)) for item in fields(self)}


@dataclass(frozen=True, slots=True)
class ErrorDiagnostics:
    comparison: ComparisonDataset
    outlier_threshold: float | None = None
    bias_threshold: float | None = None
    baseline: ComparisonDataset | None = None

    def global_summary(self) -> MetricSummary:
        return self._summary("global", "global", self.comparison.results)

    def by_variable(self) -> tuple[MetricSummary, ...]:
        return self._group("variable", lambda item: item.variable)

    def by_crop(self) -> tuple[MetricSummary, ...]:
        return self._group("crop", lambda item: item.crop)

    def by_variety(self) -> tuple[MetricSummary, ...]:
        return self._group("variety", lambda item: f"{item.crop}:{item.variety}")

    def by_plot(self) -> tuple[MetricSummary, ...]:
        return self._group("plot", lambda item: item.alignment.plot_id)

    def by_cycle(self) -> tuple[MetricSummary, ...]:
        return self._group("cycle", lambda item: f"{item.alignment.plot_id}:{item.alignment.cycle_id}")

    def by_stage(self) -> tuple[MetricSummary, ...]:
        return self._group("stage", lambda item: item.phenological_stage)

    def by_environment(self) -> tuple[MetricSummary, ...]:
        return self._group("environment", lambda item: item.environment)

    def by_time(self, period: str = "day") -> tuple[MetricSummary, ...]:
        def key(item: ComparisonResult) -> str | None:
            timestamp = item.alignment.observation_time
            if period == "day":
                return timestamp.date().isoformat()
            if period == "week":
                return f"{timestamp.isocalendar().year}-W{timestamp.isocalendar().week:02d}"
            if period == "month":
                return timestamp.strftime("%Y-%m")
            raise ValueError("period must be day, week or month")
        return self._group("time", key)

    def outliers(self) -> tuple[OutlierReport, ...]:
        if self.outlier_threshold is None:
            return ()
        return tuple(
            OutlierReport(item.alignment.observation_id, item.alignment.plot_id, item.alignment.cycle_id, item.variable, item.alignment.observation_time, item.simulated_value, item.observed_value, item.residual, item.absolute_error, self.outlier_threshold)
            for item in self.comparison.results
            if item.alignment.status is AlignmentStatus.MATCHED and item.absolute_error is not None and item.absolute_error > self.outlier_threshold
        )

    def bias_warnings(self) -> tuple[str, ...]:
        if self.bias_threshold is None:
            return ()
        warnings = []
        summary = self.global_summary()
        if summary.bias is not None and abs(summary.bias) > self.bias_threshold:
            warnings.append("BIAS_ABOVE_CONFIGURED_THRESHOLD")
        return tuple(warnings)

    def baseline_summary(self) -> MetricSummary | None:
        return ErrorDiagnostics(self.baseline).global_summary() if self.baseline is not None else None

    def relative_rmse_improvement(self) -> float | None:
        baseline = self.baseline_summary()
        current = self.global_summary()
        if baseline is None or baseline.rmse is None or current.rmse is None or baseline.rmse == 0:
            return None
        return (baseline.rmse - current.rmse) / baseline.rmse

    def to_dict(self) -> dict[str, object]:
        return {"global": self.global_summary().to_dict(), "by_variable": [item.to_dict() for item in self.by_variable()], "by_plot": [item.to_dict() for item in self.by_plot()], "by_crop": [item.to_dict() for item in self.by_crop()], "by_variety": [item.to_dict() for item in self.by_variety()], "by_cycle": [item.to_dict() for item in self.by_cycle()], "by_stage": [item.to_dict() for item in self.by_stage()], "by_environment": [item.to_dict() for item in self.by_environment()], "by_time": [item.to_dict() for item in self.by_time()], "outliers": [item.to_dict() for item in self.outliers()], "bias_warnings": list(self.bias_warnings())}

    def _group(self, grouping: str, selector: Callable[[ComparisonResult], str | None]) -> tuple[MetricSummary, ...]:
        groups: dict[str, list[ComparisonResult]] = {}
        for item in self.comparison.results:
            key = selector(item)
            if key is not None:
                groups.setdefault(key, []).append(item)
        return tuple(self._summary(grouping, key, items) for key, items in sorted(groups.items()))

    def _summary(self, grouping: str, group_key: str, items: Iterable[ComparisonResult]) -> MetricSummary:
        values = tuple(items)
        valid = tuple(item for item in values if item.alignment.status is AlignmentStatus.MATCHED and item.residual is not None)
        records = tuple(ComparisonRecord(item.alignment.observation_time, item.variable, item.observed_value, item.simulated_value, item.residual, item.absolute_error, item.observed_uncertainty) for item in valid)
        metrics = calculate_metrics(records)
        metric = metrics[0] if len({item.variable for item in valid}) <= 1 and metrics else None
        matched = sum(item.alignment.status is AlignmentStatus.MATCHED for item in values)
        ambiguous = sum(item.alignment.status is AlignmentStatus.AMBIGUOUS for item in values)
        invalid = sum(item.alignment.status in {AlignmentStatus.INVALID_OBSERVATION, AlignmentStatus.UNIT_ERROR, AlignmentStatus.MISSING_SIMULATION_VARIABLE} for item in values)
        quality = QualityCounts(
            valid_count=sum(item.quality.upper() == "VALID" and item.alignment.status is AlignmentStatus.MATCHED for item in values),
            invalid_count=sum(item.quality.upper() == "INVALID" or item.alignment.status is AlignmentStatus.INVALID_OBSERVATION for item in values),
            missing_count=sum(item.quality.upper() == "MISSING" for item in values),
            duplicate_count=sum(item.quality.upper() == "DUPLICATE" for item in values),
            unit_error_count=sum(item.alignment.status is AlignmentStatus.UNIT_ERROR for item in values),
            estimated_count=sum(item.quality.upper() == "ESTIMATED" for item in values),
            out_of_range_count=sum(item.quality.upper() == "OUT_OF_RANGE" for item in values),
        )
        denominator = len(values)
        return MetricSummary(grouping, group_key, metric.variable if metric else None, len(valid), metric.mae if metric else None, metric.rmse if metric else None, metric.bias if metric else None, metric.r2 if metric else None, matched, denominator - matched - ambiguous - invalid, ambiguous, invalid, matched / denominator if denominator else 0.0, quality, tuple(sorted({item.alignment.alignment_method.value for item in values})), "NO_DATA" if not values else "OK")


def diagnose(comparison: ComparisonDataset, *, outlier_threshold: float | None = None, bias_threshold: float | None = None, baseline: ComparisonDataset | None = None) -> ErrorDiagnostics:
    return ErrorDiagnostics(comparison, outlier_threshold, bias_threshold, baseline)


__all__ = ["ErrorDiagnostics", "MetricSummary", "OutlierReport", "QualityCounts", "diagnose"]
