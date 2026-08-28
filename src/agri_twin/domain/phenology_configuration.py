"""Optional, inactive contract for future crop phenology configuration."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


class PhenologyConfigurationError(ValueError):
    """Raised when an optional phenology declaration is malformed."""


REQUIRED_STAGE_FIELDS = {"stage_key", "gdd_to_next"}
CALIBRATION_STATUSES = {"LITERATURE", "PROVISIONAL", "CALIBRATION_REQUIRED"}


def validate_phenology_configuration(
    phenology: Any,
    stage_keys: tuple[str, ...] | None = None,
) -> None:
    """Validate a future phenology declaration without executing transitions.

    ``None`` values are accepted for agronomic quantities because the current
    repository intentionally has no measured Tbase or GDD values.
    """
    if phenology is None:
        return
    if not isinstance(phenology, Mapping):
        raise PhenologyConfigurationError("phenology must be an object")
    method = phenology.get("method")
    if method not in {"gdd", "calendar", "external"}:
        raise PhenologyConfigurationError("phenology method is invalid")
    if method == "gdd":
        base_temperature = phenology.get("base_temperature_c")
        if base_temperature is not None and (
            isinstance(base_temperature, bool)
            or not isinstance(base_temperature, (int, float))
            or not math.isfinite(base_temperature)
        ):
            raise PhenologyConfigurationError("base_temperature_c must be finite or null")
    for name in ("base_temperature_c", "upper_temperature_c"):
        value = phenology.get(name)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise PhenologyConfigurationError(f"{name} must be finite or null")
    biofix = phenology.get("biofix")
    if biofix is not None and (not isinstance(biofix, str) or not biofix):
        raise PhenologyConfigurationError("biofix must be a non-empty string or null")
    status = phenology.get("calibration_status")
    if status is not None and status not in CALIBRATION_STATUSES:
        raise PhenologyConfigurationError("calibration_status is invalid")
    source = phenology.get("source")
    if source is not None and (not isinstance(source, Mapping) or not source.get("reference") or not source.get("type")):
        raise PhenologyConfigurationError("source requires reference and type")
    stages = phenology.get("stages")
    if not isinstance(stages, list) or not stages:
        raise PhenologyConfigurationError("phenology stages must be a non-empty list")
    keys: set[str] = set()
    ordered_keys: list[str] = []
    for stage in stages:
        if not isinstance(stage, Mapping) or not REQUIRED_STAGE_FIELDS <= stage.keys():
            raise PhenologyConfigurationError("phenology stage requires stage_key and gdd_to_next")
        key = stage["stage_key"]
        if not isinstance(key, str) or not key:
            raise PhenologyConfigurationError("phenology stage_key must be non-empty")
        if key in keys:
            raise PhenologyConfigurationError(f"duplicate phenology stage: {key}")
        keys.add(key)
        ordered_keys.append(key)
        gdd = stage["gdd_to_next"]
        if gdd is not None and (isinstance(gdd, bool) or not isinstance(gdd, (int, float)) or not math.isfinite(gdd) or gdd < 0):
            raise PhenologyConfigurationError("gdd_to_next must be finite, non-negative or null")
        stage_status = stage.get("calibration_status")
        if stage_status is not None and stage_status not in CALIBRATION_STATUSES:
            raise PhenologyConfigurationError("stage calibration_status is invalid")
        stage_source = stage.get("source")
        if gdd is not None and (not isinstance(stage_source, Mapping) or not stage_source.get("reference") or not stage_source.get("type")):
            raise PhenologyConfigurationError("active gdd_to_next requires a source")
    if stage_keys is not None and tuple(ordered_keys) != stage_keys:
        raise PhenologyConfigurationError("phenology stages do not match the crop stage order")
