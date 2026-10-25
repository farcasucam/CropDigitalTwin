# Phase 6.3 / 6.3a: forecasters behind one port, TimesFM service on the Spark, and the counterfactual gate

Development pilot: 22 dev scenarios of the twin, context 168 h, horizon 24 h (backtest) or intervention length + 24 h (gate). Synthetic data; truth of the simulated twin. Small samples and no intervals: **a pilot, not the preregistered evaluation, and no quality claim**.
Reproduce: `python -u manual_phase6_3_forecast_test.py --service timesfm25=http://127.0.0.1:8088 --service timesfm3=http://127.0.0.1:8089` (writes `data/xai/forecast_pilot_report.json`, rows included). Without `--service` only the baselines run, and the report says no service was used.

## What was built (in `tsxai`)

- `tsxai.forecast`: seasonal naive, damped Holt-Winters and a lagged ridge regression (the only baseline that can react to a plan in the known-future covariates) behind `ForecastBackend`; MASE, RMSSE, NRMSE, sMAPE, pinball loss, coverage and Spearman; record/replay of responses; `backtest` over rolling origins; `counterfactual_gate`.
- `tsxai.adapters.HttpForecastBackend`: standard-library client with typed errors (unreachable, timeout, server error, malformed answer, answer to a different request, missing licence status, connection lost).
- `services/timesfm/`: the HTTP service (Dockerfile, compose, smoke test). TimesFM 2.5 (Apache-2.0 weights) by default, 3.0 (non-commercial weights) behind `TIMESFM_LICENSE_ACK=non-commercial-research`. Weights are downloaded once into a volume and served offline; no token is stored in a container.
- Core: roles that depend on the scenario (`VariableCatalogue.with_roles`, `SimulatorSeriesSource(role_overrides=...)`) and a plan stated by name (`forecast_view(plan=[...])`).

## What each model does with covariates (from the library source)

- 2.5: each target is its own series; covariates enter through XReg, a **linear** in-context regression fitted on the request's context ("xreg + timesfm": a linear fit on the covariates, TimesFM forecasts the residual). Only covariates known over context and horizon; past-only covariates cannot be used (reported as ignored). With `return_backcast` the forecast is the **tail** of the output (a head slice returns the backcast of the padded context: a bug found by the smoke test and fixed).
- 3.0: targets together; past-only and past-and-future covariates natively (call as in the project README).

## A leak found and removed (read this before any number)

The first pilot gave every forecaster, as "the plan", the realised future values of the decision-role variables (vent opening, extractor level, shading, irrigation). With the climate controller **on** those are the controller's own outputs: they react to the indoor state, so their future values carry the controller's reaction to the very target being predicted. The twin's adapter now demotes them to past-only covariates in scenarios with `control = on` (they stay decisions with the controller off, where they are a person's plan), and an intervention may state only the variable it itself sets (`IRRIGATION` -> `irrigation_mm`, `SHADING` -> `greenhouse_shading_fraction`, `VENTILATION` -> `control_vent_opening`). The numbers below are after the correction; the table of the leaky run is kept to show its size.

| Gate (20 expressible pairs) | sign agreement before / after | Spearman before / after | median relative error before / after |
|---|---|---|---|
| lagged ridge | 0.80 / 0.55 | 0.71 / 0.54 | 0.64 / 0.88 |
| TimesFM 3.0 | 0.70 / 0.40 | 0.60 / 0.12 | 0.93 / 1.01 |
| TimesFM 2.5 | 0.45 / 0.40 | -0.14 / 0.04 | 1.00 / 1.00 |

The leak flattered exactly the two forecasters that could use the plan most.

## Results after the correction

Backtest, medians over rows (means are distorted by degenerate series; 106 rows per backend have a flat context and an undefined MASE/RMSSE scale and are left out of those two columns, not turned into huge numbers):

| Backend | median MASE | median RMSSE | median NRMSE | median sMAPE | median pinball | coverage of the 80 % band |
|---|---|---|---|---|---|---|
| seasonal naive | 0.94 | 0.86 | 0.241 | 3.5 | 0.023 | 0.79 |
| Holt-Winters (damped) | 0.96 | 0.75 | 0.234 | 3.1 | 0.025 | 0.66 |
| lagged ridge | 1.15 | 0.92 | 0.280 | 4.2 | 0.032 | 0.77 |
| TimesFM 2.5 | 0.85 | 0.70 | 0.206 | 5.1 | 0.024 | 0.78 |
| TimesFM 3.0 | **0.70** | **0.62** | **0.175** | **2.3** | **0.018** | 0.75 |

- TimesFM 3.0 is first on every metric, so its lead does not depend on the scale chosen. RMSSE does not rescue flat series (it has the same denominator as MASE: the naive one-step error); NRMSE, which divides by the SD of the context, does not need that denominator.
- The middle of the ranking depends on the metric (Holt-Winters beats the naive on RMSSE and NRMSE; TimesFM 2.5 is worst on sMAPE, which punishes near-zero actuals such as radiation and rain). Intervals are nominal, not calibrated: every backend under-covers a little (nominal 0.80).

Counterfactual gate (39 interventions; 19 usable: 16 skipped for context shorter than 168 h, 4 with no effect; of 51 intervention-target pairs only 20 are expressible as a change in the plan the forecaster is given, the other 31 act through factors it cannot see):

| Backend | sign agreement | Spearman of peak effects | median relative error | coverage of the true effect | by factor (sign) |
|---|---|---|---|---|---|
| seasonal naive, Holt-Winters | 0.00 | undefined | 1.00 | 0.62 / 0.70 | all 0 (cannot use a plan) |
| lagged ridge | 0.55 | 0.54 | 0.88 | 0.76 | COLD_WAVE 0.67, LOW_RADIATION 1.0, RAIN 0.0, SHADING 0.0 |
| TimesFM 2.5 (XReg) | 0.40 | 0.04 | 1.00 | 0.65 | 0.44, 0.40, 0.0, 0.40 |
| TimesFM 3.0 (native) | 0.40 | 0.12 | 1.01 | 0.71 | 0.56, 0.20, 0.0, 0.40 |

Preregistered gate (H4): sign agreement >= 0.8 and Spearman >= 0.6 on the main factors. **No forecaster passes.** 20 expressible pairs and no intervals: a pilot, not a decision.

## Reading

- Forecast accuracy and counterfactual fidelity are different things: TimesFM 3.0 is the best forecaster on every metric and an unreliable model of what happens when the plan changes (it moves in the right direction in 40 % of the pairs, and underestimates the size).
- With the controller on, a what-if on the weather passes through the controller's reaction. A forecaster that is not given the controller's future outputs has to learn its policy from the context; none of the models does it reliably here.
- RAIN is 0.0 for every backend that can express it: a common failure (probably the threshold nature of the response), not specific to a model.
- 31 of 51 pairs are not expressible as a covariate plan: forecasting alone cannot explain those interventions; they need the twin (or its event log).

## Consequence for the plan

By the preregistered rule, when the covariates do not agree with the twin on the main factors, L2/L3 are built on a model-agnostic surrogate (or on the twin as oracle) and TimesFM stays a comparator and an object of explanation; the negative result is published. The decision stays formally open until a larger development pilot with intervals (more cases, a longer context, bootstrap over groups) and then the test partition. Nothing here was tuned on the test partition.

## Operations (Spark)

TimesFM 2.5 and 3.0 run in two new containers (`tsxai-timesfm`, `tsxai-timesfm-3`), published on the Spark's loopback only and reached through an SSH tunnel. The three FGKB containers were stopped (not removed) at the user's request to free memory; `docker start fgkb-qwen fgkb-llama fgkb-olmo` restores them. The licence acknowledgement for 3.0 follows decision D1 (research, non-commercial use).
