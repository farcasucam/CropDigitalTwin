# Phase 5.40 interactive visual simulation report

Status: **PASS**

Produced by `manual_phase5_40_visual_simulation_test.py`. The deterministic hash covers the software
checks only; browser measurements are machine-dependent and excluded from it.

## SOFTWARE_RESULT
- Visual simulation tests: PASS
- Static audit: PASS
- Record/replay: MATCH
- Full regression: PASS (passed=1364, skipped=12)
- Browser smoke: PASS

## PERFORMANCE_RESULT (measured in the browser, not inferred)
- Desktop FPS: 60.0 (target >= 30.0)
- Narrow viewport (390 px, desktop Chromium, not a physical phone) FPS: 60.0 (target >= 20.0)
- Horizontal overflow at 1280/768/390: yes

## SCIENTIFIC_EVIDENCE
None. The visual layer only displays API output; user events are USER-DEFINED SYNTHETIC FORCING.

Scientific status flags: REAL_VERIFIED = 0; CALIBRATION_PERFORMED = false; EXPERIMENTAL_VALIDATION_PERFORMED = false; BIOLOGICAL_VALIDITY_CLAIMED = false; FIELD_ACCURACY_CLAIMED = false; DATA_ASSIMILATION_IMPLEMENTED = false.
