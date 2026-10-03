"""Alternative chilling models: Utah and Dynamic (Phase 5.35).

Qualifies the implementation of the published Utah and Dynamic formulations inside
the single chilling architecture (PhenologyEngine -> DormancyChillingController ->
canonical DormancyConfiguration -> ChillingModel -> accumulation -> release),
keeping five things apart:

A) implementation (``domain/chilling_models.py`` and ``ChillingModel``);
B) model parameters (published constants, registered as literature, never tuned);
C) scientific evidence (references and NOT_ACTIVATED requirement rows);
D) activation (no species requirement exists in Utah units or chill portions, so
   both models are IMPLEMENTED_UNPARAMETERIZED and requests fall back under STRICT);
E) validation (none: every run here is SOFTWARE_TEST_ONLY).

Explicit requirements labelled SOFTWARE_TEST_ONLY exercise the release logic; they
are synthetic thresholds, not species or cultivar requirements.
"""

from __future__ import annotations

import ast
import copy
import csv
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from agri_twin.application.chilling_policy import REQUESTS as PHASE534_REQUESTS
from agri_twin.application.chilling_policy import ChillingPolicySuite
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
from agri_twin.domain.chilling_models import DYNAMIC_PARAMETERS, UTAH_BANDS, UTAH_PUBLISHED_ROWS, ChillingModelError, dynamic_step, utah_weight
from agri_twin.domain.models import CropGrowthState, SoilState, WeatherState
from agri_twin.domain.parameter_audit import ParameterRegistry
from agri_twin.domain.phenology import (
    APPROXIMATE_PROFILES,
    DEFAULT_DORMANCY_CONFIGURATION,
    MODEL_SPECS,
    ChillingModel,
    ChillingModelStatus,
    ChillingModelType,
    DormancyChillingController,
    PhenologyEngine,
    PhenologyError,
    canonicalize_dormancy_configuration,
    parse_dormancy_configuration_json,
)
from agri_twin.domain.water_balance import IrrigationRequest

UTC = timezone.utc
VERSION = "5.35.0"
SPECIES = ("peach", "apple", "plum")
PERENNIALS = ("grape", "peach", "plum", "apple")
LOCATION_ID = "NH_38N_MEDITERRANEAN"
PHASE534_ARTIFACT = Path("data") / "phenology" / "chilling_policy_report.json"
SOFTWARE_TEST_ONLY = "SOFTWARE_TEST_ONLY"
# Synthetic thresholds that exercise the release logic. NOT species or cultivar
# requirements and not derived from literature; never used outside SOFTWARE_TEST_ONLY.
TEST_REQUIREMENTS = {"UTAH": 1000.0, "DYNAMIC": 50.0}
TEST_UNITS = {"UTAH": "utah_chill_units", "DYNAMIC": "chill_portions"}
PROTOCOL_INSTANT = "2025-11-01T00:00:00+00:00"  # explicit experimental instant (Phase 5.33 PROTOCOL_START, north), never a default


def _hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def request(model: str, fallback: str = "STRICT", *, start_policy: str = "DORMANCY_STATE", start_time: str | None = None, requirement: Mapping[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"start_policy": start_policy, "chilling_model": model, "fallback_policy": fallback}
    if start_time is not None:
        body["start_time"] = start_time
    if requirement is not None:
        body["chilling_requirement"] = dict(requirement)
    return {"dormancy": body}


def software_test_requirement(model: str) -> dict[str, Any]:
    return {"value": TEST_REQUIREMENTS[model], "unit": TEST_UNITS[model], "evidence": SOFTWARE_TEST_ONLY}


CONFIGURATIONS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("CHILLING_HOURS+DEFAULT", request("CHILLING_HOURS", "DEFAULT")),
    ("CHILLING_HOURS+STRICT", request("CHILLING_HOURS")),
    ("UTAH+STRICT (no requirement)", request("UTAH")),
    ("DYNAMIC+STRICT (no requirement)", request("DYNAMIC")),
    ("UTAH+STRICT+SOFTWARE_TEST_ONLY", request("UTAH", requirement=software_test_requirement("UTAH"))),
    ("DYNAMIC+STRICT+SOFTWARE_TEST_ONLY", request("DYNAMIC", requirement=software_test_requirement("DYNAMIC"))),
    ("DYNAMIC+DEFAULT+SOFTWARE_TEST_ONLY", request("DYNAMIC", "DEFAULT", requirement=software_test_requirement("DYNAMIC"))),
    ("FIXED_DATE+DYNAMIC+SOFTWARE_TEST_ONLY", request("DYNAMIC", start_policy="FIXED_DATE", start_time=PROTOCOL_INSTANT, requirement=software_test_requirement("DYNAMIC"))),
    ("FIXED_DATE+UTAH+SOFTWARE_TEST_ONLY", request("UTAH", start_policy="FIXED_DATE", start_time=PROTOCOL_INSTANT, requirement=software_test_requirement("UTAH"))),
)
# Executed seasons whose start policy lets the model reach its test threshold. Utah from the
# start of the record (a synthetic summer peak) is reported separately: warm-hour negation
# keeps its running sum negative, the reason Utah practice starts at the most negative sum
# (MODEL_DEFINED onset, an OPEN_MODEL_CAPABILITY).
EXECUTED_SEASONS = ("DYNAMIC+STRICT+SOFTWARE_TEST_ONLY", "FIXED_DATE+UTAH+SOFTWARE_TEST_ONLY")

_BASE = {"start_policy": "DORMANCY_STATE", "chilling_model": "DYNAMIC", "fallback_policy": "STRICT"}
_DYN_REQ = {"value": 50.0, "unit": "chill_portions", "evidence": SOFTWARE_TEST_ONLY}
NEGATIVE_CASES: tuple[tuple[str, str, Any], ...] = (
    ("unknown_model", "mapping", {"dormancy": {**_BASE, "chilling_model": "NORTH_CAROLINA"}}),
    ("unknown_unit", "mapping", {"dormancy": {**_BASE, "chilling_requirement": {**_DYN_REQ, "unit": "chill_minutes"}}}),
    ("incompatible_requirement_dynamic_in_hours", "mapping", {"dormancy": {**_BASE, "chilling_requirement": {**_DYN_REQ, "unit": "chill_hours"}}}),
    ("incompatible_requirement_utah_in_hours", "mapping", {"dormancy": {**_BASE, "chilling_model": "UTAH", "chilling_requirement": {**_DYN_REQ, "unit": "chill_hours"}}}),
    ("incompatible_requirement_utah_in_portions", "mapping", {"dormancy": {**_BASE, "chilling_model": "UTAH", "chilling_requirement": _DYN_REQ}}),
    ("explicit_requirement_for_chilling_hours", "mapping", {"dormancy": {**_BASE, "chilling_model": "CHILLING_HOURS", "chilling_requirement": {**_DYN_REQ, "unit": "chill_hours"}}}),
    ("requirement_missing_value", "mapping", {"dormancy": {**_BASE, "chilling_requirement": {"unit": "chill_portions", "evidence": SOFTWARE_TEST_ONLY}}}),
    ("requirement_missing_evidence", "mapping", {"dormancy": {**_BASE, "chilling_requirement": {"value": 50.0, "unit": "chill_portions"}}}),
    ("requirement_unknown_field", "mapping", {"dormancy": {**_BASE, "chilling_requirement": {**_DYN_REQ, "cultivar": "Suplum 26"}}}),
    ("requirement_wrong_type_value", "mapping", {"dormancy": {**_BASE, "chilling_requirement": {**_DYN_REQ, "value": "50"}}}),
    ("requirement_bool_value", "mapping", {"dormancy": {**_BASE, "chilling_requirement": {**_DYN_REQ, "value": True}}}),
    ("requirement_not_a_mapping", "mapping", {"dormancy": {**_BASE, "chilling_requirement": 50.0}}),
    ("requirement_out_of_domain_zero", "mapping", {"dormancy": {**_BASE, "chilling_requirement": {**_DYN_REQ, "value": 0.0}}}),
    ("requirement_out_of_domain_negative", "mapping", {"dormancy": {**_BASE, "chilling_requirement": {**_DYN_REQ, "value": -5.0}}}),
    ("requirement_out_of_domain_nan", "mapping", {"dormancy": {**_BASE, "chilling_requirement": {**_DYN_REQ, "value": math.nan}}}),
    ("requirement_unactivated_literature_evidence", "mapping", {"dormancy": {**_BASE, "chilling_requirement": {**_DYN_REQ, "evidence": "LITERATURE"}}}),
    ("requirement_engineering_default_evidence", "mapping", {"dormancy": {**_BASE, "chilling_requirement": {**_DYN_REQ, "evidence": "ENGINEERING_DEFAULT"}}}),
    ("ambiguous_request_and_canonical_field", "mapping", {"dormancy": {**_BASE, "requested_chilling_model": "DYNAMIC"}}),
    ("duplicated_requirement_field", "json", '{"dormancy": {"start_policy": "DORMANCY_STATE", "chilling_model": "DYNAMIC", "fallback_policy": "STRICT", '
                                              '"chilling_requirement": {"value": 50.0, "value": 60.0, "unit": "chill_portions", "evidence": "SOFTWARE_TEST_ONLY"}}}'),
    ("duplicated_configuration_field", "json", '{"dormancy": {"start_policy": "DORMANCY_STATE", "chilling_model": "DYNAMIC", "chilling_model": "UTAH", "fallback_policy": "STRICT"}}'),
    ("invalid_fallback", "mapping", {"dormancy": {**_BASE, "fallback_policy": "NEAREST_MODEL"}}),
    ("incompatible_start_policy_effective_onset", "mapping", {"dormancy": {**_BASE, "start_policy": "EFFECTIVE_CHILL_ONSET", "chilling_requirement": _DYN_REQ}}),
    ("incompatible_start_policy_model_defined", "mapping", {"dormancy": {**_BASE, "chilling_model": "UTAH", "start_policy": "MODEL_DEFINED", "chilling_requirement": {**_DYN_REQ, "unit": "utah_chill_units"}}}),
    ("inconsistent_canonical_parameter_set", "canonical_patch", {"model_parameter_set": "UTAH_RICHARDSON_1974"}),
    ("inconsistent_canonical_parameterization_status", "canonical_patch", {"parameterization_status": "ENGINEERING_DEFAULT"}),
    ("inconsistent_canonical_fallback_flag", "canonical_patch", {"fallback_applied": True, "effective_chilling_model": "CHILLING_HOURS"}),
    ("incomplete_canonical_parameterized_block", "canonical_drop", "parameterization_status"),
)


def _negative_document(kind: str, value: Any) -> tuple[str, Any]:
    if kind in {"canonical_patch", "canonical_drop"}:
        body = dict(canonicalize_dormancy_configuration(request("DYNAMIC", requirement=_DYN_REQ)).to_dict()["dormancy"])
        if kind == "canonical_patch":
            body.update(value)
        else:
            del body[value]
        return "mapping", {"dormancy": body}
    return kind, value


def _chillr_dynamic_reference(temperatures: Sequence[float]) -> list[float]:
    """Line-by-line transcription of the chillR / ChillModels Dynamic_Model loop
    (independent of ``dynamic_step``); like the reference, hour 1 is not integrated."""
    e0, e1, a0, a1, slp, tetmlt = 4153.5, 12888.8, 139500.0, 2.567e18, 1.6, 277.0
    aa, ee = a0 / a1, e1 - e0
    tk = [t + 273.0 for t in temperatures]
    xi = [math.exp(slp * tetmlt * (k - tetmlt) / k) / (1.0 + math.exp(slp * tetmlt * (k - tetmlt) / k)) for k in tk]
    xs = [aa * math.exp(ee / k) for k in tk]
    ak1 = [a1 * math.exp(-e1 / k) for k in tk]
    inter_e = [0.0] * len(temperatures)
    for index in range(1, len(temperatures)):
        start = inter_e[index - 1] if inter_e[index - 1] < 1 else inter_e[index - 1] - inter_e[index - 1] * xi[index - 1]
        inter_e[index] = xs[index] - (xs[index] - start) * math.exp(-ak1[index])
    return [inter_e[i] * xi[i] if inter_e[i] >= 1 else 0.0 for i in range(len(temperatures))]


def _constant(temperature: float):
    return lambda _t: WeatherState(temperature, 70.0, 0.0, 2.0, 180.0, 0.0, 1013.0)


class ChillingModelsSuite:
    VERSION = VERSION

    def __init__(self, root: str | Path, *, registry: ParameterRegistry | None = None, seed: int = DEFAULT_SEED, species: Sequence[str] = SPECIES,
                 include_regression: bool = True, include_twin: bool = True) -> None:
        self.root = Path(root)
        self.registry = registry or ParameterRegistry.from_repository(self.root)
        self.seed = seed
        self.species = tuple(species)
        self.include_regression = include_regression
        self.include_twin = include_twin
        self._series: list[WeatherState] | None = None

    def _location(self):
        return next(item for item in LOCATIONS if item.location_id == LOCATION_ID)

    def _weather(self) -> ReplayedWeather:
        location = self._location()
        start = location.analysis_start(SEASON_YEAR)
        if self._series is None:
            self._series = record_series(location_weather(location, self.seed), start, 365)
        return ReplayedWeather(self._series, start)

    # -- catalog, evidence, readiness ---------------------------------------------------

    def model_catalog(self) -> dict[str, Any]:
        rows = []
        for model_type in ChillingModelType:
            bare = ChillingModel(model_type)
            spec = MODEL_SPECS[model_type]
            rows.append({"model": model_type.value, "implemented": bare.implemented, "status_without_requirement": bare.status.value,
                         "parameterized_for_species": model_type is ChillingModelType.CHILLING_HOURS,
                         "requirement_source": "PhenologyProfile.chilling_requirement_hours (ENGINEERING_DEFAULT)" if model_type is ChillingModelType.CHILLING_HOURS else "explicit configuration only (SOFTWARE_TEST_ONLY); no activated species requirement",
                         "supported_without_explicit_requirement": bare.ready, "scientifically_active": False,
                         "unit": spec.unit.value, "thermal_input": spec.thermal_input, "time_step": spec.time_step, "validity": spec.validity, "state": spec.state,
                         "model_parameter_set": spec.parameter_set, "traceability": spec.traceability})
        passed = [row["implemented"] for row in rows] == [True, True, True] and [row["status_without_requirement"] for row in rows] == ["IMPLEMENTED_PARAMETERIZED", "IMPLEMENTED_UNPARAMETERIZED", "IMPLEMENTED_UNPARAMETERIZED"]
        return {"status": "PASS" if passed else "FAIL", "rows": rows,
                "models_available": [row["model"] for row in rows], "models_implemented": [row["model"] for row in rows if row["implemented"]],
                "models_parameterized": [row["model"] for row in rows if row["parameterized_for_species"]],
                "models_supported": [row["model"] for row in rows if row["supported_without_explicit_requirement"]],
                "models_blocked": [row["model"] for row in rows if not row["supported_without_explicit_requirement"]],
                "units_distinct": len({row["unit"] for row in rows}) == 3}

    def evidence(self) -> dict[str, Any]:
        references = [
            {"id": "RICHARDSON_1974", "reference": "Richardson, E.A., Seeley, S.D., Walker, D.R. (1974). A model for estimating the completion of rest for 'Redhaven' and 'Elberta' peach trees. HortScience 9(4), 331-332.",
             "identifier": "ISSN 0018-5345", "supports": "Utah formulation: hourly weights per temperature band", "parameters": "Utah bands and weights", "unit": "utah_chill_units",
             "species": "peach ('Redhaven', 'Elberta')", "use": "ACTIVATES_MODEL_PARAMETERS (formulation constants only)", "limitations": "original article not retrieved; table taken from the two secondary sources below"},
            {"id": "ZHANG_TAYLOR_2011", "reference": "Zhang, J., Taylor, C. (2011). The Dynamic Model provides the best description of the chill process on 'Sirora' pistachio trees in Australia. HortScience 46(3), 420-425.",
             "identifier": "HortScience 46(3):420-425", "supports": "Table 1 (Utah chill units per temperature, citing Richardson et al. 1974); Dynamic Model equations and constants (citing Erez et al. 1988; Luedeling et al. 2009)",
             "parameters": "Utah table rows; Dynamic slp, tetmlt, a0, a1, e0, e1", "unit": "utah_chill_units; chill_portions", "species": "pistachio (context only)",
             "use": "SCIENTIFIC_EVIDENCE for the formulation; no requirement used", "limitations": "pistachio requirement (59 CP) not transferable and not used"},
            {"id": "LUEDELING_BROWN_2010", "reference": "Luedeling, E., Brown, P.H. (2010). A global analysis of the comparability of winter chill models for fruit and nut trees. Int. J. Biometeorol. 55, 411-421.",
             "identifier": "doi:10.1007/s00484-010-0352-y", "supports": "Chilling Hours, Utah and Dynamic definitions; Dynamic constants slp=1.6, Tf=277, A0=139500, A1=2.567e18, E0=4153.5, E1=12888.8",
             "parameters": "Dynamic constants", "unit": "chill_hours; utah_chill_units; chill_portions", "species": "global comparison",
             "use": "SCIENTIFIC_EVIDENCE for the formulation", "limitations": "its summary lists only the 15.9 C negative band; the -1 weight above 18 C comes from Zhang & Taylor (2011) Table 1"},
            {"id": "EREZ_1990", "reference": "Erez, A., Fishman, S., Linsley-Noakes, G.C., Allan, P. (1990). The dynamic model for rest completion in peach buds. Acta Hortic. 276, 165-174.",
             "identifier": "Acta Hortic. 276:165-174", "supports": "Dynamic Model constants and chill-portion formulation", "parameters": "Dynamic constants", "unit": "chill_portions",
             "species": "peach", "use": "ACTIVATES_MODEL_PARAMETERS (formulation constants only)", "limitations": "original article not retrieved; constants as reported by Luedeling & Brown (2010) and Zhang & Taylor (2011)"},
            {"id": "FISHMAN_1987", "reference": "Fishman, S., Erez, A., Couvillon, G.A. (1987a, 1987b). The temperature dependence of dormancy breaking in plants. J. Theor. Biol. 126, 309-321; 124, 473-483.",
             "identifier": "ISSN 0022-5193", "supports": "two-step Dynamic Model structure", "parameters": "none used directly", "unit": "chill_portions", "species": "peach",
             "use": "SCIENTIFIC_EVIDENCE", "limitations": "original articles not retrieved"},
            {"id": "CHILLR_REFERENCE_IMPLEMENTATION", "reference": "Luedeling, E. chillR: Statistical Methods for Phenology Analysis in Temperate Fruit Trees (R package), Dynamic_Model(); ChillModels (Pertille et al.) dynamic_model() adapted from it.",
             "identifier": "CRAN chillR, ChillModels", "supports": "hourly loop, Kelvin conversion T + 273, transfer with the previous hour's xi", "parameters": "kelvin_offset = 273",
             "unit": "chill_portions", "species": "n/a", "use": "SOFTWARE_REFERENCE (equivalence test)", "limitations": "software, not a scientific source; used to remove implementation ambiguity"},
        ]
        rows = []
        with (self.root / "src" / "crop_phenology.csv").open(encoding="utf-8-sig") as stream:
            for row in csv.DictReader(stream):
                if row["unit"] in {"chill_portions", "utah_chill_units", "chill_units"}:
                    rows.append({key: row[key] for key in ("id", "crop", "parameter", "value", "minimum", "maximum", "unit", "reference_cultivar", "source_id", "authors", "year", "doi", "activation_status", "notes")}
                                | {"result_type": "SCIENTIFIC_EVIDENCE"})
        activated = [row["id"] for row in rows if row["activation_status"] != "NOT_ACTIVATED"]
        utah_rows = [row["id"] for row in rows if row["unit"] != "chill_portions"]
        return {"status": "PASS" if not activated else "FAIL", "references": references, "requirement_evidence_rows": rows,
                "activated_requirement_rows": activated, "utah_requirement_rows": utah_rows,
                "assessment": {
                    "UTAH": "formulation supported; no Utah chill-unit requirement for any project species exists in the repository -> IMPLEMENTED_UNPARAMETERIZED",
                    "DYNAMIC": "formulation and constants supported; chill-portion rows exist for peach, plum and apple as cultivar-group ranges (one plum cultivar value) and all are NOT_ACTIVATED -> IMPLEMENTED_UNPARAMETERIZED",
                    "CHILLING_HOURS": "profile requirements are species-level engineering defaults (Phase 5.33)"},
                "scientific_claims": []}

    def readiness_matrix(self) -> dict[str, Any]:
        engine = PhenologyEngine()
        rows = []
        for crop in PERENNIALS:
            profile = engine.profile_for(crop)
            for model_type in ChillingModelType:
                model = ChillingModel(model_type)
                try:
                    requirement, diagnostic = model.required(profile), None
                except PhenologyError as exc:
                    requirement, diagnostic = None, str(exc)
                rows.append({"crop": crop, "model": model_type.value, "unit": model.unit.value, "requirement": requirement, "status": model.status.value,
                             "evidence": "ENGINEERING_DEFAULT" if requirement is not None else "NONE_ACTIVATED", "diagnostic": diagnostic, "scientific_execution": "BLOCKED" if requirement is None else "ENGINEERING_DEFAULT_ONLY"})
        passed = all((row["requirement"] is not None) == (row["model"] == "CHILLING_HOURS") for row in rows) and all(row["diagnostic"] is None or row["diagnostic"].startswith("MODEL_NOT_READY") for row in rows)
        return {"status": "PASS" if passed else "FAIL", "rows": rows}

    # -- analytical cases ------------------------------------------------------------------

    def analytical_cases(self) -> dict[str, Any]:
        profile = PhenologyEngine().profile_for("peach")
        hours = ChillingModel()
        ch_cases = [(t, dt, hours.increment(t, profile, dt)) for t, dt in ((-0.1, 3600.0), (0.0, 3600.0), (3.0, 3600.0), (7.2, 3600.0), (7.3, 3600.0), (25.0, 3600.0), (3.0, 1800.0))]
        ch_ok = [value for _, _, value in ch_cases] == [0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.5]
        utah_points = []
        for low, high, weight in UTAH_PUBLISHED_ROWS:
            for point in (low, high):
                if math.isfinite(point):
                    utah_points.append({"temperature_c": point, "published_weight": weight, "model_weight": utah_weight(point)})
        utah_points += [{"temperature_c": t, "published_weight": None, "model_weight": utah_weight(t), "note": "between published rows: upper row (ENGINEERING_CONVENTION)"} for t in (1.45, 2.45, 9.15, 12.45, 15.95, 18.05)]
        utah_points += [{"temperature_c": t, "published_weight": w, "model_weight": utah_weight(t)} for t, w in ((-30.0, 0.0), (45.0, -1.0))]
        grid = [round(-5.0 + 0.05 * i, 2) for i in range(int(35.0 / 0.05) + 1)]
        rising = [utah_weight(t) for t in grid if t <= 9.1]
        falling = [utah_weight(t) for t in grid if t >= 2.5]
        utah_ok = all(p["published_weight"] is None or p["published_weight"] == p["model_weight"] for p in utah_points) \
            and all(a <= b for a, b in zip(rising, rising[1:])) and all(a >= b for a, b in zip(falling, falling[1:])) \
            and max(utah_weight(t) for t in grid) == 1.0 and min(utah_weight(t) for t in grid) == -1.0
        series = [6.0 + 8.0 * math.sin(h / 24.0 * 2.0 * math.pi) + (h % 7) * 0.3 for h in range(2000)]
        reference = _chillr_dynamic_reference(series)
        state, mine = (0.0, 0.0), []
        for temperature in series[1:]:
            step = dynamic_step(state[0], state[1], temperature, 3600.0)
            state = (step.intermediate, step.transfer_fraction)
            mine.append(step.portion)
        p = DYNAMIC_PARAMETERS
        tk = 6.0 + p.kelvin_offset
        xs, ak1 = (p.a0 / p.a1) * math.exp((p.e1 - p.e0) / tk), p.a1 * math.exp(-p.e1 / tk)
        one = dynamic_step(0.0, 0.0, 6.0, 3600.0)
        closed_form = one.intermediate == xs - (xs - 0.0) * math.exp(-ak1)
        cold, warm, portions, intermediates, previous = (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), [], [], 0.0
        for _ in range(1000):
            s = dynamic_step(cold[0], cold[1], 6.0, 3600.0)
            cold = (s.intermediate, s.transfer_fraction, cold[2] + s.portion)
            portions.append(cold[2])
            intermediates.append(s.intermediate)
            w = dynamic_step(warm[0], warm[1], 20.0, 3600.0)
            warm = (w.intermediate, w.transfer_fraction, warm[2] + w.portion)
        rejected = []
        for label, call in (("dt_1800", lambda: dynamic_step(0.0, 0.0, 6.0, 1800.0)), ("nan", lambda: dynamic_step(0.0, 0.0, math.nan, 3600.0)), ("below_absolute_zero", lambda: dynamic_step(0.0, 0.0, -300.0, 3600.0)),
                            ("negative_intermediate", lambda: dynamic_step(-1.0, 0.0, 6.0, 3600.0)), ("utah_dt_1800", lambda: ChillingModel(ChillingModelType.UTAH).increment(6.0, profile, 1800.0)),
                            ("utah_inf", lambda: utah_weight(math.inf))):
            try:
                call()
                rejected.append({"case": label, "rejected": False, "error": None})
            except (ChillingModelError, PhenologyError) as exc:
                rejected.append({"case": label, "rejected": True, "error": str(exc)})
        dynamic_ok = mine == reference[1:] and closed_form and all(a <= b for a, b in zip(portions, portions[1:])) and cold[2] > 0.0 and warm[2] == 0.0 \
            and all(0.0 <= value for value in intermediates) and all(row["rejected"] for row in rejected)
        return {"status": "PASS" if ch_ok and utah_ok and dynamic_ok else "FAIL", "label": SOFTWARE_TEST_ONLY,
                "chilling_hours": {"cases": [{"temperature_c": t, "dt_seconds": dt, "chill_hours": v} for t, dt, v in ch_cases], "passed": ch_ok},
                "utah": {"points": utah_points, "monotonic_rising_to_9_1": all(a <= b for a, b in zip(rising, rising[1:])), "monotonic_falling_from_2_5": all(a >= b for a, b in zip(falling, falling[1:])), "passed": utah_ok},
                "dynamic": {"reference_hours": len(mine), "per_hour_identical_to_reference_transcription": mine == reference[1:], "reference_total_cp": sum(reference), "model_total_cp": sum(mine),
                            "one_hour_closed_form_identical": closed_form, "constant_6c_1000h_cp": cold[2], "constant_20c_1000h_cp": warm[2],
                            "portions_irreversible": all(a <= b for a, b in zip(portions, portions[1:])), "passed": dynamic_ok},
                "rejections": rejected}

    # -- configuration, fallback, negatives ------------------------------------------------------

    def configurations(self) -> dict[str, Any]:
        rows = []
        for label, document in CONFIGURATIONS:
            config = canonicalize_dormancy_configuration(document)
            text = config.to_json()
            round_trip = canonicalize_dormancy_configuration(config.to_dict()) == config and parse_dormancy_configuration_json(text) == config and parse_dormancy_configuration_json(text).to_json() == text
            rows.append({"label": label, "requested": copy.deepcopy(document), "canonical": config.to_dict(), "effective": config.effective_dict(), "described": config.describe(),
                         "configuration_hash": config.configuration_hash, "effective_hash": config.effective_hash, "round_trip": round_trip, "result_type": "SOFTWARE_RESULT"})
        by = {row["label"]: row for row in rows}
        checks = {
            "default_equals_strict": by["CHILLING_HOURS+DEFAULT"]["configuration_hash"] == by["CHILLING_HOURS+STRICT"]["configuration_hash"],
            "default_equals_strict_parameterized": by["DYNAMIC+DEFAULT+SOFTWARE_TEST_ONLY"]["configuration_hash"] == by["DYNAMIC+STRICT+SOFTWARE_TEST_ONLY"]["configuration_hash"],
            "fallback_same_effective_hash": by["DYNAMIC+STRICT (no requirement)"]["effective_hash"] == by["CHILLING_HOURS+STRICT"]["effective_hash"] == by["UTAH+STRICT (no requirement)"]["effective_hash"],
            "fallback_distinct_configuration_hash": len({by[label]["configuration_hash"] for label in ("DYNAMIC+STRICT (no requirement)", "UTAH+STRICT (no requirement)", "CHILLING_HOURS+STRICT")}) == 3,
            "executed_models_distinct_effective_hash": len({by[label]["effective_hash"] for label in ("UTAH+STRICT+SOFTWARE_TEST_ONLY", "DYNAMIC+STRICT+SOFTWARE_TEST_ONLY", "CHILLING_HOURS+STRICT")}) == 3,
            "round_trip": all(row["round_trip"] for row in rows),
        }
        return {"status": "PASS" if all(checks.values()) else "FAIL", "rows": rows, "checks": checks}

    def phase534_hash_preservation(self) -> dict[str, Any]:
        path = self.root / PHASE534_ARTIFACT
        if not path.exists():
            return {"status": "FAIL", "reason": f"Phase 5.34 artifact not found: {PHASE534_ARTIFACT.as_posix()}", "rows": []}
        committed = json.loads(path.read_text(encoding="utf-8"))
        rows = []
        for label, document in PHASE534_REQUESTS:
            config = canonicalize_dormancy_configuration(document)
            expected = committed["hashes"][label]
            rows.append({"label": label, "configuration_hash_identical": config.configuration_hash == expected["configuration_hash"], "effective_hash_identical": config.effective_hash == expected["effective_hash"],
                         "canonical_identical": config.to_dict() == committed["canonical_configurations"][label]})
        passed = bool(rows) and all(all(value for key, value in row.items() if key != "label") for row in rows)
        return {"status": "PASS" if passed else "FAIL", "artifact": PHASE534_ARTIFACT.as_posix(), "phase534_configuration_hash": committed["configuration_hash"], "rows": rows}

    def fallback_matrix(self) -> dict[str, Any]:
        rows = []
        for label in ("CHILLING_HOURS+STRICT", "UTAH+STRICT (no requirement)", "DYNAMIC+STRICT (no requirement)", "UTAH+STRICT+SOFTWARE_TEST_ONLY", "DYNAMIC+STRICT+SOFTWARE_TEST_ONLY"):
            config = canonicalize_dormancy_configuration(dict(CONFIGURATIONS)[label])
            rows.append({"case": label, "requested_model": config.requested_chilling_model.value, "requested_model_status": config.requested_model_status.value,
                         "requirement": config.requirement.to_dict() if config.requirement else None, "fallback": config.fallback_policy.value,
                         "effective_model": config.effective_chilling_model.value, "fallback_applied": config.fallback_applied, "fallback_reason": config.fallback_reason,
                         "parameterization_status": config.parameterization_status.value})
        injected = []
        for model_type in (ChillingModelType.UTAH, ChillingModelType.DYNAMIC):
            result = run_dormancy_season("peach", _constant(4.0), datetime(2026, 1, 1, tzinfo=UTC), 2, model=ChillingModel(model_type))
            injected.append({"injected_model": model_type.value, "outcome": result.outcome.value, "configuration": result.configuration, "silent_fallback": result.outcome.value != "MODEL_NOT_READY"})
        expected = [("CHILLING_HOURS", False), ("CHILLING_HOURS", True), ("CHILLING_HOURS", True), ("UTAH", False), ("DYNAMIC", False)]
        passed = [(row["effective_model"], row["fallback_applied"]) for row in rows] == expected and all(not row["silent_fallback"] and row["configuration"] is None for row in injected)
        return {"status": "PASS" if passed else "FAIL", "rows": rows, "injected_without_requirement": injected,
                "distinctions": {"NOT_IMPLEMENTED": "no model is in this state since Phase 5.35", "IMPLEMENTED_UNPARAMETERIZED": "UTAH/DYNAMIC without a requirement in their unit",
                                 "IMPLEMENTED_PARAMETERIZED": "CHILLING_HOURS (profile, engineering default) or UTAH/DYNAMIC with an explicit SOFTWARE_TEST_ONLY requirement",
                                 "explicit_selection": "requested_chilling_model in the canonical record", "fallback_applied": "requested model IMPLEMENTED_UNPARAMETERIZED -> CHILLING_HOURS under STRICT"}}

    def negative_cases(self) -> dict[str, Any]:
        def attempt(kind: str, value: Any) -> str | None:
            kind, value = _negative_document(kind, value)
            try:
                (parse_dormancy_configuration_json(value) if kind == "json" else canonicalize_dormancy_configuration(value))
            except PhenologyError as exc:
                return str(exc)
            return None

        rows = []
        for label, kind, value in NEGATIVE_CASES:
            first, second = attempt(kind, value), attempt(kind, value)
            rows.append({"case": label, "error": first, "rejected": first is not None, "deterministic_message": first == second, "names_field": first is not None and "dormancy" in first})
        return {"status": "PASS" if all(row["rejected"] and row["deterministic_message"] and row["names_field"] for row in rows) else "FAIL", "rows": rows}

    # -- behaviour ----------------------------------------------------------------------------------

    def seasons(self) -> dict[str, Any]:
        location = self._location()
        start = location.analysis_start(SEASON_YEAR)
        rows = []
        for crop in self.species:
            for label in ("CHILLING_HOURS+DEFAULT", "UTAH+STRICT (no requirement)", "DYNAMIC+STRICT (no requirement)", "UTAH+STRICT+SOFTWARE_TEST_ONLY", *EXECUTED_SEASONS):
                result = run_dormancy_season(crop, self._weather(), start, 365, location=location, configuration=dict(CONFIGURATIONS)[label])
                rows.append({"crop": crop, "configuration": label, "label": SOFTWARE_TEST_ONLY, **result.to_dict()})
        by = {(row["crop"], row["configuration"]): row for row in rows}
        fallback_identical = all(by[(crop, "UTAH+STRICT (no requirement)")] == by[(crop, "CHILLING_HOURS+DEFAULT")] | {"configuration": "UTAH+STRICT (no requirement)"}
                                 and by[(crop, "DYNAMIC+STRICT (no requirement)")] == by[(crop, "CHILLING_HOURS+DEFAULT")] | {"configuration": "DYNAMIC+STRICT (no requirement)"} for crop in self.species)
        units_ok = all(("chill_total_h" in row) == (row["model"] == "CHILLING_HOURS") and (row.get("chill_unit") in {None, "utah_chill_units", "chill_portions"}) for row in rows)
        executed = [row for row in rows if row["configuration"] in EXECUTED_SEASONS]
        released = all(row["outcome"] in {"RELEASED", "RELEASED_INCOMPLETE_CONTEXT"} and row["chill_at_release"] >= TEST_REQUIREMENTS[row["model"]] for row in executed)
        ordered = released and all(row["first_effective_chill"] < row["dormancy_release"] <= row["forcing_start"] < row["budburst"] for row in executed)
        utah_from_summer = [{"crop": row["crop"], "outcome": row["outcome"], "chill_total": row["chill_total"]} for row in rows if row["configuration"] == "UTAH+STRICT+SOFTWARE_TEST_ONLY"]
        passed = fallback_identical and units_ok and released and ordered and all(row["finite"] for row in rows)
        return {"status": "PASS" if passed else "FAIL", "location_id": LOCATION_ID, "rows": rows, "fallback_rows_identical_to_chilling_hours": fallback_identical,
                "units_never_reported_as_hours": units_ok, "executed_seasons": list(EXECUTED_SEASONS), "executed_models_release_at_test_requirement": released,
                "dormancy_release_forcing_budburst_order": ordered,
                "finding_utah_from_record_start": {"rows": utah_from_summer, "classification": "MODEL_BEHAVIOUR (SOFTWARE_RESULT)",
                                                   "detail": "counting Utah units from the start of the record (synthetic summer peak) accumulates warm-hour negation; the sum stays negative and the "
                                                             "test threshold is not reached. Utah practice starts at the most negative sum (MODEL_DEFINED onset), not implemented (OPEN_MODEL_CAPABILITY); "
                                                             "the executed Utah season therefore uses an explicit FIXED_DATE protocol instant"},
                "note": "UTAH/DYNAMIC rows with SOFTWARE_TEST_ONLY use synthetic thresholds; release dates are software results, not predictions"}

    def checkpoint_restart(self) -> dict[str, Any]:
        location = self._location()
        start = location.analysis_start(SEASON_YEAR)
        rows = []
        for label in ("CHILLING_HOURS+DEFAULT", "UTAH+STRICT+SOFTWARE_TEST_ONLY", "DYNAMIC+STRICT+SOFTWARE_TEST_ONLY"):
            config = dict(CONFIGURATIONS)[label]
            continuous = run_dormancy_season("peach", self._weather(), start, 240, location=location, configuration=config)
            for split_days in (90, 150):
                first = run_dormancy_season("peach", self._weather(), start, split_days, location=location, configuration=config)
                checkpoint = json.loads(json.dumps(first.final_state.to_dict()))
                restored = CropGrowthState.from_dict(checkpoint)
                resumed = run_dormancy_season("peach", self._weather(), start + timedelta(days=split_days), 240 - split_days, location=location, configuration=config, initial=restored)
                rows.append({"configuration": label, "split_day": split_days, "checkpoint_round_trip_exact": restored == first.final_state,
                             "checkpoint_has_model_state": "chilling_state" in checkpoint if label != "CHILLING_HOURS+DEFAULT" else "chilling_state" not in checkpoint,
                             "final_state_identical": resumed.final_state == continuous.final_state, "release_identical": resumed.dormancy_release == continuous.dormancy_release})
        passed = all(all(value for key, value in row.items() if key not in {"configuration", "split_day"}) for row in rows)
        return {"status": "PASS" if passed else "FAIL", "rows": rows, "method": "checkpoint serialized through JSON (CropGrowthState.to_dict/from_dict), restarted on a new SimulationClock"}

    def twin_integration(self) -> dict[str, Any]:
        start, days = datetime(2025, 11, 1, tzinfo=UTC), 150

        def run(phenology: PhenologyEngine | None) -> tuple[str, Any, bool, bool]:
            clock = SimulationClock(start)
            orchestrator = CropDigitalTwinOrchestrator(clock, WeatherEngine(weather_configuration(climate_profile("BASE_SEASON"), 532)), initial_dormant_state("peach", start),
                                                       SoilState(0.35, 15.0, 0.35, 0.10, 0.0, 150.0), "outdoor", phenology=phenology)
            snapshots = [orchestrator.step(3600.0, None, IrrigationRequest("scheduled", 0.4, irrigation_type="drip")) for _ in range(days * 24)]
            release = next((s.simulation_time for s in snapshots if s.crop.dormancy_released), None)
            grew_before = any(s.actual_growth_g_m2 > 0 for s in snapshots if not s.crop.dormancy_released)
            grew_after = any(s.actual_growth_g_m2 > 0 for s in snapshots if s.crop.dormancy_released)
            return trajectory_hash(snapshots), release, grew_before, grew_after

        default = run(None)
        runs = {"phase533_default_orchestrator": default, "CHILLING_HOURS+DEFAULT": run(PhenologyEngine(dormancy=DormancyChillingController(configuration=dict(CONFIGURATIONS)["CHILLING_HOURS+DEFAULT"])))}
        for label in ("DYNAMIC+STRICT+SOFTWARE_TEST_ONLY", "UTAH+STRICT+SOFTWARE_TEST_ONLY"):
            first = run(PhenologyEngine(dormancy=DormancyChillingController(configuration=dict(CONFIGURATIONS)[label])))
            replay = run(PhenologyEngine(dormancy=DormancyChillingController(configuration=dict(CONFIGURATIONS)[label])))
            runs[label] = first
            runs[f"{label} replay"] = replay
        phase534 = None
        path = self.root / PHASE534_ARTIFACT
        if path.exists():
            phase534 = json.loads(path.read_text(encoding="utf-8"))["regression_result"]["twin_integration"]["trajectory_hashes"]["phase533_default_orchestrator"]
        hours_identical = default[0] == runs["CHILLING_HOURS+DEFAULT"][0] == phase534
        executed = [label for label in runs if label.endswith("SOFTWARE_TEST_ONLY")]
        gated = all(runs[label][1] is not None and not runs[label][2] and runs[label][3] for label in executed)
        deterministic = all(runs[label][0] == runs[f"{label} replay"][0] for label in executed)
        return {"status": "PASS" if hours_identical and gated and deterministic else "FAIL",
                "trajectory_hashes": {label: value[0] for label, value in runs.items()}, "phase534_committed_default_hash": phase534,
                "chilling_hours_identical_to_phase534": hours_identical, "growth_gated_by_release": gated, "deterministic_replay": deterministic,
                "dormancy_release": {label: value[1].isoformat() if value[1] else None for label, value in runs.items()},
                "record": f"peach, BASE_SEASON seed 532, {days} days hourly from {start.isoformat()}; UTAH/DYNAMIC rows SOFTWARE_TEST_ONLY"}

    def regression_533(self) -> dict[str, Any]:
        section = ChillingPolicySuite(self.root, registry=self.registry, include_twin=False).regression_533()
        return {key: section[key] for key in ("status", "baseline_artifact", "baseline_report_hash", "rows")}

    # -- integrity, traceability, audit -------------------------------------------------------

    def _fingerprint(self) -> dict[str, str]:
        return {
            "parameter_registry": _hash([record.to_dict() for record in self.registry.records]),
            "parameter_sets": _hash({crop: ParameterSet.from_registry(self.registry, crop=crop).value_map() for crop in self.species}),
            "phenology_profiles": _hash({crop: asdict(profile) for crop, profile in APPROXIMATE_PROFILES.items()}),
            "weather_profiles": _hash({location.location_id: location.profile() for location in LOCATIONS}),
            "configurations": _hash([document for _, document in CONFIGURATIONS]),
            "model_constants": _hash({"utah": [list(band) for band in UTAH_BANDS], "dynamic": asdict(DYNAMIC_PARAMETERS)}),
            "default_configuration": DEFAULT_DORMANCY_CONFIGURATION.configuration_hash,
        }

    def traceability(self) -> dict[str, Any]:
        expected: dict[str, float] = {}
        for index, (upper, weight) in enumerate(UTAH_BANDS, start=1):
            expected[f"phenology.utah.band_{index}.weight"] = weight
            if math.isfinite(upper):
                expected[f"phenology.utah.band_{index}.upper_c"] = upper
        expected.update({f"phenology.dynamic.{name}": value for name, value in asdict(DYNAMIC_PARAMETERS).items()})
        rows, problems = [], []
        for parameter_id, value in expected.items():
            try:
                record = self.registry.get(parameter_id).to_dict()
            except Exception:  # missing record
                problems.append(f"missing {parameter_id}")
                continue
            rows.append({key: record[key] for key in ("parameter_id", "value", "unit", "source_type", "source_reference", "calibration_status", "calibration_allowed")})
            if record["value"] != value:
                problems.append(f"{parameter_id}: registry {record['value']!r} != code {value!r}")
            if record["calibration_status"] in {"calibrated", "CALIBRATED"} or record["calibration_allowed"]:
                problems.append(f"{parameter_id}: must be fixed (model definition), not calibrated or tunable")
        requirement_records = sorted(record.parameter_id for record in self.registry.records if record.parameter_id.startswith("phenology.") and ("portion" in record.parameter_id or "utah_units" in record.parameter_id or "chill_units" in record.parameter_id))
        if requirement_records:
            problems.append(f"unexpected requirement records: {requirement_records}")
        calibrated = sorted(record.parameter_id for record in self.registry.records if str(record.calibration_status).lower() == "calibrated")
        if calibrated:
            problems.append(f"calibrated records exist: {calibrated}")
        return {"status": "PASS" if not problems else "FAIL", "model_parameter_records": rows, "problems": problems,
                "requirement_records_in_utah_units_or_portions": requirement_records,
                "note": "only parameters used by the implemented formulations are registered; no Utah or chill-portion requirement is registered or activated"}

    def static_audit(self) -> dict[str, Any]:
        files = ("src/agri_twin/domain/chilling_models.py", "src/agri_twin/domain/phenology.py", "src/agri_twin/domain/models.py", "src/agri_twin/domain/parameter_audit.py",
                 "src/agri_twin/application/chilling_models_framework.py", "src/agri_twin/application/chilling_policy.py", "src/agri_twin/application/dormancy_chilling_framework.py")
        forbidden_calls = {"datetime.now", "datetime.utcnow", "datetime.today", "date.today", "time.time", "time.sleep", "sleep", "time.perf_counter", "perf_counter", "time.monotonic"}
        forbidden_prefixes = ("random.", "np.random.", "numpy.random.")
        forbidden_imports = {"random", "requests", "urllib", "socket", "http", "httpx", "aiohttp", "serial"}
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
                        if name.split(".")[0] in forbidden_imports or name.startswith("numpy.random"):
                            findings.append({"file": relative, "line": node.lineno, "rule": "network_hardware_or_random_import", "detail": name})
                elif isinstance(node, ast.ClassDef) and node.name.endswith(("Engine", "Clock", "Scheduler", "Registry", "Controller")):
                    classes.setdefault(relative, []).append(node.name)
        source_root = self.root / "src" / "agri_twin"
        singletons = {name: sorted(p.relative_to(source_root.parent).as_posix() for p in source_root.rglob("*.py") for node in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
                                   if isinstance(node, ast.ClassDef) and node.name == name)
                      for name in ("PhenologyEngine", "DormancyChillingController", "ParameterRegistry", "WeatherEngine", "SimulationClock", "SimulationScheduler")}
        unique = all(len(paths) == 1 for paths in singletons.values())
        new_core = classes.get("src/agri_twin/domain/chilling_models.py", []) + classes.get("src/agri_twin/application/chilling_models_framework.py", [])
        project = static_audit(self.root)
        passed = not findings and unique and not new_core and project["status"] == "PASS"
        return {"status": "PASS" if passed else "FAIL", "files": list(files), "findings": findings, "singleton_classes": singletons, "unique_core_classes": unique, "new_core_classes": new_core,
                "rules": {"forbidden_calls": sorted(forbidden_calls), "forbidden_call_prefixes": list(forbidden_prefixes), "forbidden_imports": sorted(forbidden_imports)},
                "project_static_audit": {key: project[key] for key in ("status", "violations", "duplicate_core_classes", "missing_core_classes")}}

    # -- report -------------------------------------------------------------------------------------

    def _contract_sections(self) -> dict[str, Any]:
        return {"model_catalog": self.model_catalog(), "evidence": self.evidence(), "readiness_matrix": self.readiness_matrix(), "analytical_cases": self.analytical_cases(),
                "configurations": self.configurations(), "phase534_hash_preservation": self.phase534_hash_preservation(), "fallback_matrix": self.fallback_matrix(),
                "negative_cases": self.negative_cases(), "seasons": self.seasons(), "checkpoint_restart": self.checkpoint_restart()}

    def build_report(self) -> "ChillingModelsReport":
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
        return ChillingModelsReport(VERSION, self.seed, self.species, sections)

    def write_report(self, report: "ChillingModelsReport", directory: str | Path | None = None) -> tuple[Path, Path]:
        output = Path(directory) if directory is not None else self.root / "data" / "phenology"
        output.mkdir(parents=True, exist_ok=True)
        report_path, readme_path = output / "chilling_models_report.json", output / "chilling_models_README.md"
        payload = report.to_dict()
        report_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        catalog = payload["models"]
        readme_path.write_text("\n".join([
            "# Alternative chilling models: Utah and Dynamic (Phase 5.35)",
            "",
            "SOFTWARE_RESULT: implementation and contract qualification. SCIENTIFIC_EVIDENCE: references and NOT_ACTIVATED requirement rows.",
            "SCIENTIFIC_CLAIM: none. Nothing here is calibration, experimental validation or a biological claim.",
            "",
            f"- status: `{payload['status']}`",
            f"- configuration hash: `{payload['configuration_hash']}`",
            f"- effective hash: `{payload['effective_hash']}`",
            f"- report hash: `{payload['report_hash']}`",
            "",
            "## Models",
            "",
            "| Model | Unit | Implemented | Status without requirement | Parameterized for species | Scientifically active |",
            "|---|---|---|---|---|---|",
            *[f"| {row['model']} | {row['unit']} | {str(row['implemented']).lower()} | {row['status_without_requirement']} | {str(row['parameterized_for_species']).lower()} | false |" for row in catalog["rows"]],
            "",
            "## Fallback (STRICT)",
            "",
            "| Case | Requested | Effective | Fallback applied | Reason |",
            "|---|---|---|---|---|",
            *[f"| {row['case']} | {row['requested_model']} | {row['effective_model']} | {str(row['fallback_applied']).lower()} | {row['fallback_reason'] or '-'} |" for row in payload["fallback_matrix"]],
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


OPEN_SCIENTIFIC_DECISIONS = (
    {"decision": "CHILLING_MODEL_SELECTION", "classification": "OPEN_SCIENTIFIC_DECISION", "detail": "Chilling Hours, Utah and Dynamic are all implemented; which model represents peach, apple and plum at the project sites is not decided and needs observations"},
    {"decision": "DYNAMIC_REQUIREMENT_ACTIVATION", "classification": "OPEN_SCIENTIFIC_DECISION", "detail": "chill-portion rows (peach 49-69 CP, plum 26-51 CP and Earliqueen 30 CP, apple 40-70 / 35-88 CP) are cultivar-group ranges and NOT_ACTIVATED; activating one needs cultivar selection, not a range midpoint"},
    {"decision": "UTAH_REQUIREMENT_EVIDENCE", "classification": "OPEN_SCIENTIFIC_DECISION", "detail": "no Utah chill-unit requirement for any project species exists in the repository"},
    {"decision": "CULTIVAR_REQUIREMENTS", "classification": "OPEN_SCIENTIFIC_DECISION", "detail": "Chilling Hours requirements remain species-level engineering defaults"},
    {"decision": "UTAH_BOUNDARY_CONVENTION", "classification": "OPEN_SCIENTIFIC_DECISION", "detail": "the published Utah table has 0.1 C rows; readings between rows use an upper-row convention (ENGINEERING_CONVENTION) that reproduces every published row"},
)
OPEN_MODEL_CAPABILITIES = (
    {"capability": "UTAH_MODEL_DEFINED_ONSET", "detail": "start of Utah accumulation at the most negative running sum (MODEL_DEFINED) is not implemented; Utah/Dynamic accept DORMANCY_STATE and FIXED_DATE only"},
    {"capability": "EFFECTIVE_CHILL_ONSET_FOR_UTAH_DYNAMIC", "detail": "EFFECTIVE_CHILL_ONSET is defined only for Chilling Hours"},
    {"capability": "SUB_HOURLY_UTAH_DYNAMIC", "detail": "Utah and Dynamic are defined on hourly temperatures; other time steps are rejected (MODEL_NOT_APPLICABLE)"},
    {"capability": "DORMANCY_INDUCTION", "detail": "no transition from post-harvest into endodormancy (Phase 5.33)"},
    {"capability": "ENVIRONMENTAL_WINDOW_START_POLICY", "detail": "declared, not implemented"},
)

SCIENTIFIC_STATUS = (
    "PHASE 5.35 COMPLETE",
    "CHILLING_HOURS IMPLEMENTED, PARAMETERIZED WITH ENGINEERING DEFAULTS",
    "UTAH IMPLEMENTED (PUBLISHED FORMULATION), UNPARAMETERIZED FOR PROJECT SPECIES",
    "DYNAMIC IMPLEMENTED (PUBLISHED FORMULATION AND CONSTANTS), UNPARAMETERIZED FOR PROJECT SPECIES",
    "STRICT FALLBACK PRESERVED",
    "REAL AGRICULTURAL DATA NOT VERIFIED",
    "CALIBRATION NOT PERFORMED",
    "EXPERIMENTAL VALIDATION NOT PERFORMED",
    "BIOLOGICAL VALIDITY NOT CLAIMED",
    "FIELD ACCURACY NOT CLAIMED",
    "DATA ASSIMILATION NOT IMPLEMENTED",
)


@dataclass(frozen=True, slots=True)
class ChillingModelsReport:
    version: str
    seed: int
    species: tuple[str, ...]
    sections: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        statuses = {name: value["status"] for name, value in self.sections.items()}
        software_ok = all(status == "PASS" for status in statuses.values())
        catalog = self.sections["model_catalog"]
        configurations = self.sections["configurations"]["rows"]
        payload = {
            "phase": "5.35",
            "version": self.version,
            "seed": self.seed,
            "status": "PASS" if software_ok else "FAIL",
            "species": list(self.species),
            "models": catalog,
            "models_available": catalog["models_available"],
            "models_implemented": catalog["models_implemented"],
            "models_parameterized": catalog["models_parameterized"],
            "models_supported": catalog["models_supported"],
            "models_blocked": catalog["models_blocked"],
            "evidence": self.sections["evidence"],
            "configurations": {row["label"]: {"requested": row["requested"], "canonical": row["canonical"], "effective": row["effective"]} for row in configurations},
            "hashes": {row["label"]: {"configuration_hash": row["configuration_hash"], "effective_hash": row["effective_hash"]} for row in configurations},
            "configuration_hash": _hash([row["canonical"] for row in configurations]),
            "effective_hash": _hash([row["effective"] for row in configurations]),
            "fallback_matrix": self.sections["fallback_matrix"]["rows"],
            "case_matrix": self.sections["readiness_matrix"]["rows"],
            "results": {name: self.sections[name] for name in ("analytical_cases", "seasons", "checkpoint_restart", "twin_integration", "regression_533", "phase534_hash_preservation") if name in self.sections},
            "software_result": dict(self.sections),
            "section_status": statuses,
            "tests": {"suites": ["tests/test_chilling_models.py", "tests/test_chilling_policy.py", "tests/test_dormancy_chilling_framework.py"], "manual": "manual_phase5_35_chilling_models_test.py"},
            "scientific_evidence": self.sections["evidence"]["references"],
            "scientific_claims": [],
            "scientific_status": list(SCIENTIFIC_STATUS) if software_ok else ["PHASE 5.35 NOT COMPLETE (software checks failed)", *SCIENTIFIC_STATUS[5:]],
            "open_scientific_decisions": [dict(item) for item in OPEN_SCIENTIFIC_DECISIONS],
            "open_model_capabilities": [dict(item) for item in OPEN_MODEL_CAPABILITIES],
            "limitations": [
                "Utah and Dynamic run only with an explicit SOFTWARE_TEST_ONLY requirement; those thresholds are synthetic, not species requirements.",
                "A Utah or Dynamic request without a requirement runs Chilling Hours (STRICT fallback); its results are chill hours.",
                "Utah units, chill portions and chill hours are never converted into each other.",
                "Utah and Dynamic are hourly models; the original Richardson (1974) and Erez (1990) articles were not retrieved, so formulations are taken from secondary peer-reviewed sources and checked against the chillR reference loop.",
                "All seasons are synthetic Phase 5.33 locations and the Phase 5.32 climate, not observations.",
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
    "CONFIGURATIONS",
    "ChillingModelsReport",
    "ChillingModelsSuite",
    "NEGATIVE_CASES",
    "TEST_REQUIREMENTS",
    "request",
    "software_test_requirement",
]
