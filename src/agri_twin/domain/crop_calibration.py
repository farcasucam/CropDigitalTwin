"""Crop/variety calibration protocol built on the Phase 5.2 framework."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from agri_twin.domain.calibration import (
    CalibrationCase,
    CalibrationObjective,
    CalibrationResult,
    CalibrationStatus,
    CalibrationParameter,
    DatasetRole,
    FunctionSimulationRunner,
    GridSearchCalibrator,
    ObservationDataset,
    ParameterSet,
    SimulationPoint,
)
from agri_twin.domain.parameter_audit import ParameterRecord, ParameterRegistry


class CropCalibrationError(ValueError):
    """Raised when a crop calibration protocol is invalid."""


class ScientificStatus(StrEnum):
    NOT_EVALUATED = "NOT_EVALUATED"
    FRAMEWORK_READY = "FRAMEWORK_READY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    CALIBRATION_READY = "CALIBRATION_READY"
    CALIBRATED = "CALIBRATED"
    VALIDATED = "VALIDATED"


class CalibrationLevel(StrEnum):
    SPECIES = "species"
    VARIETY = "variety"
    PLOT = "plot"
    ENVIRONMENT = "environment"


class CalibrationPriority(StrEnum):
    PHENOLOGY = "phenology"
    GROWTH = "growth"
    WATER = "water"
    STRESS = "stress"
    PRODUCTION = "production"


KNOWN_VARIETIES = {
    ("tomato", "RAF", "plot_12010"),
    ("pepper", "Lamuyo", "plot_40811"),
    ("grape", "Monastrell", "plot_30412"),
    ("plum", "Suplum 26", "plot_14705"),
}


@dataclass(frozen=True, slots=True)
class ObservationAudit:
    crop: str
    variety: str | None
    plot: str | None
    available_files: tuple[str, ...]
    observation_count: int
    variables: tuple[str, ...]
    status: ScientificStatus
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CalibrabilityRecord:
    parameter_id: str
    crop: str
    variety: str | None
    plot: str | None
    stage: str | None
    level: CalibrationLevel
    priority: CalibrationPriority
    prior_value: Any
    minimum: float | None
    maximum: float | None
    unit: str | None
    source: str
    evidence_level: str
    confidence: str
    calibration_allowed: bool
    required_observations: str
    calibration_status: ScientificStatus
    why_calibrate: str
    confounds: tuple[str, ...]
    identifiability_risk: str


@dataclass(frozen=True, slots=True)
class CropCalibrationProtocol:
    crop: str
    variety: str | None
    plot: str | None
    environment_type: str
    observation_audit: ObservationAudit
    matrix: tuple[CalibrabilityRecord, ...]
    status: ScientificStatus
    warnings: tuple[str, ...]

    def parameter_set(self) -> ParameterSet:
        parameters = []
        for record in self.matrix:
            if not record.calibration_allowed or record.minimum is None or record.maximum is None or record.prior_value is None:
                continue
            value = float(record.prior_value)
            parameters.append(CalibrationParameter(record.parameter_id, value, value, record.minimum, record.maximum, max((record.maximum - record.minimum) / 10, 1e-9), record.unit or "", "engineering_default" if record.source == "engineering_default" else "literature", "candidate_for_calibration", True))
        return ParameterSet(tuple(parameters), name=f"{self.crop}-{self.variety or 'generic'}-{self.environment_type}")

    def to_report(self) -> str:
        lines = [f"# Crop Calibration Protocol: {self.crop} / {self.variety or 'generic'}", "", f"- scientific_status: `{self.status.value}`", f"- environment: `{self.environment_type}`", f"- observations: `{self.observation_audit.observation_count}`", "", "## Matrix", "", "| Parameter | Level | Priority | Prior | Range | Unit | Status | Risk |", "|---|---|---|---|---|---|---|---|"]
        for record in self.matrix:
            range_text = f"{record.minimum}..{record.maximum}" if record.minimum is not None else "none"
            lines.append(f"| {record.parameter_id} | {record.level.value} | {record.priority.value} | {record.prior_value} | {range_text} | {record.unit or 'none'} | {record.calibration_status.value} | {record.identifiability_risk} |")
        lines.extend(["", "## Warnings", ""] + [f"- {warning}" for warning in self.warnings])
        lines.extend(["", "## Observation limitations", ""] + [f"- {item}" for item in self.observation_audit.limitations])
        return "\n".join(lines) + "\n"


def audit_observations(root: str | Path, crop: str, variety: str | None, plot: str | None) -> ObservationAudit:
    root = Path(root)
    files = tuple(sorted(str(path.relative_to(root)) for path in (root / "data").rglob("*") if path.is_file())) if (root / "data").exists() else ()
    agronomic = tuple(path for path in files if any(token in path.lower() for token in ("lai", "biomass", "phenology", "yield", "vwc", "irrigation", "fertil")))
    if not agronomic:
        return ObservationAudit(crop, variety, plot, files, 0, (), ScientificStatus.INSUFFICIENT_DATA, ("no field LAI, biomass, phenology, VWC, irrigation, fertilizer, stress or yield observations found", "weather CSV is forcing data, not crop observation data", "crop_phenology.csv contains external evidence, not local observations"))
    return ObservationAudit(crop, variety, plot, files, 0, (), ScientificStatus.INSUFFICIENT_DATA, ("observation parser is not configured for a verified field dataset",))


def _priority(record: ParameterRecord) -> CalibrationPriority:
    name = record.name.lower()
    if any(token in name for token in ("tbase", "tupper", "gdd", "chill", "thermal", "maturity")):
        return CalibrationPriority.PHENOLOGY
    if any(token in name for token in ("lai", "rue", "biomass", "senescence")):
        return CalibrationPriority.GROWTH
    if any(token in name for token in ("vwc", "water", "root", "drainage")):
        return CalibrationPriority.WATER
    if any(token in name for token in ("stress", "vpd", "radiation", "heat", "frost")):
        return CalibrationPriority.STRESS
    return CalibrationPriority.PRODUCTION


def build_protocol(root: str | Path, registry: ParameterRegistry, crop: str, variety: str | None = None, plot: str | None = None, environment_type: str = "OUTDOOR") -> CropCalibrationProtocol:
    if crop not in {"tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple"}:
        raise CropCalibrationError(f"unknown crop: {crop}")
    audit = audit_observations(root, crop, variety, plot)
    matrix = []
    for parameter in registry.records:
        if parameter.crop not in {None, crop}:
            continue
        level = CalibrationLevel.VARIETY if parameter.variety == variety and variety else CalibrationLevel.SPECIES
        status = ScientificStatus.CALIBRATION_READY if audit.observation_count > 0 and parameter.calibration_allowed else ScientificStatus.INSUFFICIENT_DATA
        matrix.append(CalibrabilityRecord(parameter.parameter_id, crop, variety, plot, parameter.phenological_stage, level, _priority(parameter), parameter.value, parameter.minimum, parameter.maximum, parameter.unit, parameter.source_type, parameter.evidence_level, parameter.confidence, parameter.calibration_allowed, parameter.observational_data_required, status, f"constrain {parameter.name} with observations", ("RUE/LAI correlation", "soil/plant stress confounding"), "HIGH" if parameter.name.lower() in {"rue", "root_depth_m", "thermal_upper_temperature_c"} else "MODERATE"))
    warnings = []
    if variety and (crop, variety, plot) not in KNOWN_VARIETIES:
        warnings.append("variety/plot is not in the known project inventory; no variety-specific prior is inferred")
    if not audit.observation_count:
        warnings.append("INSUFFICIENT_DATA: no real agronomic observations available")
    warnings.extend(["LITERATURE_PRIOR_NOT_CALIBRATED", "synthetic calibration demonstrations are not crop validation"])
    status = ScientificStatus.INSUFFICIENT_DATA if not audit.observation_count else ScientificStatus.CALIBRATION_READY
    return CropCalibrationProtocol(crop, variety, plot, environment_type, audit, tuple(matrix), status, tuple(warnings))


@dataclass(frozen=True, slots=True)
class CropCalibrationReport:
    protocol: CropCalibrationProtocol
    result: CalibrationResult | None
    validation_status: ScientificStatus
    warnings: tuple[str, ...]
    boundary_parameters: tuple[str, ...] = ()
    overfitting_risk: str = "UNKNOWN"

    def to_markdown(self) -> str:
        text = self.protocol.to_report()
        result_status = self.result.status.value if self.result else "NOT_RUN"
        return text + "\n## Calibration result\n\n" + f"- result: `{result_status}`\n- validation: `{self.validation_status.value}`\n- overfitting_risk: `{self.overfitting_risk}`\n- boundary_parameters: `{', '.join(self.boundary_parameters) or 'none'}`\n" + "\n".join(f"- {warning}" for warning in self.warnings) + "\n"


def synthetic_calibration_report(protocol: CropCalibrationProtocol, runner_function: Callable[..., tuple[SimulationPoint, ...]], observations: ObservationDataset) -> CropCalibrationReport:
    parameters = protocol.parameter_set()
    if not parameters.values:
        return CropCalibrationReport(protocol, None, ScientificStatus.INSUFFICIENT_DATA, protocol.warnings)
    start = observations.observations[0].timestamp
    end = max(observations.observations[-1].timestamp, start + __import__("datetime").timedelta(days=1))
    case = CalibrationCase(protocol.crop, protocol.variety, protocol.plot, start, end, observations, parameters)
    result = GridSearchCalibrator(FunctionSimulationRunner(runner_function), CalibrationObjective({variable: 1.0 for variable in {item.variable for item in observations.observations}}), 100).fit(case)
    boundary = tuple(parameter.parameter_id for parameter in result.calibrated_parameters.values if parameter.value in {parameter.minimum, parameter.maximum}) if result.calibrated_parameters else ()
    warnings = protocol.warnings + (("BOUNDARY_SOLUTION",) if boundary else ())
    return CropCalibrationReport(protocol, result, ScientificStatus.CALIBRATED if result.status == CalibrationStatus.SUCCESS else ScientificStatus.INSUFFICIENT_DATA, warnings, boundary, "MODERATE")