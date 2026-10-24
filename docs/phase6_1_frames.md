# Phase 6.1 - Multivariate frames

Status: COMPLETE (software qualification). The data are synthetic; the exogenous weather is `FORCING`; no `REAL_VERIFIED` data exists.

## What was built

* **Framework side (`tsxai`, `tsxai.core.frame`, standard library only):** `MultivariateFrame` (aligned series, time labels, the variable catalogue with its roles, a provenance label per variable, a content hash),
  `window()`, `forecast_view(cutoff, horizon, plan)` (the only way to hand a frame to a forecaster: after the cut-off only known-future covariates, and decision covariates only when a plan is given; the true
  future of the targets is kept apart as `truth`), `quality()` (gaps, non-finite values, constant series and sentinel values reported as facts, never repaired), `PairedFrames`/`paired_frames` (baseline versus
  intervention), the `SeriesSource` port and `SimulatorSeriesSource` (frames from any `SimulatorPort`).
* **Twin side (`interfaces/xai_adapter.py`):** `twin_series_source()`; exogenous weather and rain labelled `FORCING`, everything the twin computes `SYNTHETIC`. A new context variant covers the controller plus the
  crop's feedback on the greenhouse air (`feedback=on`, the simplified greenhouse with `crop_exchange`), so the benchmark has 16 contexts. A scenario may carry its own `greenhouse` request in `options`.
* **Catalogue:** four exogenous variables added to the twin's variable catalogue (greenhouse scope, as `outdoor_temperature_c`): `outdoor_radiation_w_m2`, `outdoor_relative_humidity_pct`,
  `outdoor_wind_speed_m_s` and `outdoor_rain_rate_mm_h` (a rate, so no step length is assumed). All are `known_future_covariate` in `src/xai_variable_roles.json`.

## Checks

* `tests/test_xai_adapter.py`: stable frame hashes in the four environments; provenance; no computed variable is ever exposed as a future covariate; the branch of a what-if equals the baseline up to the
  intervention and differs exactly from the sample after its start; a window of a long frame equals the frame built for that window.
* `tsxai/tests/test_frame.py`: the same rules on the toy room, data-quality facts, misaligned and undeclared series rejected.
* `python -u manual_phase6_1_frames_test.py` writes `data/xai/frames_report.json` (4 cases, deterministic hashes).

## Findings to carry into 6.2

* **Many series are constant in a one-week window** (for example soil water, irrigation, stress indices, cooling power when no cooling is needed, `crop_stage`). The quality facts report them; the analyzer (6.2)
  must treat a constant target as "nothing to explain" and say so, not fabricate a trend.
* **EnergyPlus** frames are not part of the automated checks: the backend is a precomputed timeline that needs the installed program and cannot take the crop's feedback. The adapter passes a scenario's own
  `greenhouse` request through, so an EnergyPlus frame can be built where it is installed.

## Limits

The frames carry the simulated twin, whose crop model is not calibrated. Nothing here is a validation or a calibration.
