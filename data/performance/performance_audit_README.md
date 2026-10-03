# Performance, latency and scalability audit (Phase 5.36)

PERFORMANCE_MEASUREMENT values are wall-clock measurements on the audit machine (not deterministic, never hashed).
SOFTWARE_RESULT: determinism, mutation and optimization-equivalence checks. SCIENTIFIC_EVIDENCE: none.

- status: `PASS`; deterministic hash: `97cc6a686225cf6d813561849c5006de4967bf8d4d0d7f92496ea11ea4197374`
- environment: Python 3.13.9 on Windows-10-10.0.19045-SP0

## Twin simulation vs validation/reporting

- twin simulation (tomato outdoor full season): 1.185 s
- validation/reporting infrastructure on the same campaign: 4.363 s

## Benchmark matrix (simulation only)

| Workload | Days | Plots x cycles | Steps | Seconds | ms/step | s/simulated day |
|---|---|---|---|---|---|---|
| small_tomato_outdoor_7d | 7 | 1x1 | 168 | 0.085 | 0.508 | 0.0122 |
| medium_tomato_outdoor_full_season | 156 | 1x1 | 3744 | 1.717 | 0.459 | 0.0110 |
| scenario_tomato_outdoor_hot_season | 156 | 1x1 | 3744 | 1.742 | 0.465 | 0.0112 |
| scenario_tomato_outdoor_cold_season | 156 | 1x1 | 3744 | 1.633 | 0.436 | 0.0105 |
| scenario_tomato_outdoor_dry_season | 156 | 1x1 | 3744 | 1.616 | 0.432 | 0.0104 |
| scenario_tomato_outdoor_humid_season | 156 | 1x1 | 3744 | 1.648 | 0.440 | 0.0106 |
| scenario_tomato_outdoor_heat_wave | 156 | 1x1 | 3744 | 1.624 | 0.434 | 0.0104 |
| scenario_tomato_outdoor_cold_wave | 156 | 1x1 | 3744 | 1.633 | 0.436 | 0.0105 |
| scenario_tomato_outdoor_heat_wave_with_dryness | 156 | 1x1 | 3744 | 1.636 | 0.437 | 0.0105 |
| crop_lettuce_outdoor_full_season | 42 | 1x1 | 1008 | 0.436 | 0.432 | 0.0104 |
| crop_pepper_outdoor_full_season | 194 | 1x1 | 4656 | 2.034 | 0.437 | 0.0105 |
| crop_grape_outdoor_full_season | 319 | 1x1 | 7656 | 3.655 | 0.477 | 0.0115 |
| crop_peach_outdoor_full_season | 242 | 1x1 | 5808 | 2.254 | 0.388 | 0.0093 |
| crop_plum_outdoor_full_season | 242 | 1x1 | 5808 | 2.463 | 0.424 | 0.0102 |
| crop_apple_outdoor_full_season | 242 | 1x1 | 5808 | 2.202 | 0.379 | 0.0091 |
| greenhouse_tomato_full_season | 156 | 1x1 | 3744 | 1.603 | 0.428 | 0.0103 |
| greenhouse_lettuce_full_season | 42 | 1x1 | 1008 | 0.418 | 0.415 | 0.0100 |
| greenhouse_pepper_full_season | 194 | 1x1 | 4656 | 1.987 | 0.427 | 0.0102 |
| multi_plot_7_crops_outdoor | 30 | 7x1 | 5040 | 1.794 | 0.356 | 0.0085 |
| multi_cycle_lettuce_outdoor_x3 | 42 | 1x3 | 3024 | 1.249 | 0.413 | 0.0099 |
| chilling_chilling_hours_default_peach_365d | 365 | 1x1 | 8760 | 0.971 | 0.111 | 0.0027 |
| chilling_fixed_date_utah_peach_365d | 365 | 1x1 | 8760 | 0.969 | 0.111 | 0.0027 |
| chilling_dynamic_strict_peach_365d | 365 | 1x1 | 8760 | 1.037 | 0.118 | 0.0028 |

## Frontend classification (advisory)

- interactive_short_one_crop_one_plot: 0.09 s -> `INTERACTIVE`
- interactive_full_season_one_crop_one_plot: 1.72 s -> `INTERACTIVE_WITH_PROGRESS`
- multi_plot_7_plots_full_season_estimate: 9.99 s -> `INTERACTIVE_WITH_PROGRESS`
- multi_plot_50_plots_full_season_estimate: 71.38 s -> `BACKGROUND_TASK`
- greenhouse_tomato_full_season: 1.60 s -> `INTERACTIVE_WITH_PROGRESS`
- greenhouse_lettuce_full_season: 0.42 s -> `INTERACTIVE`
- greenhouse_pepper_full_season: 1.99 s -> `INTERACTIVE_WITH_PROGRESS`

## Scaling

- simulation_days: LINEAR (R^2 1.0000, slope 0.0099 s/unit)
- number_of_plots: LINEAR (R^2 0.9997, slope 0.1389 s/unit)
- number_of_crops: LINEAR (R^2 0.9966, slope 0.1263 s/unit)
- number_of_scenarios: LINEAR (R^2 0.9998, slope 0.1501 s/unit)
- number_of_cycles: LINEAR (R^2 0.9997, slope 0.1467 s/unit)
