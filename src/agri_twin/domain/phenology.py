"""Deterministic thermal-time phenology without a real-time dependency."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from agri_twin.domain.models import CropGrowthState, WeatherState


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


@dataclass(frozen=True, slots=True)
class ChillingModel:
    """HOW TO COUNT. Only the Chilling Hours rule already used by the project is
    implemented; Utah and Dynamic are declared for traceability, not implemented."""

    model_type: ChillingModelType = ChillingModelType.CHILLING_HOURS
    unit: str = "chill_hours"
    temperature_resolution: str = "per simulation step, weighted by dt (hourly steps give whole hours)"
    applicability: str = "hours with air temperature in [lower, upper] C count; no negation by warm hours"
    traceability: str = "project CHILLING_HOURS rule (PhenologyProfile chilling_min/max_temperature_c); Weinberger (1950) counted hours below 7.2 C"

    @property
    def implemented(self) -> bool:
        return self.model_type is ChillingModelType.CHILLING_HOURS

    def increment(self, temperature_c: float, profile: PhenologyProfile, dt_seconds: float) -> float:
        if not self.implemented:
            raise PhenologyError(f"MODEL_NOT_SUPPORTED: chilling model {self.model_type.value} is not implemented")
        if profile.chilling_min_temperature_c <= temperature_c <= profile.chilling_max_temperature_c:
            return dt_seconds / 3600.0
        return 0.0


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
SUPPORTED_CHILLING_MODELS = frozenset({ChillingModelType.CHILLING_HOURS})
STRICT_FALLBACK_MODEL = ChillingModelType.CHILLING_HOURS
_REQUEST_KEYS = ("start_policy", "chilling_model", "fallback_policy")
_CANONICAL_KEYS = ("requested_start_policy", "effective_start_policy", "start_time", "requested_chilling_model", "effective_chilling_model", "fallback_policy", "fallback_applied")
_EQUIVALENT_KEYS = {"start_policy": "requested_start_policy", "chilling_model": "requested_chilling_model"}


def _enum_value(enum: type[StrEnum], field_name: str, raw: object) -> StrEnum:
    if not isinstance(raw, str):
        raise PhenologyError(f"dormancy.{field_name} must be a string, got {type(raw).__name__}")
    try:
        return enum(raw)
    except ValueError:
        raise PhenologyError(f"dormancy.{field_name}: unknown value {raw!r}; allowed: {', '.join(item.value for item in enum)}") from None


@dataclass(frozen=True, slots=True)
class DormancyConfiguration:
    """Canonical dormancy / chilling configuration (requested + effective + fallback).

    Built only by ``canonicalize_dormancy_configuration``. Unsupported chilling
    models resolve through the STRICT fallback to CHILLING_HOURS; the request is
    kept for traceability. The start policy, profile requirement and thresholds
    are never changed by the fallback.
    """

    requested_start_policy: ChillingStartPolicyType
    effective_start_policy: ChillingStartPolicyType
    start_time: datetime | None
    requested_chilling_model: ChillingModelType
    effective_chilling_model: ChillingModelType
    fallback_policy: ChillingFallbackPolicy
    fallback_applied: bool

    def __post_init__(self) -> None:
        typed = (
            (self.requested_start_policy, ChillingStartPolicyType), (self.effective_start_policy, ChillingStartPolicyType),
            (self.requested_chilling_model, ChillingModelType), (self.effective_chilling_model, ChillingModelType),
            (self.fallback_policy, ChillingFallbackPolicy), (self.fallback_applied, bool),
        )
        if not all(isinstance(value, kind) for value, kind in typed):
            raise PhenologyError("DormancyConfiguration fields have wrong types; build it with canonicalize_dormancy_configuration")
        unsupported = self.requested_chilling_model not in SUPPORTED_CHILLING_MODELS
        if (self.fallback_applied != unsupported or self.effective_chilling_model is not (STRICT_FALLBACK_MODEL if unsupported else self.requested_chilling_model)
                or self.effective_start_policy is not self.requested_start_policy):
            raise PhenologyError("DormancyConfiguration is inconsistent with the STRICT fallback; build it with canonicalize_dormancy_configuration")

    def to_dict(self) -> dict[str, object]:
        return {"dormancy": {
            "requested_start_policy": self.requested_start_policy.value,
            "effective_start_policy": self.effective_start_policy.value,
            "start_time": self.start_time.isoformat() if self.start_time is not None else None,
            "requested_chilling_model": self.requested_chilling_model.value,
            "effective_chilling_model": self.effective_chilling_model.value,
            "fallback_policy": self.fallback_policy.value,
            "fallback_applied": self.fallback_applied,
        }}

    def effective_dict(self) -> dict[str, object]:
        """What the controller runs; requests and fallback metadata excluded."""
        inner = self.to_dict()["dormancy"]
        return {"dormancy": {key: inner[key] for key in ("effective_start_policy", "start_time", "effective_chilling_model", "fallback_policy")}}

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
        return ChillingModel(self.effective_chilling_model)

    def audit_entries(self) -> tuple[dict[str, object], ...]:
        """Configuration trace; engineering configuration, never literature or calibration."""
        inner = self.to_dict()["dormancy"]
        keys = ("requested_chilling_model", "effective_chilling_model", "fallback_policy", "fallback_applied", "requested_start_policy", "effective_start_policy", "start_time")
        return tuple({"field": key, "value": inner[key], "source_type": "engineering_configuration", "calibration_status": "not_applicable"} for key in keys)


def canonicalize_dormancy_configuration(document: object) -> DormancyConfiguration:
    """The single canonicalization path for dormancy configuration.

    Accepts the request form ``{"dormancy": {start_policy, chilling_model,
    fallback_policy[, start_time]}}`` or the canonical form produced by
    ``DormancyConfiguration.to_dict`` (round trip). Aliases (DEFAULT -> STRICT)
    are resolved, values validated, unsupported models resolved by the STRICT
    fallback, and ambiguous, duplicated, missing or unknown fields rejected.
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
    allowed = set(_CANONICAL_KEYS) if canonical else set(_REQUEST_KEYS) | {"start_time"}
    required = set(_CANONICAL_KEYS) if canonical else set(_REQUEST_KEYS)
    if keys - allowed:
        raise PhenologyError(f"dormancy configuration has unknown fields: {', '.join(sorted(keys - allowed))}")
    if required - keys:
        raise PhenologyError(f"dormancy configuration is incomplete; missing: {', '.join(sorted(required - keys))}")
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
    fallback_applied = requested_model not in SUPPORTED_CHILLING_MODELS
    effective_model = STRICT_FALLBACK_MODEL if fallback_applied else requested_model
    result = DormancyConfiguration(start_policy, start_policy, start_time, requested_model, effective_model, fallback, fallback_applied)
    if canonical:
        if not isinstance(body["fallback_applied"], bool):
            raise PhenologyError(f"dormancy.fallback_applied must be a boolean, got {type(body['fallback_applied']).__name__}")
        effective_start = _enum_value(ChillingStartPolicyType, "effective_start_policy", body["effective_start_policy"])
        effective_stated = _enum_value(ChillingModelType, "effective_chilling_model", body["effective_chilling_model"])
        if (effective_start, effective_stated, body["fallback_applied"]) != (result.effective_start_policy, result.effective_chilling_model, result.fallback_applied):
            raise PhenologyError("dormancy configuration is inconsistent: stated effective fields differ from the STRICT resolution of the request")
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
    (profile requirement) -> dormancy state. Time comes only from the caller's
    SimulationClock instant; no latitude, hemisphere or calendar month is used.

    Model selection goes through a canonical ``DormancyConfiguration`` (the only
    path with the STRICT fallback). Direct ``policy``/``model`` injection is kept
    for Phase 5.33 compatibility: an injected unimplemented model is not a
    selection and still reports MODEL_NOT_SUPPORTED, never a silent fallback.
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
        if self.model.implemented:
            self.configuration = canonicalize_dormancy_configuration({"dormancy": {
                "start_policy": self.policy.policy_type.value, "chilling_model": self.model.model_type.value, "fallback_policy": "STRICT",
                **({"start_time": self.policy.start_time.isoformat()} if self.policy.start_time is not None else {}),
            }})

    def advance(self, chilling_hours: float, profile: PhenologyProfile, weather: WeatherState, simulation_time: datetime, dt_seconds: float) -> tuple[float, bool]:
        if self.policy.counting(simulation_time):
            chilling_hours += self.model.increment(weather.temperature_c, profile, dt_seconds)
        return chilling_hours, chilling_hours >= profile.chilling_requirement_hours


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
            chilling, dormancy_released = self.dormancy.advance(chilling, profile, weather, simulation_time, dt_seconds)
            return replace(
                state,
                simulation_time=simulation_time,
                chilling_hours=chilling,
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