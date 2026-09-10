"""Phase 5.19 real agronomic data integration & calibration readiness layer.

This module does not introduce a second observation, ingestion, alignment,
diagnostics, identifiability, registry or calibration system. It reuses the
existing Phase 5.8-5.18 contracts unchanged and adds only:

- a small, explicit manifest/quality-report contract for a real dataset;
- a plot registration lookup against the existing farm catalog;
- a conservative calibration-readiness *gate* built purely from the existing
  `ParameterIdentifiabilityAnalyzer` and `parameter_readiness()` outputs.

Scientific boundaries (must not be crossed by this module):
- no parameter calibration (no GridSearchCalibrator, no optimizer);
- no data assimilation (TwinState is never derived from observations);
- no invented numeric readiness thresholds;
- no claim of experimental/scientific validation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any

from agri_twin.application.error_diagnostics import ErrorDiagnostics, diagnose
from agri_twin.application.parameter_identifiability import (
    IdentifiabilityReport,
    IdentifiabilityStatus,
    ParameterIdentifiabilityAnalyzer,
)
from agri_twin.application.twin_alignment import ComparisonDataset, TemporalAlignment, compare_dataset
from agri_twin.application.twin_state import TwinStateRepository
from agri_twin.domain.calibration import ObservationDataset
from agri_twin.domain.observation_ingestion import (
    ObservationIngestionResult,
    ParameterReadiness,
    ParameterReadinessStatus,
    parameter_readiness,
)
from agri_twin.domain.parameter_audit import ParameterRegistry

THRESHOLD_POLICY = "TO_BE_DEFINED"  # Phase 5.19 introduces no invented numeric readiness thresholds.


class RealDataIntegrationError(ValueError):
    """Raised for invalid real-dataset manifests or readiness assessments."""


@dataclass(frozen=True, slots=True)
class RealDatasetManifest:
    """Traceable metadata for one real agronomic dataset import."""

    dataset_id: str
    source: str
    source_type: str
    collection_method: str
    imported_at: datetime
    original_reference: str | None
    plot_coverage: tuple[str, ...]
    plot_registration: dict[str, str]
    crop_coverage: tuple[str, ...]
    variety_coverage: tuple[str, ...]
    cycle_coverage: tuple[str, ...]
    environment_coverage: tuple[str, ...]
    variables: tuple[str, ...]
    units: dict[str, str]
    timezone_policy: str = "explicit timezone-aware ISO-8601 required; ambiguous timestamps are rejected"
    quality_policy: str = "VALID/MISSING/INVALID/ESTIMATED/DUPLICATE/OUT_OF_RANGE/UNIT_ERROR; no imputation, no automatic correction"
    provenance: str = "REAL_IMPORTED"
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.dataset_id or not self.source:
            raise RealDataIntegrationError("dataset_id and source are required")
        if self.imported_at.tzinfo is None:
            raise RealDataIntegrationError("imported_at is process metadata and must be timezone-aware")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for item in fields(self):
            value = getattr(self, item.name)
            result[item.name] = value.isoformat() if isinstance(value, datetime) else value
        return result

    @classmethod
    def from_ingestion(
        cls,
        root: str | Path,
        ingestion: ObservationIngestionResult,
        *,
        dataset_id: str,
        source: str,
        collection_method: str,
        imported_at: datetime,
        original_reference: str | None = None,
        notes: tuple[str, ...] = (),
    ) -> "RealDatasetManifest":
        observations = ingestion.dataset.observations if ingestion.dataset is not None else ()
        plots = tuple(sorted({item.plot_id for item in observations if item.plot_id}))
        units: dict[str, str] = {}
        for item in observations:
            units.setdefault(item.variable, item.unit_original or item.unit)
        return cls(
            dataset_id=dataset_id,
            source=source,
            source_type=ingestion.source_type.value,
            collection_method=collection_method,
            imported_at=imported_at,
            original_reference=original_reference or ingestion.original_filename,
            plot_coverage=plots,
            plot_registration={plot: plot_registration_status(root, plot) for plot in plots},
            crop_coverage=tuple(sorted({item.crop for item in observations if item.crop})),
            variety_coverage=tuple(sorted({item.variety for item in observations if item.variety})),
            cycle_coverage=tuple(sorted({item.cycle_id for item in observations if item.cycle_id})),
            environment_coverage=tuple(sorted({item.environment for item in observations if item.environment})),
            variables=tuple(sorted({item.variable for item in observations})),
            units=units,
            notes=notes,
        )


def plot_registration_status(root: str | Path, plot_id: str | None) -> str:
    """REGISTERED for plots already known to the farm catalog; EXTERNAL_UNREGISTERED otherwise.

    Never blocks ingestion and never mutates the farm catalog.
    """

    if not plot_id:
        return "UNKNOWN"
    farm_path = Path(root) / "src" / "farm_config.json"
    if not farm_path.exists():
        return "UNKNOWN"
    payload = json.loads(farm_path.read_text(encoding="utf-8"))
    registered = {plot["id"] for plot in payload.get("plots", ())}
    return "REGISTERED" if plot_id in registered else "EXTERNAL_UNREGISTERED"


@dataclass(frozen=True, slots=True)
class RealDataQualityReport:
    """Deterministic, serializable quality summary for one real dataset import."""

    total_records: int
    valid_records: int
    invalid_records: int
    duplicate_records: int
    missing_records: int
    unit_error_records: int
    out_of_range_records: int
    temporal_issue_records: int
    plots: tuple[str, ...]
    crops: tuple[str, ...]
    varieties: tuple[str, ...]
    cycles: tuple[str, ...]
    environments: tuple[str, ...]
    variables: tuple[str, ...]
    time_start: datetime | None
    time_end: datetime | None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for item in fields(self):
            value = getattr(self, item.name)
            result[item.name] = value.isoformat() if isinstance(value, datetime) else value
        return result


def build_quality_report(ingestion: ObservationIngestionResult) -> RealDataQualityReport:
    observations = ingestion.dataset.observations if ingestion.dataset is not None else ()
    readiness = ingestion.readiness
    temporal_issues = sum("timestamp" in issue.message.lower() or "timezone" in issue.message.lower() for issue in ingestion.qc)
    return RealDataQualityReport(
        total_records=readiness.n_observations,
        valid_records=readiness.n_valid,
        invalid_records=readiness.n_invalid,
        duplicate_records=readiness.n_duplicates,
        missing_records=readiness.n_missing,
        unit_error_records=sum(1 for issue in ingestion.qc if issue.quality.value == "UNIT_ERROR"),
        out_of_range_records=sum(1 for issue in ingestion.qc if issue.quality.value == "OUT_OF_RANGE"),
        temporal_issue_records=temporal_issues,
        plots=tuple(sorted({item.plot_id for item in observations if item.plot_id})),
        crops=tuple(sorted({item.crop for item in observations if item.crop})),
        varieties=tuple(sorted({item.variety for item in observations if item.variety})),
        cycles=tuple(sorted({item.cycle_id for item in observations if item.cycle_id})),
        environments=tuple(sorted({item.environment for item in observations if item.environment})),
        variables=tuple(sorted({item.variable for item in observations})),
        time_start=readiness.date_start,
        time_end=readiness.date_end,
    )


@dataclass(frozen=True, slots=True)
class CalibrationReadinessRecord:
    """One parameter's conservative calibration-readiness gate outcome."""

    parameter_id: str
    crop: str | None
    variety: str | None
    identifiability_status: IdentifiabilityStatus
    data_readiness_status: ParameterReadinessStatus
    confounders: tuple[str, ...]
    gate_status: ParameterReadinessStatus
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter_id": self.parameter_id, "crop": self.crop, "variety": self.variety,
            "identifiability_status": self.identifiability_status.value,
            "data_readiness_status": self.data_readiness_status.value,
            "confounders": list(self.confounders), "gate_status": self.gate_status.value,
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class CalibrationReadinessGate:
    """Read-only synthesis of existing identifiability and data-readiness signals.

    READY_FOR_CALIBRATION means only "there is enough evidence to study a future
    calibration attempt". It never means the model is calibrated or validated.
    """

    records: tuple[CalibrationReadinessRecord, ...]
    threshold_policy: str = THRESHOLD_POLICY

    def ready_parameters(self) -> tuple[CalibrationReadinessRecord, ...]:
        return tuple(item for item in self.records if item.gate_status is ParameterReadinessStatus.READY_FOR_CALIBRATION)

    def not_ready_parameters(self) -> tuple[CalibrationReadinessRecord, ...]:
        return tuple(item for item in self.records if item.gate_status is ParameterReadinessStatus.NOT_READY)

    def to_dict(self) -> dict[str, Any]:
        return {
            "threshold_policy": self.threshold_policy,
            "ready_count": len(self.ready_parameters()),
            "not_ready_count": len(self.not_ready_parameters()),
            "records": [item.to_dict() for item in self.records],
        }


def assess_calibration_readiness(
    registry: ParameterRegistry, dataset: ObservationDataset | None, identifiability: IdentifiabilityReport
) -> CalibrationReadinessGate:
    """Combine existing identifiability and data-readiness outputs into one gate. Decides nothing new."""

    data_readiness: tuple[ParameterReadiness, ...] = parameter_readiness(registry, dataset) if dataset is not None else ()
    data_by_id = {item.parameter_id: item for item in data_readiness}
    records = []
    for assessment in identifiability.assessments:
        data_item = data_by_id.get(assessment.parameter_id)
        data_status = data_item.status if data_item is not None else ParameterReadinessStatus.NOT_READY
        ready = (
            assessment.identifiability_status is IdentifiabilityStatus.IDENTIFIABLE
            and data_status is ParameterReadinessStatus.READY_FOR_CALIBRATION
            and not assessment.confounders
        )
        gate_status = ParameterReadinessStatus.READY_FOR_CALIBRATION if ready else ParameterReadinessStatus.NOT_READY
        rationale = (
            "identifiable, data-ready and unconfounded: candidate for a future calibration study"
            if ready
            else f"blocked by identifiability={assessment.identifiability_status.value}, data_readiness={data_status.value}, confounders={list(assessment.confounders) or 'none'}"
        )
        records.append(
            CalibrationReadinessRecord(
                assessment.parameter_id, assessment.crop, assessment.variety, assessment.identifiability_status,
                data_status, assessment.confounders, gate_status, rationale,
            )
        )
    return CalibrationReadinessGate(tuple(records))


@dataclass(slots=True)
class RealDataAssessment:
    """Full Phase 5.19 pipeline output for one real dataset. Read-only; no mutation of core state."""

    manifest: RealDatasetManifest
    quality_report: RealDataQualityReport
    comparison: ComparisonDataset | None
    diagnostics: ErrorDiagnostics | None
    identifiability: IdentifiabilityReport
    readiness_gate: CalibrationReadinessGate
    pipeline_status: str
    scientific_status: tuple[str, ...]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest.to_dict(),
            "quality_report": self.quality_report.to_dict(),
            "comparison_count": len(self.comparison.results) if self.comparison is not None else 0,
            "diagnostics": self.diagnostics.global_summary().to_dict() if self.diagnostics is not None else None,
            "identifiability": self.identifiability.to_dict(),
            "readiness_gate": self.readiness_gate.to_dict(),
            "pipeline_status": self.pipeline_status,
            "scientific_status": list(self.scientific_status),
            "limitations": list(self.limitations),
        }


def assess_real_dataset(
    root: str | Path,
    registry: ParameterRegistry,
    ingestion: ObservationIngestionResult,
    manifest: RealDatasetManifest,
    quality_report: RealDataQualityReport,
    *,
    twin_repository: TwinStateRepository | None = None,
    alignment: TemporalAlignment = TemporalAlignment(),
) -> RealDataAssessment:
    """Run alignment (if a twin history is supplied), diagnostics, identifiability and the readiness gate."""

    analyzer = ParameterIdentifiabilityAnalyzer(registry, repository_root=Path(root))
    identifiability = analyzer.analyze_all(ingestion.dataset)
    comparison = (
        compare_dataset(twin_repository, ingestion.dataset, alignment)
        if twin_repository is not None and ingestion.dataset is not None
        else None
    )
    diagnostics = diagnose(comparison) if comparison is not None else None
    gate = assess_calibration_readiness(registry, ingestion.dataset, identifiability)
    pipeline_status = "REAL_DATA_INGESTION_VERIFIED" if ingestion.dataset is not None else "REAL_DATA_NOT_AVAILABLE"
    return RealDataAssessment(
        manifest=manifest,
        quality_report=quality_report,
        comparison=comparison,
        diagnostics=diagnostics,
        identifiability=identifiability,
        readiness_gate=gate,
        pipeline_status=pipeline_status,
        scientific_status=(
            "REAL_DATA_PIPELINE_VERIFIED" if ingestion.dataset is not None else "REAL_DATA_NOT_AVAILABLE",
            "CALIBRATION_READINESS_ASSESSED",
            "CALIBRATION_NOT_PERFORMED",
            "DATA_ASSIMILATION_NOT_IMPLEMENTED",
            "NOT_SCIENTIFICALLY_VALIDATED",
        ),
        limitations=(
            "REAL AGRONOMIC DATA MAY BE INCOMPLETE, SMALL OR HETEROGENEOUS",
            "CALIBRATION NOT PERFORMED",
            "DATA ASSIMILATION NOT IMPLEMENTED",
            "EXPERIMENTAL VALIDATION NOT CLAIMED",
            f"readiness threshold policy: {THRESHOLD_POLICY}",
        ),
    )


__all__ = [
    "CalibrationReadinessGate",
    "CalibrationReadinessRecord",
    "RealDataAssessment",
    "RealDataIntegrationError",
    "RealDataQualityReport",
    "RealDatasetManifest",
    "THRESHOLD_POLICY",
    "assess_calibration_readiness",
    "assess_real_dataset",
    "build_quality_report",
    "plot_registration_status",
]
