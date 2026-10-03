# Interactive simulation API and execution contract (Phase 5.37)

SOFTWARE_RESULT: contract, determinism, checkpoint/resume, cancellation, error, result, immutability and static-audit checks.
PERFORMANCE_MEASUREMENT: machine-dependent timings, never hashed. SCIENTIFIC_EVIDENCE: none.

- status: `PASS`; deterministic hash: `74811542b9194953e1412f09edcfd64dbd9c355a1a1bd273451058fde5687aac`; API version `1.0`

## Sections

| Section | Status |
|---|---|
| cancellation | PASS |
| canonical_request | PASS |
| canonical_response | PASS |
| checkpoint_resume | PASS |
| classification | PASS |
| determinism | PASS |
| direct_equivalence | PASS |
| errors | PASS |
| immutability | PASS |
| progress | PASS |
| result_contract | PASS |
| scientific_status | PASS |
| static_audit | PASS |

## Determinism (two executions per case)

| Case | Mode | Steps | Trajectory hash | Deterministic |
|---|---|---|---|---|
| tomato_outdoor_7d | INTERACTIVE | 168 | `54e8bc8c9acb92d7` | True |
| lettuce_greenhouse_full_season | INTERACTIVE | 1008 | `4d25b233ecf24ae1` | True |
| tomato_outdoor_heat_wave_full_season | INTERACTIVE_WITH_PROGRESS | 3744 | `55148cbf27b2916c` | True |
| pepper_greenhouse_full_season | INTERACTIVE_WITH_PROGRESS | 4656 | `946361e7b9353a54` | True |
| peach_dynamic_software_test_season | INTERACTIVE_WITH_PROGRESS | 5808 | `f5cad782b4b355b4` | True |
| tomato_outdoor_weather_override_14d | INTERACTIVE | 336 | `248577ef93b945b0` | True |

## Checkpoint / resume (full == partial + checkpoint + resume)

| Case | Checkpoint | Steps | Equivalent |
|---|---|---|---|
| tomato_outdoor_base | 2026-04-10T00:00:00+00:00 | 3744 | True |
| lettuce_greenhouse_base | 2026-01-20T12:00:00+00:00 | 1008 | True |
| tomato_outdoor_heat_wave_before_window | 2026-04-20T00:00:00+00:00 | 3744 | True |
| peach_chilling_hours_default | 2026-02-10T00:00:00+00:00 | 2880 | True |
| peach_dynamic_software_test | 2026-02-10T00:00:00+00:00 | 2880 | True |
| tomato_outdoor_cancelled_at_step_100_then_resumed | 2026-02-19T04:00:00+00:00 | 672 | True |

## Performance (seconds; minimum of sequential repeats)

| Case | Steps | Direct | API simulation | API overhead | Overhead % | With trajectory hash % | to_json | Bytes |
|---|---|---|---|---|---|---|---|---|
| tomato_outdoor_7d | 168 | 0.052 | 0.054 | 0.0062 | 11.9 | 44.9 | 0.004 | 75860 |
| lettuce_greenhouse_full_season | 1008 | 0.347 | 0.331 | 0.0065 | 1.9 | 30.6 | 0.024 | 433611 |
| tomato_outdoor_full_season | 3744 | 1.226 | 1.200 | 0.0402 | 3.3 | 35.9 | 0.081 | 1317384 |

Canonicalization per request: 0.048 ms.

## Limitations

- start_time is fixed by the crop's synthetic cycle; the horizon is set with end_time, a later start only through a checkpoint
- a checkpoint inside a ramped scenario event is rejected (INVALID_CHECKPOINT): the existing resumed_scenario re-anchors event ramps
- weather is the Phase 5.32 synthetic seasonal generator only; local CSV / downloaded weather is not exposed by API 1.0
- execution is synchronous and in-process; BACKGROUND plans are classified, a decoupled executor is a future adapter
- the execution-mode estimate uses the Phase 5.36 per-step cost measured on one machine (advisory)
- the actuated greenhouse mode is not exposed (no actuator schedule contract yet)
- one configured variety and plot per crop (the existing synthetic plots); other varieties are rejected, never invented

## Scientific status

REAL_VERIFIED = 0; CALIBRATION_PERFORMED = false; EXPERIMENTAL_VALIDATION_PERFORMED = false; BIOLOGICAL_VALIDITY_CLAIMED = false; FIELD_ACCURACY_CLAIMED = false; DATA_ASSIMILATION_IMPLEMENTED = false.
