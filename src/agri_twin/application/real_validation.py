"""Real-data validation readiness and out-of-sample evaluation orchestration.

This module is a gate and adapter around the existing ingestion, validation,
alignment, diagnostics and readiness contracts. It never promotes synthetic,
literature or forcing files to real agronomic observations.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable, Mapping

from agri_twin.application.scientific_readiness import ScientificReadinessGate
from agri_twin.domain.calibration import DatasetRole, ObservationDataset, ParameterSet
from agri_twin.domain.observation_ingestion import (
    ObservationIngestionResult,
    ObservationSourceType,
    ReadinessStatus,
    ingest_rows,
)
from agri_twin.domain.parameter_audit import ParameterRegistry
from agri_twin.domain.validation import AlignmentPolicy, ValidationCase, ValidationEngine, ValidationResult, ValidationStatus


class DataSourceClassification(StrEnum):
    REAL_VERIFIED = "REAL_VERIFIED"
    REAL_UNVERIFIED = "REAL_UNVERIFIED"
    SYNTHETIC = "SYNTHETIC"
    SIMULATED_REAL_DATA_SUBSTITUTE = "SIMULATED_REAL_DATA_SUBSTITUTE"
    FORCING = "FORCING"
    LITERATURE = "LITERATURE"
    UNKNOWN = "UNKNOWN"


class ValidationReadiness(StrEnum):
    VALIDATION_FRAMEWORK_READY = "VALIDATION_FRAMEWORK_READY"
    INSUFFICIENT_REAL_DATA = "INSUFFICIENT_REAL_DATA"
    INSUFFICIENT_COVERAGE = "INSUFFICIENT_COVERAGE"
    INSUFFICIENT_TEMPORAL_RANGE = "INSUFFICIENT_TEMPORAL_RANGE"
    INSUFFICIENT_VARIABLES = "INSUFFICIENT_VARIABLES"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"
    SUFFICIENT_FOR_VALIDATION = "SUFFICIENT_FOR_VALIDATION"


class ValidationScope(StrEnum):
    IN_SAMPLE = "IN_SAMPLE"
    OUT_OF_SAMPLE = "OUT_OF_SAMPLE"
    TEMPORAL_HOLDOUT = "TEMPORAL_HOLDOUT"
    CYCLE_HOLDOUT = "CYCLE_HOLDOUT"
    PLOT_HOLDOUT = "PLOT_HOLDOUT"
    VARIETY_HOLDOUT = "VARIETY_HOLDOUT"
    ENVIRONMENT_HOLDOUT = "ENVIRONMENT_HOLDOUT"


@dataclass(frozen=True, slots=True)
class DataSourceAudit:
    path: str
    classification: DataSourceClassification
    source_type: str
    evidence: tuple[str, ...] = ()
    variables: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"classification": self.classification.value}


@dataclass(frozen=True, slots=True)
class ValidationSplit:
    calibration_dataset_id: str | None
    validation_dataset_id: str | None
    scope: ValidationScope
    training_observations: int
    validation_observations: int
    contamination_detected: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"scope": self.scope.value}


@dataclass(frozen=True, slots=True)
class RealValidationResult:
    status: ValidationStatus
    readiness: ValidationReadiness
    data_source_status: DataSourceClassification
    validation_scope: ValidationScope
    alignment_policy: AlignmentPolicy
    quality_status: str
    calibration_status: str
    dataset_id: str | None
    validation: ValidationResult | None
    exclusions: tuple[dict[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "readiness": self.readiness.value,
            "data_source_status": self.data_source_status.value,
            "validation_scope": self.validation_scope.value,
            "alignment_policy": self.alignment_policy.value,
            "quality_status": self.quality_status,
            "calibration_status": self.calibration_status,
            "dataset_id": self.dataset_id,
            "validation": None if self.validation is None else {
                "status": self.validation.status.value,
                "observation_count": self.validation.observation_count,
                "metrics": [asdict(metric) for metric in self.validation.metrics],
                "warnings": list(self.validation.warnings),
                "limitations": list(self.validation.limitations),
            },
            "exclusions": list(self.exclusions),
            "warnings": list(self.warnings),
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class RealValidationReport:
    version: str
    sources: tuple[DataSourceAudit, ...]
    readiness: ValidationReadiness
    real_data_verified: bool
    synthetic_fixture_status: str
    results: tuple[RealValidationResult, ...]
    configuration_hash: str
    software_readiness_status: str = "SOFTWARE_READY"
    scientific_readiness_status: str = "INSUFFICIENT_DATA"
    calibration_status: str = "NOT_PERFORMED"
    experimental_validation_status: str = "NOT_CLAIMED"
    assimilation_status: str = "NOT_IMPLEMENTED"
    limitations: tuple[str, ...] = (
        "No real agronomic dataset with verified provenance was found.",
        "Synthetic fixtures qualify the software pipeline only.",
        "Forcing data is not treated as crop-response observation.",
        "No calibration, optimization or data assimilation is performed.",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "sources": [source.to_dict() for source in self.sources],
            "readiness": self.readiness.value,
            "real_data_verified": self.real_data_verified,
            "synthetic_fixture_status": self.synthetic_fixture_status,
            "results": [result.to_dict() for result in self.results],
            "configuration_hash": self.configuration_hash,
            "software_readiness_status": self.software_readiness_status,
            "scientific_readiness_status": self.scientific_readiness_status,
            "calibration_status": self.calibration_status,
            "experimental_validation_status": self.experimental_validation_status,
            "assimilation_status": self.assimilation_status,
            "limitations": list(self.limitations),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


class RealValidationSuite:
    """Audit data and run the existing validation engine without calibration."""

    VERSION = "5.25.1"

    def __init__(self, root: str | Path, *, registry: ParameterRegistry | None = None) -> None:
        self.root = Path(root)
        self.registry = registry or ParameterRegistry.from_repository(self.root)

    def audit_sources(self) -> tuple[DataSourceAudit, ...]:
        files = sorted(
            path for path in self.root.rglob("*")
            if path.is_file() and path.suffix.lower() in {".csv", ".xlsx", ".json", ".txt", ".parquet"}
            and ".venv" not in path.parts and "__pycache__" not in path.parts and ".git" not in path.parts
        )
        audits: list[DataSourceAudit] = []
        for path in files:
            relative = path.relative_to(self.root).as_posix()
            audits.append(self._classify_file(relative, path))
        return tuple(audits)

    def _classify_file(self, relative: str, path: Path) -> DataSourceAudit:
        lower = relative.lower()
        evidence: list[str] = []
        variables: list[str] = []
        notes: list[str] = []
        source_type = "unknown"
        classification = DataSourceClassification.UNKNOWN
        try:
            if path.suffix.lower() == ".json":
                payload = json.loads(path.read_text(encoding="utf-8"))
                text = json.dumps(payload, sort_keys=True).lower()
                variables = tuple(sorted(str(item) for item in payload.get("variables", ()))) if isinstance(payload, Mapping) else ()
            else:
                text = path.read_text(encoding="utf-8", errors="replace").lower()
        except (OSError, UnicodeError, json.JSONDecodeError):
            text = ""
            notes.append("metadata could not be parsed")

        if "synthetic_real_substitute" in lower or "simulated_real_data_substitute" in text:
            classification = DataSourceClassification.SIMULATED_REAL_DATA_SUBSTITUTE
            source_type = "synthetic"
            evidence.append("explicit synthetic real-data substitute provenance")
        elif "/synthetic/" in f"/{lower}" or lower.startswith("data/synthetic") or "synthetic_test" in text:
            classification = DataSourceClassification.SYNTHETIC
            source_type = "synthetic_test_data"
            evidence.append("synthetic path or explicit synthetic test metadata")
        elif "/templates/" in f"/{lower}" or lower.startswith("templates/"):
            classification = DataSourceClassification.UNKNOWN
            source_type = "template"
            evidence.append("template contract, not an observation dataset")
        elif "phenology" in lower and ("doi" in text or "literature" in text or "source_id" in text):
            classification = DataSourceClassification.LITERATURE
            source_type = "literature"
            evidence.append("literature/evidence fields present")
        elif "weather" in lower or "forecast" in lower or "open-meteo" in text or "forcing" in text:
            classification = DataSourceClassification.FORCING
            source_type = "forcing"
            evidence.append("weather or forecast forcing metadata")
            notes.append("not eligible as independent crop-response observation")
        elif "real" in text or "measured" in text or "observation" in text:
            classification = DataSourceClassification.REAL_UNVERIFIED
            source_type = "unverified_observation"
            evidence.append("observation-like metadata without sufficient provenance")
            notes.append("origin/context/evidence not sufficient for REAL_VERIFIED")
        else:
            notes.append("configuration or non-observation file")
        return DataSourceAudit(relative, classification, source_type, tuple(evidence), variables, tuple(notes))

    def assess_readiness(self, sources: Iterable[DataSourceAudit] | None = None) -> ValidationReadiness:
        sources = tuple(sources or self.audit_sources())
        if any(source.classification is DataSourceClassification.REAL_VERIFIED for source in sources):
            return ValidationReadiness.SUFFICIENT_FOR_VALIDATION
        return ValidationReadiness.INSUFFICIENT_REAL_DATA

    def ingest_fixture(self, rows: Iterable[Mapping[str, Any]], *, dataset_id: str = "synthetic_validation_fixture") -> ObservationIngestionResult:
        return ingest_rows(rows, dataset_id=dataset_id, role=DatasetRole.TEST, source="synthetic_validation_fixture", source_type=ObservationSourceType.SYNTHETIC_TEST)

    def evaluate(self, case: ValidationCase, *, source_status: DataSourceClassification, scope: ValidationScope, runner: Any) -> RealValidationResult:
        if source_status is not DataSourceClassification.REAL_VERIFIED:
            validation = ValidationEngine().evaluate(case, runner)
            return RealValidationResult(
                validation.status,
                ValidationReadiness.INSUFFICIENT_REAL_DATA,
                source_status,
                scope,
                case.alignment,
                "SYNTHETIC_FIXTURE_ONLY" if source_status is DataSourceClassification.SYNTHETIC else "NOT_READY",
                "NOT_PERFORMED",
                case.dataset.name,
                validation,
                limitations=("This execution is a software fixture and cannot establish scientific validation.",),
            )
        validation = ValidationEngine().evaluate(case, runner)
        readiness = ValidationReadiness.SUFFICIENT_FOR_VALIDATION if validation.status is ValidationStatus.SUCCESS else ValidationReadiness.INSUFFICIENT_CONTEXT
        return RealValidationResult(validation.status, readiness, source_status, scope, case.alignment, "INGESTED", "NOT_PERFORMED", case.dataset.name, validation)

    def build_report(self, fixture_result: RealValidationResult | None = None) -> RealValidationReport:
        sources = self.audit_sources()
        result_tuple = (fixture_result,) if fixture_result else ()
        payload = {"version": self.VERSION, "sources": [item.to_dict() for item in sources], "results": [item.to_dict() for item in result_tuple], "readiness": self.assess_readiness(sources).value}
        readiness = ScientificReadinessGate(self.root).evaluate()
        return RealValidationReport(
            self.VERSION,
            sources,
            ValidationReadiness.INSUFFICIENT_REAL_DATA,
            False,
            "SYNTHETIC_FIXTURE_ONLY",
            result_tuple,
            _hash(payload),
            readiness.software_readiness.value,
            readiness.scientific_validation_status.value,
        )

    def write_report(self, report: RealValidationReport, directory: str | Path | None = None) -> tuple[Path, Path]:
        output = Path(directory) if directory is not None else self.root / "data" / "validation"
        output.mkdir(parents=True, exist_ok=True)
        report_path = output / "validation_report.json"
        readme_path = output / "README.md"
        report_path.write_text(report.to_json() + "\n", encoding="utf-8")
        readme_path.write_text(
            "# Validation report\n\n"
            "This artifact records validation readiness. Current status is `INSUFFICIENT_REAL_DATA`; synthetic fixtures are software checks only.\n\n"
            f"- readiness: `{report.readiness.value}`\n- real data verified: `{report.real_data_verified}`\n- configuration hash: `{report.configuration_hash}`\n",
            encoding="utf-8",
        )
        return report_path, readme_path


def _hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


__all__ = [
    "DataSourceAudit",
    "DataSourceClassification",
    "RealValidationReport",
    "RealValidationResult",
    "RealValidationSuite",
    "ValidationReadiness",
    "ValidationScope",
    "ValidationSplit",
]
