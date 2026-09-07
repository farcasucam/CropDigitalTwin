"""Optional eppy-based generation of deterministic greenhouse IDF variants.

This module configures IDF files only. It does not run EnergyPlus or participate
in the Phase 5.7.1 microclimate timestep.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class EppyStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    INCOMPATIBLE = "INCOMPATIBLE"
    MISCONFIGURED = "MISCONFIGURED"


@dataclass(frozen=True, slots=True)
class EppyAvailability:
    status: EppyStatus
    version: str | None = None
    detail: str = ""


def detect_eppy() -> EppyAvailability:
    """Return an explicit eppy state without importing it into the core domain."""
    try:
        module = importlib.import_module("eppy")
    except ModuleNotFoundError:
        return EppyAvailability(EppyStatus.UNAVAILABLE, detail="eppy is not installed")
    except Exception as exc:
        return EppyAvailability(EppyStatus.INCOMPATIBLE, detail=f"eppy import failed: {exc}")
    version = getattr(module, "__version__", None)
    if version is None:
        try:
            from importlib.metadata import version as package_version

            version = package_version("eppy")
        except Exception:
            version = None
    return EppyAvailability(EppyStatus.AVAILABLE, version=version)


class EppyGreenhouseError(RuntimeError):
    """Raised for an unavailable, invalid, or incorrectly configured builder."""


@dataclass(frozen=True, slots=True)
class GreenhouseVariant:
    name: str
    description: str
    source_configuration: Mapping[str, Any] = field(default_factory=dict)
    modifications: Mapping[str, Any] = field(default_factory=dict)
    generated_idf_path: Path | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("variant name is required")
        if not self.description:
            raise ValueError("variant description is required")

    @property
    def configuration_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "source_configuration": _json_value(self.source_configuration),
            "modifications": _json_value(self.modifications),
        }

    @property
    def configuration_hash(self) -> str:
        payload = json.dumps(self.configuration_payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        result = dict(self.configuration_payload)
        result["configuration_hash"] = self.configuration_hash
        result["generated_idf_path"] = str(self.generated_idf_path) if self.generated_idf_path else None
        return result


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


VARIANT_DEFINITIONS: dict[str, dict[str, Any]] = {
    "baseline": {"description": "Engineering baseline greenhouse IDF", "modifications": {}},
    "high_ventilation": {"description": "High design ventilation rate", "modifications": {"ventilation_ach": 12.0}},
    "low_ventilation": {"description": "Low design ventilation rate", "modifications": {"ventilation_ach": 1.0}},
    "high_solar_transmission": {"description": "High solar heat gain through glazing", "modifications": {"solar_transmission": 0.85}},
    "low_solar_transmission": {"description": "Low solar heat gain through glazing", "modifications": {"solar_transmission": 0.55}},
    "shading": {"description": "Fixed partial interior shading", "modifications": {"shading_fraction": 0.5}},
    "high_heating": {"description": "Higher ideal-load heating supply temperature", "modifications": {"heating_supply_temperature_c": 45.0}},
    "low_heating": {"description": "Lower ideal-load heating supply temperature", "modifications": {"heating_supply_temperature_c": 35.0}},
    "high_cooling": {"description": "Higher ideal-load cooling capability", "modifications": {"cooling_supply_temperature_c": 12.0}},
    "low_cooling": {"description": "Lower ideal-load cooling capability", "modifications": {"cooling_supply_temperature_c": 18.0}},
}

PARAMETER_REGISTRY_IDS = {
    "solar_transmission": "greenhouse.cover_transmission",
}


class EppyGreenhouseBuilder:
    """Load a template with eppy, apply whitelisted edits, validate, and save."""

    _FIELD_MAP = {
        "ventilation_ach": ("ZoneVentilation:DesignFlowRate", "Greenhouse Natural Ventilation", "Air_Changes_per_Hour"),
        "solar_transmission": ("WindowMaterial:SimpleGlazingSystem", "Greenhouse Glazing", "Solar_Heat_Gain_Coefficient"),
        "heating_supply_temperature_c": ("ZoneHVAC:IdealLoadsAirSystem", "Greenhouse Ideal Loads", "Maximum_Heating_Supply_Air_Temperature"),
        "cooling_supply_temperature_c": ("ZoneHVAC:IdealLoadsAirSystem", "Greenhouse Ideal Loads", "Minimum_Cooling_Supply_Air_Temperature"),
        "shading_fraction": ("Schedule:Constant", "Greenhouse Shade Fraction", "Hourly_Value"),
    }

    def __init__(self, template_path: str | Path | None = None, output_dir: str | Path | None = None, idd_path: str | Path | None = None) -> None:
        root = Path(__file__).resolve().parents[3]
        self.template_path = Path(template_path) if template_path else root / "templates" / "greenhouse" / "greenhouse_template.idf"
        self.output_dir = Path(output_dir) if output_dir else root / "data" / "greenhouse" / "variants"
        configured_idd = idd_path or os.environ.get("ENERGYPLUS_IDD")
        self.idd_path = Path(configured_idd) if configured_idd else None

    def status(self) -> EppyAvailability:
        availability = detect_eppy()
        if availability.status is not EppyStatus.AVAILABLE:
            return availability
        if self.idd_path is None or not self.idd_path.is_file():
            return EppyAvailability(EppyStatus.MISCONFIGURED, availability.version, "EnergyPlus IDD is required; set ENERGYPLUS_IDD or idd_path")
        if not self.template_path.is_file():
            return EppyAvailability(EppyStatus.MISCONFIGURED, availability.version, f"template not found: {self.template_path}")
        return availability

    def load_template(self) -> Any:
        state = self.status()
        if state.status is not EppyStatus.AVAILABLE:
            raise EppyGreenhouseError(f"eppy builder is {state.status.value}: {state.detail}")
        try:
            from eppy.modeleditor import IDF

            IDF.setiddname(str(self.idd_path))
            return IDF(str(self.template_path))
        except Exception as exc:
            raise EppyGreenhouseError(f"could not load IDF template: {exc}") from exc

    def build(self, variant: GreenhouseVariant | str, *, output_dir: str | Path | None = None) -> GreenhouseVariant:
        if isinstance(variant, str):
            try:
                definition = VARIANT_DEFINITIONS[variant]
            except KeyError as exc:
                raise ValueError(f"unknown greenhouse variant: {variant}") from exc
            variant = GreenhouseVariant(
                variant,
                definition["description"],
                source_configuration={"parameter_registry_ids": PARAMETER_REGISTRY_IDS},
                modifications=definition["modifications"],
            )
        unknown = set(variant.modifications) - set(self._FIELD_MAP)
        if unknown:
            raise ValueError(f"unsupported greenhouse modifications: {sorted(unknown)}")
        self._validate_values(variant.modifications)
        idf = self.load_template()
        for parameter, value in variant.modifications.items():
            object_type, object_name, field_name = self._FIELD_MAP[parameter]
            objects = idf.idfobjects[object_type]
            matches = [item for item in objects if str(getattr(item, "Name", "")) == object_name]
            if not matches:
                raise EppyGreenhouseError(f"required object not found: {object_type}/{object_name}")
            setattr(matches[0], field_name, value)
        self._validate_objects(idf, variant.modifications)
        destination = Path(output_dir) if output_dir else self.output_dir
        destination.mkdir(parents=True, exist_ok=True)
        output_path = destination / f"{variant.name}-{variant.configuration_hash[:12]}.idf"
        idf.saveas(str(output_path))
        return GreenhouseVariant(variant.name, variant.description, variant.source_configuration, variant.modifications, output_path)

    @staticmethod
    def _validate_values(modifications: Mapping[str, Any]) -> None:
        ranges = {"ventilation_ach": (0.0, 100.0), "solar_transmission": (0.0, 1.0), "heating_supply_temperature_c": (0.0, 100.0), "cooling_supply_temperature_c": (0.0, 100.0), "shading_fraction": (0.0, 1.0)}
        for name, value in modifications.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not ranges[name][0] <= value <= ranges[name][1]:
                raise ValueError(f"invalid value for {name}: {value!r}")

    @staticmethod
    def _validate_objects(idf: Any, modifications: Mapping[str, Any]) -> None:
        for parameter in modifications:
            object_type, object_name, field_name = EppyGreenhouseBuilder._FIELD_MAP[parameter]
            objects = idf.idfobjects[object_type]
            matches = [item for item in objects if str(getattr(item, "Name", "")) == object_name]
            if not matches or getattr(matches[0], field_name, None) is None:
                raise EppyGreenhouseError(f"modified object could not be validated: {object_type}/{object_name}.{field_name}")
