# Phase 5.38 frontend report

<<<<<<< HEAD
Status: **INCOMPLETE**
=======
Status: **PASS**
>>>>>>> 03c25fbf473b381ba50ae6376a578e256ebae33e

This report is produced by `manual_phase5_38_frontend_test.py`. Its deterministic
hash covers contract, software checks and their outcomes. Machine-dependent
performance observations are recorded separately and excluded from that hash.
No timestamp is added to the report.

- Frontend test suite: PASS
- Frontend build: PASS (static assets; no build pipeline required)
<<<<<<< HEAD
- Full regression: NOT_RUN
=======
- Full regression: PASS
>>>>>>> 03c25fbf473b381ba50ae6376a578e256ebae33e
- Browser UI smoke: PASS
- API contract: 1.0
- Supported crops: tomato, lettuce, pepper, grape, peach, plum, apple
- E2E checks: PASS
- Responsive/accessibility static checks: PASS
- Deterministic execution: PASS
- Scientific evidence produced: none

Performance observations: see `interactive_frontend_report.json`. All durations
are operational measurements, not evidence of scientific validity.

To regenerate after running the browser smoke test and `pytest -q`:

```powershell
python manual_phase5_38_frontend_test.py --frontend-render-ms <short-ms> --full-season-render-ms <season-ms> --browser-smoke-status PASS --full-regression-status PASS --full-regression-passed 1224 --full-regression-skipped 12
```
