# Phase 6.3d: safety net of the ridge and device-declared ON threshold

Development partition only (134 scenarios, 393 interventions, main-context bank); synthetic data; truth of the simulated twin; exploratory, no quality claim.
Script: `manual_phase6_3d_ridge_net_device_threshold.py`; report: `data/xai/forecast_c_ridge_net_report.json`.

## 1. Safety net of the ridge (tsxai `LaggedRegressionBackend(clip_factor=5.0)`)

A last resort against divergence of the recursive linear forecast, not an analytical fix: each step is bounded to the context range widened by 5 times that range on each side. A target with a constant context has no range
to widen and is left unbounded (named in `unbounded_flat_targets`). Every response reports `clipped_steps` (per target and total) and `forecast_steps`; backtest and gate rows carry them.

* The net acted in **290 of 20 672 gate forecast steps (1.4 %)** and in 0.15 % of the backtest steps: the linear model diverged in 1.4 % of the steps under multi-step recursion and needed the net.
* Gate with and without the net: sign agreement of the peak 0.642 in both; the preregistered verdict (sign >= 0.8, Spearman >= 0.6) is the same (not passed). Integral median relative error 0.864 with, 0.887 without (difference -0.023);
  Spearman of peaks 0.631 / 0.592; coverage 0.846 / 0.834. The net moves the secondary figures slightly and **does not change any conclusion**. (The flag `primary_median_unchanged` compares exact equality and is False: read the differences.)

## 2. ON threshold declared by the device

`VariableSpec.activation_fraction` and `nominal` (tsxai catalogue): the threshold is `fraction * nominal`, an engineering property. The twin declares 5 % of the rated thermal power (`src/xai_variable_roles.json`, **provisional design
convention, not a sourced value**); the nominal is that of the scenario's equipment (`TwinSimulator.catalogue_for`): heating 6.48 kW, cooling 19.44 kW in the bank. Without controller there is no device and no threshold.

Onset F1 (pooled controller targets) with the device thresholds: seasonal naive 0.827, Holt-Winters 0.749, ridge 0.808 (0.808 unclipped).

Complementary robustness report (fixed thresholds, the earlier sweep; F1 for seasonal naive / Holt-Winters / ridge): 0 kW 0.78 / 0.34 / 0.29; 1 kW 0.78 / 0.52 / 0.41; 5 kW 0.81 / 0.64 / 0.63. The ranking of the forecasters depends on the analyst's tolerance,
which is why the threshold must come from the device and not from tuning.
