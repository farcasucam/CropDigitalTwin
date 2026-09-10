"""Read-only experimental observation and data-acquisition planning."""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import StrEnum
from typing import Any, Iterable

from agri_twin.application.parameter_identifiability import (
    IdentifiabilityReport,
    IdentifiabilityStatus,
    ParameterIdentifiability,
)


class RequirementSource(StrEnum):
    SCIENTIFIC_REQUIREMENT = "scientific_requirement"
    ENGINEERING_RECOMMENDATION = "engineering_recommendation"
    PROJECT_REQUIREMENT = "project_requirement"
    UNKNOWN = "unknown"


class PlanPriority(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class PlanStatus(StrEnum):
    NOT_PLANNED = "NOT_PLANNED"
    PARTIAL = "PARTIAL"
    PLANNED = "PLANNED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ObservationPlanItem:
    observation_id: str
    parameter_ids: tuple[str, ...]
    variable: str | None
    purpose: str
    crop: str | None
    variety: str | None
    plot: str | None
    environment: str | None
    phenological_stage: str | None
    measurement_method: str
    unit: str | None
    temporal_resolution: str
    spatial_scope: str
    required_conditions: tuple[str, ...]
    uncertainty_target: str
    quality_requirements: tuple[str, ...]
    source_type: RequirementSource
    source_reference: str | None
    evidence_level: str
    confidence: str
    priority: PlanPriority
    status: PlanStatus
    confounders: tuple[str, ...]
    identifiability_status: IdentifiabilityStatus
    notes: str

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for item in fields(self):
            value = getattr(self, item.name)
            if isinstance(value, StrEnum):
                value = value.value
            elif isinstance(value, tuple):
                value = [part.value if isinstance(part, StrEnum) else part for part in value]
            result[item.name] = value
        return result


@dataclass(frozen=True, slots=True)
class ExperimentalObservationPlan:
    items: tuple[ObservationPlanItem, ...]
    real_data_available: bool = False
    campaign_status: str = "DESIGNED_NOT_EXECUTED"

    @classmethod
    def from_identifiability_report(cls, report: IdentifiabilityReport) -> "ExperimentalObservationPlan":
        items = tuple(_item_from_assessment(assessment) for assessment in report.assessments)
        return cls(items, report.real_data_available, "DESIGNED_NOT_EXECUTED")

    def for_parameter(self, parameter_id: str) -> tuple[ObservationPlanItem, ...]:
        return tuple(item for item in self.items if parameter_id in item.parameter_ids)

    def for_observable(self, variable: str) -> tuple[ObservationPlanItem, ...]:
        return tuple(item for item in self.items if item.variable == variable)

    def for_crop(self, crop: str) -> tuple[ObservationPlanItem, ...]:
        return tuple(item for item in self.items if item.crop in {None, crop})

    def for_variety(self, crop: str, variety: str) -> tuple[ObservationPlanItem, ...]:
        return tuple(item for item in self.items if item.crop in {None, crop} and item.variety in {None, variety})

    def for_plot(self, plot_id: str) -> tuple[ObservationPlanItem, ...]:
        return tuple(item for item in self.items if item.plot in {None, plot_id})

    def for_environment(self, environment: str) -> tuple[ObservationPlanItem, ...]:
        value = environment.upper()
        return tuple(item for item in self.items if item.environment is None or item.environment.upper() == value)

    def for_stage(self, stage: str) -> tuple[ObservationPlanItem, ...]:
        return tuple(item for item in self.items if item.phenological_stage in {None, stage})

    def coverage(self) -> dict[str, int]:
        return {status.value: sum(item.status is status for item in self.items) for status in PlanStatus}

    def confounded_parameters(self) -> tuple[ObservationPlanItem, ...]:
        return tuple(item for item in self.items if item.confounders)

    def campaign_checklist(self) -> tuple[dict[str, Any], ...]:
        return tuple({"observation_id": item.observation_id, "crop": item.crop, "variety": item.variety or "generic", "environment": item.environment or "UNKNOWN", "variable": item.variable or "UNKNOWN", "stage": item.phenological_stage or "UNKNOWN", "method": item.measurement_method, "priority": item.priority.value, "status": item.status.value} for item in self.items)

    def to_dict(self) -> dict[str, Any]:
        return {"campaign_status": self.campaign_status, "real_data_available": self.real_data_available, "coverage": self.coverage(), "items": [item.to_dict() for item in self.items]}


def _item_from_assessment(assessment: ParameterIdentifiability) -> ObservationPlanItem:
    priority = _priority(assessment)
    source = RequirementSource.UNKNOWN
    status = PlanStatus.UNKNOWN if not assessment.observable_variables else PlanStatus.PLANNED
    notes = "PLANNED does not mean measured, identified, calibrated or validated."
    if assessment.identifiability_status is IdentifiabilityStatus.INSUFFICIENT_DATA:
        notes += " Real observations are required before readiness can be reassessed."
    if assessment.identifiability_status is IdentifiabilityStatus.FIXED:
        priority = PlanPriority.LOW
        status = PlanStatus.NOT_PLANNED
        notes += " Calibration is not allowed by the registry contract."
    return ObservationPlanItem(
        observation_id=f"plan.{assessment.parameter_id}",
        parameter_ids=(assessment.parameter_id,),
        variable=assessment.observable_variables[0] if assessment.observable_variables else None,
        purpose=f"Provide evidence for {assessment.name}",
        crop=assessment.crop,
        variety=assessment.variety,
        plot=assessment.plot,
        environment=assessment.required_environmental_coverage[0] if assessment.required_environmental_coverage else None,
        phenological_stage=assessment.phenological_stage,
        measurement_method=assessment.measurement_method or "TO_BE_DEFINED",
        unit=None,
        temporal_resolution=assessment.temporal_resolution or "UNKNOWN",
        spatial_scope="plot" if assessment.plot else "crop/variety scope",
        required_conditions=assessment.required_environmental_coverage,
        uncertainty_target=assessment.uncertainty_requirement or "UNKNOWN",
        quality_requirements=("VALID", "MISSING", "ESTIMATED", "INVALID", "DUPLICATE", "OUT_OF_RANGE", "UNIT_ERROR"),
        source_type=source,
        source_reference=None,
        evidence_level=assessment.evidence_level,
        confidence=assessment.confidence,
        priority=priority,
        status=status,
        confounders=assessment.confounders,
        identifiability_status=assessment.identifiability_status,
        notes=notes,
    )


def _priority(assessment: ParameterIdentifiability) -> PlanPriority:
    if not assessment.calibration_allowed or assessment.identifiability_status is IdentifiabilityStatus.NOT_CALIBRATABLE:
        return PlanPriority.LOW
    if assessment.confounders and assessment.category in {"biological", "soil", "greenhouse"}:
        return PlanPriority.HIGH
    if assessment.category in {"biological", "soil", "environmental"}:
        return PlanPriority.MEDIUM
    if assessment.category in {"management", "greenhouse"}:
        return PlanPriority.MEDIUM
    return PlanPriority.UNKNOWN


__all__ = ["ExperimentalObservationPlan", "ObservationPlanItem", "PlanPriority", "PlanStatus", "RequirementSource"]
