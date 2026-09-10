"""Conservative parameter identifiability and future calibration readiness analysis."""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable

from agri_twin.domain.calibration import ObservationDataset
from agri_twin.domain.crop_calibration import CropCalibrationProtocol, build_protocol
from agri_twin.domain.parameter_audit import ParameterRecord, ParameterRegistry


class IdentifiabilityStatus(StrEnum):
    NOT_CALIBRATABLE = "NOT_CALIBRATABLE"
    FIXED = "FIXED"
    CANDIDATE = "CANDIDATE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    IDENTIFIABLE = "IDENTIFIABLE"
    CONFOUNDED = "CONFOUNDED"
    VARIETY_SPECIFIC = "VARIETY_SPECIFIC"
    ENVIRONMENT_SPECIFIC = "ENVIRONMENT_SPECIFIC"


@dataclass(frozen=True, slots=True)
class ParameterIdentifiability:
    parameter_id: str
    name: str
    crop: str | None
    variety: str | None
    plot: str | None
    phenological_stage: str | None
    subsystem: str
    category: str
    observable_variables: tuple[str, ...]
    required_observation_types: tuple[str, ...]
    required_environmental_coverage: tuple[str, ...]
    required_stage_coverage: tuple[str, ...]
    measurement_method: str | None
    temporal_resolution: str | None
    uncertainty_requirement: str | None
    provenance: str
    evidence_level: str
    confidence: str
    calibration_allowed: bool
    calibration_status: str
    identifiability_status: IdentifiabilityStatus
    confounders: tuple[str, ...]
    notes: str
    scientific_warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        result = {}
        for item in fields(self):
            value = getattr(self, item.name)
            result[item.name] = value.value if isinstance(value, IdentifiabilityStatus) else value
        return result


@dataclass(frozen=True, slots=True)
class IdentifiabilityReport:
    assessments: tuple[ParameterIdentifiability, ...]
    real_data_available: bool
    synthetic_data_only: bool
    scope: str = "species"

    def by_status(self, status: IdentifiabilityStatus) -> tuple[ParameterIdentifiability, ...]:
        return tuple(item for item in self.assessments if item.identifiability_status is status)

    def by_crop(self, crop: str) -> tuple[ParameterIdentifiability, ...]:
        return tuple(item for item in self.assessments if item.crop in {None, crop})

    def by_variety(self, crop: str, variety: str) -> tuple[ParameterIdentifiability, ...]:
        return tuple(item for item in self.assessments if item.crop in {None, crop} and item.variety in {None, variety})

    def by_plot(self, plot: str) -> tuple[ParameterIdentifiability, ...]:
        return tuple(item for item in self.assessments if item.plot in {None, plot})

    def by_environment(self, environment: str) -> tuple[ParameterIdentifiability, ...]:
        return tuple(item for item in self.assessments if not item.required_environmental_coverage or environment.upper() in {value.upper() for value in item.required_environmental_coverage})

    def to_dict(self) -> dict[str, Any]:
        return {
            "real_data_available": self.real_data_available,
            "synthetic_data_only": self.synthetic_data_only,
            "scope": self.scope,
            "assessments": [item.to_dict() for item in self.assessments],
        }


class ParameterIdentifiabilityAnalyzer:
    """Read-only analysis over the existing registry, protocol and observations."""

    def __init__(self, parameter_registry: ParameterRegistry, calibration_protocol: CropCalibrationProtocol | None = None, repository_root: str | Path | None = None) -> None:
        self.parameter_registry = parameter_registry
        self.calibration_protocol = calibration_protocol
        self.repository_root = Path(repository_root) if repository_root is not None else None

    def analyze_parameter(self, parameter_id: str, observations: ObservationDataset | None = None) -> ParameterIdentifiability:
        record = self.parameter_registry.get(parameter_id)
        return self._assess(record, observations)

    def analyze_all(self, observations: ObservationDataset | None = None, *, crop: str | None = None, variety: str | None = None, plot: str | None = None, environment: str | None = None) -> IdentifiabilityReport:
        records = [record for record in self.parameter_registry.records if crop is None or record.crop in {None, crop}]
        if variety is not None:
            records = [record for record in records if record.variety in {None, variety}]
        assessments = tuple(self._assess(record, observations, plot=plot, environment=environment) for record in sorted(records, key=lambda item: item.parameter_id))
        real = bool(observations and observations.source_type not in {"synthetic_test_data", "forcing"})
        synthetic = bool(observations and observations.source_type == "synthetic_test_data")
        return IdentifiabilityReport(assessments, real, synthetic)

    def analyze_protocol(self, root: str | Path, crop: str, variety: str | None = None, plot: str | None = None, environment: str = "OUTDOOR", observations: ObservationDataset | None = None) -> IdentifiabilityReport:
        protocol = self.calibration_protocol or build_protocol(root, self.parameter_registry, crop, variety, plot, environment)
        analyzer = ParameterIdentifiabilityAnalyzer(self.parameter_registry, protocol, root)
        return analyzer.analyze_all(observations, crop=crop, variety=variety, plot=plot, environment=environment)

    def parameter_observation_matrix(self, observations: ObservationDataset | None = None) -> tuple[ParameterIdentifiability, ...]:
        return self.analyze_all(observations).assessments

    def confounder_matrix(self) -> dict[str, tuple[str, ...]]:
        groups: dict[str, list[ParameterRecord]] = {
            "growth_scaling": [], "radiation_interception": [], "phenology": [], "water_stress": [],
            "vpd": [], "co2": [], "senescence_damage": [], "fruit_development": [],
        }
        for record in self.parameter_registry.records:
            text = f"{record.parameter_id} {record.name} {record.subsystem}".lower()
            for group, terms in _CONFOUNDER_TERMS.items():
                if any(term in text for term in terms):
                    groups[group].append(record)
        return {group: tuple(sorted(record.parameter_id for record in records)) for group, records in groups.items() if len(records) > 1}

    def _assess(self, record: ParameterRecord, observations: ObservationDataset | None, *, plot: str | None = None, environment: str | None = None) -> ParameterIdentifiability:
        observables = _observables(record)
        required_types = (record.observational_data_required,) if record.observational_data_required else ()
        required_stage = (record.phenological_stage,) if record.phenological_stage else ()
        required_environment = (environment,) if environment and record.category in {"greenhouse", "environmental"} else ()
        warnings: list[str] = []
        if record.calibration_status == "not_applicable":
            status = IdentifiabilityStatus.NOT_CALIBRATABLE
        elif not record.calibration_allowed:
            status = IdentifiabilityStatus.FIXED
        elif record.variety is not None:
            status = IdentifiabilityStatus.VARIETY_SPECIFIC
            warnings.append("variety-specific scope does not mean calibrated or identifiable")
        elif record.category == "greenhouse" or record.subsystem in {"actuator_contract", "runtime_code"} and record.parameter_id.startswith(("greenhouse.", "feedback.")):
            status = IdentifiabilityStatus.ENVIRONMENT_SPECIFIC
            warnings.append("environment-specific scope requires site observations")
        elif observations is None or not observations.observations:
            status = IdentifiabilityStatus.INSUFFICIENT_DATA
            warnings.append("no observation dataset supplied")
        elif observations.source_type in {"synthetic_test_data", "forcing"}:
            status = IdentifiabilityStatus.INSUFFICIENT_DATA
            warnings.append("synthetic or forcing data cannot establish scientific identifiability")
        else:
            available = {item.variable for item in observations.observations if item.quality == "VALID"}
            if observables and not available.intersection(observables):
                status = IdentifiabilityStatus.INSUFFICIENT_DATA
                warnings.append("required observables are absent")
            else:
                status = IdentifiabilityStatus.CANDIDATE
                warnings.append("identifiability requires coverage and confounder assessment")
        confounders = self._confounders_for(record)
        if status is IdentifiabilityStatus.CANDIDATE and confounders:
            status = IdentifiabilityStatus.CONFOUNDED
            warnings.append("potential parameter confounding is unresolved")
        if not record.unit:
            warnings.append("parameter unit is not defined")
        return ParameterIdentifiability(
            record.parameter_id, record.name, record.crop, record.variety, plot, record.phenological_stage,
            record.subsystem, record.category, observables, required_types, required_environment, required_stage,
            None, None, None, record.source_type, record.evidence_level, record.confidence, record.calibration_allowed,
            record.calibration_status, status, confounders, record.notes, tuple(warnings),
        )

    def _confounders_for(self, record: ParameterRecord) -> tuple[str, ...]:
        text = f"{record.parameter_id} {record.name}".lower()
        related = []
        for candidate in self.parameter_registry.records:
            if candidate.parameter_id == record.parameter_id:
                continue
            candidate_text = f"{candidate.parameter_id} {candidate.name}".lower()
            if any(term in text and term in candidate_text for term in _CONFOUNDER_TERMS_FLAT):
                related.append(candidate.parameter_id)
        return tuple(sorted(related))


def _observables(record: ParameterRecord) -> tuple[str, ...]:
    text = record.observational_data_required.lower()
    mapping = {
        "lai": "lai", "biomass": "biomass", "phenology": "flowering", "event": "flowering",
        "stage": "flowering", "soil": "soil_water_content", "vwc": "soil_water_content",
        "irrigation": "irrigation", "water": "soil_water_content", "temperature": "air_temperature",
        "climate": "air_temperature", "radiation": "solar_radiation", "co2": "co2", "yield": "yield",
        "fruit": "fruit_weight", "stress": "vpd", "vpd": "vpd",
    }
    return tuple(sorted({value for key, value in mapping.items() if key in text}))


_CONFOUNDER_TERMS = {
    "growth_scaling": ("rue", "sla", "leaf_area", "biomass"),
    "radiation_interception": ("extinction", "radiation", "lai"),
    "phenology": ("tbase", "tupper", "gdd", "stage", "maturity", "thermal"),
    "water_stress": ("water", "vwc", "soil", "irrigation", "root"),
    "vpd": ("vpd", "humidity", "temperature"),
    "co2": ("co2", "ventilation", "transmission"),
    "senescence_damage": ("senescence", "damage", "stress", "frost", "heat"),
    "fruit_development": ("fruit", "maturity", "yield", "source_sink"),
}
_CONFOUNDER_TERMS_FLAT = tuple(sorted({term for terms in _CONFOUNDER_TERMS.values() for term in terms}))


__all__ = ["IdentifiabilityReport", "IdentifiabilityStatus", "ParameterIdentifiability", "ParameterIdentifiabilityAnalyzer"]
