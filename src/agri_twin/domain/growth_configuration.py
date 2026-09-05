"""Inactive configuration contract for the future crop-growth model."""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from agri_twin.domain.crop import CropConfigRepository
from agri_twin.domain.farm import FarmConfigRepository


class GrowthModelConfigurationError(ValueError):
    """Raised when the growth-model configuration contract is invalid."""


class GrowthModelConfigurationRepository:
    """Loads an inactive growth-model contract without starting a simulation."""

    def __init__(self, path: str | Path, crop_path: str | Path, farm_path: str | Path) -> None:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GrowthModelConfigurationError("growth-model configuration is invalid") from exc
        if not isinstance(payload, Mapping) or payload.get("activation_status") != "CONTRACT_ONLY":
            raise GrowthModelConfigurationError("growth-model configuration must remain contract-only")
        crop_profiles = payload.get("crop_profiles")
        soil_profiles = payload.get("soil_profiles")
        parameter_contract = payload.get("crop_parameter_contract")
        if not all(isinstance(value, Mapping) for value in (crop_profiles, soil_profiles, parameter_contract)):
            raise GrowthModelConfigurationError("growth-model configuration sections are invalid")
        crops = CropConfigRepository(crop_path)
        farm = FarmConfigRepository(farm_path)
        if set(crop_profiles) != {crop.crop_key for crop in crops.crops}:
            raise GrowthModelConfigurationError("crop profiles must cover exactly the crop configuration")
        missing_soils = {plot.soil_type for plot in farm.plots} - set(soil_profiles)
        if missing_soils:
            raise GrowthModelConfigurationError(f"soil profiles missing for: {', '.join(sorted(missing_soils))}")
        for name, descriptor in parameter_contract.items():
            self._validate_parameter(str(name), descriptor)
        self._payload = MappingProxyType(dict(payload))

    @staticmethod
    def _validate_parameter(name: str, descriptor: Any) -> None:
        if not isinstance(descriptor, Mapping) or not isinstance(descriptor.get("unit"), str):
            raise GrowthModelConfigurationError(f"parameter contract is invalid: {name}")
        bounds = descriptor.get("reasonable_range")
        if not isinstance(bounds, list) or len(bounds) != 2:
            raise GrowthModelConfigurationError(f"parameter range is invalid: {name}")
        for bound in bounds:
            if bound is not None and (isinstance(bound, bool) or not isinstance(bound, (int, float)) or not math.isfinite(bound)):
                raise GrowthModelConfigurationError(f"parameter range is invalid: {name}")
        if descriptor.get("evidence_status") != "CALIBRATION_REQUIRED" or descriptor.get("default_value") is not None:
            raise GrowthModelConfigurationError(f"unsupported crop parameter activation: {name}")

    @property
    def crop_profiles(self) -> Mapping[str, Any]:
        return self._payload["crop_profiles"]

    @property
    def soil_profiles(self) -> Mapping[str, Any]:
        return self._payload["soil_profiles"]

    @property
    def environment_profiles(self) -> Mapping[str, Any]:
        return self._payload["environment_profiles"]
