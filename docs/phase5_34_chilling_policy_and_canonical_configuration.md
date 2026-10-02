# Phase 5.34 — Chilling model policy, STRICT fallback and canonical configuration

## Result

```text
Dynamic is declared but not implemented.
Unsupported models use explicit STRICT fallback to CHILLING_HOURS.
DEFAULT is an alias of STRICT.
No biological claim is made.

CHILLING MODEL POLICY QUALIFIED          STRICT FALLBACK QUALIFIED
CANONICAL CONFIGURATION QUALIFIED        DETERMINISTIC CONFIGURATION HASH QUALIFIED
BACKWARD COMPATIBILITY QUALIFIED         DYNAMIC / UTAH NOT IMPLEMENTED
REAL AGRICULTURAL DATA VERIFIED: NO    CALIBRATION PERFORMED: NO    BIOLOGICAL VALIDITY CLAIMED: NO
```

## 1. Why this phase

Phase 5.33 declared `UTAH` and `DYNAMIC` but left two questions open:
- what happens when a configuration requests one of them;
- what "default" means for that request.

Injecting `ChillingModel(DYNAMIC)` returned `MODEL_NOT_SUPPORTED`, and there was no
serializable configuration that could record a request. This phase fixes that with one
deterministic, auditable contract. It is a policy and configuration phase only. No
chilling model, requirement, threshold, climate profile or date changes.

## 2. DEFAULT / STRICT contract

- `ChillingFallbackPolicy` has one member, `STRICT`.
- `DEFAULT` is a public alias that canonicalization resolves to `STRICT`
  (`FALLBACK_POLICY_ALIASES`). There is no relaxed or heuristic path and no duplicated
  logic.
- After canonicalization, `DEFAULT` and `STRICT` give the same object, JSON,
  `configuration_hash`, `effective_hash` and simulation.

| Policy | Canonical policy |
|---|---|
| DEFAULT | STRICT |
| STRICT | STRICT |

## 3. STRICT fallback (one rule for every unsupported model)

`SUPPORTED_CHILLING_MODELS = {CHILLING_HOURS}`. Any other requested model resolves to
`STRICT_FALLBACK_MODEL = CHILLING_HOURS`. The canonical record keeps the request and
sets `fallback_applied = true`.

| Requested model | Fallback | Effective model | Fallback applied |
|---|---|---|---|
| CHILLING_HOURS | STRICT | CHILLING_HOURS | false |
| DYNAMIC | STRICT | CHILLING_HOURS | true |
| UTAH | STRICT | CHILLING_HOURS | true |

The fallback is deterministic, explicit, traceable and backward compatible. It never
changes any of the following:
- the start policy or its instant;
- the profile requirement;
- the 0 / 7.2 °C thresholds;
- phenology parameters or weather.

It also never uses latitude, network, wall clock or randomness.

A `DYNAMIC` or `UTAH` request produces exactly the season of an explicit
`CHILLING_HOURS` request. That season is measured in chill hours and carries no Dynamic
or Utah meaning.

There is no Dynamic or Utah formula: `ChillingModel(UTAH | DYNAMIC).increment` still
raises `MODEL_NOT_SUPPORTED`. The fallback belongs to configuration selection.
Directly injecting an unimplemented `ChillingModel` (the Phase 5.33 implementation
path) is not a selection. It keeps reporting `MODEL_NOT_SUPPORTED`, with
`configuration = None`, and never falls back silently.

Unsupported start policies (`MODEL_DEFINED`, `ENVIRONMENTAL_WINDOW`) are not changed by
the fallback. They are kept as requested and still report `MODEL_NOT_SUPPORTED`.

## 4. Canonical configuration

**Request form:** `start_time` is required for `FIXED_DATE` and forbidden for any other
start policy.

```json
{"dormancy": {"start_policy": "DORMANCY_STATE", "chilling_model": "DYNAMIC", "fallback_policy": "STRICT"}}
```

**Canonical form:** produced by `DormancyConfiguration.to_dict()`.

```json
{"dormancy": {
  "requested_start_policy": "DORMANCY_STATE", "effective_start_policy": "DORMANCY_STATE", "start_time": null,
  "requested_chilling_model": "DYNAMIC", "effective_chilling_model": "CHILLING_HOURS",
  "fallback_policy": "STRICT", "fallback_applied": true}}
```

`DormancyConfiguration` (in `domain/phenology.py`) is frozen and hashable. You can read
the request, the effective values, the policy and whether a fallback happened without
running the model. `DEFAULT_DORMANCY_CONFIGURATION` is the request
`DORMANCY_STATE + CHILLING_HOURS + DEFAULT`.

## 5. Canonicalization

`canonicalize_dormancy_configuration` is the only canonicalization path.
`parse_dormancy_configuration_json` adds rejection of duplicated JSON keys at every
level. Canonicalization:
1. accepts the request form or the canonical form;
2. resolves `DEFAULT → STRICT`;
3. validates enum values, types, the root key and unknown fields;
4. applies the STRICT fallback;
5. normalizes `start_time` to one UTC representation;
6. for the canonical form, checks that the stated effective fields equal the STRICT
   resolution;
7. rejects ambiguous inputs, such as both `chilling_model` and
   `requested_chilling_model`.

Errors are `PhenologyError` with a deterministic, field-specific message (20 negative
cases). Examples:
- `dormancy.chilling_model: unknown value 'DYNAMIC_APPROX'; allowed: CHILLING_HOURS, UTAH, DYNAMIC`
- `dormancy configuration is incomplete; missing: fallback_policy`

`DormancyConfiguration.__post_init__` rejects direct construction that is inconsistent
with the STRICT rule.

## 6. Hashing

The canonical record has two hashes:
- `configuration_hash`: SHA-256 of the full canonical JSON (requested, effective and
  fallback metadata);
- `effective_hash`: SHA-256 of what is executed (effective start policy, instant,
  effective model and fallback policy).

`DEFAULT` and `STRICT` give the same value for both hashes. `DYNAMIC + STRICT` has the
same `effective_hash` as `CHILLING_HOURS + STRICT`, but a different
`configuration_hash`, because it requested Dynamic. The report's `configuration_hash`
hashes every canonical configuration it qualifies. No timings, timestamps or ephemeral
data enter any hash.

## 7. Architecture and Phase 5.33 compatibility

```text
PhenologyEngine (existing)
  └── DormancyChillingController(configuration=DormancyConfiguration | request mapping)
        ├── ChillingStartPolicy  (effective start policy)
        └── ChillingModel        (effective model = CHILLING_HOURS)
```

The architecture is unchanged:
- no second engine, controller, clock, scheduler, registry or weather engine;
- `DormancyChillingController()` uses `DEFAULT_DORMANCY_CONFIGURATION`, and its policy and
  model equal the 5.33 defaults;
- `policy` / `model` injection still works; giving both a configuration and a
  policy/model is rejected;
- `run_dormancy_season(..., configuration=...)` is the selection path;
  `DormancySeasonResult.configuration` carries the canonical record, outside `to_dict()`
  and equality, so 5.33 rows are unchanged.

Compatibility evidence (`ChillingPolicySuite`):
- **regression_533:** `DEFAULT` and a `DYNAMIC` request reproduce every field of all 18
  committed Phase 5.33 `DORMANCY_STATE` policy-matrix rows (6 locations × 3 species),
  including trajectory hashes;
- **equivalence:** 9 requests × 3 species × 2 locations are identical to their effective
  reference and to the 5.33 default path;
- **twin_integration:** the full orchestrator (peach, BASE_SEASON seed 532, 150 days) gives
  one trajectory hash for the 5.33 default and for `CHILLING_HOURS+DEFAULT`,
  `DYNAMIC+STRICT` and `UTAH+STRICT`.

## 8. Traceability

- **New `ParameterRegistry` record:** `phenology.chilling_fallback_policy = STRICT`
  (`engineering_default`, `not_applicable`). This brings the registry to 552 records;
  `docs/parameter_audit_report.md` was regenerated.
- **Per-configuration audit:** `DormancyConfiguration.audit_entries()` records:
  - `requested_chilling_model` and `effective_chilling_model`;
  - `fallback_policy` and `fallback_applied`;
  - `requested_start_policy`, `effective_start_policy` and `start_time`.

  All are labelled `engineering_configuration`. Nothing is labelled literature,
  calibrated or real-verified.

## 9. Artifact

`data/phenology/chilling_policy_report.json` and `chilling_policy_README.md`, written by
`manual_phase5_34_chilling_policy_test.py`.

The JSON contains:
- requested, canonical and effective configurations, with their hashes;
- the fallback and policy matrices;
- determinism, parameter mutation and regression results;
- `software_result` (all sections);
- `scientific_evidence: []`, kept separate;
- the scientific status.

The manual builds the report twice and requires byte-identical JSON and an identical
SHA-256.

## 10. Limitations and open decisions

- `OPEN_SCIENTIFIC_DECISION` **CHILLING_MODEL_SELECTION:** a Dynamic or Utah request runs
  Chilling Hours, so its results are chill hours, not chill portions or chill units.
- `OPEN_MODEL_CAPABILITY` **DYNAMIC_MODEL_IMPLEMENTATION**,
  **UTAH_MODEL_IMPLEMENTATION:** both need their published parameters and cultivar
  requirements in the model's own unit. None are invented.
- `OPEN_MODEL_CAPABILITY` **UNSUPPORTED_START_POLICIES:** `MODEL_DEFINED` and
  `ENVIRONMENTAL_WINDOW` are not implemented.
- `OPEN_SCIENTIFIC_DECISION` **CULTIVAR_REQUIREMENTS:** requirements stay species-level
  engineering defaults.
- Equivalence is shown on synthetic 5.33 locations and the 5.32 climate, not on
  observations.

Experimental validation is deferred to the final validation stage. Biological validity
and field accuracy are not claimed, and data assimilation is not implemented.
