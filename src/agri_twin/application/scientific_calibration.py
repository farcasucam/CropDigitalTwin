"""Conditionally controlled scientific calibration orchestration.

The existing ``GridSearchCalibrator`` remains the only calibration algorithm.
This module supplies readiness, source and split gates around it. No scientific
calibration is executed unless a verified real dataset, eligible identifiable
parameters and an independent holdout are all present.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from agri_twin.application.parameter_identifiability import (
    IdentifiabilityStatus,
    ParameterIdentifiabilityAnalyzer,
)
from agri_twin.application.real_validation import (
    DataSourceAudit,
    DataSourceClassification,
    RealValidationSuite,
)
from agri_twin.application.sensitivity import ParameterSensitivityAnalyzer
from agri_twin.domain.calibration import (
    CalibrationCase,
    CalibrationError,
    CalibrationObjective,
    CalibrationParameter,
    CalibrationResult,
    DatasetRole,
    GridSearchCalibrator,
    ObservationDataset,
    ParameterSet,
    SimulationRunner,
)
from agri_twin.domain.parameter_audit import ParameterRegistry


class CalibrationReadiness(StrEnum):
    READY_FOR_CALIBRATION = "READY_FOR_CALIBRATION"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    NOT_IDENTIFIABLE = "NOT_IDENTIFIABLE"
    NO_CALIBRATABLE_PARAMETERS = "NO_CALIBRATABLE_PARAMETERS"
    NO_INDEPENDENT_HOLDOUT = "NO_INDEPENDENT_HOLDOUT"


class CalibrationExecutionStatus(StrEnum):
    NOT_PERFORMED = "NOT_PERFORMED"
    SOFTWARE_TEST_ONLY = "SOFTWARE_TEST_ONLY"
    PERFORMED = "PERFORMED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class CalibrationSplit:
    calibration_observation_ids: tuple[str, ...]
    holdout_observation_ids: tuple[str, ...]
    split_method: str
    split_reason: str
    overlap: tuple[str, ...] = ()

    @property
    def independent(self) -> bool:
        return not self.overlap and bool(self.calibration_observation_ids) and bool(self.holdout_observation_ids)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"independent": self.independent}


@dataclass(frozen=True, slots=True)
class CalibrationParameterAudit:
    parameter_id: str
    calibration_allowed: bool
    bounds_available: bool
    identifiability: str
    sensitivity: str
    accepted: bool
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ScientificCalibrationResult:
    status: CalibrationExecutionStatus
    readiness: CalibrationReadiness
    real_data_verified: bool
    calibration_performed: bool
    calibration_status: str
    initial_parameters: ParameterSet
    calibrated_parameters: ParameterSet | None
    parameter_audits: tuple[CalibrationParameterAudit, ...]
    rejected_parameters: tuple[dict[str, Any], ...]
    calibration_result: CalibrationResult | None
    split: CalibrationSplit | None
    configuration_hash: str
    baseline_metrics: tuple[dict[str, Any], ...] = ()
    calibrated_metrics: tuple[dict[str, Any], ...] = ()
    objective: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "readiness": self.readiness.value,
            "real_data_verified": self.real_data_verified,
            "calibration_performed": self.calibration_performed,
            "calibration_status": self.calibration_status,
            "initial_parameters": self.initial_parameters.value_map(),
            "calibrated_parameters": self.calibrated_parameters.value_map() if self.calibrated_parameters else None,
            "parameter_audits": [item.to_dict() for item in self.parameter_audits],
            "rejected_parameters": list(self.rejected_parameters),
            "calibration_result": None if self.calibration_result is None else {
                "status": self.calibration_result.status.value,
                "evaluations": self.calibration_result.evaluations,
                "score": self.calibration_result.score,
                "message": self.calibration_result.message,
            },
            "split": self.split.to_dict() if self.split else None,
            "configuration_hash": self.configuration_hash,
            "baseline_metrics": list(self.baseline_metrics),
            "calibrated_metrics": list(self.calibrated_metrics),
            "objective": dict(self.objective),
            "warnings": list(self.warnings),
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class ScientificCalibrationReport:
    phase: str
    status: CalibrationExecutionStatus
    data_readiness: CalibrationReadiness
    real_data_verified: bool
    sources_audited: tuple[DataSourceAudit, ...]
    real_verified_sources: tuple[str, ...]
    synthetic_sources: tuple[str, ...]
    simulated_real_substitute_sources: tuple[str, ...]
    forcing_sources: tuple[str, ...]
    literature_sources: tuple[str, ...]
    unknown_sources: tuple[str, ...]
    template_sources: tuple[str, ...]
    calibration_performed: bool
    calibration_status: str
    calibration_case: str | None
    calibration_observations: tuple[str, ...]
    holdout_observations: tuple[str, ...]
    parameter_candidates: tuple[str, ...]
    parameters_calibrated: tuple[str, ...]
    parameters_rejected: tuple[dict[str, Any], ...]
    identifiability: tuple[dict[str, Any], ...]
    confounders: Mapping[str, tuple[str, ...]]
    baseline_metrics: tuple[dict[str, Any], ...]
    calibrated_metrics: tuple[dict[str, Any], ...]
    objective: Mapping[str, Any]
    split: CalibrationSplit | None
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]
    configuration_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "status": self.status.value,
            "data_readiness": self.data_readiness.value,
            "real_data_verified": self.real_data_verified,
            "sources_audited": [item.to_dict() for item in self.sources_audited],
            "real_verified_sources": list(self.real_verified_sources),
            "synthetic_sources": list(self.synthetic_sources),
            "simulated_real_substitute_sources": list(self.simulated_real_substitute_sources),
            "forcing_sources": list(self.forcing_sources),
            "literature_sources": list(self.literature_sources),
            "unknown_sources": list(self.unknown_sources),
            "template_sources": list(self.template_sources),
            "calibration_performed": self.calibration_performed,
            "calibration_status": self.calibration_status,
            "calibration_case": self.calibration_case,
            "calibration_observations": list(self.calibration_observations),
            "holdout_observations": list(self.holdout_observations),
            "parameter_candidates": list(self.parameter_candidates),
            "parameters_calibrated": list(self.parameters_calibrated),
            "parameters_rejected": list(self.parameters_rejected),
            "identifiability": list(self.identifiability),
            "confounders": {key: list(value) for key, value in self.confounders.items()},
            "baseline_metrics": list(self.baseline_metrics),
            "calibrated_metrics": list(self.calibrated_metrics),
            "objective": dict(self.objective),
            "split": self.split.to_dict() if self.split else None,
            "warnings": list(self.warnings),
            "limitations": list(self.limitations),
            "configuration_hash": self.configuration_hash,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


class ScientificCalibrationSuite:
    """Readiness gate and transaction boundary around the existing calibrator."""

    VERSION = "5.26.1"

    def __init__(self, root: str | Path, *, registry: ParameterRegistry | None = None) -> None:
        self.root = Path(root)
        self.registry = registry or ParameterRegistry.from_repository(self.root)
        self.validation = RealValidationSuite(self.root, registry=self.registry)
        self.sensitivity = ParameterSensitivityAnalyzer(self.registry, root=self.root)
        self.identifiability = ParameterIdentifiabilityAnalyzer(self.registry, repository_root=self.root)

    def audit_sources(self) -> tuple[DataSourceAudit, ...]:
        return self.validation.audit_sources()

    def audit_parameters(self, observations: ObservationDataset | None = None, *, crop: str | None = None, variety: str | None = None, environment: str | None = None) -> tuple[CalibrationParameterAudit, ...]:
        report = self.identifiability.analyze_all(observations, crop=crop, variety=variety, environment=environment)
        by_id = {item.parameter_id: item for item in report.assessments}
        audits: list[CalibrationParameterAudit] = []
        for record in sorted(self.registry.records, key=lambda item: item.parameter_id):
            identification = by_id.get(record.parameter_id)
            reasons: list[str] = []
            bounds = record.minimum is not None and record.maximum is not None
            allowed = record.calibration_allowed
            status = identification.identifiability_status.value if identification else IdentifiabilityStatus.INSUFFICIENT_DATA.value
            if not allowed:
                reasons.append("calibration_allowed=false")
            if not bounds:
                reasons.append("traceable bounds unavailable")
            if status not in {IdentifiabilityStatus.CANDIDATE.value, IdentifiabilityStatus.IDENTIFIABLE.value}:
                reasons.append(f"identifiability={status}")
            sensitivity_status = "NOT_RUN"
            if record.value is not None and isinstance(record.value, (int, float)) and record.minimum is not None and record.maximum is not None:
                try:
                    sensitivity_status = self.sensitivity.analyze_parameter(record.parameter_id, crop=crop).classification.value
                except (KeyError, ValueError, TypeError):
                    sensitivity_status = "UNAVAILABLE"
            audits.append(CalibrationParameterAudit(record.parameter_id, allowed, bounds, status, sensitivity_status, not reasons, tuple(reasons)))
        return tuple(audits)

    def build_split(self, calibration: ObservationDataset, holdout: ObservationDataset | None = None, *, method: str = "explicit_dataset") -> CalibrationSplit:
        calibration_ids = tuple(_observation_id(item, index) for index, item in enumerate(calibration.observations))
        holdout_ids = tuple(_observation_id(item, index) for index, item in enumerate(holdout.observations)) if holdout else ()
        overlap = tuple(sorted(set(calibration_ids).intersection(holdout_ids)))
        reason = "explicit independent holdout supplied" if holdout else "NO_INDEPENDENT_HOLDOUT"
        return CalibrationSplit(calibration_ids, holdout_ids, method, reason, overlap)

    def readiness(self, *, observations: ObservationDataset | None = None, holdout: ObservationDataset | None = None, audits: tuple[CalibrationParameterAudit, ...] | None = None) -> CalibrationReadiness:
        sources = self.audit_sources()
        if not any(source.classification is DataSourceClassification.REAL_VERIFIED for source in sources):
            return CalibrationReadiness.INSUFFICIENT_DATA
        if observations is None or observations.source_type != "measured_data" or not observations.observations:
            return CalibrationReadiness.INSUFFICIENT_DATA
        if holdout is None:
            return CalibrationReadiness.NO_INDEPENDENT_HOLDOUT
        split = self.build_split(observations, holdout)
        if not split.independent:
            return CalibrationReadiness.NO_INDEPENDENT_HOLDOUT
        parameter_audits = audits or self.audit_parameters(observations)
        if not any(item.accepted for item in parameter_audits):
            return CalibrationReadiness.NO_CALIBRATABLE_PARAMETERS
        return CalibrationReadiness.READY_FOR_CALIBRATION

    def calibrate(self, case: CalibrationCase, *, runner: SimulationRunner, objective: CalibrationObjective, holdout: ObservationDataset | None = None, parameter_ids: Iterable[str] | None = None, max_evaluations: int = 100) -> ScientificCalibrationResult:
        sources = self.audit_sources()
        audits = self.audit_parameters(case.calibration_dataset)
        selected = set(parameter_ids) if parameter_ids is not None else None
        accepted = tuple(item for item in audits if item.accepted and (selected is None or item.parameter_id in selected))
        rejected = tuple({"parameter_id": item.parameter_id, "reasons": list(item.reasons)} for item in audits if not item.accepted or (selected is not None and item.parameter_id not in selected))
        split = self.build_split(case.calibration_dataset, holdout)
        readiness = self.readiness(observations=case.calibration_dataset, holdout=holdout, audits=audits)
        config = {"case": case.calibration_dataset.name, "parameters": case.parameters.value_map(), "accepted": [item.parameter_id for item in accepted], "objective": asdict(objective), "max_evaluations": max_evaluations, "split": split.to_dict()}
        initial = case.parameters
        if readiness is not CalibrationReadiness.READY_FOR_CALIBRATION:
            return ScientificCalibrationResult(CalibrationExecutionStatus.NOT_PERFORMED, readiness, False, False, "INSUFFICIENT_DATA", initial, None, audits, rejected, None, split, _hash(config), objective=asdict(objective), warnings=("CALIBRATION NOT PERFORMED", "INSUFFICIENT REAL DATA"), limitations=("No REAL_VERIFIED dataset is available; synthetic and forcing sources are rejected.", "Independent validation is reserved for Phase 5.27."))
        if not accepted:
            return ScientificCalibrationResult(CalibrationExecutionStatus.NOT_PERFORMED, CalibrationReadiness.NO_CALIBRATABLE_PARAMETERS, True, False, "NO_CALIBRATABLE_PARAMETERS", initial, None, audits, rejected, None, split, _hash(config), objective=asdict(objective), warnings=("NO_CALIBRATABLE_PARAMETERS",))
        selected_parameters = tuple(parameter for parameter in case.parameters.values if parameter.parameter_id in {item.parameter_id for item in accepted})
        if not selected_parameters:
            return ScientificCalibrationResult(CalibrationExecutionStatus.NOT_PERFORMED, CalibrationReadiness.NO_CALIBRATABLE_PARAMETERS, True, False, "NO_CALIBRATABLE_PARAMETERS", initial, None, audits, rejected, None, split, _hash(config))
        scoped_case = CalibrationCase(case.crop, case.variety, case.plot, case.start, case.end, case.calibration_dataset, ParameterSet(selected_parameters, case.parameters.name), holdout, case.model_name, case.configuration_version, case.initial_state)
        result = GridSearchCalibrator(runner, objective, max_evaluations=max_evaluations).fit(scoped_case)
        status = CalibrationExecutionStatus.PERFORMED if result.status.value == "SUCCESS" else CalibrationExecutionStatus.FAILED
        calibrated_ids = tuple(parameter.parameter_id for parameter in result.calibrated_parameters.values) if result.calibrated_parameters else ()
        return ScientificCalibrationResult(status, readiness, True, status is CalibrationExecutionStatus.PERFORMED, result.status.value, initial, result.calibrated_parameters, audits, rejected, result, split, _hash(config), calibrated_metrics=tuple(asdict(metric) for metric in result.metrics), objective=asdict(objective), limitations=("Independent validation interpretation is reserved for Phase 5.27.",))

    def software_fixture_calibration(self, case: CalibrationCase, *, runner: SimulationRunner, objective: CalibrationObjective, max_evaluations: int = 100) -> CalibrationResult:
        """Run the existing grid search for a synthetic software test only."""
        return GridSearchCalibrator(runner, objective, max_evaluations=max_evaluations).fit(case)

    def build_report(self, result: ScientificCalibrationResult | None = None) -> ScientificCalibrationReport:
        sources = self.audit_sources()
        readiness = result.readiness if result else CalibrationReadiness.INSUFFICIENT_DATA
        if result is None:
            audits = self.audit_parameters()
            rejected = tuple({"parameter_id": item.parameter_id, "reasons": list(item.reasons)} for item in audits if not item.accepted)
            result = ScientificCalibrationResult(
                CalibrationExecutionStatus.NOT_PERFORMED,
                readiness,
                False,
                False,
                "INSUFFICIENT_DATA",
                ParameterSet((), "no scientific calibration"),
                None,
                audits,
                rejected,
                None,
                None,
                _hash({"phase": self.VERSION, "readiness": readiness.value, "audits": [item.to_dict() for item in audits]}),
                warnings=("CALIBRATION NOT PERFORMED",),
            )
        classifications = {classification: tuple(source.path for source in sources if source.classification is classification) for classification in DataSourceClassification}
        identifiability = tuple(item.to_dict() for item in self.identifiability.analyze_all().assessments)
        parameter_candidates = tuple(item.parameter_id for item in result.parameter_audits if item.accepted)
        confounders = self.identifiability.confounder_matrix()
        payload = result.to_dict()
        return ScientificCalibrationReport(self.VERSION, result.status, readiness, result.real_data_verified, sources, classifications[DataSourceClassification.REAL_VERIFIED], classifications[DataSourceClassification.SYNTHETIC], classifications[DataSourceClassification.SIMULATED_REAL_DATA_SUBSTITUTE], classifications[DataSourceClassification.FORCING], classifications[DataSourceClassification.LITERATURE], classifications[DataSourceClassification.UNKNOWN], classifications[DataSourceClassification.TEMPLATE], result.calibration_performed, result.calibration_status, result.calibration_result.dataset if result.calibration_result else None, result.split.calibration_observation_ids if result.split else (), result.split.holdout_observation_ids if result.split else (), parameter_candidates, tuple(result.calibrated_parameters.value_map()) if result.calibrated_parameters else (), result.rejected_parameters, identifiability, confounders, result.baseline_metrics, result.calibrated_metrics, result.objective, result.split, result.warnings, result.limitations, _hash({"sources": [source.to_dict() for source in sources], "result": payload, "identifiability": identifiability}))

    def write_report(self, report: ScientificCalibrationReport, directory: str | Path | None = None) -> tuple[Path, Path]:
        output = Path(directory) if directory is not None else self.root / "data" / "calibration"
        output.mkdir(parents=True, exist_ok=True)
        report_path = output / "calibration_report.json"
        readme_path = output / "README.md"
        report_path.write_text(report.to_json() + "\n", encoding="utf-8")
        readme_path.write_text("# Calibration report\n\nThis artifact records conditional calibration readiness. Current scientific calibration is not performed without REAL_VERIFIED observations.\n\n" + f"- status: `{report.status.value}`\n- data readiness: `{report.data_readiness.value}`\n- configuration hash: `{report.configuration_hash}`\n", encoding="utf-8")
        return report_path, readme_path


def _observation_id(observation: Any, index: int) -> str:
    return f"{observation.dataset_id or 'dataset'}:{index}:{observation.timestamp.isoformat()}:{observation.variable}"


def _hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


__all__ = [
    "CalibrationExecutionStatus",
    "CalibrationParameterAudit",
    "CalibrationReadiness",
    "CalibrationSplit",
    "ScientificCalibrationReport",
    "ScientificCalibrationResult",
    "ScientificCalibrationSuite",
]
