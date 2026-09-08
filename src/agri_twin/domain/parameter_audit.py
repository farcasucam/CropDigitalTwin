"""Scientific provenance registry and deterministic parameter audit."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable


class ParameterAuditError(ValueError):
    """Raised when a parameter registry entry violates its contract."""


SOURCE_TYPES = {"literature", "project_data", "measured_data", "derived", "engineering_default", "calibrated", "unknown"}
EVIDENCE_LEVELS = {"high", "medium", "low", "none"}
CALIBRATION_STATUSES = {"not_calibrated", "candidate_for_calibration", "calibrated", "fixed", "not_applicable"}
CATEGORIES = {"biological", "environmental", "soil", "management", "greenhouse", "engineering_default"}
SEVEN_CROPS = {"tomato", "lettuce", "pepper", "grape", "peach", "plum", "apple"}
STAGES = {"establishment", "vegetative_growth", "yield_maturation", "post_harvest_dormancy"}


@dataclass(frozen=True, slots=True)
class ParameterRecord:
    parameter_id: str
    name: str
    description: str
    category: str
    subsystem: str
    crop: str | None
    variety: str | None
    phenological_stage: str | None
    unit: str | None
    value: Any
    minimum: float | None
    maximum: float | None
    source_type: str
    source_reference: str | None
    source_detail: str
    evidence_level: str
    confidence: str
    calibration_status: str
    calibration_allowed: bool
    observational_data_required: str
    notes: str = ""
    used_by: str = ""

    def __post_init__(self) -> None:
        if not self.parameter_id or not self.name or not self.description:
            raise ParameterAuditError("parameter identity and description are required")
        if self.category not in CATEGORIES:
            raise ParameterAuditError(f"invalid parameter category: {self.category}")
        if self.source_type not in SOURCE_TYPES:
            raise ParameterAuditError(f"invalid source type: {self.source_type}")
        if self.evidence_level not in EVIDENCE_LEVELS:
            raise ParameterAuditError(f"invalid evidence level: {self.evidence_level}")
        if self.calibration_status not in CALIBRATION_STATUSES:
            raise ParameterAuditError(f"invalid calibration status: {self.calibration_status}")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ParameterAuditError(f"invalid range: {self.parameter_id}")
        if self.value is not None and isinstance(self.value, (int, float)) and not isinstance(self.value, bool):
            if not math.isfinite(float(self.value)):
                raise ParameterAuditError(f"non-finite value: {self.parameter_id}")
            if self.minimum is not None and self.value < self.minimum or self.maximum is not None and self.value > self.maximum:
                raise ParameterAuditError(f"value outside range: {self.parameter_id}")
        if self.source_type == "literature" and not self.source_reference:
            raise ParameterAuditError(f"literature parameter requires reference: {self.parameter_id}")
        if self.source_type == "calibrated" and self.calibration_status != "calibrated":
            raise ParameterAuditError(f"calibrated source requires calibrated status: {self.parameter_id}")
        if self.calibration_status == "calibrated" and self.source_type != "calibrated":
            raise ParameterAuditError(f"calibrated status requires calibrated source: {self.parameter_id}")
        if self.crop is not None and self.crop not in SEVEN_CROPS:
            raise ParameterAuditError(f"unknown crop: {self.crop}")
        if self.phenological_stage is not None and self.phenological_stage not in STAGES and self.phenological_stage != "UNKNOWN":
            raise ParameterAuditError(f"unknown phenological stage: {self.phenological_stage}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ParameterAudit:
    records: tuple[ParameterRecord, ...]
    errors: tuple[str, ...] = ()

    @property
    def summary(self) -> dict[str, int]:
        return {
            "total_parameters": len(self.records),
            "literature_parameters": sum(r.source_type == "literature" for r in self.records),
            "project_data_parameters": sum(r.source_type == "project_data" for r in self.records),
            "measured_parameters": sum(r.source_type == "measured_data" for r in self.records),
            "derived_parameters": sum(r.source_type == "derived" for r in self.records),
            "engineering_defaults": sum(r.source_type == "engineering_default" for r in self.records),
            "unknown_parameters": sum(r.source_type == "unknown" for r in self.records),
            "calibrated_parameters": sum(r.calibration_status == "calibrated" for r in self.records),
            "calibration_candidates": sum(r.calibration_status == "candidate_for_calibration" for r in self.records),
        }

    @property
    def scientific_debt(self) -> tuple[ParameterRecord, ...]:
        return tuple(r for r in self.records if r.source_type in {"unknown", "engineering_default"} or r.evidence_level in {"low", "none"} or r.calibration_status == "candidate_for_calibration")

    def validate(self) -> tuple[str, ...]:
        errors = list(self.errors)
        seen: set[str] = set()
        for record in self.records:
            if record.parameter_id in seen:
                errors.append(f"duplicate parameter_id: {record.parameter_id}")
            seen.add(record.parameter_id)
            if record.unit is None:
                errors.append(f"missing unit: {record.parameter_id}")
            if record.source_type == "engineering_default" and record.evidence_level == "high":
                errors.append(f"engineering default cannot have high evidence: {record.parameter_id}")
        return tuple(sorted(set(errors)))

    def to_markdown(self) -> str:
        lines = ["# Parameter Audit Report", "", "## Summary", ""]
        for key, value in self.summary.items():
            lines.append(f"- `{key}`: {value}")
        lines.extend(["", "## By crop", ""])
        for crop in sorted(SEVEN_CROPS):
            lines.append(f"- `{crop}`: {sum(r.crop == crop for r in self.records)} parameters")
        lines.extend(["", "## Scientific debt", "", "| ID | Name | Source | Evidence | Status | Scope | Notes |", "|---|---|---|---|---|---|---|"])
        for record in sorted(self.scientific_debt, key=lambda item: item.parameter_id):
            scope = "/".join(value for value in (record.crop, record.variety, record.phenological_stage) if value) or "global"
            lines.append(f"| {record.parameter_id} | {record.name} | {record.source_type} | {record.evidence_level} | {record.calibration_status} | {scope} | {record.notes} |")
        lines.extend(["", "## Validation", "", "- status: " + ("PASS" if not self.validate() else "FAIL"), "- errors: " + ("none" if not self.validate() else "; ".join(self.validate()))])
        return "\n".join(lines) + "\n"


class ParameterRegistry:
    """Build a registry from the active JSON/CSV repository files."""

    def __init__(self, records: Iterable[ParameterRecord]) -> None:
        self.records = tuple(records)

    @classmethod
    def from_repository(cls, root: str | Path) -> "ParameterRegistry":
        root = Path(root)
        records: list[ParameterRecord] = []
        crop_payload = json.loads((root / "src" / "crop_config.json").read_text(encoding="utf-8"))
        for crop, definition in crop_payload["crops"].items():
            for stage, stage_config in definition["stages"].items():
                records.extend(cls._flatten(stage_config, f"crop.{crop}.{stage}", crop, stage, "crop_config", "environmental", "unknown", "", "crop stage thresholds have no source metadata"))
        growth_payload = json.loads((root / "src" / "growth_model_config.json").read_text(encoding="utf-8"))
        records.extend(cls._growth_records(growth_payload))
        records.extend(cls._phenology_records(root / "src" / "crop_phenology.csv"))
        farm = json.loads((root / "src" / "farm_config.json").read_text(encoding="utf-8"))
        for plot in farm["plots"]:
            records.append(cls._record(f"plot.{plot['id']}.area_ha", "plot area", "plot area", "management", "farm_config", plot["crop_key"], plot.get("crop_variety"), None, "ha", plot["area_ha"], 0, None, "project_data", "", "plot configuration", "none", "medium", "not_applicable", False, "plot inventory"))
            records.append(cls._record(f"plot.{plot['id']}.soil_type", "soil type", "configured plot soil", "soil", "farm_config", plot["crop_key"], plot.get("crop_variety"), None, "category", plot.get("soil_type"), None, None, "project_data", "", "plot configuration", "none", "medium", "candidate_for_calibration", True, "soil sampling"))
        for actuator, descriptor in growth_payload.get("actuator_contract", {}).items():
            records.append(cls._record(f"actuator.{actuator}.capacity", f"{actuator} capacity", "actuator capacity", "greenhouse" if actuator != "irrigation" else "management", "actuator_contract", None, None, None, descriptor.get("unit"), descriptor.get("capacity"), 0, None, "unknown", None, "growth_model_config:actuator_contract", "none", "none", "candidate_for_calibration", True, "site inventory and actuator tests"))
        records.extend(cls._code_defaults())
        return cls(records)

    @staticmethod
    def _record(parameter_id: str, name: str, description: str, category: str, subsystem: str, crop: str | None, variety: str | None, stage: str | None, unit: str | None, value: Any, minimum: float | None, maximum: float | None, source_type: str, reference: str | None, detail: str, evidence: str, confidence: str, calibration: str, allowed: bool, observations: str, notes: str = "", used_by: str = "") -> ParameterRecord:
        consumers = {"crop_config": "CropEngine; ClimateStressEngine", "growth_model_config": "Growth configuration consumers", "farm_config": "CropDigitalTwinOrchestrator", "crop_phenology.csv": "PhenologyEngine evidence", "runtime_code": detail, "actuator_contract": "GreenhouseMicroclimateEngine"}
        return ParameterRecord(parameter_id, name, description, category, subsystem, crop, variety, stage, unit, value, minimum, maximum, source_type, reference or None, detail, evidence or "none", confidence or "low", calibration, allowed, observations, notes, used_by or consumers.get(subsystem, subsystem))

    @classmethod
    def _flatten(cls, payload: dict[str, Any], prefix: str, crop: str, stage: str, subsystem: str, category: str, source_type: str, reference: str, notes: str) -> list[ParameterRecord]:
        records = []
        for key, value in payload.items():
            if isinstance(value, dict):
                records.extend(cls._flatten(value, f"{prefix}.{key}", crop, stage, subsystem, category, source_type, reference, notes))
            elif key != "stage_name" and isinstance(value, (int, float)) and not isinstance(value, bool):
                unit = {"min_temp_c": "degC", "max_temp_c": "degC", "critical_heat_c": "degC", "critical_frost_c": "degC", "optimal_min_kpa": "kPa", "optimal_max_kpa": "kPa", "stress_max_kpa": "kPa", "optimal_max_w_m2": "W_m-2", "photoinhibition_w_m2": "W_m-2", "field_capacity": "m3_m-3", "optimal_min": "m3_m-3", "moderate_min": "m3_m-3", "wilting_point": "m3_m-3", "preventive_hours_before_peak": "h", "shading_reduction_pct": "%", "target_vwc_after_irrigation": "m3_m-3"}.get(key)
                records.append(cls._record(f"{prefix}.{key}", key, f"Configured {key}", category, subsystem, crop, None, stage, unit, value, None, None, source_type, reference, f"{subsystem}:{prefix}", "none", "low", "candidate_for_calibration", True, "stage observations or sensor data", notes))
        return records

    @classmethod
    def _growth_records(cls, payload: dict[str, Any]) -> list[ParameterRecord]:
        records = []
        for name, descriptor in payload["crop_parameter_contract"].items():
            records.append(cls._record(f"contract.{name}", name, f"Growth contract parameter {name}", "biological", "growth_model_config", None, None, None, descriptor.get("unit"), descriptor.get("default_value"), *(descriptor.get("reasonable_range") or [None, None]), "unknown", None, "growth_model_config:crop_parameter_contract", "none", "none", "candidate_for_calibration", True, "crop, stage, variety and plot observations", "contract currently has no operational default"))
        for soil, values in payload["soil_profiles"].items():
            for name, value in values.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    unit = {"field_capacity_vwc": "m3_m-3", "wilting_point_vwc": "m3_m-3", "available_water_capacity_mm_m": "mm_m-1"}.get(name)
                    records.append(cls._record(f"soil.{soil}.{name}", name, f"Soil profile {name}", "soil", "growth_model_config", None, None, None, unit, value, None, None, "engineering_default", None, f"soil_profiles.{soil}", "none", "low", "candidate_for_calibration", True, "soil sampling and hydraulic tests"))
        for mode, values in payload["environment_profiles"].items():
            for name, value in values.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    unit = {"solar_transmission_fraction": "fraction", "thermal_mass_kJ_K-1": "kJ_K-1"}.get(name, name)
                    records.append(cls._record(f"greenhouse.{mode}.{name}", name, f"Greenhouse {name}", "greenhouse", "growth_model_config", None, None, None, unit, value, 0, 1 if "fraction" in unit else None, "engineering_default", None, f"environment_profiles.{mode}", "none", "low", "candidate_for_calibration", True, "site inventory and actuator tests"))
        return records

    @classmethod
    def _phenology_records(cls, path: Path) -> list[ParameterRecord]:
        records = []
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                value = row["value"] or None
                parsed: Any = float(value) if value is not None else None
                reference = row["url"] or row["doi"] or None
                status = "candidate_for_calibration" if row["activation_status"] == "NOT_ACTIVATED" else "not_calibrated"
                external_event = row["stage"] if row["stage"] not in {"UNKNOWN", *STAGES} else ""
                records.append(cls._record(f"evidence.{row['id']}", row["parameter"], row["notes"] or row["parameter"], "biological", "crop_phenology.csv", row["crop"], row["reference_cultivar"] or None, row["stage"] if row["stage"] in STAGES else None, row["unit"] or None, parsed, float(row["minimum"]) if row["minimum"] else None, float(row["maximum"]) if row["maximum"] else None, "literature", reference, row["source_id"], {"PRIMARY_EXPERIMENT": "high", "PEER_REVIEWED_REVIEW": "high", "INSTITUTIONAL": "medium"}.get(row["evidence_level"], "low"), row["confidence"].lower(), status, True, "phenology event dates, cultivar and local weather", f"external event {external_event or 'not mapped'}; evidence retained; not activated", "PhenologyEngine (future activation)"))
        return records

    @classmethod
    def _code_defaults(cls) -> list[ParameterRecord]:
        constants = [
            ("radiation.par_fraction", "PAR fraction of shortwave", "fraction", 0.48, "radiation_growth.py:PAR_FRACTION_OF_SHORTWAVE"),
            ("radiation.extinction_coefficient", "Beer-Lambert extinction coefficient", "dimensionless", 0.6, "radiation_growth.py:APPROXIMATE_RADIATION_PROFILES"),
            ("radiation.rue", "radiation use efficiency", "g_DM_MJ_PAR-1", 2.0, "radiation_growth.py:APPROXIMATE_RADIATION_PROFILES"),
            ("radiation.sla", "specific leaf area", "m2_g_DM-1", 0.02, "radiation_growth.py:APPROXIMATE_RADIATION_PROFILES"),
            ("greenhouse.cover_transmission", "default greenhouse transmission", "fraction", 0.78, "greenhouse.py:PROFILES"),
            ("greenhouse.thermal_exchange_area", "feedback thermal exchange normalization", "m2", 1.0, "greenhouse.py:GreenhouseConfiguration"),
            ("feedback.latent_heat_vaporization", "latent heat of vaporization", "J_kg-1", 2450000.0, "crop_greenhouse_feedback.py:CropGreenhouseFeedbackConfiguration"),
            ("feedback.sensible_heat_transfer", "leaf-air sensible heat coefficient", "W_m-2_K-1", 5.0, "crop_greenhouse_feedback.py:CropGreenhouseFeedbackConfiguration"),
            ("feedback.leaf_air_delta", "radiation to leaf-air delta proxy", "K_m2_W-1", 0.002, "crop_greenhouse_feedback.py:CropGreenhouseFeedbackConfiguration"),
            ("feedback.co2_carbon_fraction", "dry matter carbon fraction", "fraction", 0.45, "crop_greenhouse_feedback.py:CropGreenhouseFeedbackConfiguration"),
            ("feedback.air_density", "greenhouse air density", "kg_m-3", 1.2, "crop_greenhouse_feedback.py:CropGreenhouseFeedbackConfiguration"),
            ("feedback.air_volume", "greenhouse air volume", "m3", 1000.0, "crop_greenhouse_feedback.py:CropGreenhouseFeedbackConfiguration"),
            ("feedback.relaxation_alpha", "fixed-point relaxation factor", "fraction", 0.4, "crop_greenhouse_feedback.py:CropGreenhouseFeedbackConfiguration"),
            ("water.et_temperature_range", "ET approximation temperature range", "degC", 10.0, "water_balance.py:_et0_mm"),
        ]
        return [cls._record(parameter_id, name, "Hardcoded engineering baseline", "engineering_default", "runtime_code", None, None, None, unit, value, 0, None, "engineering_default", None, detail, "none", "low", "candidate_for_calibration", True, "radiation, biomass, site and climate observations", "must not be presented as biological validation") for parameter_id, name, unit, value, detail in constants]

    def audit(self) -> ParameterAudit:
        audit = ParameterAudit(tuple(sorted(self.records, key=lambda record: record.parameter_id)))
        return replace(audit, errors=audit.validate())

    def get(self, parameter_id: str) -> ParameterRecord:
        for record in self.records:
            if record.parameter_id == parameter_id:
                return record
        raise ParameterAuditError(f"parameter not found: {parameter_id}")

    def write_report(self, path: str | Path) -> ParameterAudit:
        audit = self.audit()
        Path(path).write_text(audit.to_markdown(), encoding="utf-8")
        return audit