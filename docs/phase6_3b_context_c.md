# Phase 6.3b: forecasters and the counterfactual gate in the main context (greenhouse with the controller on)

Decisions D8-D11 (`docs/xai/DECISIONS_XAI.md`): the main context is the greenhouse with the climate controller on, on the hourly scale; the explained object is the **controller's demand** (`greenhouse_heating_kw`, `greenhouse_cooling_kw`) under the exterior forcing; the indoor climate is the observed consequence.
Development partition only; a pilot with intervals over crop-season groups, not the preregistered evaluation; no quality claim. Truth is the truth of the SIMULATED twin (uncalibrated crop model).

## The bank (`manual_phase6_3b_context_c_bank.py`)

134 development scenarios, 393 interventions, in the six contexts of the main scenario (tomato, lettuce, pepper; controller on; crop feedback off and on: 15 to 26 scenarios each). Only the six exterior-forcing events are offered (54 to 72 interventions each); windows of 21 to 28 days; 2 to 4 interventions per scenario. The test partition was **not** generated. Manifest hash `3554941e...`; generated at the twin commit recorded in `data/xai/gctsb_c_dev_report.json`. The scenario files (15 MB) are not tracked: they are deterministic and hash-checked by the manifest (`manual_phase6_3b_context_c_bank.py 200 6` regenerates them).

## Analysis (`manual_phase6_3b_context_c_analysis.py`, report `data/xai/forecast_c_report.json`)

Context 168 h; gate horizon up to 96 h. Of the 393 interventions 270 are usable (123 start before a week of context exists). The controller's own outputs are past-only covariates (never a plan). Intervals are 95 % percentile intervals resampling whole crop-season groups.

### Counterfactual gate, controller demand (148 intervention-target pairs; every pair is expressible: the four factors with a material effect on the demand move the exterior covariates)

| Backend | sign agreement | Spearman of peak effects | median relative error |
|---|---|---|---|
| seasonal naive, Holt-Winters | 0.00 | undefined | 1.00 (cannot use a plan) |
| lagged ridge | 0.64 [0.55, 0.73] | 0.59 [0.42, 0.74] | 0.86 [0.56, 0.97] |
| TimesFM 2.5 (linear XReg) | 0.49 [0.43, 0.55] | -0.06 [-0.24, 0.11] | 1.00 [1.00, 1.00] |
| TimesFM 3.0 (native covariates) | 0.64 [0.55, 0.72] | 0.45 [0.28, 0.60] | 0.92 [0.86, 1.00] |

Preregistered gate (H4): sign agreement >= 0.8 and Spearman >= 0.6. **No forecaster passes**: the upper end of every sign-agreement interval is below 0.8. TimesFM 2.5 is at the level of a coin flip; TimesFM 3.0 and a plain lagged ridge are equal in sign and the ridge is better in rank order. All of them underestimate the size of the effect (relative error 0.86 to 1.00).

Same gate on the indoor consequences (483 pairs: temperature, relative humidity, VPD): sign agreement 0.60 (ridge), 0.59 (3.0), 0.47 (2.5); Spearman 0.24, 0.12, -0.01. Weaker than for the demand.

### Backtest (rolling origins, 24 h horizon; medians over rows)

Controller demand is intermittent: in 692 of 1340 rows the context is flat (the demand is zero), so MASE and RMSSE have no scale there and are undefined (left out, not turned into huge numbers). sMAPE and pinball are degenerate for the same reason (median 0), and the coverage of the 80 % band is inflated by zero-width bands on flat zeros. On the rows where the scale exists:

| Backend | median MASE | median RMSSE | median NRMSE |
|---|---|---|---|
| seasonal naive | 0.65 | 0.65 | 0.188 |
| Holt-Winters | 1.08 | 0.75 | 0.386 |
| lagged ridge | 0.98 | 0.60 | 0.249 |
| TimesFM 2.5 | 0.70 | 0.56 | 0.168 |
| TimesFM 3.0 | **0.48** | **0.44** | **0.125** |

Indoor consequences (2010 rows, no undefined scale): median MASE 0.83 (3.0), 0.95 (naive), 1.03 (2.5), 1.05 (ridge), 1.11 (Holt-Winters); RMSSE and NRMSE give the same first place to TimesFM 3.0.

## Reading

- TimesFM 3.0 is the best forecaster in the main context too, on every scale-free metric: its lead does not depend on the metric and holds for the demand and for the indoor climate.
- Forecast accuracy is not counterfactual fidelity: the best forecaster moves the controller's demand in the right direction in about two thirds of the what-ifs, and a plain regression does as well.
- Hypothesis, not tested: a thermostat responds with a threshold. When the context never had heating on (about half of the rows), no model can learn from that context what a cold wave will trigger. A stratified analysis (context with and without demand activity) would test it.
- The controller demand needs its own measures: intermittent demand (a long run of zeros and then activations) is not served by MASE or sMAPE; onset detection (does demand appear within the horizon, when) and the size of the activation are what D11 asks to explain.

## Consequence for the plan

By the preregistered rule, L2 and L3 in the main context do not rest on a forecaster's covariate response: they are built on a model-agnostic surrogate or on the twin as the oracle, and TimesFM stays a comparator and an object of explanation (its own attributions and counterfactuals are evaluated against the exact effect). The negative result, with intervals, is part of the paper. This is a development result; the test partition is evaluated once, after the freeze.
