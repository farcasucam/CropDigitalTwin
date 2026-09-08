"""Traceable real-observation ingestion without calibration side effects."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable, Mapping

from agri_twin.domain.calibration import DatasetRole, Observation, ObservationDataset, ObservationResolution
from agri_twin.domain.parameter_audit import ParameterRegistry


class ObservationIngestionError(ValueError):
    """Raised for invalid ingestion configuration or unsupported data."""


class QualityFlag(StrEnum):
    VALID = "VALID"
    MISSING = "MISSING"
    INVALID = "INVALID"
    SUSPECT = "SUSPECT"
    ESTIMATED = "ESTIMATED"
    DUPLICATE = "DUPLICATE"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    UNIT_ERROR = "UNIT_ERROR"


class ObservationSourceType(StrEnum):
    MEASURED = "measured_data"
    DERIVED = "derived"
    SYNTHETIC_TEST = "synthetic_test_data"
    FORCING = "forcing"


class Environment(StrEnum):
    OUTDOOR = "OUTDOOR"
    GREENHOUSE = "GREENHOUSE"
    UNKNOWN = "UNKNOWN"


class ReadinessStatus(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    INVALID = "INVALID"


class ParameterReadinessStatus(StrEnum):
    NOT_READY = "NOT_READY"
    CANDIDATE = "CANDIDATE"
    READY_FOR_CALIBRATION = "READY_FOR_CALIBRATION"


OBSERVABLE_VARIABLES = frozenset({
    "emergence", "transplant", "flowering", "fruit_set", "veraison", "maturity", "harvest", "budburst", "dormancy_release",
    "lai", "biomass", "plant_height", "canopy_cover", "fruit_weight", "fruit_number",
    "soil_water_content", "vwc", "soil_moisture", "irrigation", "transpiration",
    "air_temperature", "relative_humidity", "vpd", "solar_radiation", "par", "co2", "leaf_temperature",
    "yield", "fruit_mass", "fruit_count",
})

VARIABLE_ALIASES = {
    "LAI": "lai", "leaf_area_index": "lai", "temperature": "air_temperature", "air_temperature_c": "air_temperature",
    "relative_humidity_pct": "relative_humidity", "rh": "relative_humidity", "VPD": "vpd", "solar_radiation_w_m2": "solar_radiation",
    "CO2": "co2", "co2_ppm": "co2", "soil_water": "soil_water_content", "soil_water_vwc": "vwc",
    "biomass_total": "biomass", "yield_kg": "yield", "fruit_mass": "fruit_weight",
}

UNIT_ALIASES = {
    "degc": "degC", "°c": "degC", "c": "degC", "percent": "%", "pct": "%", "fraction": "fraction",
    "w/m2": "W_m-2", "w m-2": "W_m-2", "wm-2": "W_m-2", "kpa": "kPa", "ppm": "ppm",
    "m2 m-2": "m2_m-2", "m2/m2": "m2_m-2", "m3/m3": "m3_m-3", "mm/h": "mm_h-1", "mm h-1": "mm_h-1",
    "mol m-2 s-1": "mol_m-2_s-1", "umol m-2 s-1": "umol_m-2_s-1", "g/m2": "g_m-2", "g m-2": "g_m-2",
    "kg/m2": "kg_m-2", "kg m-2": "kg_m-2", "kg": "kg", "t/ha": "t_ha-1",
}

CANONICAL_UNITS = {
    "air_temperature": "degC", "leaf_temperature": "degC", "relative_humidity": "%", "vpd": "kPa",
    "solar_radiation": "W_m-2", "par": "mol_m-2_s-1", "lai": "m2_m-2", "biomass": "g_m-2",
    "soil_water_content": "m3_m-3", "vwc": "m3_m-3", "soil_moisture": "m3_m-3", "irrigation": "mm",
    "transpiration": "mm_h-1", "co2": "ppm", "yield": "kg_m-2", "fruit_weight": "g", "fruit_mass": "g",
    "plant_height": "m", "canopy_cover": "fraction", "fruit_number": "count", "fruit_count": "count",
}

_MISSING = {"", "na", "n/a", "null", "none", "-999", "9999"}


@dataclass(frozen=True, slots=True)
class ObservationQC:
    row_number: int
    quality: QualityFlag
    message: str
    variable: str | None = None


@dataclass(frozen=True, slots=True)
class DatasetReadiness:
    status: ReadinessStatus
    n_observations: int
    n_valid: int
    n_invalid: int
    n_missing: int
    n_duplicates: int
    n_variables: int
    n_plots: int
    n_crops: int
    n_varieties: int
    date_start: datetime | None
    date_end: datetime | None
    messages: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ParameterReadiness:
    parameter_id: str
    required_observations: tuple[str, ...]
    available_observations: tuple[str, ...]
    n_valid: int
    temporal_coverage: tuple[datetime, datetime] | None
    spatial_coverage: tuple[str, ...]
    identifiability: str
    status: ParameterReadinessStatus


@dataclass(frozen=True, slots=True)
class ObservationIngestionResult:
    dataset: ObservationDataset | None
    readiness: DatasetReadiness
    qc: tuple[ObservationQC, ...]
    source: str
    source_type: ObservationSourceType
    original_filename: str | None


def _canonical_variable(value: str) -> str:
    key = value.strip()
    return VARIABLE_ALIASES.get(key, key.lower())


def _canonical_unit(value: str) -> str:
    key = value.strip().lower()
    return UNIT_ALIASES.get(key, value.strip())


def _timestamp(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ObservationIngestionError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _numeric(value: Any) -> float:
    if value is None or str(value).strip().lower() in _MISSING:
        raise ObservationIngestionError("missing value")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ObservationIngestionError("value must be finite")
    return parsed


def _normalize_value(variable: str, value: float, unit: str) -> tuple[float, str]:
    canonical = _canonical_unit(unit)
    target = CANONICAL_UNITS[variable]
    if variable in {"emergence", "transplant", "flowering", "fruit_set", "veraison", "maturity", "harvest", "budburst", "dormancy_release"}:
        return value, canonical
    if variable == "air_temperature" or variable == "leaf_temperature":
        if canonical == "degC":
            return value, canonical
        if canonical in {"degF", "F"}:
            return (value - 32.0) * 5.0 / 9.0, "degC"
    if variable == "relative_humidity":
        if canonical == "%" and 0 <= value <= 100:
            return value, "%"
        if canonical == "fraction" and 0 <= value <= 1:
            return value * 100.0, "%"
    if variable in {"vwc", "soil_water_content", "soil_moisture", "canopy_cover"}:
        if canonical == target:
            return value, target
        if canonical == "%" and 0 <= value <= 100:
            return value / 100.0, target
        if canonical == "fraction" and 0 <= value <= 1:
            return value, target
    if variable == "par" and canonical == "umol_m-2_s-1":
        return value / 1_000_000.0, target
    if variable == "biomass" and canonical == "kg_m-2":
        return value * 1000.0, target
    if variable == "yield" and canonical == "t_ha-1":
        return value / 10.0, target
    if canonical == target:
        return value, target
    raise ObservationIngestionError(f"unsupported unit {unit!r} for {variable}")


def _range_ok(variable: str, value: float) -> bool:
    if variable in {"relative_humidity", "canopy_cover"}:
        return 0 <= value <= (100 if variable == "relative_humidity" else 1)
    if variable in {"lai", "biomass", "vwc", "soil_water_content", "soil_moisture", "solar_radiation", "par", "co2", "irrigation", "transpiration", "yield", "fruit_weight", "fruit_mass", "plant_height", "fruit_number", "fruit_count"}:
        return value >= 0
    return True


def _row_to_observation(row: Mapping[str, Any], dataset_id: str, source: str, source_type: ObservationSourceType, row_number: int) -> tuple[Observation | None, ObservationQC | None]:
    try:
        required = ("timestamp", "variable", "value", "unit", "source")
        missing = [key for key in required if key not in row or row[key] in (None, "")]
        if missing:
            return None, ObservationQC(row_number, QualityFlag.INVALID, f"missing required fields: {missing}")
        variable = _canonical_variable(str(row["variable"]))
        if variable not in OBSERVABLE_VARIABLES:
            return None, ObservationQC(row_number, QualityFlag.INVALID, f"unknown observable variable: {variable}", variable)
        if str(row.get("resolution", ObservationResolution.INSTANT)) == ObservationResolution.EVENT.value:
            parsed: float | str = str(row["value"])
            normalized, normalized_unit = parsed, _canonical_unit(str(row["unit"]))
        else:
            parsed = _numeric(row["value"])
            normalized, normalized_unit = _normalize_value(variable, parsed, str(row["unit"]))
        if not _range_ok(variable, normalized):
            return None, ObservationQC(row_number, QualityFlag.OUT_OF_RANGE, f"physically invalid range for {variable}", variable)
        quality = QualityFlag(str(row.get("quality", QualityFlag.VALID)).upper())
        if quality in {QualityFlag.MISSING, QualityFlag.INVALID, QualityFlag.DUPLICATE}:
            return None, ObservationQC(row_number, quality, f"row quality is {quality.value}", variable)
        resolution = ObservationResolution(str(row.get("resolution", ObservationResolution.INSTANT)))
        observation = Observation(
            timestamp=_timestamp(row["timestamp"]), variable=variable, value=normalized, unit=normalized_unit,
            uncertainty=float(row["uncertainty"]) if row.get("uncertainty") not in (None, "") else None,
            source=str(row["source"]), quality=quality.value, resolution=resolution,
            observation_type="event" if resolution == ObservationResolution.EVENT else str(row.get("observation_type", "continuous")),
            dataset_id=dataset_id, source_type=source_type.value, plot_id=row.get("plot_id") or None,
            crop=row.get("crop") or None, variety=row.get("variety") or None,
            environment=str(row.get("environment", Environment.UNKNOWN)), measurement_method=row.get("measurement_method") or None,
            unit_original=str(row["unit"]), duration_seconds=float(row["duration_seconds"]) if row.get("duration_seconds") not in (None, "") else None,
        )
        return observation, None
    except (ValueError, TypeError, ObservationIngestionError) as exc:
        flag = QualityFlag.MISSING if "missing" in str(exc).lower() else QualityFlag.UNIT_ERROR if "unit" in str(exc).lower() else QualityFlag.INVALID
        return None, ObservationQC(row_number, flag, str(exc), str(row.get("variable")) if row.get("variable") else None)


def ingest_rows(rows: Iterable[Mapping[str, Any]], *, dataset_id: str, role: DatasetRole, source: str, source_type: ObservationSourceType = ObservationSourceType.MEASURED, original_filename: str | None = None, imported_at: datetime | None = None) -> ObservationIngestionResult:
    if source_type == ObservationSourceType.FORCING:
        raise ObservationIngestionError("forcing data cannot be ingested as agronomic observations")
    observations: list[Observation] = []
    qc: list[ObservationQC] = []
    seen: set[tuple[str | None, str, datetime]] = set()
    for row_number, row in enumerate(rows, start=2):
        observation, issue = _row_to_observation(row, dataset_id, source, source_type, row_number)
        if issue:
            qc.append(issue)
            continue
        assert observation is not None
        key = (observation.plot_id, observation.variable, observation.timestamp)
        if key in seen:
            qc.append(ObservationQC(row_number, QualityFlag.DUPLICATE, f"duplicate observation key: {key}", observation.variable))
            continue
        seen.add(key)
        observations.append(observation)
    dataset = ObservationDataset(dataset_id, role, tuple(observations), source=source, source_type=source_type.value, original_filename=original_filename, imported_at=imported_at) if observations else None
    readiness = _readiness(observations, qc)
    return ObservationIngestionResult(dataset, readiness, tuple(qc), source, source_type, original_filename)


def ingest_csv(path: str | Path, *, dataset_id: str, role: DatasetRole, source: str, source_type: ObservationSourceType = ObservationSourceType.MEASURED, imported_at: datetime | None = None) -> ObservationIngestionResult:
    path = Path(path)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return ingest_rows(csv.DictReader(stream), dataset_id=dataset_id, role=role, source=source, source_type=source_type, original_filename=path.name, imported_at=imported_at)


def ingest_json(path: str | Path, *, dataset_id: str, role: DatasetRole, source: str, source_type: ObservationSourceType = ObservationSourceType.MEASURED, imported_at: datetime | None = None) -> ObservationIngestionResult:
    path = Path(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload["observations"] if isinstance(payload, Mapping) and "observations" in payload else payload
    if not isinstance(rows, list):
        raise ObservationIngestionError("JSON observations must be a list or an observations list")
    return ingest_rows(rows, dataset_id=dataset_id, role=role, source=source, source_type=source_type, original_filename=path.name, imported_at=imported_at)


def _readiness(observations: list[Observation], qc: list[ObservationQC]) -> DatasetReadiness:
    dates = [item.timestamp for item in observations]
    invalid = sum(issue.quality in {QualityFlag.INVALID, QualityFlag.UNIT_ERROR, QualityFlag.OUT_OF_RANGE} for issue in qc)
    missing = sum(issue.quality == QualityFlag.MISSING for issue in qc)
    duplicates = sum(issue.quality == QualityFlag.DUPLICATE for issue in qc)
    if not observations:
        status = ReadinessStatus.INVALID if invalid else ReadinessStatus.INSUFFICIENT_DATA
    elif invalid:
        status = ReadinessStatus.PARTIAL
    elif qc:
        status = ReadinessStatus.PARTIAL
    else:
        status = ReadinessStatus.READY
    return DatasetReadiness(status, len(observations) + len(qc), len(observations), invalid, missing, duplicates, len({item.variable for item in observations}), len({item.plot_id for item in observations if item.plot_id}), len({item.crop for item in observations if item.crop}), len({item.variety for item in observations if item.variety}), min(dates) if dates else None, max(dates) if dates else None)


def parameter_readiness(registry: ParameterRegistry, dataset: ObservationDataset) -> tuple[ParameterReadiness, ...]:
    variables = {item.variable for item in dataset.observations if item.quality == QualityFlag.VALID}
    dates = [item.timestamp for item in dataset.observations]
    plots = tuple(sorted({item.plot_id for item in dataset.observations if item.plot_id}))
    requirements = {"radiation.rue": ("biomass", "solar_radiation"), "radiation.sla": ("lai", "biomass"), "greenhouse.cover_transmission": ("solar_radiation", "air_temperature"), "water.et_temperature_range": ("soil_water_content", "irrigation")}
    result = []
    for record in registry.records:
        required = requirements.get(record.parameter_id)
        if not required:
            continue
        available = tuple(variable for variable in required if variable in variables)
        count = sum(item.variable in required and item.quality == QualityFlag.VALID for item in dataset.observations)
        status = ParameterReadinessStatus.READY_FOR_CALIBRATION if len(available) == len(required) and count >= 2 and plots else ParameterReadinessStatus.CANDIDATE if available else ParameterReadinessStatus.NOT_READY
        result.append(ParameterReadiness(record.parameter_id, required, available, count, (min(dates), max(dates)) if dates else None, plots, "screening only; identifiability not established" if status != ParameterReadinessStatus.READY_FOR_CALIBRATION else "screening candidate; independent identifiability required", status))
    return tuple(result)


def crop_variety_readiness(dataset: ObservationDataset) -> tuple[dict[str, Any], ...]:
    keys = [("tomato", "RAF"), ("lettuce", None), ("pepper", "Lamuyo"), ("grape", "Monastrell"), ("peach", None), ("plum", "Suplum 26"), ("apple", None)]
    return tuple({"crop": crop, "variety": variety, "observations": sum(item.crop == crop and (variety is None or item.variety == variety) for item in dataset.observations), "status": ReadinessStatus.READY.value if any(item.crop == crop and (variety is None or item.variety == variety) for item in dataset.observations) else ReadinessStatus.INSUFFICIENT_DATA.value} for crop, variety in keys)


def plot_readiness(dataset: ObservationDataset) -> tuple[dict[str, Any], ...]:
    """Summarize only plots explicitly present in observation linkage."""
    plots = sorted({item.plot_id for item in dataset.observations if item.plot_id})
    return tuple(
        {
            "plot_id": plot,
            "crop": next((item.crop for item in dataset.observations if item.plot_id == plot and item.crop), None),
            "variety": next((item.variety for item in dataset.observations if item.plot_id == plot and item.variety), None),
            "environment": next((item.environment for item in dataset.observations if item.plot_id == plot), Environment.UNKNOWN.value),
            "observation_count": sum(item.plot_id == plot for item in dataset.observations),
            "date_start": min(item.timestamp for item in dataset.observations if item.plot_id == plot),
            "date_end": max(item.timestamp for item in dataset.observations if item.plot_id == plot),
            "variables": tuple(sorted({item.variable for item in dataset.observations if item.plot_id == plot})),
            "quality": tuple(sorted({item.quality for item in dataset.observations if item.plot_id == plot})),
        }
        for plot in plots
    )
