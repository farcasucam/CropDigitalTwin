# Phase 6.3c: the latent-threshold hypothesis and measures for an intermittent demand

Development partition only (134 scenarios, 393 interventions of the main-context bank, phase 6.3b); synthetic data; the truth is that of the simulated twin, whose crop model is not calibrated.
Exploratory analysis: no mechanism is proved, the test partition is untouched and nothing here is a quality claim. Script: `manual_phase6_3c_thermostat_intermittency.py`;
reports: `data/xai/forecast_c_strata_report.json` (threshold 0 kW) and `data/xai/forecast_c_intermittency_threshold_{1,5}kw.json` (backtest sensitivity).

## What was added (tsxai)

* `onset_counts` / `f1_of_counts`: switching-on events matched one to one within the host's onset tolerance (±2 h in the hourly convention, declared in `TimeScale.onset_tolerance_minutes`); F1 of counts pooled over rows.
* `dual_conditional_mae`: the error over the instants of demand, always beside the error over the instants without (what the forecast invented).
* `integral_error`: the volume over the horizon (kWh at an hourly sample). The gate carries the integral of the effect (sign agreement, relative error, Spearman, intervals) and `context_total`.
* `stratified_summary`: per stratum, group-resampled 95 % intervals; cells under 10 pairs are declared not estimable.

## Stratification of the 148 pairs of the controller's demand

Stratum = demand summed over the 168 h of context before the cut-off (nothing of the horizon): ACTIVE if above zero, FLAT if identically zero. **129 pairs are active (47 crop-seasons) and 19 are flat (14)**: the flat ones are
13 % of the pairs. (The 51 % quoted earlier counted rows of the backtest, which has a different unit.) Heating has 57 active and only 6 flat pairs: not estimable.
Reading rule stated before the numbers (see `PREREGISTRATION.md`, 5b): failing in the flat stratum and working in the active one means lack of prior excitation; failing in both means excitation does not explain it.

Sign agreement of the peak effect, 95 % interval resampling crop-seasons (the integral gives the same picture):

| backend | active, both | flat, both | cooling active | cooling flat (13) | heating active |
|---|---|---|---|---|---|
| lagged ridge | 0.74 [0.66, 0.81] | 0.00 | **0.89** [0.81, 0.96] | 0.00 | 0.54 [0.40, 0.68] |
| TimesFM 3.0 | 0.74 [0.66, 0.81] | 0.00 | 0.78 [0.68, 0.88] | 0.00 | 0.68 [0.56, 0.81] |
| TimesFM 2.5 | 0.47 [0.39, 0.53] | 0.63 [0.45, 0.82] | 0.44 [0.35, 0.55] | 0.62 | 0.49 [0.38, 0.59] |

Spearman of the peaks across cases (active): ridge 0.64 [0.45, 0.79] (cooling 0.61 [0.38, 0.85], heating 0.27 [-0.13, 0.60]); TimesFM 3.0 0.49 [0.30, 0.65]; TimesFM 2.5 -0.07 [-0.26, 0.11], and on heating -0.38 [-0.60, -0.13], that is, significantly in the wrong direction.
Seasonal naive and Holt-Winters cannot express a plan (0 everywhere).

Reading, with its limits:

* **Flat stratum: consistent with the excitation hypothesis for the ridge and TimesFM 3.0.** With a context in which the device never switched on, both forecast exactly zero demand under both plans, so they predict no effect: 0 of 19 pairs. The interval of 0/19 from the bootstrap is degenerate ([0, 0]);
  an exact one-sided 95 % limit ignoring the clustering is about 0.15. TimesFM 2.5 does not forecast an exact zero, and its 0.63 is a sign that is no better than a coin (its Spearman interval contains 0).
* **Active stratum, cooling: the ridge reaches 0.89 in sign and 0.96 in the sign of the integral**, above the preregistered 0.8 with a lower bound of 0.81; its Spearman (0.61) is at the 0.6 threshold with a wide interval. **Heating does not:** 0.54 for the ridge and 0.68 for TimesFM 3.0. So excitation does not explain the heating failure; with the data at hand a nonlinearity of the response to the cold cannot be told apart from other causes.
* This is a subgroup defined after seeing the pooled result: it may suggest where an evaluation could be informative, but it cannot count as the gate passed. Only a stratification declared before the test partition is generated would have that standing.

## Measures that need no scale of the context (backtest, 1340 rows of the controller's demand, 439 with demand in the horizon)

F1 of the onset matching (tolerance ±2 h) depends on what counts as "on", and the forecasters do not emit exact zeros, so three thresholds are shown (a sensitivity of the development pilot, not a tuned value):

| backend | F1 at 0 kW | F1 at 1 kW | F1 at 5 kW | mean abs. error with demand (kW, at 5 kW) | mean abs. error without demand (kW, at 5 kW) |
|---|---|---|---|---|---|
| seasonal naive | 0.78 | 0.78 | 0.81 | 18.0 | 1.8 |
| Holt-Winters | 0.34 | 0.52 | 0.64 | 17.4 | 4.0 |
| lagged ridge | 0.29 | 0.42 | 0.63 | 17.2 | unstable (below) |
| TimesFM 2.5 | 0.18 | 0.51 | 0.71 | 17.0 | 2.5 |
| TimesFM 3.0 | 0.30 | 0.66 | 0.76 | 12.8 | 2.0 |

* The ranking of onset detection **depends on the threshold**: at 0 kW every forecaster that emits small positive values is flooded with false alarms; the seasonal naive, whose demand is a daily cycle, detects onsets best at every threshold, and TimesFM 3.0 is the best of the learned ones. A device-on threshold has to be declared by the host before any evaluation.
* TimesFM 3.0 has the lowest error on the instants with demand (12.8 against 17-18 kW) and a low error on the instants without (2.0 kW): it does not buy that by inventing demand.
* Over the 24 h horizon the mean demand is 685 kWh; the median relative error of the integral is 5.7 % for TimesFM 3.0 and 5.6 % for the ridge, 9.2 % for 2.5, 11-12 % for the naive and Holt-Winters.
* **The recursive lagged ridge diverges on a few rows** (the largest forecast integral is 5.4e11 kWh while the 99th percentile is 4.5e3): the median is unaffected, the mean is meaningless. It is a limit of the baseline on an intermittent series, not of the method to be explained; a stability guard on the baseline is a decision to take explicitly, not silently.

## Decisions recorded and what this does not show

* The integral of the effect is adopted as the main volume criterion of the counterfactual (a decision derived from development, recorded in the preregistration); the peak stays as a secondary criterion.
* Not shown: that the excitation explains the failure in general (the flat stratum has 19 pairs from 14 crop-seasons and heating has 6); that any forecaster passes the gate (the pooled result of 6.3b stands: none does); anything about real data.
* Open: a stability guard for the ridge baseline; the host-declared "on" threshold of a device (the twin declares none yet); whether the L2/L3 layers use the twin as an oracle for the flat stratum, where the forecasters predict no response by construction.
