# Phase 5.35 — Alternative chilling models: Utah and Dynamic

## Result

```text
CHILLING_HOURS  implemented, parameterized with species-level ENGINEERING_DEFAULT requirements (unchanged)
UTAH            implemented (published formulation), UNPARAMETERIZED for every project species
DYNAMIC         implemented (published formulation and constants), UNPARAMETERIZED for every project species
STRICT FALLBACK preserved: an unparameterized UTAH/DYNAMIC request runs CHILLING_HOURS, request kept
REAL AGRICULTURAL DATA VERIFIED: NO    CALIBRATION PERFORMED: NO    EXPERIMENTAL VALIDATION PERFORMED: NO
BIOLOGICAL VALIDITY CLAIMED: NO        FIELD ACCURACY CLAIMED: NO   DATA ASSIMILATION IMPLEMENTED: NO
```

A mathematically implemented model is not a scientifically validated model. A
literature parameter is not a calibration. A synthetic test is not experimental
validation.

## 1. Objective

Phase 5.35 adds computational capability for the Utah and Dynamic chilling models
without fabricating evidence. It keeps five layers separate:
- **Implementation:** `domain/chilling_models.py` and `ChillingModel`.
- **Model parameters:** published constants, registered as fixed literature values.
- **Scientific evidence:** references, plus requirement rows that remain `NOT_ACTIVATED`.
- **Activation:** none. No species requirement exists in Utah units or chill portions.
- **Validation:** none. Every run here is `SOFTWARE_TEST_ONLY`.

Three result categories are reported separately:
- `SOFTWARE_RESULT`: the qualification sections of `data/phenology/chilling_models_report.json`.
- `SCIENTIFIC_EVIDENCE`: references and `crop_phenology.csv` requirement rows.
- `SCIENTIFIC_CLAIM`: none.

## 2. Evidence audit (before implementation)

What the repository already held:
- Citations of Richardson et al. (1974) and Fishman, Erez & Couvillon (1987), with no
  formulation or constants (`docs/phase5_33_chilling_start_scientific_decision.md`).
- `src/crop_phenology.csv` chill-portion rows, all `NOT_ACTIVATED`:
  - peach 49–69 CP (14 cultivars, SRC-011);
  - plum 26–51 CP (21 cultivars) and 'Earliqueen' 30 CP (SRC-014);
  - apple 40–70 CP (review, SRC-016) and 35–88 CP (12 cultivars, SRC-017).
- No Utah chill-unit requirement for any species.

External sources consulted (the project already uses external literature research,
`src/crop_phenology.md`):

| Source | Supports | Use |
|---|---|---|
| Richardson, Seeley & Walker (1974) HortScience 9:331–332 | Utah weights | model parameters (original not retrieved) |
| Zhang & Taylor (2011) HortScience 46(3):420–425, Table 1 | Utah table rows incl. −1 above 18 °C; Dynamic equations and constants | formulation source |
| Luedeling & Brown (2010) Int. J. Biometeorol. 55:411–421, doi:10.1007/s00484-010-0352-y | CH, Utah, Dynamic definitions; Dynamic constants | formulation source |
| Erez, Fishman, Linsley-Noakes & Allan (1990) Acta Hortic. 276:165–174 | Dynamic constants | model parameters (original not retrieved) |
| Fishman, Erez & Couvillon (1987a,b) J. Theor. Biol. 124:473–483, 126:309–321 | two-step structure | evidence |
| chillR `Dynamic_Model` / ChillModels `dynamic_model` | hourly loop, T + 273, transfer with previous hour's ξ | software reference (equivalence test only) |

The pistachio requirement in Zhang & Taylor (59 CP) is not transferable and is not used.

## 3. Architecture

```text
PhenologyEngine (existing)
  └── DormancyChillingController.step(state, profile, weather, t, dt)   (existing, single path)
        ├── canonical DormancyConfiguration                              (Phase 5.34, extended)
        ├── ChillingStartPolicy                                          WHEN TO COUNT
        └── ChillingModel(model_type, requirement)                       HOW TO COUNT / HOW MUCH
              └── accumulate(): CHILLING_HOURS | utah_step | dynamic_step (domain/chilling_models.py)
      → CropGrowthState.chilling_hours  (chill hours)
      → CropGrowthState.chilling_state  (Utah units or chill portions + Dynamic state; None for CH)
      → dormancy_released
```

The single architecture is preserved:
- one `PhenologyEngine`, one `DormancyChillingController`, one registry, one
  `WeatherEngine`, one clock and one scheduler;
- `ChillingModel.accumulate` is the only accumulation path for all three models;
- `DormancyChillingController.step` is the only dormancy update;
- time comes only from the caller's `SimulationClock`.

## 4. Formulations

**Chilling Hours** (unchanged):
- 1 chill hour per hour with 0 ≤ T ≤ 7.2 °C;
- dt-weighted;
- unit `chill_hours`.

**Utah** (`utah_chill_units`): hourly weights per temperature band.

| T (°C) | ≤ 1.4 | 1.5–2.4 | 2.5–9.1 | 9.2–12.4 | 12.5–15.9 | 16–18 | > 18 |
|---|---|---|---|---|---|---|---|
| units/h | 0 | 0.5 | 1 | 0.5 | 0 | −0.5 | −1 |

- The running sum can be negative.
- Readings between the published 0.1 °C rows (e.g. 2.45 °C) use bands that are
  lower-exclusive and upper-inclusive. This is an `ENGINEERING_CONVENTION`, and it
  reproduces every published row.
- Hourly steps only.

**Dynamic** (`chill_portions`), one hour at a time:

```text
TK = T + 273
xi = e^f / (1 + e^f),   f = slope · Tf · (TK − Tf) / TK
xs = (A0/A1) e^((E1 − E0)/TK)
k1 = A1 e^(−E1/TK)
S  = E(t−1) if E(t−1) < 1, else E(t−1) (1 − xi(t−1))
E(t) = xs − (xs − S) e^(−k1)
portion(t) = xi(t) · E(t) if E(t) ≥ 1, else 0
```

- Constants: E0 = 4153.5, E1 = 12888.8, A0 = 139500, A1 = 2.567·10¹⁸, slope = 1.6,
  Tf = 277 K.
- State: intermediate `E`, previous transfer fraction `xi` and accumulated portions.
  It is stored in `CropGrowthState.chilling_state` and is JSON-serializable
  (`ChillingAccumulation.to_dict/from_dict`, `CropGrowthState.from_dict`), so
  checkpoint/restart is exact.
- Hourly steps only.
- Equivalence with the chillR reference loop is exact hour by hour (1 999 hours;
  like chillR, its first hour is not integrated).
- The one-hour closed form is exact.
- At a constant 6 °C the model gives 34.2 CP per 1000 h; at 20 °C it gives 0.

**Units are never converted.** Utah units and chill portions are never reported as
hours: season rows for these models use `chill_unit` / `chill_total` instead of
`chill_total_h`.

## 5. Readiness, requirements and fallback

| State | Meaning |
|---|---|
| `NOT_IMPLEMENTED` | no model since 5.35 |
| `IMPLEMENTED_UNPARAMETERIZED` | UTAH/DYNAMIC without a requirement in their unit (all species) |
| `IMPLEMENTED_PARAMETERIZED` | CHILLING_HOURS (profile, `ENGINEERING_DEFAULT`), or UTAH/DYNAMIC with an explicit `SOFTWARE_TEST_ONLY` requirement |

Requirement rules (the canonical parser rejects anything else):
- **Chilling Hours:** the requirement comes only from the profile; an explicit
  requirement is rejected.
- **Utah:** only `utah_chill_units`.
- **Dynamic:** only `chill_portions`.
- **Evidence:** only `SOFTWARE_TEST_ONLY` is accepted. `LITERATURE`, `CALIBRATED`,
  `REAL_VERIFIED` and `ENGINEERING_DEFAULT` are rejected because no requirement is
  activated.
- **Error format:** errors name the field, model, expected unit and received unit, e.g.
  `dormancy.chilling_requirement.unit: model DYNAMIC expects 'chill_portions', received 'chill_hours'`.

STRICT fallback (unchanged rule, now with an explicit reason):

| Case | Requested | Effective | Fallback applied | Reason |
|---|---|---|---|---|
| CHILLING_HOURS | CHILLING_HOURS | CHILLING_HOURS | false | – |
| UTAH, no requirement | UTAH | CHILLING_HOURS | true | REQUESTED_MODEL_NOT_PARAMETERIZED |
| DYNAMIC, no requirement | DYNAMIC | CHILLING_HOURS | true | REQUESTED_MODEL_NOT_PARAMETERIZED |
| UTAH + SOFTWARE_TEST_ONLY requirement | UTAH | UTAH | false | – |
| DYNAMIC + SOFTWARE_TEST_ONLY requirement | DYNAMIC | DYNAMIC | false | – |

An injected `ChillingModel(UTAH|DYNAMIC)` without a requirement reports
`MODEL_NOT_READY` (new `DormancyOutcome`), with `configuration = None`. It never falls
back silently.

Utah and Dynamic accept only the `DORMANCY_STATE` and `FIXED_DATE` start policies.
`EFFECTIVE_CHILL_ONSET`, `MODEL_DEFINED` and `ENVIRONMENTAL_WINDOW` are rejected for
an executed Utah or Dynamic model.

## 6. Canonical configuration and hashes

The Phase 5.34 form is unchanged. A request without `chilling_requirement` serializes
byte for byte as in 5.34: all 9 Phase 5.34 configurations keep their committed
`configuration_hash`, `effective_hash` and canonical JSON.

A parameterized request adds three fields:

```json
"chilling_requirement": {"value": 50.0, "unit": "chill_portions", "evidence": "SOFTWARE_TEST_ONLY"},
"model_parameter_set": "DYNAMIC_EREZ_1990",
"parameterization_status": "SOFTWARE_TEST_ONLY"
```

`describe()` and `audit_entries()` add derived fields:
- `requested_model_status` and `fallback_reason`;
- `effective_unit` and `effective_requirement`;
- `scientifically_active: false`.

Hash behaviour:

| Comparison | `effective_hash` | `configuration_hash` |
|---|---|---|
| DEFAULT vs STRICT | same | same |
| unparameterized DYNAMIC/UTAH vs CHILLING_HOURS (fallback) | same | differs |
| executed UTAH/DYNAMIC vs CHILLING_HOURS | differs | differs |

## 7. Traceability

`ParameterRegistry` gains 20 records (552 → 572; literature 37 → 57):
- `phenology.utah.band_N.weight` (7) and `phenology.utah.band_N.upper_c` (6);
- `phenology.dynamic.{e0,e1,a0,a1,slope,tf,kelvin_offset}` (7).

All are `source_type = literature`, `calibration_status = fixed` and not tunable.
`kelvin_offset` is labelled a software convention of the reference implementation.

No requirement in Utah units or chill portions is registered or activated, and no
record is `calibrated`. The notes of `phenology.chilling_model` and
`phenology.chilling_fallback_policy` were updated; their values are unchanged.

## 8. Software results (`SOFTWARE_TEST_ONLY`)

**Synthetic test thresholds:** UTAH 1000 units and DYNAMIC 50 CP. They are not species
requirements and not derived from literature.

**Seasons** (synthetic NH_38N location, peach, apple and plum):
- Unparameterized UTAH/DYNAMIC requests are row-identical to Chilling Hours.
- Dynamic releases at ≥ 50 CP.
- Utah with a FIXED_DATE protocol instant (1 Nov) releases at ≥ 1000 units.
- Order is first chill < release ≤ forcing < budburst.

**Finding:** Utah counted from the record start (a synthetic summer peak) reaches about
−3000 units and never releases. This is warm-hour negation, and the reason Utah
practice starts at the most negative sum. That onset (`MODEL_DEFINED`) is not
implemented.

**Checkpoint/restart:** restarting through JSON at day 90 or 150 gives exactly the
continuous final state and release, for Chilling Hours, Utah and Dynamic.

**Full twin** (orchestrator, peach, BASE_SEASON seed 532, 150 days):
- Chilling Hours reproduces the committed Phase 5.34 trajectory hash.
- Dynamic and Utah test runs release (14 Feb / 1 Mar), show no growth before release,
  show growth after it, and replay deterministically.

**Regression:**
- All 18 Phase 5.33 `DORMANCY_STATE` artifact rows are reproduced field by field.
- Phase 5.33 and 5.34 tests pass.
- Three historical assertions that stated Utah/Dynamic were *not implemented* were
  updated to the new truth (`MODEL_NOT_READY`; the no-silent-fallback intent is
  unchanged), and so was the 5.34 suite's `unsupported_models` section.
- Historical 5.33/5.34 artifacts were regenerated by their manuals (PASS) and then
  restored to the committed versions.

## 9. What is implemented, parameterized, scientifically supported

| | Implemented | Model constants | Species requirement | Scientifically active |
|---|---|---|---|---|
| CHILLING_HOURS | yes | profile thresholds (engineering default) | species-level engineering default | no |
| UTAH | yes | literature (Richardson 1974 via Zhang & Taylor 2011) | none | no |
| DYNAMIC | yes | literature (Erez et al. 1990 via Luedeling & Brown 2010) | none activated (ranges, NOT_ACTIVATED) | no |

## 10. Open items

**OPEN_SCIENTIFIC_DECISION**
- Chilling model selection per species and site.
- Activation of a Dynamic requirement: it needs cultivar selection, not a range midpoint.
- Utah requirement evidence: none exists.
- Cultivar requirements.
- The Utah boundary convention between published rows.

**OPEN_MODEL_CAPABILITY**
- `MODEL_DEFINED` Utah onset (most negative sum).
- `EFFECTIVE_CHILL_ONSET` for Utah/Dynamic.
- Sub-hourly Utah/Dynamic.
- Dormancy induction.
- The `ENVIRONMENTAL_WINDOW` start policy.
