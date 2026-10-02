# Chilling model policy and canonical configuration (Phase 5.34)

Software qualification of the dormancy configuration contract. Every entry is SOFTWARE_RESULT; this phase produces no
SCIENTIFIC_EVIDENCE. Nothing here is calibration, experimental validation or a biological claim.

- status: `PASS`
- configuration hash: `81f79a25fae27485f66a54d9b0f617f0145c5fe8b46808e63ff645afe0c0ffb0`
- report hash: `99328f9d7f299fc8371529492a8cb92f74e7d08503dd7b4c5f54502f6dfa3cdd`

Dynamic is declared but not implemented. Unsupported models use explicit STRICT fallback to CHILLING_HOURS.
DEFAULT is an alias of STRICT. No biological claim is made.

## Fallback matrix

| Requested model | Fallback | Effective model | Fallback applied |
|---|---|---|---|
| CHILLING_HOURS | STRICT | CHILLING_HOURS | false |
| DYNAMIC | STRICT | CHILLING_HOURS | true |
| UTAH | STRICT | CHILLING_HOURS | true |

| Policy | Canonical policy |
|---|---|
| DEFAULT | STRICT |
| STRICT | STRICT |

## Sections

- configurations: `PASS`
- fallback_matrix: `PASS`
- policy_alias_matrix: `PASS`
- negative_cases: `PASS`
- unsupported_models: `PASS`
- equivalence: `PASS`
- regression_533: `PASS`
- twin_integration: `PASS`
- determinism: `PASS`
- traceability: `PASS`
- static_audit: `PASS`
- parameter_mutation: `PASS`
