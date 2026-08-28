"""Typed crop definitions and phenological stages."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


class CropConfigurationError(ValueError):
    """Raised when crop configuration or stage resolution is invalid."""


@dataclass(frozen=True, slots=True)
class CropStageDefinition:
    stage_key: str
    stage_name: str
    parameters: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class CropDefinition:
    crop_key: str
    name: str
    location: str
    stages: Mapping[str, CropStageDefinition]

    def resolve_stage(self, stage_key: str) -> CropStageDefinition:
        try:
            return self.stages[stage_key]
        except KeyError as exc:
            raise CropConfigurationError(
                f"stage not found for crop {self.crop_key}: {stage_key}"
            ) from exc


class CropConfigRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CropConfigurationError("crop configuration is invalid") from exc
        raw_crops = payload.get("crops") if isinstance(payload, Mapping) else None
        if not isinstance(raw_crops, Mapping):
            raise CropConfigurationError("crop configuration must contain a crops object")
        self._crops: dict[str, CropDefinition] = {}
        for key, raw in raw_crops.items():
            if not isinstance(raw, Mapping) or not isinstance(raw.get("stages"), Mapping):
                raise CropConfigurationError(f"crop configuration is invalid: {key}")
            stages: dict[str, CropStageDefinition] = {}
            for stage_key, stage in raw["stages"].items():
                if not isinstance(stage, Mapping) or not stage.get("stage_name"):
                    raise CropConfigurationError(f"stage configuration is invalid: {key}/{stage_key}")
                stages[str(stage_key)] = CropStageDefinition(
                    str(stage_key), str(stage["stage_name"]), MappingProxyType(dict(stage))
                )
            crop_key = str(key).lower()
            self._crops[crop_key] = CropDefinition(
                crop_key, str(raw.get("crop_type", crop_key)), str(raw.get("location", "")), MappingProxyType(stages)
            )

    def get_crop(self, crop_key: str) -> CropDefinition:
        try:
            return self._crops[crop_key.lower()]
        except KeyError as exc:
            raise CropConfigurationError(f"crop not found: {crop_key}") from exc

    def resolve_stage(self, crop_key: str, stage_key: str) -> CropStageDefinition:
        return self.get_crop(crop_key).resolve_stage(stage_key)

    @property
    def crops(self) -> tuple[CropDefinition, ...]:
        return tuple(self._crops.values())
