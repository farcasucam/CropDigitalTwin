"""Independent post-calibration validation gate and evaluation orchestration.

This module consumes the Phase 5.26 calibration artifact and existing
observation comparison/diagnostic contracts. It never calibrates, mutates
parameters or promotes synthetic fixtures to scientific validation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

from agri_twin.application.real_validation import (
    DataSourceAudit,
    DataSourceClassification,
    RealValidationSuite,
)
from agri_twin.domain.calibration import (
    ObservationComparator,
    ObservationDataset,
    ParameterSet,
    SimulationPoint,
    calculate_metrics,
)
from agri_twin.domain.parameter_audit import ParameterRegistry


class PostCalibrationValidationStatus(StrEnum):
    READY_FOR_VALIDATION = "READY_FOR_VALIDATION"
    INSUFFICIENT_REAL_DATA = "INSUFFICIENT_REAL_DATA"
    NO_CALIBRATION = "NO_CALIBRATION"
    NO_INDEPENDENT_HOLDOUT = "NO_INDEPENDENT_HOLDOUT"
    DATA_LEAKAGE = "DATA_LEAKAGE"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    INCOMPATIBLE_OBSERVATIONS = "INCOMPATIBLE_OBSERVATIONS"
    VALIDATION_PERFORMED = "VALIDATION_PERFORMED"
    FAILED = "FAILED"


class ValidationExecutionStatus(StrEnum):
    NOT_PERFORMED = "NOT_PERFORMED"
    SOFTWARE_TEST_ONLY = "SOFTWARE_TEST_ONLY"
    PERFORMED = "PERFORMED"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class ValidationIndependence:
    calibration_observation_ids: tuple[str, ...]
    validation_observation_ids: tuple[str, ...]
    split_method: str
    split_reason: str
    basis: tuple[str, ...]
    overlap: tuple[str, ...] = ()
    duplicate_timestamps: tuple[str, ...] = ()

    @property
    def independent(self) -> bool:
        return not self.overlap and not self.duplicate_timestamps and bool(self.validation_observation_ids)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"independent": self.independent}


@dataclass(frozen=True, slots=True)
class ValidationMetric:
    variable: str
    count: int
    mae: float | None
    rmse: float | None
    bias: float | None
    r2: float | None
    event_error_days: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PostCalibrationValidationResult:
    status: ValidationExecutionStatus
    readiness: PostCalibrationValidationStatus
    real_data_verified: bool
    validation_performed: bool
    data_leakage: bool
    source_status: DataSourceClassification
    calibration_report_hash: str | None
    validation_dataset: str | None
    independence: ValidationIndependence | None
    baseline_metrics: tuple[ValidationMetric, ...] = ()
    calibrated_metrics: tuple[ValidationMetric, ...] = ()
    delta_metrics: tuple[dict[str, Any], ...] = ()
    global_diagnostics: dict[str, Any] = field(default_factory=dict)
    multilevel_diagnostics: dict[str, Any] = field(default_factory=dict)
    overfit_diagnostics: dict[str, Any] = field(default_factory=dict)
    uncertainty: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "readiness": self.readiness.value,
            "real_data_verified": self.real_data_verified,
            "validation_performed": self.validation_performed,
            "data_leakage": self.data_leakage,
            "source_status": self.source_status.value,
            "calibration_report_hash": self.calibration_report_hash,
            "validation_dataset": self.validation_dataset,
            "independence": self.independence.to_dict() if self.independence else None,
            "baseline_metrics": [metric.to_dict() for metric in self.baseline_metrics],
            "calibrated_metrics": [metric.to_dict() for metric in self.calibrated_metrics],
            "delta_metrics": list(self.delta_metrics),
            "global_diagnostics": self.global_diagnostics,
            "multilevel_diagnostics": self.multilevel_diagnostics,
            "overfit_diagnostics": self.overfit_diagnostics,
            "uncertainty": self.uncertainty,
            "warnings": list(self.warnings),
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class PostCalibrationValidationReport:
    phase: str
    status: PostCalibrationValidationStatus
    configuration_hash: str
    real_data_verified: bool
    real_verified_sources: tuple[str, ...]
    sources_audited: tuple[DataSourceAudit, ...]
    calibration_performed: bool
    calibration_report_hash: str | None
    calibrated_parameters: tuple[str, ...]
    validation_performed: bool
    calibration_dataset: str | None
    validation_dataset: str | None
    independence: ValidationIndependence | None
    data_leakage: bool
    data_quality: str
    baseline_metrics: tuple[ValidationMetric, ...]
    calibrated_metrics: tuple[ValidationMetric, ...]
    delta_metrics: tuple[dict[str, Any], ...]
    global_diagnostics: dict[str, Any]
    multilevel_diagnostics: dict[str, Any]
    overfit_diagnostics: dict[str, Any]
    uncertainty: dict[str, Any]
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "status": self.status.value,
            "configuration_hash": self.configuration_hash,
            "real_data_verified": self.real_data_verified,
            "real_verified_sources": list(self.real_verified_sources),
            "sources_audited": [source.to_dict() for source in self.sources_audited],
            "calibration_performed": self.calibration_performed,
            "calibration_report_hash": self.calibration_report_hash,
            "calibrated_parameters": list(self.calibrated_parameters),
            "validation_performed": self.validation_performed,
            "calibration_dataset": self.calibration_dataset,
            "validation_dataset": self.validation_dataset,
            "independence": self.independence.to_dict() if self.independence else None,
            "data_leakage": self.data_leakage,
            "data_quality": self.data_quality,
            "baseline_metrics": [metric.to_dict() for metric in self.baseline_metrics],
            "calibrated_metrics": [metric.to_dict() for metric in self.calibrated_metrics],
            "delta_metrics": list(self.delta_metrics),
            "global_diagnostics": self.global_diagnostics,
            "multilevel_diagnostics": self.multilevel_diagnostics,
            "overfit_diagnostics": self.overfit_diagnostics,
            "uncertainty": self.uncertainty,
            "warnings": list(self.warnings),
            "limitations": list(self.limitations),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


class PostCalibrationValidationSuite:
    """Evaluate a frozen calibrated parameter set only after all gates pass."""

    VERSION = "5.27.1"

    def __init__(self, root: str | Path, *, registry: ParameterRegistry | None = None, calibration_report_path: str | Path | None = None) -> None:
        self.root = Path(root)
        self.registry = registry or ParameterRegistry.from_repository(self.root)
        self.validation = RealValidationSuite(self.root, registry=self.registry)
        self.calibration_report_path = Path(calibration_report_path) if calibration_report_path else self.root / "data" / "calibration" / "calibration_report.json"

    def audit_sources(self) -> tuple[DataSourceAudit, ...]:
        return self.validation.audit_sources()

    def calibration_report(self) -> dict[str, Any]:
        if not self.calibration_report_path.exists():
            return {}
        return json.loads(self.calibration_report_path.read_text(encoding="utf-8"))

    def _calibration_hash(self) -> str | None:
        report = self.calibration_report()
        return report.get("configuration_hash") or None

    @staticmethod
    def observation_ids(dataset: ObservationDataset) -> tuple[str, ...]:
        return tuple(_observation_id(dataset, index) for index, _ in enumerate(dataset.observations))

    def independence(self, calibration: ObservationDataset, validation: ObservationDataset, *, method: str = "explicit_independent_dataset", basis: tuple[str, ...] = ("dataset_id",)) -> ValidationIndependence:
        calibration_ids = self.observation_ids(calibration)
        validation_ids = self.observation_ids(validation)
        overlap = tuple(sorted(set(calibration_ids).intersection(validation_ids)))
        calibration_timestamps = {item.timestamp.isoformat() for item in calibration.observations}
        validation_timestamps = {item.timestamp.isoformat() for item in validation.observations}
        duplicate_timestamps = tuple(sorted(calibration_timestamps.intersection(validation_timestamps)))
        return ValidationIndependence(calibration_ids, validation_ids, method, "independent datasets supplied", basis, overlap, duplicate_timestamps)

    def readiness(self, *, calibration_dataset: ObservationDataset | None = None, validation_dataset: ObservationDataset | None = None, independence: ValidationIndependence | None = None) -> PostCalibrationValidationStatus:
        sources = self.audit_sources()
        if not any(source.classification is DataSourceClassification.REAL_VERIFIED for source in sources):
            return PostCalibrationValidationStatus.INSUFFICIENT_REAL_DATA
        report = self.calibration_report()
        if not report.get("calibration_performed", False) or not report.get("calibrated_parameters"):
            return PostCalibrationValidationStatus.NO_CALIBRATION
        if calibration_dataset is None or validation_dataset is None:
            return PostCalibrationValidationStatus.NO_INDEPENDENT_HOLDOUT
        independence = independence or self.independence(calibration_dataset, validation_dataset)
        if not independence.independent:
            return PostCalibrationValidationStatus.DATA_LEAKAGE
        if not validation_dataset.observations:
            return PostCalibrationValidationStatus.INCOMPATIBLE_OBSERVATIONS
        return PostCalibrationValidationStatus.READY_FOR_VALIDATION

    def evaluate(self, *, calibration_dataset: ObservationDataset | None, validation_dataset: ObservationDataset | None, baseline_parameters: ParameterSet | None, calibrated_parameters: ParameterSet | None, baseline_runner: Any | None = None, calibrated_runner: Any | None = None, source_status: DataSourceClassification | None = None, independence: ValidationIndependence | None = None) -> PostCalibrationValidationResult:
        sources = self.audit_sources()
        real_verified = any(source.classification is DataSourceClassification.REAL_VERIFIED for source in sources)
        source_status = source_status or (DataSourceClassification.REAL_VERIFIED if real_verified else DataSourceClassification.SYNTHETIC)
        if calibration_dataset is not None and validation_dataset is not None and independence is None:
            independence = self.independence(calibration_dataset, validation_dataset)
        readiness = self.readiness(calibration_dataset=calibration_dataset, validation_dataset=validation_dataset, independence=independence)
        calibration_report_hash = self._calibration_hash()
        if source_status is not DataSourceClassification.REAL_VERIFIED or readiness is not PostCalibrationValidationStatus.READY_FOR_VALIDATION:
            if independence is not None and not independence.independent:
                readiness = PostCalibrationValidationStatus.DATA_LEAKAGE
            return PostCalibrationValidationResult(
                ValidationExecutionStatus.NOT_PERFORMED,
                readiness,
                real_verified,
                False,
                readiness is PostCalibrationValidationStatus.DATA_LEAKAGE,
                source_status,
                calibration_report_hash,
                validation_dataset.name if validation_dataset else None,
                independence,
                warnings=("VALIDATION NOT PERFORMED", "INSUFFICIENT REAL DATA" if not real_verified else "NO CALIBRATION AVAILABLE"),
                limitations=("Synthetic and simulated substitute sources are not independent scientific validation data.", "No validation claim is made.",),
            )
        if baseline_parameters is None or calibrated_parameters is None or baseline_runner is None or calibrated_runner is None:
            return PostCalibrationValidationResult(ValidationExecutionStatus.INVALID, PostCalibrationValidationStatus.INVALID_CONFIGURATION, True, False, False, source_status, calibration_report_hash, validation_dataset.name if validation_dataset else None, independence, warnings=("baseline and calibrated evaluation contracts are required",))
        baseline_points = tuple(baseline_runner(validation_dataset, baseline_parameters))
        calibrated_points = tuple(calibrated_runner(validation_dataset, calibrated_parameters))
        baseline_metrics = _metrics(validation_dataset, baseline_points)
        calibrated_metrics = _metrics(validation_dataset, calibrated_points)
        deltas = _delta_metrics(baseline_metrics, calibrated_metrics)
        overfit = {"status": "NOT_SPECIFIED", "signal": False, "reason": "scientific acceptance threshold is not specified"}
        return PostCalibrationValidationResult(ValidationExecutionStatus.PERFORMED, PostCalibrationValidationStatus.VALIDATION_PERFORMED, True, True, False, source_status, calibration_report_hash, validation_dataset.name, independence, baseline_metrics, calibrated_metrics, deltas, overfit_diagnostics=overfit, limitations=("Metrics do not establish biological validity without a project acceptance criterion.",))

    def software_fixture_compare(self, *, calibration_dataset: ObservationDataset, validation_dataset: ObservationDataset, baseline_parameters: ParameterSet, calibrated_parameters: ParameterSet, baseline_runner: Any, calibrated_runner: Any, independence: ValidationIndependence | None = None) -> PostCalibrationValidationResult:
        """Compare frozen parameter sets using synthetic fixtures only."""
        independence = independence or self.independence(calibration_dataset, validation_dataset)
        if not independence.independent:
            return self.evaluate(calibration_dataset=calibration_dataset, validation_dataset=validation_dataset, baseline_parameters=baseline_parameters, calibrated_parameters=calibrated_parameters, baseline_runner=baseline_runner, calibrated_runner=calibrated_runner, source_status=DataSourceClassification.SYNTHETIC, independence=independence)
        baseline_metrics = _metrics(validation_dataset, tuple(baseline_runner(validation_dataset, baseline_parameters)))
        calibrated_metrics = _metrics(validation_dataset, tuple(calibrated_runner(validation_dataset, calibrated_parameters)))
        calibration_baseline = _metrics(calibration_dataset, tuple(baseline_runner(calibration_dataset, baseline_parameters)))
        calibration_calibrated = _metrics(calibration_dataset, tuple(calibrated_runner(calibration_dataset, calibrated_parameters)))
        deltas = _delta_metrics(baseline_metrics, calibrated_metrics)
        calibration_before = {metric.variable: metric for metric in calibration_baseline}
        calibration_after = {metric.variable: metric for metric in calibration_calibrated}
        validation_before = {metric.variable: metric for metric in baseline_metrics}
        validation_after = {metric.variable: metric for metric in calibrated_metrics}
        overfit_signal = any(
            calibration_after.get(variable) is not None
            and calibration_before.get(variable) is not None
            and validation_after.get(variable) is not None
            and validation_before.get(variable) is not None
            and calibration_after[variable].rmse is not None
            and calibration_before[variable].rmse is not None
            and validation_after[variable].rmse is not None
            and validation_before[variable].rmse is not None
            and calibration_after[variable].rmse < calibration_before[variable].rmse
            and validation_after[variable].rmse > validation_before[variable].rmse
            for variable in calibration_after
        )
        return PostCalibrationValidationResult(ValidationExecutionStatus.SOFTWARE_TEST_ONLY, PostCalibrationValidationStatus.INSUFFICIENT_REAL_DATA, False, False, False, DataSourceClassification.SYNTHETIC, self._calibration_hash(), validation_dataset.name, independence, baseline_metrics, calibrated_metrics, deltas, overfit_diagnostics={"status": "SOFTWARE_TEST_ONLY", "signal": overfit_signal, "label": "POTENTIAL_OVERFIT" if overfit_signal else "NOT_DETECTED"}, warnings=("SYNTHETIC_SOFTWARE_TEST",), limitations=("Synthetic comparison is not scientific validation.",))

    def build_report(self, result: PostCalibrationValidationResult | None = None) -> PostCalibrationValidationReport:
        sources = self.audit_sources()
        calibration = self.calibration_report()
        result = result or self.evaluate(calibration_dataset=None, validation_dataset=None, baseline_parameters=None, calibrated_parameters=None)
        classifications = {classification: tuple(source.path for source in sources if source.classification is classification) for classification in DataSourceClassification}
        payload = result.to_dict()
        config_hash = _hash({"phase": self.VERSION, "sources": [source.to_dict() for source in sources], "calibration_report_hash": self._calibration_hash(), "result": payload})
        return PostCalibrationValidationReport(self.VERSION, result.readiness, config_hash, result.real_data_verified, classifications[DataSourceClassification.REAL_VERIFIED], sources, bool(calibration.get("calibration_performed", False)), self._calibration_hash(), tuple(calibration.get("calibrated_parameters", ())), result.validation_performed, None, result.validation_dataset, result.independence, result.data_leakage, "NOT_AVAILABLE" if not result.validation_performed else "ASSESSED", result.baseline_metrics, result.calibrated_metrics, result.delta_metrics, result.global_diagnostics, result.multilevel_diagnostics, result.overfit_diagnostics, result.uncertainty, result.warnings, result.limitations)

    def write_report(self, report: PostCalibrationValidationReport, directory: str | Path | None = None) -> tuple[Path, Path]:
        output = Path(directory) if directory is not None else self.root / "data" / "validation"
        output.mkdir(parents=True, exist_ok=True)
        report_path = output / "post_calibration_validation_report.json"
        readme_path = output / "post_calibration_validation_README.md"
        report_path.write_text(report.to_json() + "\n", encoding="utf-8")
        readme_path.write_text("# Post-calibration validation report\n\nScientific validation is not performed without REAL_VERIFIED observations and a valid Phase 5.26 calibration.\n\n" + f"- status: `{report.status.value}`\n- validation performed: `{report.validation_performed}`\n- configuration hash: `{report.configuration_hash}`\n", encoding="utf-8")
        return report_path, readme_path


def _observation_id(dataset: ObservationDataset, index: int) -> str:
    observation = dataset.observations[index]
    return f"{dataset.name}:{index}:{observation.timestamp.isoformat()}:{observation.variable}"


def _metrics(dataset: ObservationDataset, points: tuple[SimulationPoint, ...]) -> tuple[ValidationMetric, ...]:
    records = ObservationComparator().compare(dataset.observations, points)
    return tuple(ValidationMetric(metric.variable, metric.count, metric.mae, metric.rmse, metric.bias, metric.r2, metric.event_error_days) for metric in calculate_metrics(records))


def _delta_metrics(baseline: tuple[ValidationMetric, ...], calibrated: tuple[ValidationMetric, ...]) -> tuple[dict[str, Any], ...]:
    baseline_by_variable = {metric.variable: metric for metric in baseline}
    output: list[dict[str, Any]] = []
    for metric in calibrated:
        before = baseline_by_variable.get(metric.variable)
        output.append({"variable": metric.variable, "rmse_delta": _difference(before.rmse if before else None, metric.rmse), "mae_delta": _difference(before.mae if before else None, metric.mae), "bias_delta": _difference(before.bias if before else None, metric.bias)})
    return tuple(output)


def _difference(before: float | None, after: float | None) -> float | None:
    return None if before is None or after is None else after - before


def _hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


__all__ = [
    "PostCalibrationValidationReport",
    "PostCalibrationValidationResult",
    "PostCalibrationValidationStatus",
    "PostCalibrationValidationSuite",
    "ValidationExecutionStatus",
    "ValidationIndependence",
    "ValidationMetric",
]
