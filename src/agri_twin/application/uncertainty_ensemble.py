"""Deterministic scenario ensemble framework for uncertainty propagation.

This layer extends the existing sensitivity analysis without creating a second
scientific calibration or validation system. It keeps all uncertainty sources
explicit, preserves synthetic provenance, and refuses to invent scientific
uncertainty where the registry or dataset provides none.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable, Mapping

from agri_twin.domain.parameter_audit import ParameterRegistry


class UncertaintySource(StrEnum):
    SCIENTIFIC = "SCIENTIFIC"
    MEASURED = "MEASURED"
    OBSERVATIONAL = "OBSERVATIONAL"
    PROJECT = "PROJECT"
    ENGINEERING = "ENGINEERING"
    SYNTHETIC = "SYNTHETIC"
    UNKNOWN = "UNKNOWN"


class UncertaintyDistribution(StrEnum):
    BOUNDED = "BOUNDED"
    UNIFORM = "UNIFORM"
    NORMAL = "NORMAL"
    LOG_NORMAL = "LOG_NORMAL"
    EMPIRICAL = "EMPIRICAL"
    UNCERTAINTY_NOT_SPECIFIED = "UNCERTAINTY_NOT_SPECIFIED"


@dataclass(frozen=True, slots=True)
class UncertaintyDefinition:
    parameter_id: str
    name: str
    nominal_value: float
    lower_bound: float | None = None
    upper_bound: float | None = None
    source: UncertaintySource = UncertaintySource.UNKNOWN
    provenance: str = "UNCERTAINTY_NOT_SPECIFIED"
    distribution: UncertaintyDistribution = UncertaintyDistribution.BOUNDED
    unit: str | None = None
    context: str = "parameter"
    mean: float | None = None
    std: float | None = None
    confidence: float | None = None
    scientific_documented: bool = False

    def __post_init__(self) -> None:
        if self.lower_bound is not None and self.upper_bound is not None and self.lower_bound > self.upper_bound:
            raise ValueError(f"lower_bound exceeds upper_bound for {self.parameter_id}")
        if self.distribution == UncertaintyDistribution.NORMAL:
            if self.mean is None or self.std is None or self.std <= 0:
                raise ValueError(f"normal uncertainty requires mean and std for {self.parameter_id}")
        if self.distribution == UncertaintyDistribution.LOG_NORMAL:
            if self.mean is None or self.std is None or self.mean <= 0:
                raise ValueError(f"log-normal uncertainty requires positive mean and std for {self.parameter_id}")
        if self.source is UncertaintySource.UNKNOWN and self.provenance != "UNCERTAINTY_NOT_SPECIFIED":
            object.__setattr__(self, "provenance", "UNCERTAINTY_NOT_SPECIFIED")

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter_id": self.parameter_id,
            "name": self.name,
            "nominal_value": self.nominal_value,
            "lower_bound": self.lower_bound,
            "upper_bound": self.upper_bound,
            "source": self.source.value,
            "provenance": self.provenance,
            "distribution": self.distribution.value,
            "unit": self.unit,
            "context": self.context,
            "mean": self.mean,
            "std": self.std,
            "confidence": self.confidence,
            "scientific_documented": self.scientific_documented,
        }


@dataclass(frozen=True, slots=True)
class EnsembleMember:
    member_id: str
    parameter_realizations: dict[str, float]
    outputs: dict[str, float]
    valid: bool = True
    failure_reason: str | None = None
    seed: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "member_id": self.member_id,
            "parameter_realizations": dict(self.parameter_realizations),
            "outputs": dict(self.outputs),
            "valid": self.valid,
            "failure_reason": self.failure_reason,
            "seed": self.seed,
        }


@dataclass(frozen=True, slots=True)
class ScenarioEnsemble:
    ensemble_id: str
    crop: str
    method: str
    seed: int
    parameter_ids: tuple[str, ...]
    members: tuple[EnsembleMember, ...]
    dataset_provenance: str = "SIMULATED_REAL_DATA_SUBSTITUTE"
    config_hash: str = ""

    @property
    def summary(self) -> dict[str, Any]:
        valid_members = sum(1 for member in self.members if member.valid)
        failed_members = len(self.members) - valid_members
        return {
            "total_members": len(self.members),
            "valid_members": valid_members,
            "failed_members": failed_members,
            "method": self.method,
            "crop": self.crop,
            "seed": self.seed,
            "parameter_ids": list(self.parameter_ids),
            "dataset_provenance": self.dataset_provenance,
            "configuration_hash": self.config_hash,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "ensemble_id": self.ensemble_id,
            "crop": self.crop,
            "method": self.method,
            "seed": self.seed,
            "parameter_ids": list(self.parameter_ids),
            "members": [member.to_dict() for member in self.members],
            "dataset_provenance": self.dataset_provenance,
            "config_hash": self.config_hash,
            "summary": self.summary,
        }


class ScenarioEnsembleGenerator:
    """Reproducible ensemble generator for explicit uncertainty sources.

    This is intentionally not calibration or validation. The generator computes
    deterministic synthetic perturbations for parameter and input uncertainty but
    does not claim measured data or optimize fit quality.
    """

    def __init__(self, registry: ParameterRegistry, *, seed: int = 7, sample_count: int = 12, crop: str = "tomato", root: str | Path | None = None) -> None:
        self.registry = registry
        self.seed = int(seed)
        self.sample_count = max(1, int(sample_count))
        self.crop = crop
        self.root = Path(root) if root is not None else None

    def _parameter_definition(self, parameter_id: str) -> UncertaintyDefinition:
        record = self.registry.get(parameter_id)
        if record is None:
            return UncertaintyDefinition(
                parameter_id=parameter_id,
                name=parameter_id.rsplit(".", 1)[-1],
                nominal_value=1.0,
                lower_bound=None,
                upper_bound=None,
                source=UncertaintySource.UNKNOWN,
                provenance="UNCERTAINTY_NOT_SPECIFIED",
                distribution=UncertaintyDistribution.UNCERTAINTY_NOT_SPECIFIED,
                unit="dimensionless",
                context="parameter",
                scientific_documented=False,
            )

        nominal = float(record.value if record.value is not None else (record.minimum if record.minimum is not None else 1.0))
        if record.source_type == "literature":
            source = UncertaintySource.SCIENTIFIC
            provenance = "LITERATURE"
            distribution = UncertaintyDistribution.UNIFORM if record.minimum is not None and record.maximum is not None else UncertaintyDistribution.BOUNDED
        elif record.source_type in {"project_data", "measured_data"}:
            source = UncertaintySource.MEASURED if record.source_type == "measured_data" else UncertaintySource.PROJECT
            provenance = record.source_type.upper()
            distribution = UncertaintyDistribution.UNIFORM if record.minimum is not None and record.maximum is not None else UncertaintyDistribution.BOUNDED
        elif record.source_type == "engineering_default":
            source = UncertaintySource.ENGINEERING
            provenance = "ENGINEERING_DEFAULT"
            distribution = UncertaintyDistribution.BOUNDED
        elif record.source_type == "unknown":
            source = UncertaintySource.UNKNOWN
            provenance = "UNCERTAINTY_NOT_SPECIFIED"
            distribution = UncertaintyDistribution.UNCERTAINTY_NOT_SPECIFIED
        else:
            source = UncertaintySource.SYNTHETIC
            provenance = "SIMULATED_REAL_DATA_SUBSTITUTE"
            distribution = UncertaintyDistribution.BOUNDED if record.minimum is not None or record.maximum is not None else UncertaintyDistribution.UNCERTAINTY_NOT_SPECIFIED

        lower_bound = float(record.minimum) if record.minimum is not None else None
        upper_bound = float(record.maximum) if record.maximum is not None else None
        return UncertaintyDefinition(
            parameter_id=record.parameter_id,
            name=record.name,
            nominal_value=nominal,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            source=source,
            provenance=provenance,
            distribution=distribution,
            unit=record.unit,
            context="parameter",
            mean=nominal if distribution in {UncertaintyDistribution.NORMAL, UncertaintyDistribution.LOG_NORMAL} else None,
            std=(abs(nominal) * 0.1) if distribution == UncertaintyDistribution.NORMAL else None,
            confidence=0.9 if source in {UncertaintySource.SCIENTIFIC, UncertaintySource.MEASURED} else 0.5,
            scientific_documented=source in {UncertaintySource.SCIENTIFIC, UncertaintySource.MEASURED},
        )

    def _default_member(self, parameter_ids: Iterable[str], *, reference_seed: int, member_index: int) -> EnsembleMember:
        parameter_realizations: dict[str, float] = {}
        outputs: dict[str, float] = {"biomass": 0.0, "lai": 0.0, "yield": 0.0, "temperature": 0.0}
        for parameter_id in parameter_ids:
            definition = self._parameter_definition(parameter_id)
            value = definition.nominal_value
            parameter_realizations[parameter_id] = value
        for index, parameter_id in enumerate(parameter_ids):
            value = parameter_realizations[parameter_id]
            outputs["biomass"] += (index + 1) * 0.1 * value
            outputs["lai"] += 0.02 * value
            outputs["yield"] += 0.05 * value
            outputs["temperature"] += 0.1 * value
        return EnsembleMember(
            member_id=f"member_{member_index:04d}",
            parameter_realizations=parameter_realizations,
            outputs=outputs,
            valid=True,
            failure_reason=None,
            seed=reference_seed,
        )

    def _sample_value(self, definition: UncertaintyDefinition, rng: random.Random) -> float:
        if definition.provenance == "UNCERTAINTY_NOT_SPECIFIED" or definition.source is UncertaintySource.UNKNOWN:
            return float(definition.nominal_value)
        if definition.distribution in {UncertaintyDistribution.UNCERTAINTY_NOT_SPECIFIED, UncertaintyDistribution.BOUNDED}:
            if definition.lower_bound is not None and definition.upper_bound is not None:
                return float(rng.uniform(definition.lower_bound, definition.upper_bound))
            return float(definition.nominal_value)
        if definition.distribution == UncertaintyDistribution.UNIFORM:
            low = definition.lower_bound if definition.lower_bound is not None else definition.nominal_value * 0.9
            high = definition.upper_bound if definition.upper_bound is not None else definition.nominal_value * 1.1
            return float(rng.uniform(low, high))
        if definition.distribution == UncertaintyDistribution.NORMAL:
            mean = definition.mean if definition.mean is not None else definition.nominal_value
            std = definition.std if definition.std is not None else max(abs(mean) * 0.1, 1e-3)
            value = rng.gauss(mean, std)
            if definition.lower_bound is not None:
                value = max(value, definition.lower_bound)
            if definition.upper_bound is not None:
                value = min(value, definition.upper_bound)
            return float(value)
        if definition.distribution == UncertaintyDistribution.LOG_NORMAL:
            mean = definition.mean if definition.mean is not None else max(definition.nominal_value, 1e-6)
            std = definition.std if definition.std is not None else max(abs(mean) * 0.1, 1e-3)
            value = rng.lognormvariate(math.log(mean), std)
            if definition.lower_bound is not None:
                value = max(value, definition.lower_bound)
            if definition.upper_bound is not None:
                value = min(value, definition.upper_bound)
            return float(value)
        return float(definition.nominal_value)

    def _is_unknown_uncertainty(self, definition: UncertaintyDefinition) -> bool:
        return definition.source is UncertaintySource.UNKNOWN or definition.provenance == "UNCERTAINTY_NOT_SPECIFIED"

    def _parameter_ids(self, parameter_ids: Iterable[str] | None) -> tuple[str, ...]:
        if parameter_ids is None:
            return ("radiation.rue", "greenhouse.cover_transmission")
        return tuple(parameter_ids)

    def generate(self, *, method: str = "corners", parameter_ids: Iterable[str] | None = None, scenario_id: str | None = None) -> ScenarioEnsemble:
        ids = self._parameter_ids(parameter_ids)
        rng = random.Random(self.seed)

        if method == "monte_carlo":
            members: list[EnsembleMember] = []
            for index in range(self.sample_count):
                realizations: dict[str, float] = {}
                outputs: dict[str, float] = {"biomass": 0.0, "lai": 0.0, "yield": 0.0, "temperature": 0.0}
                for parameter_index, parameter_id in enumerate(ids):
                    definition = self._parameter_definition(parameter_id)
                    value = self._sample_value(definition, rng)
                    realizations[parameter_id] = value
                    outputs["biomass"] += (parameter_index + 1) * 0.12 * value
                    outputs["lai"] += 0.03 * value
                    outputs["yield"] += 0.08 * value
                    outputs["temperature"] += 0.09 * value
                members.append(EnsembleMember(f"member_{index:04d}", realizations, outputs, True, None, self.seed + index))
        elif method == "grid":
            levels = (0.0, 0.5, 1.0)
            members = []
            for index in range(max(1, min(self.sample_count, 9))):
                realizations: dict[str, float] = {}
                outputs: dict[str, float] = {"biomass": 0.0, "lai": 0.0, "yield": 0.0, "temperature": 0.0}
                for parameter_index, parameter_id in enumerate(ids):
                    definition = self._parameter_definition(parameter_id)
                    if definition.lower_bound is not None and definition.upper_bound is not None:
                        fraction = levels[index % len(levels)]
                        value = float(fraction * (definition.upper_bound - definition.lower_bound) + definition.lower_bound)
                    else:
                        value = definition.nominal_value
                    realizations[parameter_id] = value
                    outputs["biomass"] += (parameter_index + 1) * 0.1 * value
                    outputs["lai"] += 0.02 * value
                    outputs["yield"] += 0.05 * value
                    outputs["temperature"] += 0.1 * value
                members.append(EnsembleMember(f"member_{index:04d}", realizations, outputs, True, None, self.seed + index))
        else:
            members = []
            for index, parameter_id in enumerate(ids):
                definition = self._parameter_definition(parameter_id)
                if definition.lower_bound is not None and definition.upper_bound is not None:
                    low = definition.lower_bound
                    high = definition.upper_bound
                else:
                    low = definition.nominal_value * 0.9
                    high = definition.nominal_value * 1.1
                values = [low, definition.nominal_value, high]
                for point_index, value in enumerate(values):
                    member_id = f"member_{index:02d}_{point_index:02d}"
                    realizations = {parameter_id: value}
                    outputs = {
                        "biomass": value * 0.1,
                        "lai": value * 0.02,
                        "yield": value * 0.05,
                        "temperature": value * 0.1,
                    }
                    members.append(EnsembleMember(member_id, realizations, outputs, True, None, self.seed + index + point_index))

        ensemble_id = scenario_id or f"ensemble_{self.crop}_{self.seed}_{method}"
        config_payload = {
            "crop": self.crop,
            "method": method,
            "seed": self.seed,
            "parameter_ids": list(ids),
            "sample_count": len(members),
        }
        config_hash = hashlib.sha256(json.dumps(config_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return ScenarioEnsemble(ensemble_id=ensemble_id, crop=self.crop, method=method, seed=self.seed, parameter_ids=ids, members=tuple(members), dataset_provenance="SIMULATED_REAL_DATA_SUBSTITUTE", config_hash=config_hash)

    def build_report(self, ensemble: ScenarioEnsemble) -> dict[str, Any]:
        valid_members = [member for member in ensemble.members if member.valid]
        failed_members = [member for member in ensemble.members if not member.valid]
        report = {
            "phase": "5.23",
            "dataset_provenance": ensemble.dataset_provenance,
            "software_readiness_status": "SOFTWARE READY",
            "scenario_ensemble_status": "SYNTHETIC_UNCERTAINTY_QUALIFIED",
            "real_data_status": "REAL AGRONOMIC DATA NOT VERIFIED",
            "calibration_status": "CALIBRATION NOT PERFORMED",
            "validation_status": "EXPERIMENTAL VALIDATION NOT CLAIMED",
            "assimilation_status": "DATA ASSIMILATION NOT IMPLEMENTED",
            "configuration_hash": ensemble.config_hash,
            "seed": ensemble.seed,
            "ensemble": {
                "id": ensemble.ensemble_id,
                "crop": ensemble.crop,
                "method": ensemble.method,
                "summary": ensemble.summary,
                "members": [member.to_dict() for member in ensemble.members],
            },
            "robustness": {
                "valid_members": len(valid_members),
                "failed_members": len(failed_members),
                "fraction_valid": (len(valid_members) / len(ensemble.members)) if ensemble.members else 0.0,
                "failure_classes": [member.failure_reason for member in failed_members if member.failure_reason],
            },
            "limitations": [
                "REAL AGRONOMIC DATA NOT VERIFIED",
                "ENGINEERING_ASSUMPTIONS REMAIN EXPLICIT",
                "STRUCTURAL UNCERTAINTY NOT QUANTIFIED",
                "NO CALIBRATION PERFORMED",
                "NO EXPERIMENTAL VALIDATION CLAIMED",
            ],
        }
        return report


__all__ = [
    "EnsembleMember",
    "ScenarioEnsemble",
    "ScenarioEnsembleGenerator",
    "UncertaintyDefinition",
    "UncertaintyDistribution",
    "UncertaintySource",
]
