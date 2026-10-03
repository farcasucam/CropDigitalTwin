"""Chilling model policy, STRICT fallback and canonical configuration (Phase 5.34).

Qualifies the single canonical ``DormancyConfiguration`` contract of
``domain/phenology.py``: DEFAULT is an alias of STRICT; UTAH and DYNAMIC are
declared but not implemented and resolve through the one STRICT fallback to
CHILLING_HOURS, keeping the request for traceability. Runs reuse the Phase 5.33
season driver (one ``SimulationClock``/``SimulationScheduler`` per run, the
existing ``PhenologyEngine`` / ``DormancyChillingController``) and the existing
orchestrator.

Everything here is SOFTWARE_RESULT (contracts, determinism, traceability). No
chilling model, requirement, threshold, climate or date is changed, and nothing
is calibration, experimental validation or biological evidence.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from agri_twin.application.clock import SimulationClock
from agri_twin.application.dormancy_chilling_framework import (
    DEFAULT_SEED,
    LOCATIONS,
    SEASON_YEAR,
    ReplayedWeather,
    initial_dormant_state,
    location_weather,
    record_series,
    run_dormancy_season,
)
from agri_twin.application.integrated_synthetic_validation import static_audit, trajectory_hash
from agri_twin.application.orchestrator import CropDigitalTwinOrchestrator
from agri_twin.application.seasonal_synthetic_campaign import climate_profile, weather_configuration
from agri_twin.application.weather import WeatherEngine
from agri_twin.domain.calibration import ParameterSet
from agri_twin.domain.models import SoilState, WeatherState
from agri_twin.domain.water_balance import IrrigationRequest
from agri_twin.domain.parameter_audit import ParameterRegistry
from agri_twin.domain.phenology import (
    APPROXIMATE_PROFILES,
    DEFAULT_DORMANCY_CONFIGURATION,
    FALLBACK_POLICY_ALIASES,
    STRICT_FALLBACK_MODEL,
    SUPPORTED_CHILLING_MODELS,
    ChillingModel,
    ChillingModelType,
    ChillingStartPolicy,
    ChillingStartPolicyType,
    DormancyChillingController,
    PhenologyEngine,
    PhenologyError,
    canonicalize_dormancy_configuration,
    parse_dormancy_configuration_json,
)

UTC = timezone.utc
VERSION = "5.34.0"
SPECIES = ("peach", "apple", "plum")
EQUIVALENCE_LOCATIONS = ("NH_38N_MEDITERRANEAN", "SH_35S_TEMPERATE")
FIXED_DATE_INSTANT = "2025-11-01T00:00:00+00:00"  # explicit experimental protocol instant (5.33 PROTOCOL_START, north), never a default
BASELINE_ARTIFACT = Path("data") / "phenology" / "chilling_framework_report.json"
REFERENCE_LABEL = "CHILLING_HOURS+STRICT"


def _hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def request(chilling_model: str, fallback_policy: str, start_policy: str = "DORMANCY_STATE", start_time: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"start_policy": start_policy, "chilling_model": chilling_model, "fallback_policy": fallback_policy}
    if start_time is not None:
        body["start_time"] = start_time
    return {"dormancy": body}


REQUESTS: tuple[tuple[str, dict[str, Any]], ...] = (
    *((f"{model.value}+{fallback}", request(model.value, fallback)) for model in ChillingModelType for fallback in ("DEFAULT", "STRICT")),
    ("FIXED_DATE+CHILLING_HOURS+STRICT", request("CHILLING_HOURS", "STRICT", "FIXED_DATE", FIXED_DATE_INSTANT)),
    ("FIXED_DATE+DYNAMIC+STRICT", request("DYNAMIC", "STRICT", "FIXED_DATE", FIXED_DATE_INSTANT)),
    ("MODEL_DEFINED+DYNAMIC+STRICT", request("DYNAMIC", "STRICT", "MODEL_DEFINED")),
)

EXPECTED_FALLBACK = {
    "CHILLING_HOURS": ("STRICT", "CHILLING_HOURS", False),
    "DYNAMIC": ("STRICT", "CHILLING_HOURS", True),
    "UTAH": ("STRICT", "CHILLING_HOURS", True),
}
EXPECTED_ALIASES = {"DEFAULT": "STRICT", "STRICT": "STRICT"}

_BASE = {"start_policy": "DORMANCY_STATE", "chilling_model": "DYNAMIC", "fallback_policy": "STRICT"}
NEGATIVE_CASES: tuple[tuple[str, str, Any], ...] = (
    ("unknown_model", "mapping", {"dormancy": {**_BASE, "chilling_model": "DYNAMIC_APPROX"}}),
    ("unknown_fallback", "mapping", {"dormancy": {**_BASE, "fallback_policy": "LENIENT"}}),
    ("unknown_start_policy", "mapping", {"dormancy": {**_BASE, "start_policy": "FIRST_OF_NOVEMBER"}}),
    ("duplicated_json_field", "json", '{"dormancy": {"start_policy": "DORMANCY_STATE", "chilling_model": "DYNAMIC", "chilling_model": "CHILLING_HOURS", "fallback_policy": "STRICT"}}'),
    ("ambiguous_request_and_canonical_field", "mapping", {"dormancy": {**_BASE, "requested_chilling_model": "DYNAMIC"}}),
    ("incomplete_missing_fallback", "mapping", {"dormancy": {"start_policy": "DORMANCY_STATE", "chilling_model": "DYNAMIC"}}),
    ("incomplete_fixed_date_without_instant", "mapping", {"dormancy": {**_BASE, "start_policy": "FIXED_DATE"}}),
    ("missing_root_key", "mapping", dict(_BASE)),
    ("unknown_field", "mapping", {"dormancy": {**_BASE, "latitude": 38.0}}),
    ("wrong_type_model", "mapping", {"dormancy": {**_BASE, "chilling_model": 3}}),
    ("wrong_type_fallback", "mapping", {"dormancy": {**_BASE, "fallback_policy": None}}),
    ("wrong_type_body", "mapping", {"dormancy": ["DORMANCY_STATE", "DYNAMIC", "STRICT"]}),
    ("wrong_type_fallback_applied", "mapping", {"dormancy": {**DEFAULT_DORMANCY_CONFIGURATION.to_dict()["dormancy"], "fallback_applied": 0}}),
    ("out_of_domain_lowercase_model", "mapping", {"dormancy": {**_BASE, "chilling_model": "dynamic"}}),
    ("out_of_domain_naive_instant", "mapping", {"dormancy": {**_BASE, "start_policy": "FIXED_DATE", "start_time": "2025-11-01T00:00:00"}}),
    ("out_of_domain_unparseable_instant", "mapping", {"dormancy": {**_BASE, "start_policy": "FIXED_DATE", "start_time": "1 November"}}),
    ("start_time_on_non_fixed_policy", "mapping", {"dormancy": {**_BASE, "start_time": FIXED_DATE_INSTANT}}),
    ("inconsistent_canonical_effective_model", "mapping", {"dormancy": {**canonicalize_dormancy_configuration(request("DYNAMIC", "STRICT")).to_dict()["dormancy"], "effective_chilling_model": "DYNAMIC"}}),
    ("inconsistent_canonical_fallback_flag", "mapping", {"dormancy": {**canonicalize_dormancy_configuration(request("UTAH", "STRICT")).to_dict()["dormancy"], "fallback_applied": False}}),
    ("invalid_json", "json", '{"dormancy": '),
)


def _season_signature(result: Any) -> dict[str, Any]:
    return {"result": result.to_dict(), "final_state": repr(result.final_state)}


class ChillingPolicySuite:
    VERSION = VERSION

    def __init__(self, root: str | Path, *, registry: ParameterRegistry | None = None, seed: int = DEFAULT_SEED, species: Sequence[str] = SPECIES,
                 equivalence_locations: Sequence[str] = EQUIVALENCE_LOCATIONS, include_regression: bool = True, include_twin: bool = True) -> None:
        self.root = Path(root)
        self.registry = registry or ParameterRegistry.from_repository(self.root)
        self.seed = seed
        self.species = tuple(species)
        self.equivalence_locations = tuple(equivalence_locations)
        self.include_regression = include_regression
        self.include_twin = include_twin
        self._series: dict[str, list[Any]] = {}

    def _location(self, location_id: str):
        return next(item for item in LOCATIONS if item.location_id == location_id)

    def _weather(self, location_id: str) -> ReplayedWeather:
        """Recorded once per location; replays exactly the 5.33 hourly WeatherEngine values."""
        location = self._location(location_id)
        start = location.analysis_start(SEASON_YEAR)
        if location_id not in self._series:
            self._series[location_id] = record_series(location_weather(location, self.seed), start, 365)
        return ReplayedWeather(self._series[location_id], start)

    # -- configuration contract -------------------------------------------------------

    def configurations(self) -> dict[str, Any]:
        rows = []
        for label, document in REQUESTS:
            config = canonicalize_dormancy_configuration(document)
            text = config.to_json()
            round_trip = canonicalize_dormancy_configuration(config.to_dict()) == config and parse_dormancy_configuration_json(text) == config and parse_dormancy_configuration_json(text).to_json() == text
            rows.append({"label": label, "requested": copy.deepcopy(document), "canonical": config.to_dict(), "effective": config.effective_dict(),
                         "configuration_hash": config.configuration_hash, "effective_hash": config.effective_hash, "round_trip": round_trip,
                         "start_policy_implemented": config.start_policy_implemented, "audit_entries": [dict(entry) for entry in config.audit_entries()],
                         "result_type": "SOFTWARE_RESULT"})
        return {"status": "PASS" if all(row["round_trip"] for row in rows) else "FAIL", "rows": rows}

    def fallback_matrix(self) -> dict[str, Any]:
        rows = []
        for model in map(ChillingModelType, EXPECTED_FALLBACK):
            config = canonicalize_dormancy_configuration(request(model.value, "STRICT"))
            row = {"requested_model": model.value, "fallback": config.fallback_policy.value, "effective_model": config.effective_chilling_model.value, "fallback_applied": config.fallback_applied,
                   "requested_model_recorded": config.requested_chilling_model is model, "implemented": model in SUPPORTED_CHILLING_MODELS}
            row["passed"] = (row["fallback"], row["effective_model"], row["fallback_applied"]) == EXPECTED_FALLBACK[model.value] and row["requested_model_recorded"]
            rows.append(row)
        return {"status": "PASS" if all(row["passed"] for row in rows) else "FAIL", "rows": rows, "single_fallback_target": STRICT_FALLBACK_MODEL.value,
                "supported_models": sorted(model.value for model in SUPPORTED_CHILLING_MODELS)}

    def policy_alias_matrix(self) -> dict[str, Any]:
        rows = [{"policy": alias, "canonical_policy": FALLBACK_POLICY_ALIASES[alias].value, "passed": FALLBACK_POLICY_ALIASES[alias].value == EXPECTED_ALIASES[alias]} for alias in EXPECTED_ALIASES]
        pairs = []
        for model in ChillingModelType:
            default, strict = (canonicalize_dormancy_configuration(request(model.value, alias)) for alias in ("DEFAULT", "STRICT"))
            pairs.append({"chilling_model": model.value, "same_object": default == strict, "same_json": default.to_json() == strict.to_json(),
                          "same_configuration_hash": default.configuration_hash == strict.configuration_hash, "same_effective_hash": default.effective_hash == strict.effective_hash})
        dynamic, explicit = canonicalize_dormancy_configuration(request("DYNAMIC", "STRICT")), canonicalize_dormancy_configuration(request("CHILLING_HOURS", "STRICT"))
        separation = {"dynamic_vs_chilling_hours_same_effective_hash": dynamic.effective_hash == explicit.effective_hash,
                      "dynamic_vs_chilling_hours_distinct_configuration_hash": dynamic.configuration_hash != explicit.configuration_hash,
                      "dynamic_request_recorded": dynamic.requested_chilling_model is ChillingModelType.DYNAMIC}
        passed = all(row["passed"] for row in rows) and all(all(value for key, value in pair.items() if key != "chilling_model") for pair in pairs) and all(separation.values())
        return {"status": "PASS" if passed else "FAIL", "rows": rows, "default_strict_pairs": pairs, "requested_vs_effective_hash_separation": separation,
                "contract": "DEFAULT == STRICT: one policy, one code path; DEFAULT is resolved to STRICT during canonicalization"}

    def negative_cases(self) -> dict[str, Any]:
        def attempt(kind: str, value: Any) -> str | None:
            try:
                (parse_dormancy_configuration_json(value) if kind == "json" else canonicalize_dormancy_configuration(value))
            except PhenologyError as exc:
                return str(exc)
            return None

        rows = []
        for label, kind, value in NEGATIVE_CASES:
            first, second = attempt(kind, value), attempt(kind, value)
            rows.append({"case": label, "input_kind": kind, "error": first, "rejected": first is not None, "deterministic_message": first == second})
        return {"status": "PASS" if all(row["rejected"] and row["deterministic_message"] for row in rows) else "FAIL", "rows": rows}

    def unsupported_models(self) -> dict[str, Any]:
        profile = PhenologyEngine().profile_for("peach")
        rows = []
        for model in (ChillingModelType.UTAH, ChillingModelType.DYNAMIC):
            # Phase 5.35: the formulations exist, but without a requirement in their unit they cannot decide release.
            try:
                ChillingModel(model).required(profile)
                raised = False
            except PhenologyError as exc:
                raised = "MODEL_NOT_READY" in str(exc)
            injected = run_dormancy_season("peach", lambda _t: WeatherState(4.0, 70.0, 0.0, 2.0, 180.0, 0.0, 1013.0), datetime(2026, 1, 1, tzinfo=UTC), 1, model=ChillingModel(model))
            rows.append({"model": model.value, "unparameterized_raises_model_not_ready": raised, "injected_implementation_outcome": injected.outcome.value, "injected_configuration": injected.configuration})
        passed = all(row["unparameterized_raises_model_not_ready"] and row["injected_implementation_outcome"] == "MODEL_NOT_READY" and row["injected_configuration"] is None for row in rows)
        return {"status": "PASS" if passed else "FAIL", "rows": rows, "supported_models": sorted(model.value for model in SUPPORTED_CHILLING_MODELS),
                "note": "since Phase 5.35 Utah/Dynamic formulations exist but no requirement is activated; the STRICT fallback applies only to configuration requests, never to an injected model (MODEL_NOT_READY, Phase 5.33 path)"}

    # -- behaviour ------------------------------------------------------------------------

    def equivalence(self) -> dict[str, Any]:
        """Every request gives exactly the season of its effective configuration."""
        labels = dict(REQUESTS)
        rows = []
        for location_id in self.equivalence_locations:
            location = self._location(location_id)
            start = location.analysis_start(SEASON_YEAR)
            for crop in self.species:
                legacy = _season_signature(run_dormancy_season(crop, self._weather(location_id), start, 365, location=location))
                reference = _season_signature(run_dormancy_season(crop, self._weather(location_id), start, 365, location=location, configuration=labels[REFERENCE_LABEL]))
                fixed_legacy = _season_signature(run_dormancy_season(crop, self._weather(location_id), start, 365, location=location,
                                                                     policy=ChillingStartPolicy(ChillingStartPolicyType.FIXED_DATE, datetime.fromisoformat(FIXED_DATE_INSTANT), "explicit experimental protocol instant")))
                for label, document in REQUESTS:
                    result = run_dormancy_season(crop, self._weather(location_id), start, 365, location=location, configuration=document)
                    signature = _season_signature(result)
                    expected = fixed_legacy if label.startswith("FIXED_DATE") else reference
                    model_defined = label.startswith("MODEL_DEFINED")
                    rows.append({"location_id": location_id, "crop": crop, "label": label, "outcome": result.outcome.value, "trajectory_hash": result.to_dict()["trajectory_hash"],
                                 "requested_chilling_model": result.configuration.requested_chilling_model.value, "effective_chilling_model": result.configuration.effective_chilling_model.value,
                                 "fallback_applied": result.configuration.fallback_applied,
                                 "identical_to_effective_reference": (result.outcome.value == "MODEL_NOT_SUPPORTED") if model_defined else signature == expected,
                                 "identical_to_phase533_default": signature == legacy if label in {"CHILLING_HOURS+DEFAULT", "CHILLING_HOURS+STRICT", "DYNAMIC+DEFAULT", "DYNAMIC+STRICT", "UTAH+DEFAULT", "UTAH+STRICT"} else None})
        passed = all(row["identical_to_effective_reference"] and row["identical_to_phase533_default"] in {True, None} for row in rows)
        return {"status": "PASS" if passed else "FAIL", "rows": rows, "reference": REFERENCE_LABEL,
                "note": "MODEL_DEFINED is a start policy the fallback never changes: it stays MODEL_NOT_SUPPORTED; FIXED_DATE requests compare with the 5.33 FIXED_DATE path at the same instant"}

    def regression_533(self) -> dict[str, Any]:
        """DEFAULT reproduces the committed Phase 5.33 DORMANCY_STATE rows field by field."""
        path = self.root / BASELINE_ARTIFACT
        if not path.exists():
            return {"status": "FAIL", "reason": f"baseline artifact not found: {BASELINE_ARTIFACT.as_posix()}", "rows": []}
        baseline = json.loads(path.read_text(encoding="utf-8"))
        committed = {(row["location_id"], row["crop"]): {k: v for k, v in row.items() if k not in {"experiment", "requirement_h"}}
                     for row in baseline["experiments"]["policy_matrix"]["rows"] if row["experiment"] == "DORMANCY_STATE"}
        rows = []
        for location in LOCATIONS:
            start = location.analysis_start(SEASON_YEAR)
            for crop in self.species:
                if (location.location_id, crop) not in committed:
                    continue
                expected = committed[(location.location_id, crop)]
                default = json.loads(json.dumps(run_dormancy_season(crop, self._weather(location.location_id), start, 365, location=location, configuration=request("CHILLING_HOURS", "DEFAULT")).to_dict(), default=str))
                dynamic = json.loads(json.dumps(run_dormancy_season(crop, self._weather(location.location_id), start, 365, location=location, configuration=request("DYNAMIC", "STRICT")).to_dict(), default=str))
                rows.append({"location_id": location.location_id, "crop": crop, "phase533_trajectory_hash": expected["trajectory_hash"],
                             "default_identical": default == expected, "dynamic_fallback_identical": dynamic == expected})
        passed = bool(rows) and all(row["default_identical"] and row["dynamic_fallback_identical"] for row in rows)
        return {"status": "PASS" if passed else "FAIL", "baseline_artifact": BASELINE_ARTIFACT.as_posix(), "baseline_report_hash": baseline.get("report_hash"), "rows": rows,
                "comparison": "every field of each Phase 5.33 DORMANCY_STATE policy-matrix row (trajectory hash, release, budburst, chill totals, outcome)"}

    def twin_integration(self) -> dict[str, Any]:
        """Full orchestrator (crop, water, nutrients, stress) with configured PhenologyEngines."""
        start, days = datetime(2025, 11, 1, tzinfo=UTC), 150

        def run(phenology: PhenologyEngine | None) -> tuple[str, Any]:
            clock = SimulationClock(start)
            orchestrator = CropDigitalTwinOrchestrator(clock, WeatherEngine(weather_configuration(climate_profile("BASE_SEASON"), 532)), initial_dormant_state("peach", start),
                                                       SoilState(0.35, 15.0, 0.35, 0.10, 0.0, 150.0), "outdoor", phenology=phenology)
            snapshots = [orchestrator.step(3600.0, None, IrrigationRequest("scheduled", 0.4, irrigation_type="drip")) for _ in range(days * 24)]
            release = next((s.simulation_time for s in snapshots if s.crop.dormancy_released), None)
            return trajectory_hash(snapshots), release

        runs = {"phase533_default_orchestrator": run(None)}
        for label in ("CHILLING_HOURS+DEFAULT", "DYNAMIC+STRICT", "UTAH+STRICT"):
            runs[label] = run(PhenologyEngine(dormancy=DormancyChillingController(configuration=dict(REQUESTS)[label])))
        hashes = {label: value[0] for label, value in runs.items()}
        release = runs["phase533_default_orchestrator"][1]
        passed = len(set(hashes.values())) == 1 and release is not None
        return {"status": "PASS" if passed else "FAIL", "trajectory_hashes": hashes, "dormancy_release": release.isoformat() if release else None,
                "record": f"peach, BASE_SEASON seed 532, {days} days hourly from {start.isoformat()} (explicit experiment start)"}

    # -- integrity, traceability, audit --------------------------------------------------

    def _fingerprint(self) -> dict[str, str]:
        return {
            "parameter_registry": _hash([record.to_dict() for record in self.registry.records]),
            "parameter_sets": _hash({crop: ParameterSet.from_registry(self.registry, crop=crop).value_map() for crop in self.species}),
            "phenology_profiles": _hash({crop: asdict(profile) for crop, profile in APPROXIMATE_PROFILES.items()}),
            "weather_profiles": _hash({location.location_id: location.profile() for location in LOCATIONS}),
            "request_documents": _hash([document for _, document in REQUESTS]),
            "default_configuration": DEFAULT_DORMANCY_CONFIGURATION.configuration_hash,
        }

    def traceability(self) -> dict[str, Any]:
        ids = ("phenology.chilling_model", "phenology.chilling_fallback_policy", "phenology.chilling_start_policy")
        records = {parameter_id: self.registry.get(parameter_id).to_dict() for parameter_id in ids}
        forbidden = {"literature", "calibrated", "real_verified", "REAL_VERIFIED", "LITERATURE", "CALIBRATED"}
        labels_ok = all(record["source_type"] not in forbidden and record["calibration_status"] not in forbidden for record in records.values())
        default_trace = {entry["field"]: entry["value"] for entry in DEFAULT_DORMANCY_CONFIGURATION.audit_entries()}
        values_ok = records["phenology.chilling_model"]["value"] == default_trace["effective_chilling_model"] and records["phenology.chilling_fallback_policy"]["value"] == default_trace["fallback_policy"] \
            and records["phenology.chilling_start_policy"]["value"] == default_trace["effective_start_policy"]
        required = {"requested_chilling_model", "effective_chilling_model", "fallback_policy", "fallback_applied", "requested_start_policy", "effective_start_policy"}
        entries_ok = all(required <= {entry["field"] for entry in canonicalize_dormancy_configuration(document).audit_entries()} for _, document in REQUESTS)
        entry_labels_ok = all(entry["source_type"] == "engineering_configuration" for _, document in REQUESTS for entry in canonicalize_dormancy_configuration(document).audit_entries())
        return {"status": "PASS" if labels_ok and values_ok and entries_ok and entry_labels_ok else "FAIL", "registry_records": records, "default_configuration_trace": default_trace,
                "per_configuration_fields": sorted(required), "no_literature_calibrated_or_real_verified_label": labels_ok and entry_labels_ok}

    def static_audit(self) -> dict[str, Any]:
        files = ("src/agri_twin/domain/phenology.py", "src/agri_twin/application/chilling_policy.py", "src/agri_twin/application/dormancy_chilling_framework.py", "src/agri_twin/domain/parameter_audit.py")
        forbidden_calls = {"datetime.now", "datetime.utcnow", "datetime.today", "date.today", "time.time", "time.sleep", "sleep", "time.perf_counter", "perf_counter", "time.monotonic"}
        forbidden_prefixes = ("random.", "np.random.", "numpy.random.")
        forbidden_imports = {"random", "requests", "urllib", "socket", "http", "httpx", "aiohttp", "serial", "numpy.random"}
        core = ("Engine", "Clock", "Scheduler", "Registry", "Controller")
        findings, classes = [], {}
        for relative in files:
            tree = ast.parse((self.root / relative).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = _dotted(node.func)
                    if name in forbidden_calls or name.startswith(forbidden_prefixes):
                        findings.append({"file": relative, "line": node.lineno, "rule": "wall_clock_sleep_or_global_random", "detail": name})
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    for name in ([alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]):
                        if name in forbidden_imports or name.split(".")[0] in forbidden_imports - {"numpy.random"}:
                            findings.append({"file": relative, "line": node.lineno, "rule": "network_hardware_or_random_import", "detail": name})
                elif isinstance(node, ast.ClassDef) and node.name.endswith(core):
                    classes.setdefault(relative, []).append(node.name)
        new_core = classes.get("src/agri_twin/application/chilling_policy.py", [])
        project = static_audit(self.root)
        passed = not findings and not new_core and project["status"] == "PASS"
        return {"status": "PASS" if passed else "FAIL", "files": list(files), "findings": findings, "core_classes_in_files": classes, "new_core_classes": new_core,
                "rules": {"forbidden_calls": sorted(forbidden_calls), "forbidden_call_prefixes": list(forbidden_prefixes), "forbidden_imports": sorted(forbidden_imports)},
                "project_static_audit": {key: project[key] for key in ("status", "violations", "duplicate_core_classes", "missing_core_classes")}}

    # -- report ----------------------------------------------------------------------------

    def _contract_sections(self) -> dict[str, Any]:
        return {"configurations": self.configurations(), "fallback_matrix": self.fallback_matrix(), "policy_alias_matrix": self.policy_alias_matrix(),
                "negative_cases": self.negative_cases(), "unsupported_models": self.unsupported_models(), "equivalence": self.equivalence()}

    def build_report(self) -> "ChillingPolicyReport":
        before = self._fingerprint()
        sections = self._contract_sections()
        if self.include_regression:
            sections["regression_533"] = self.regression_533()
        if self.include_twin:
            sections["twin_integration"] = self.twin_integration()
        replay = self._contract_sections()
        mismatches = sorted(name for name in replay if _hash(replay[name]) != _hash(sections[name]))
        sections["determinism"] = {"status": "PASS" if not mismatches else "FAIL", "replayed_sections": sorted(replay), "mismatches": mismatches,
                                   "section_hashes": {name: _hash(sections[name]) for name in sorted(replay)}}
        sections["traceability"] = self.traceability()
        sections["static_audit"] = self.static_audit()
        after = self._fingerprint()
        sections["parameter_mutation"] = {"status": "PASS" if before == after else "FAIL", "before": before, "after": after}
        return ChillingPolicyReport(VERSION, self.seed, self.species, sections)

    def write_report(self, report: "ChillingPolicyReport", directory: str | Path | None = None) -> tuple[Path, Path]:
        output = Path(directory) if directory is not None else self.root / "data" / "phenology"
        output.mkdir(parents=True, exist_ok=True)
        report_path, readme_path = output / "chilling_policy_report.json", output / "chilling_policy_README.md"
        payload = report.to_dict()
        report_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        fallback_rows = [f"| {row['requested_model']} | {row['fallback']} | {row['effective_model']} | {str(row['fallback_applied']).lower()} |" for row in payload["software_result"]["fallback_matrix"]["rows"]]
        alias_rows = [f"| {row['policy']} | {row['canonical_policy']} |" for row in payload["software_result"]["policy_alias_matrix"]["rows"]]
        readme_path.write_text("\n".join([
            "# Chilling model policy and canonical configuration (Phase 5.34)",
            "",
            "Software qualification of the dormancy configuration contract. Every entry is SOFTWARE_RESULT; this phase produces no",
            "SCIENTIFIC_EVIDENCE. Nothing here is calibration, experimental validation or a biological claim.",
            "",
            f"- status: `{payload['status']}`",
            f"- configuration hash: `{payload['configuration_hash']}`",
            f"- report hash: `{payload['report_hash']}`",
            "",
            "Dynamic is declared but not implemented. Unsupported models use explicit STRICT fallback to CHILLING_HOURS.",
            "DEFAULT is an alias of STRICT. No biological claim is made.",
            "",
            "## Fallback matrix",
            "",
            "| Requested model | Fallback | Effective model | Fallback applied |",
            "|---|---|---|---|",
            *fallback_rows,
            "",
            "| Policy | Canonical policy |",
            "|---|---|",
            *alias_rows,
            "",
            "## Sections",
            "",
            *[f"- {name}: `{status}`" for name, status in payload["section_status"].items()],
            "",
        ]), encoding="utf-8")
        return report_path, readme_path


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


SCIENTIFIC_STATUS = (
    "PHASE 5.34 COMPLETE",
    "CHILLING MODEL POLICY QUALIFIED",
    "STRICT FALLBACK QUALIFIED",
    "DEFAULT == STRICT",
    "DYNAMIC NOT IMPLEMENTED",
    "UTAH NOT IMPLEMENTED",
    "CANONICAL CONFIGURATION QUALIFIED",
    "DETERMINISTIC CONFIGURATION HASH QUALIFIED",
    "BACKWARD COMPATIBILITY QUALIFIED",
    "REAL AGRICULTURAL DATA NOT VERIFIED",
    "CALIBRATION NOT PERFORMED",
    "EXPERIMENTAL VALIDATION DEFERRED TO FINAL VALIDATION STAGE",
    "BIOLOGICAL VALIDITY NOT CLAIMED",
    "FIELD ACCURACY NOT CLAIMED",
    "DATA ASSIMILATION NOT IMPLEMENTED",
)

OPEN_DECISIONS = (
    {"decision": "CHILLING_MODEL_SELECTION", "classification": "OPEN_SCIENTIFIC_DECISION", "detail": "only Chilling Hours is implemented; a DYNAMIC or UTAH request runs Chilling Hours (explicit STRICT fallback), so its results are in chill hours, not chill portions or chill units"},
    {"decision": "DYNAMIC_MODEL_IMPLEMENTATION", "classification": "OPEN_MODEL_CAPABILITY", "detail": "the Dynamic Model needs its published parameters and cultivar requirements in chill portions before it can be implemented; none are invented here"},
    {"decision": "UTAH_MODEL_IMPLEMENTATION", "classification": "OPEN_MODEL_CAPABILITY", "detail": "the Utah Model needs its chill-unit weights and cultivar requirements in chill units; not implemented"},
    {"decision": "UNSUPPORTED_START_POLICIES", "classification": "OPEN_MODEL_CAPABILITY", "detail": "MODEL_DEFINED and ENVIRONMENTAL_WINDOW are declared, not implemented; the fallback never changes the start policy, so they report MODEL_NOT_SUPPORTED"},
    {"decision": "CULTIVAR_REQUIREMENTS", "classification": "OPEN_SCIENTIFIC_DECISION", "detail": "requirements stay species-level engineering defaults (Phase 5.33); no cultivar calibration"},
)


@dataclass(frozen=True, slots=True)
class ChillingPolicyReport:
    version: str
    seed: int
    species: tuple[str, ...]
    sections: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        statuses = {name: value["status"] for name, value in self.sections.items()}
        software_ok = all(status == "PASS" for status in statuses.values())
        configurations = self.sections["configurations"]["rows"]
        payload = {
            "phase": "5.34",
            "version": self.version,
            "seed": self.seed,
            "status": "PASS" if software_ok else "FAIL",
            "species": list(self.species),
            "requested_configurations": {row["label"]: row["requested"] for row in configurations},
            "canonical_configurations": {row["label"]: row["canonical"] for row in configurations},
            "effective_configurations": {row["label"]: row["effective"] for row in configurations},
            "hashes": {row["label"]: {"configuration_hash": row["configuration_hash"], "effective_hash": row["effective_hash"]} for row in configurations},
            "default_configuration": DEFAULT_DORMANCY_CONFIGURATION.to_dict(),
            "configuration_hash": _hash([row["canonical"] for row in configurations]),
            "fallback_matrix": self.sections["fallback_matrix"]["rows"],
            "policy_matrix": self.sections["policy_alias_matrix"]["rows"],
            "determinism_result": self.sections["determinism"],
            "parameter_mutation_result": self.sections["parameter_mutation"],
            "regression_result": {name: self.sections[name] for name in ("regression_533", "twin_integration") if name in self.sections},
            "software_result": {name: value for name, value in self.sections.items()},
            "section_status": statuses,
            "scientific_evidence": [],
            "scientific_evidence_note": "NONE: this phase qualifies software contracts only and produces no scientific evidence",
            "scientific_status": list(SCIENTIFIC_STATUS) if software_ok else ["PHASE 5.34 NOT COMPLETE (software checks failed)", *SCIENTIFIC_STATUS[9:]],
            "contract": [
                "Dynamic is declared but not implemented.",
                "Utah is declared but not implemented.",
                "Unsupported models use explicit STRICT fallback to CHILLING_HOURS.",
                "DEFAULT is an alias of STRICT.",
                "No biological claim is made.",
            ],
            "open_scientific_decisions": [dict(item) for item in OPEN_DECISIONS],
            "limitations": [
                "A DYNAMIC or UTAH request is executed with Chilling Hours; its outputs are chill hours and carry no Dynamic or Utah meaning.",
                "Equivalence and regression are shown on synthetic Phase 5.33 locations and the Phase 5.32 BASE_SEASON climate, not on observations.",
                "Requirements, thresholds, climates and dates are unchanged Phase 5.33 engineering defaults.",
            ],
            "real_agricultural_data_verified": False,
            "calibration_performed": False,
            "experimental_validation_performed": False,
            "biological_validity_claimed": False,
            "field_accuracy_claimed": False,
            "data_assimilation_implemented": False,
        }
        payload["report_hash"] = _hash(payload)
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, default=str)


__all__ = [
    "ChillingPolicyReport",
    "ChillingPolicySuite",
    "EXPECTED_FALLBACK",
    "NEGATIVE_CASES",
    "REQUESTS",
    "request",
]
