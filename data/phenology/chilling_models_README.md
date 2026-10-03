# Alternative chilling models: Utah and Dynamic (Phase 5.35)

SOFTWARE_RESULT: implementation and contract qualification. SCIENTIFIC_EVIDENCE: references and NOT_ACTIVATED requirement rows.
SCIENTIFIC_CLAIM: none. Nothing here is calibration, experimental validation or a biological claim.

- status: `PASS`
- configuration hash: `85b500ec50c62648ea869485b3d9cb8e8d3153a61c8e5a0d3f6118a0fff02a04`
- effective hash: `b425fe8f76e9363f3619157750accf20e2fdc9b6f943394dbfed68228fb14ae2`
- report hash: `92aef11f1bc9926378ec1365aabfe4d72e917fadfed28b80917a70ba5189f3f3`

## Models

| Model | Unit | Implemented | Status without requirement | Parameterized for species | Scientifically active |
|---|---|---|---|---|---|
| CHILLING_HOURS | chill_hours | true | IMPLEMENTED_PARAMETERIZED | true | false |
| UTAH | utah_chill_units | true | IMPLEMENTED_UNPARAMETERIZED | false | false |
| DYNAMIC | chill_portions | true | IMPLEMENTED_UNPARAMETERIZED | false | false |

## Fallback (STRICT)

| Case | Requested | Effective | Fallback applied | Reason |
|---|---|---|---|---|
| CHILLING_HOURS+STRICT | CHILLING_HOURS | CHILLING_HOURS | false | - |
| UTAH+STRICT (no requirement) | UTAH | CHILLING_HOURS | true | REQUESTED_MODEL_NOT_PARAMETERIZED |
| DYNAMIC+STRICT (no requirement) | DYNAMIC | CHILLING_HOURS | true | REQUESTED_MODEL_NOT_PARAMETERIZED |
| UTAH+STRICT+SOFTWARE_TEST_ONLY | UTAH | UTAH | false | - |
| DYNAMIC+STRICT+SOFTWARE_TEST_ONLY | DYNAMIC | DYNAMIC | false | - |

## Sections

- model_catalog: `PASS`
- evidence: `PASS`
- readiness_matrix: `PASS`
- analytical_cases: `PASS`
- configurations: `PASS`
- phase534_hash_preservation: `PASS`
- fallback_matrix: `PASS`
- negative_cases: `PASS`
- seasons: `PASS`
- checkpoint_restart: `PASS`
- regression_533: `PASS`
- twin_integration: `PASS`
- determinism: `PASS`
- traceability: `PASS`
- static_audit: `PASS`
- parameter_mutation: `PASS`
