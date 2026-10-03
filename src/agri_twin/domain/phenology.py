"""Deterministic thermal-time phenology without a real-time dependency."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from agri_twin.domain.chilling_models import ChillingModelError, dynamic_step, utah_step
from agri_twin.domain.models import ChillingAccumulation, CropGrowthState, WeatherState


class PhenologyError(ValueError):
    """Raised when phenology inputs or profiles are invalid."""


class PhenologyEvidenceLevel(StrEnum):
    SCIENTIFIC_BASE = "SCIENTIFIC_BASE"
    ENGINEERING_APPROXIMATION = "ENGINEERING_APPROXIMATION"
    CALIBRATED = "CALIBRATED"


@dataclass(frozen=True, slots=True)
class PhenologyProfile:
    """Explicit profile; approximate defaults are never cultivar-specific."""

    crop_key: str
    perennial: bool
    base_temperature_c: float
    upper_temperature_c: float
    stage_gdd_targets: tuple[float, float, float]
    maturity_gdd_target: float
    evidence_level: PhenologyEvidenceLevel = PhenologyEvidenceLevel.ENGINEERING_APPROXIMATION
    chilling_requirement_hours: float | None = None
    chilling_min_temperature_c: float = 0.0
    chilling_max_temperature_c: float = 7.2

    def __post_init__(self) -> None:
        if not self.crop_key or not math.isfinite(self.base_temperature_c) or not math.isfinite(self.upper_temperature_c):
            raise PhenologyError("crop key and thermal limits must be valid")
        if self.upper_temperature_c <= self.base_temperature_c:
            raise PhenologyError("upper temperature must exceed base temperature")
        if len(self.stage_gdd_targets) != 3 or any(value <= 0 or not math.isfinite(value) for value in self.stage_gdd_targets):
            raise PhenologyError("three positive stage GDD targets are required")
        if self.maturity_gdd_target <= 0 or not math.isfinite(self.maturity_gdd_target):
            raise PhenologyError("maturity GDD target must be positive")
        if self.perennial and (self.chilling_requirement_hours is None or self.chilling_requirement_hours <= 0):
            raise PhenologyError("perennial profiles require chilling hours")
        if not self.perennial and self.chilling_requirement_hours is not None:
            raise PhenologyError("annual profiles cannot require chilling")


APPROXIMATE_PROFILES = {
    "tomato": PhenologyProfile("tomato", False, 10.0, 30.0, (250.0, 500.0, 900.0), 1200.0),
    "lettuce": PhenologyProfile("lettuce", False, 4.0, 28.0, (150.0, 350.0, 600.0), 750.0),
    "pepper": PhenologyProfile("pepper", False, 10.0, 30.0, (250.0, 550.0, 950.0), 1200.0),
    "grape": PhenologyProfile("grape", True, 5.0, 30.0, (200.0, 500.0, 900.0), 1100.0, chilling_requirement_hours=400.0),
    "peach": PhenologyProfile("peach", True, 4.5, 30.0, (200.0, 500.0, 900.0), 1100.0, chilling_requirement_hours=600.0),
    "plum": PhenologyProfile("plum", True, 4.5, 25.0, (200.0, 500.0, 850.0), 1050.0, chilling_requirement_hours=500.0),
    "apple": PhenologyProfile("apple", True, 4.0, 30.0, (200.0, 500.0, 900.0), 1100.0, chilling_requirement_hours=600.0),
}

STAGES = ("establishment", "vegetative_growth", "yield_maturation", "post_harvest_dormancy")


class ChillingModelType(StrEnum):
    CHILLING_HOURS = "CHILLING_HOURS"
    UTAH = "UTAH"
    DYNAMIC = "DYNAMIC"


class ChillingStartPolicyType(StrEnum):
    DORMANCY_STATE = "DORMANCY_STATE"
    FIXED_DATE = "FIXED_DATE"
    EFFECTIVE_CHILL_ONSET = "EFFECTIVE_CHILL_ONSET"
    MODEL_DEFINED = "MODEL_DEFINED"
    ENVIRONMENTAL_WINDOW = "ENVIRONMENTAL_WINDOW"


class ChillingUnit(StrEnum):
    """Accumulation units; never interchangeable or converted."""

    CHILL_HOURS = "chill_hours"
    UTAH_CHILL_UNITS = "utah_chill_units"
    CHILL_PORTIONS = "chill_portions"


class ChillingModelStatus(StrEnum):
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    IMPLEMENTED_UNPARAMETERIZED = "IMPLEMENTED_UNPARAMETERIZED"  # formulation + constants, no requirement in its unit
    IMPLEMENTED_PARAMETERIZED = "IMPLEMENTED_PARAMETERIZED"


class RequirementEvidence(StrEnum):
    """Provenance of a chilling requirement. No activated scientific requirement exists."""

    ENGINEERING_DEFAULT = "ENGINEERING_DEFAULT"  # PhenologyProfile chilling_requirement_hours
    SOFTWARE_TEST_ONLY = "SOFTWARE_TEST_ONLY"  # explicit synthetic threshold for software qualification


@dataclass(frozen=True, slots=True)
class ChillingModelSpec:
    unit: ChillingUnit
    thermal_input: str
    time_step: str
    validity: str
    state: str
    parameter_set: str
    traceability: str


MODEL_SPECS: dict[ChillingModelType, ChillingModelSpec] = {
    ChillingModelType.CHILLING_HOURS: ChillingModelSpec(
        ChillingUnit.CHILL_HOURS, "air temperature (C)", "per simulation step, weighted by dt (hourly steps give whole hours)",
        "hours with air temperature in [lower, upper] C count; no negation by warm hours", "scalar chill hours (CropGrowthState.chilling_hours)",
        "CHILLING_HOURS_PROFILE_THRESHOLDS",
        "project CHILLING_HOURS rule (PhenologyProfile chilling_min/max_temperature_c); Weinberger (1950) counted hours below 7.2 C"),
    ChillingModelType.UTAH: ChillingModelSpec(
        ChillingUnit.UTAH_CHILL_UNITS, "hourly air temperature (C)", "hourly only (dt_seconds == 3600)",
        "published weight table; warm hours subtract units; the running sum can be negative", "scalar Utah chill units (CropGrowthState.chilling_state)",
        "UTAH_RICHARDSON_1974", "Richardson, Seeley & Walker (1974) HortScience 9:331-332; table as in Zhang & Taylor (2011) HortScience 46:420-425"),
    ChillingModelType.DYNAMIC: ChillingModelSpec(
        ChillingUnit.CHILL_PORTIONS, "hourly air temperature (C), converted as T + 273", "hourly only (dt_seconds == 3600)",
        "two-step process: reversible intermediate, irreversible chill portions", "intermediate product, previous transfer fraction and chill portions (CropGrowthState.chilling_state)",
        "DYNAMIC_EREZ_1990", "Fishman, Erez & Couvillon (1987) J. Theor. Biol. 124:473-483, 126:309-321; Erez et al. (1990) Acta Hortic. 276:165-174; constants as in Luedeling & Brown (2010) doi:10.1007/s00484-010-0352-y"),
}
STATEFUL_START_POLICIES = frozenset({ChillingStartPolicyType.DORMANCY_STATE, ChillingStartPolicyType.FIXED_DATE})


@dataclass(frozen=True, slots=True)
class ChillingRequirement:
    """Release requirement expressed in the unit of the model that counts it."""

    value: float
    unit: ChillingUnit
    evidence: RequirementEvidence

    def __post_init__(self) -> None:
        if not isinstance(self.unit, ChillingUnit) or not isinstance(self.evidence, RequirementEvidence):
            raise PhenologyError("ChillingRequirement unit and evidence must be ChillingUnit and RequirementEvidence")
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)) or not math.isfinite(self.value) or self.value <= 0:
            raise PhenologyError(f"dormancy.chilling_requirement.value must be a finite number > 0, got {self.value!r}")

    def to_dict(self) -> dict[str, object]:
        return {"value": float(self.value), "unit": self.unit.value, "evidence": self.evidence.value}


@dataclass(frozen=True, slots=True)
class ChillingModel:
    """HOW TO COUNT. CHILLING_HOURS, UTAH and DYNAMIC share one contract: a thermal
    input, a unit, an hourly (or dt-weighted) update, a state and deterministic errors.

    CHILLING_HOURS takes its requirement from the phenology profile (chill hours).
    UTAH and DYNAMIC are implemented formulations with published constants but no
    activated species requirement: they execute only with an explicit requirement in
    their own unit, otherwise they are IMPLEMENTED_UNPARAMETERIZED (MODEL_NOT_READY).
    """

    model_type: ChillingModelType = ChillingModelType.CHILLING_HOURS
    requirement: ChillingRequirement | None = None

    def __post_init__(self) -> None:
        if self.requirement is None:
            return
        if self.model_type is ChillingModelType.CHILLING_HOURS:
            raise PhenologyError("dormancy.chilling_requirement: model CHILLING_HOURS takes its requirement from the phenology profile (chill_hours); an explicit requirement is not accepted")
        if self.requirement.unit is not self.unit:
            raise PhenologyError(f"dormancy.chilling_requirement.unit: model {self.model_type.value} expects '{self.unit.value}', received '{self.requirement.unit.value}'")

    @property
    def spec(self) -> ChillingModelSpec:
        return MODEL_SPECS[self.model_type]

    @property
    def unit(self) -> ChillingUnit:
        return self.spec.unit

    @property
    def implemented(self) -> bool:
        """The formulation is implemented (all three models since Phase 5.35)."""
        return self.model_type in MODEL_SPECS

    @property
    def ready(self) -> bool:
        """A requirement in the model's own unit is available, so release can be decided."""
        return self.model_type is ChillingModelType.CHILLING_HOURS or self.requirement is not None

    @property
    def status(self) -> ChillingModelStatus:
        if not self.implemented:
            return ChillingModelStatus.NOT_IMPLEMENTED
        return ChillingModelStatus.IMPLEMENTED_PARAMETERIZED if self.ready else ChillingModelStatus.IMPLEMENTED_UNPARAMETERIZED

    def required(self, profile: PhenologyProfile) -> float:
        if self.model_type is ChillingModelType.CHILLING_HOURS:
            return profile.chilling_requirement_hours
        if self.requirement is None:
            raise PhenologyError(f"MODEL_NOT_READY: chilling model {self.model_type.value} is implemented but has no requirement in {self.unit.value}; no species requirement is activated")
        return self.requirement.value

    def increment(self, temperature_c: float, profile: PhenologyProfile, dt_seconds: float) -> float:
        """Stateless per-step contribution (CHILLING_HOURS, UTAH); DYNAMIC needs ``accumulate``."""
        if self.model_type is ChillingModelType.CHILLING_HOURS:
            if profile.chilling_min_temperature_c <= temperature_c <= profile.chilling_max_temperature_c:
                return dt_seconds / 3600.0
            return 0.0
        if self.model_type is ChillingModelType.UTAH:
            try:
                return utah_step(0.0, temperature_c, dt_seconds)
            except ChillingModelError as exc:
                raise PhenologyError(str(exc)) from None
        raise PhenologyError("DYNAMIC is stateful (intermediate product); use ChillingModel.accumulate")

    def initial(self, chilling_hours: float = 0.0) -> ChillingAccumulation:
        accumulated = chilling_hours if self.model_type is ChillingModelType.CHILLING_HOURS else 0.0
        return ChillingAccumulation(self.model_type.value, self.unit.value, accumulated)

    def accumulate(self, chill: ChillingAccumulation, temperature_c: float, profile: PhenologyProfile, dt_seconds: float) -> ChillingAccumulation:
        """The single accumulation path of every model."""
        if chill.model != self.model_type.value or chill.unit != self.unit.value:
            raise PhenologyError(f"chilling state holds {chill.model}/{chill.unit}; model {self.model_type.value} counts {self.unit.value}")
        if self.model_type is not ChillingModelType.DYNAMIC:
            return replace(chill, accumulated=chill.accumulated + self.increment(temperature_c, profile, dt_seconds))
        try:
            step = dynamic_step(chill.intermediate, chill.previous_transfer_fraction, temperature_c, dt_seconds)
        except ChillingModelError as exc:
            raise PhenologyError(str(exc)) from None
        return ChillingAccumulation(chill.model, chill.unit, chill.accumulated + step.portion, step.intermediate, step.transfer_fraction)


@dataclass(frozen=True, slots=True)
class ChillingStartPolicy:
    """WHEN TO COUNT. No policy carries a built-in calendar date: FIXED_DATE requires
    an explicit, configured instant; the default counts whenever the crop is endodormant."""

    policy_type: ChillingStartPolicyType = ChillingStartPolicyType.DORMANCY_STATE
    start_time: datetime | None = None
    rationale: str = "count whenever the crop state is endodormant (dormancy_released is False)"

    def __post_init__(self) -> None:
        if self.policy_type is ChillingStartPolicyType.FIXED_DATE:
            if self.start_time is None or self.start_time.tzinfo is None:
                raise PhenologyError("FIXED_DATE requires an explicit timezone-aware start_time")
        elif self.start_time is not None:
            raise PhenologyError(f"{self.policy_type.value} does not take a start_time")

    @staticmethod
    def is_implemented(policy_type: ChillingStartPolicyType) -> bool:
        return policy_type in {ChillingStartPolicyType.DORMANCY_STATE, ChillingStartPolicyType.FIXED_DATE, ChillingStartPolicyType.EFFECTIVE_CHILL_ONSET}

    @property
    def implemented(self) -> bool:
        return self.is_implemented(self.policy_type)

    def counting(self, simulation_time: datetime) -> bool:
        if not self.implemented:
            raise PhenologyError(f"MODEL_NOT_SUPPORTED: start policy {self.policy_type.value} is not implemented")
        if self.policy_type is ChillingStartPolicyType.FIXED_DATE:
            assert self.start_time is not None
            return simulation_time >= self.start_time
        # DORMANCY_STATE and EFFECTIVE_CHILL_ONSET count every endodormant step; with the
        # Chilling Hours rule only effective hours add, so the effective onset is implicit.
        return True


class ChillingFallbackPolicy(StrEnum):
    """Single fallback policy; DEFAULT is a public alias resolved to STRICT."""

    STRICT = "STRICT"


FALLBACK_POLICY_ALIASES = {"DEFAULT": ChillingFallbackPolicy.STRICT, "STRICT": ChillingFallbackPolicy.STRICT}
# Models executable without an explicit requirement (their requirement is in the profile).
SUPPORTED_CHILLING_MODELS = frozenset({ChillingModelType.CHILLING_HOURS})
STRICT_FALLBACK_MODEL = ChillingModelType.CHILLING_HOURS
FALLBACK_REASON = "REQUESTED_MODEL_NOT_PARAMETERIZED"
_REQUEST_KEYS = ("start_policy", "chilling_model", "fallback_policy")
_CANONICAL_KEYS = ("requested_start_policy", "effective_start_policy", "start_time", "requested_chilling_model", "effective_chilling_model", "fallback_policy", "fallback_applied")
_PARAMETERIZED_KEYS = ("chilling_requirement", "model_parameter_set", "parameterization_status")
_REQUIREMENT_KEYS = ("value", "unit", "evidence")
_EQUIVALENT_KEYS = {"start_policy": "requested_start_policy", "chilling_model": "requested_chilling_model"}


def _enum_value(enum: type[StrEnum], field_name: str, raw: object) -> StrEnum:
    if not isinstance(raw, str):
        raise PhenologyError(f"dormancy.{field_name} must be a string, got {type(raw).__name__}")
    try:
        return enum(raw)
    except ValueError:
        raise PhenologyError(f"dormancy.{field_name}: unknown value {raw!r}; allowed: {', '.join(item.value for item in enum)}") from None


def _requirement(raw: object, model: ChillingModelType) -> ChillingRequirement:
    """Parse ``chilling_requirement`` for ``model``; the unit must be the model's own unit."""
    if not isinstance(raw, Mapping):
        raise PhenologyError(f"dormancy.chilling_requirement must be a mapping with {', '.join(_REQUIREMENT_KEYS)}, got {type(raw).__name__}")
    keys = set(raw)
    if keys - set(_REQUIREMENT_KEYS):
        raise PhenologyError(f"dormancy.chilling_requirement has unknown fields: {', '.join(sorted(keys - set(_REQUIREMENT_KEYS)))}")
    if set(_REQUIREMENT_KEYS) - keys:
        raise PhenologyError(f"dormancy.chilling_requirement is incomplete; missing: {', '.join(sorted(set(_REQUIREMENT_KEYS) - keys))}")
    if model is ChillingModelType.CHILLING_HOURS:
        raise PhenologyError("dormancy.chilling_requirement: model CHILLING_HOURS takes its requirement from the phenology profile (chill_hours); an explicit requirement is not accepted")
    unit = _enum_value(ChillingUnit, "chilling_requirement.unit", raw["unit"])
    expected = MODEL_SPECS[model].unit
    if unit is not expected:
        raise PhenologyError(f"dormancy.chilling_requirement.unit: model {model.value} expects '{expected.value}', received '{unit.value}'")
    evidence = raw["evidence"]
    if not isinstance(evidence, str):
        raise PhenologyError(f"dormancy.chilling_requirement.evidence must be a string, got {type(evidence).__name__}")
    if evidence != RequirementEvidence.SOFTWARE_TEST_ONLY.value:
        raise PhenologyError(f"dormancy.chilling_requirement.evidence: {evidence!r} is not accepted; no activated scientific requirement exists for {model.value} "
                             f"(literature rows are NOT_ACTIVATED); allowed: {RequirementEvidence.SOFTWARE_TEST_ONLY.value}")
    value = raw["value"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhenologyError(f"dormancy.chilling_requirement.value must be a number, got {type(value).__name__}")
    return ChillingRequirement(float(value), unit, RequirementEvidence.SOFTWARE_TEST_ONLY)


def _check_start_policy(start_policy: ChillingStartPolicyType, model: ChillingModelType) -> None:
    if model is not ChillingModelType.CHILLING_HOURS and start_policy not in STATEFUL_START_POLICIES:
        allowed = ", ".join(sorted(policy.value for policy in STATEFUL_START_POLICIES))
        raise PhenologyError(f"dormancy.start_policy: {start_policy.value} cannot be combined with an executed {model.value} model; allowed: {allowed}")


@dataclass(frozen=True, slots=True)
class DormancyConfiguration:
    """Canonical dormancy / chilling configuration (requested + effective + fallback).

    Built only by ``canonicalize_dormancy_configuration``. A requested UTAH or DYNAMIC
    model without a requirement in its own unit is IMPLEMENTED_UNPARAMETERIZED and
    resolves through the STRICT fallback to CHILLING_HOURS (Phase 5.34 behaviour);
    the request is kept for traceability. With an explicit requirement it executes.
    The start policy, profile requirement and thresholds are never changed by the
    fallback. Without a requirement the JSON is exactly the Phase 5.34 form.
    """

    requested_start_policy: ChillingStartPolicyType
    effective_start_policy: ChillingStartPolicyType
    start_time: datetime | None
    requested_chilling_model: ChillingModelType
    effective_chilling_model: ChillingModelType
    fallback_policy: ChillingFallbackPolicy
    fallback_applied: bool
    requirement: ChillingRequirement | None = None

    def __post_init__(self) -> None:
        typed = (
            (self.requested_start_policy, ChillingStartPolicyType), (self.effective_start_policy, ChillingStartPolicyType),
            (self.requested_chilling_model, ChillingModelType), (self.effective_chilling_model, ChillingModelType),
            (self.fallback_policy, ChillingFallbackPolicy), (self.fallback_applied, bool),
        )
        if not all(isinstance(value, kind) for value, kind in typed) or not (self.requirement is None or isinstance(self.requirement, ChillingRequirement)):
            raise PhenologyError("DormancyConfiguration fields have wrong types; build it with canonicalize_dormancy_configuration")
        unparameterized = self.requested_chilling_model not in SUPPORTED_CHILLING_MODELS and self.requirement is None
        expected_model = STRICT_FALLBACK_MODEL if unparameterized else self.requested_chilling_model
        if self.fallback_applied != unparameterized or self.effective_chilling_model is not expected_model or self.effective_start_policy is not self.requested_start_policy:
            raise PhenologyError("DormancyConfiguration is inconsistent with the STRICT fallback; build it with canonicalize_dormancy_configuration")
        ChillingModel(self.effective_chilling_model, self.requirement)  # unit / model compatibility
        if self.requirement is not None:
            _check_start_policy(self.effective_start_policy, self.effective_chilling_model)

    @property
    def model_parameter_set(self) -> str:
        return MODEL_SPECS[self.effective_chilling_model].parameter_set

    @property
    def parameterization_status(self) -> RequirementEvidence:
        return self.requirement.evidence if self.requirement is not None else RequirementEvidence.ENGINEERING_DEFAULT

    @property
    def requested_model_status(self) -> ChillingModelStatus:
        return ChillingModel(self.requested_chilling_model, self.requirement).status

    @property
    def fallback_reason(self) -> str | None:
        return FALLBACK_REASON if self.fallback_applied else None

    def to_dict(self) -> dict[str, object]:
        inner: dict[str, object] = {
            "requested_start_policy": self.requested_start_policy.value,
            "effective_start_policy": self.effective_start_policy.value,
            "start_time": self.start_time.isoformat() if self.start_time is not None else None,
            "requested_chilling_model": self.requested_chilling_model.value,
            "effective_chilling_model": self.effective_chilling_model.value,
            "fallback_policy": self.fallback_policy.value,
            "fallback_applied": self.fallback_applied,
        }
        if self.requirement is not None:
            inner.update({"chilling_requirement": self.requirement.to_dict(), "model_parameter_set": self.model_parameter_set,
                          "parameterization_status": self.parameterization_status.value})
        return {"dormancy": inner}

    def effective_dict(self) -> dict[str, object]:
        """What the controller runs; requests and fallback metadata excluded."""
        inner = self.to_dict()["dormancy"]
        keys = ("effective_start_policy", "start_time", "effective_chilling_model", "fallback_policy", "chilling_requirement", "model_parameter_set")
        return {"dormancy": {key: inner[key] for key in keys if key in inner}}

    def describe(self) -> dict[str, object]:
        """Full derived view (deterministic function of the canonical record)."""
        unit = MODEL_SPECS[self.effective_chilling_model].unit.value
        requirement = self.requirement.to_dict() if self.requirement is not None else {"value": None, "unit": unit, "evidence": RequirementEvidence.ENGINEERING_DEFAULT.value,
                                                                                         "source": "PhenologyProfile.chilling_requirement_hours (per crop)"}
        return {**self.to_dict()["dormancy"], "requested_model_status": self.requested_model_status.value, "fallback_reason": self.fallback_reason,
                "effective_unit": unit, "effective_requirement": requirement, "model_parameter_set": self.model_parameter_set,
                "parameterization_status": self.parameterization_status.value, "scientifically_active": False}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @property
    def configuration_hash(self) -> str:
        """SHA-256 of the full canonical record (requested, effective and fallback)."""
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @property
    def effective_hash(self) -> str:
        """SHA-256 of the effective configuration only."""
        return hashlib.sha256(json.dumps(self.effective_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    @property
    def start_policy_implemented(self) -> bool:
        return ChillingStartPolicy.is_implemented(self.effective_start_policy)

    def start_policy(self) -> ChillingStartPolicy:
        if self.effective_start_policy is ChillingStartPolicyType.DORMANCY_STATE:
            return ChillingStartPolicy()
        return ChillingStartPolicy(self.effective_start_policy, self.start_time, "canonical DormancyConfiguration")

    def chilling_model(self) -> ChillingModel:
        return ChillingModel(self.effective_chilling_model, self.requirement)

    def audit_entries(self) -> tuple[dict[str, object], ...]:
        """Configuration trace; engineering configuration, never literature or calibration."""
        described = self.describe()
        keys = ("requested_chilling_model", "effective_chilling_model", "fallback_policy", "fallback_applied", "requested_start_policy", "effective_start_policy", "start_time",
                "requested_model_status", "fallback_reason", "effective_unit", "effective_requirement", "model_parameter_set", "parameterization_status")
        return tuple({"field": key, "value": described[key], "source_type": "engineering_configuration", "calibration_status": "not_applicable"} for key in keys)


def canonicalize_dormancy_configuration(document: object) -> DormancyConfiguration:
    """The single canonicalization path for dormancy configuration.

    Accepts the request form ``{"dormancy": {start_policy, chilling_model,
    fallback_policy[, start_time][, chilling_requirement]}}`` or the canonical form
    produced by ``DormancyConfiguration.to_dict`` (round trip). Aliases (DEFAULT ->
    STRICT) are resolved, values and units validated, unparameterized models resolved
    by the STRICT fallback, and ambiguous, duplicated, missing or unknown fields rejected.
    """
    if isinstance(document, DormancyConfiguration):
        return document
    if not isinstance(document, Mapping) or set(document) != {"dormancy"}:
        raise PhenologyError("dormancy configuration must be a mapping with the single key 'dormancy'")
    body = document["dormancy"]
    if not isinstance(body, Mapping):
        raise PhenologyError("dormancy configuration 'dormancy' must be a mapping")
    keys = set(body)
    for short, long in _EQUIVALENT_KEYS.items():
        if short in keys and long in keys:
            raise PhenologyError(f"dormancy configuration is ambiguous: both {short!r} and {long!r} given")
    canonical = bool(keys & set(_CANONICAL_KEYS) - {"start_time", "fallback_policy"})
    allowed = set(_CANONICAL_KEYS) | set(_PARAMETERIZED_KEYS) if canonical else set(_REQUEST_KEYS) | {"start_time", "chilling_requirement"}
    required = set(_CANONICAL_KEYS) if canonical else set(_REQUEST_KEYS)
    if keys - allowed:
        raise PhenologyError(f"dormancy configuration has unknown fields: {', '.join(sorted(keys - allowed))}")
    if required - keys:
        raise PhenologyError(f"dormancy configuration is incomplete; missing: {', '.join(sorted(required - keys))}")
    if canonical and keys & set(_PARAMETERIZED_KEYS) and set(_PARAMETERIZED_KEYS) - keys:
        raise PhenologyError(f"dormancy configuration is incomplete; missing: {', '.join(sorted(set(_PARAMETERIZED_KEYS) - keys))}")
    start_key, model_key = ("requested_start_policy", "requested_chilling_model") if canonical else ("start_policy", "chilling_model")
    start_policy = _enum_value(ChillingStartPolicyType, start_key, body[start_key])
    requested_model = _enum_value(ChillingModelType, model_key, body[model_key])
    raw_fallback = body["fallback_policy"]
    if not isinstance(raw_fallback, str):
        raise PhenologyError(f"dormancy.fallback_policy must be a string, got {type(raw_fallback).__name__}")
    if raw_fallback not in FALLBACK_POLICY_ALIASES:
        raise PhenologyError(f"dormancy.fallback_policy: unknown value {raw_fallback!r}; allowed: {', '.join(FALLBACK_POLICY_ALIASES)}")
    fallback = FALLBACK_POLICY_ALIASES[raw_fallback]
    start_time = body.get("start_time")
    if start_time is not None:
        if not isinstance(start_time, str):
            raise PhenologyError(f"dormancy.start_time must be an ISO-8601 string or null, got {type(start_time).__name__}")
        try:
            start_time = datetime.fromisoformat(start_time)
        except ValueError:
            raise PhenologyError(f"dormancy.start_time: not an ISO-8601 instant: {body['start_time']!r}") from None
    try:
        ChillingStartPolicy(start_policy, start_time)  # FIXED_DATE requires a tz-aware instant; others take none
    except PhenologyError as exc:
        raise PhenologyError(f"dormancy.start_time: {exc}") from None
    if start_time is not None:
        start_time = start_time.astimezone(timezone.utc)  # one representation per instant
    requirement = _requirement(body["chilling_requirement"], requested_model) if "chilling_requirement" in body else None
    if requirement is not None:
        _check_start_policy(start_policy, requested_model)
    fallback_applied = requested_model not in SUPPORTED_CHILLING_MODELS and requirement is None
    effective_model = STRICT_FALLBACK_MODEL if fallback_applied else requested_model
    result = DormancyConfiguration(start_policy, start_policy, start_time, requested_model, effective_model, fallback, fallback_applied, requirement)
    if canonical:
        if not isinstance(body["fallback_applied"], bool):
            raise PhenologyError(f"dormancy.fallback_applied must be a boolean, got {type(body['fallback_applied']).__name__}")
        effective_start = _enum_value(ChillingStartPolicyType, "effective_start_policy", body["effective_start_policy"])
        effective_stated = _enum_value(ChillingModelType, "effective_chilling_model", body["effective_chilling_model"])
        if (effective_start, effective_stated, body["fallback_applied"]) != (result.effective_start_policy, result.effective_chilling_model, result.fallback_applied):
            raise PhenologyError("dormancy configuration is inconsistent: stated effective fields differ from the STRICT resolution of the request")
        if requirement is not None and (body["model_parameter_set"], body["parameterization_status"]) != (result.model_parameter_set, result.parameterization_status.value):
            raise PhenologyError(f"dormancy configuration is inconsistent: model_parameter_set/parameterization_status must be "
                                 f"{result.model_parameter_set!r}/{result.parameterization_status.value!r} for {effective_model.value}")
    return result


def parse_dormancy_configuration_json(text: str) -> DormancyConfiguration:
    """Parse JSON text, rejecting duplicated keys at any level, then canonicalize."""

    def no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        seen: dict[str, object] = {}
        for key, value in pairs:
            if key in seen:
                raise PhenologyError(f"dormancy configuration has a duplicated field: {key!r}")
            seen[key] = value
        return seen

    try:
        document = json.loads(text, object_pairs_hook=no_duplicates)
    except json.JSONDecodeError as exc:
        raise PhenologyError(f"dormancy configuration is not valid JSON: {exc.msg}") from None
    return canonicalize_dormancy_configuration(document)


DEFAULT_DORMANCY_CONFIGURATION = canonicalize_dormancy_configuration({"dormancy": {"start_policy": "DORMANCY_STATE", "chilling_model": "CHILLING_HOURS", "fallback_policy": "DEFAULT"}})


class DormancyChillingController:
    """Dormancy / chilling layer used by PhenologyEngine (not a second phenology engine).

    WHEN TO COUNT (start policy) + HOW TO COUNT (chilling model) + HOW MUCH IS REQUIRED
    (requirement in the model's unit) -> dormancy state. Time comes only from the
    caller's SimulationClock instant; no latitude, hemisphere or calendar month is used.

    Model selection goes through a canonical ``DormancyConfiguration`` (the only
    path with the STRICT fallback). Direct ``policy``/``model`` injection is kept
    for Phase 5.33 compatibility: an injected model without a requirement in its
    unit is not a selection and reports MODEL_NOT_READY, never a silent fallback.
    """

    def __init__(self, policy: ChillingStartPolicy | None = None, model: ChillingModel | None = None, *, configuration: DormancyConfiguration | Mapping[str, object] | None = None) -> None:
        if configuration is not None and (policy is not None or model is not None):
            raise PhenologyError("give either a dormancy configuration or policy/model, not both")
        if configuration is None and policy is None and model is None:
            configuration = DEFAULT_DORMANCY_CONFIGURATION
        if configuration is not None:
            self.configuration: DormancyConfiguration | None = canonicalize_dormancy_configuration(configuration)
            self.policy = self.configuration.start_policy()
            self.model = self.configuration.chilling_model()
            return
        self.policy = policy or ChillingStartPolicy()
        self.model = model or ChillingModel()
        self.configuration = None
        if self.model.ready:
            self.configuration = canonicalize_dormancy_configuration({"dormancy": {
                "start_policy": self.policy.policy_type.value, "chilling_model": self.model.model_type.value, "fallback_policy": "STRICT",
                **({"start_time": self.policy.start_time.isoformat()} if self.policy.start_time is not None else {}),
                **({"chilling_requirement": self.model.requirement.to_dict()} if self.model.requirement is not None else {}),
            }})

    def chill_state(self, state: CropGrowthState) -> ChillingAccumulation:
        """The accumulation carried by ``state`` for this controller's model."""
        if self.model.model_type is ChillingModelType.CHILLING_HOURS:
            if state.chilling_state is not None:
                raise PhenologyError(f"crop state holds {state.chilling_state.model} chill ({state.chilling_state.unit}); model CHILLING_HOURS counts chill_hours")
            return self.model.initial(state.chilling_hours)
        if state.chilling_hours != 0.0:
            raise PhenologyError(f"crop state holds chill_hours; model {self.model.model_type.value} counts {self.model.unit.value}")
        return state.chilling_state if state.chilling_state is not None else self.model.initial()

    def step(self, state: CropGrowthState, profile: PhenologyProfile, weather: WeatherState, simulation_time: datetime, dt_seconds: float) -> tuple[float, ChillingAccumulation | None, bool]:
        """One endodormant step: (chilling_hours, chilling_state, dormancy_released)."""
        requirement = self.model.required(profile)
        chill = self.chill_state(state)
        if self.policy.counting(simulation_time):
            chill = self.model.accumulate(chill, weather.temperature_c, profile, dt_seconds)
        released = chill.accumulated >= requirement
        if self.model.model_type is ChillingModelType.CHILLING_HOURS:
            return chill.accumulated, None, released
        return state.chilling_hours, chill, released


class PhenologyEngine:
    """Advance phenology only from provided weather and simulation time."""

    def __init__(self, profiles: dict[str, PhenologyProfile] | None = None, dormancy: DormancyChillingController | None = None) -> None:
        self._profiles = dict(APPROXIMATE_PROFILES if profiles is None else profiles)
        self.dormancy = dormancy or DormancyChillingController()

    @staticmethod
    def endodormant(state: CropGrowthState) -> bool:
        """Perennial dormancy not yet released by chilling: no active growth."""
        return not state.dormancy_released

    @classmethod
    def growth_active(cls, state: CropGrowthState) -> bool:
        """Active growth requires released dormancy and a non-terminal stage."""
        return not cls.endodormant(state) and state.current_stage != "post_harvest_dormancy"

    def profile_for(self, crop_key: str) -> PhenologyProfile:
        try:
            return self._profiles[crop_key.lower()]
        except KeyError as exc:
            raise PhenologyError(f"phenology profile not found: {crop_key}") from exc

    @staticmethod
    def degree_days(temperature_c: float, profile: PhenologyProfile, dt_seconds: float) -> float:
        if not math.isfinite(temperature_c) or not math.isfinite(dt_seconds) or dt_seconds < 0:
            raise PhenologyError("temperature and dt_seconds must be finite and non-negative")
        clipped_temperature = min(profile.upper_temperature_c, max(profile.base_temperature_c, temperature_c))
        return (clipped_temperature - profile.base_temperature_c) * dt_seconds / 86400.0

    def advance(
        self,
        state: CropGrowthState,
        weather: WeatherState,
        simulation_time: datetime,
        dt_seconds: float,
    ) -> CropGrowthState:
        if not isinstance(state, CropGrowthState):
            raise PhenologyError("state must be a CropGrowthState")
        if simulation_time.tzinfo is None:
            raise PhenologyError("simulation_time must be timezone-aware")
        if simulation_time != state.simulation_time + timedelta(seconds=dt_seconds):
            raise PhenologyError("simulation_time must advance by dt_seconds")
        profile = self.profile_for(state.crop_key)
        chilling = state.chilling_hours
        dormancy_released = state.dormancy_released
        if profile.perennial and not dormancy_released:
            chilling, chill_state, dormancy_released = self.dormancy.step(state, profile, weather, simulation_time, dt_seconds)
            return replace(
                state,
                simulation_time=simulation_time,
                chilling_hours=chilling,
                chilling_state=chill_state,
                dormancy_released=dormancy_released,
                phenology_model=profile.evidence_level.value,
            )
        gdd = state.gdd_accumulated + self.degree_days(weather.temperature_c, profile, dt_seconds)
        stage_index = STAGES.index(state.current_stage)
        while stage_index < len(profile.stage_gdd_targets) and gdd >= profile.stage_gdd_targets[stage_index]:
            stage_index += 1
        maturity = min(1.0, gdd / profile.maturity_gdd_target)
        return replace(
            state,
            simulation_time=simulation_time,
            current_stage=STAGES[stage_index],
            phenology_progress=self._stage_progress(gdd, profile, stage_index),
            gdd_accumulated=gdd,
            chilling_hours=chilling,
            dormancy_released=dormancy_released,
            maturity_index=max(state.maturity_index, maturity),
            phenology_model=profile.evidence_level.value,
        )

    @staticmethod
    def _stage_progress(gdd: float, profile: PhenologyProfile, stage_index: int) -> float:
        start = 0.0 if stage_index == 0 else profile.stage_gdd_targets[stage_index - 1]
        end = profile.maturity_gdd_target if stage_index == len(STAGES) - 1 else profile.stage_gdd_targets[stage_index]
        return min(1.0, max(0.0, (gdd - start) / (end - start)))