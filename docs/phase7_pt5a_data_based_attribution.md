# Phase 7 / PT-5a: a data-based attribution against the re-simulation truth, in two capacity regimes

Status: DEVELOPMENT. Tomato, greenhouse, controller on, four held-out DEV seasons per regime (34, 35, 37, 38), a deliberately simple surrogate. Script `manual_phase7_pt5a_data_based_attribution.py`, report `data/xai/effects_pt5a_data_based.json`. The design and the reading rules (material cell, false effect, normalised error, sign agreement) were fixed in the script's docstring before the run.

## Method compared (what a method with only data does)
A surrogate (ridge on the four outdoor channels at lags 0 to 3, hour of day and 300 fixed random ReLU features; numpy only) is fit on 24 DEV seasons, one run each with 0 to 3 natural random events and no re-simulation, separately for each capacity regime. It never sees the controller's commands, the indoor state or a perturbation label. An episode is explained by occlusion: a coalition keeps the factual outdoor forcing over its player's segment (the heat and cold waves also carry the outdoor humidity, an edge of declared graph v0.2) and the baseline elsewhere; exact Shapley over the four PT-2 players on the predicted outcome. Baselines: ORACLE (the unperturbed run's forcing; it isolates the model's error and is not available without the simulator) and CLIMATOLOGY (mean forcing per hour over the training seasons). Truth: re-simulation, reactive policy, same outcomes. The candidate segments are GIVEN to the method.

## Results (four held-out seasons per regime; counts and ranges)
Surrogate quality, held-out RMSE over the series' standard deviation: cooling power 0.32 to 0.48, heating power 0.35 to 0.45, air temperature 0.10 to 0.12.

| regime | outcome | material cells | top player agrees | sign right (players above 5 % of the sum of absolute true shares) | normalised error (oracle / climatology) | false effects |
|---|---|---|---|---|---|---|
| headroom (1.0) | cooling energy | 4 of 4 | 4 / 4 | 7 of 8 / 8 of 8 | 0.06-0.09 / 0.06-0.07 | none |
| headroom | heating energy | 4 of 4 | 4 / 4 | 7 of 8 / 5 of 8 | 0.11-0.17 / 0.19-0.23 (total error 0.31-0.74) | none |
| headroom | peak temperature | 0 of 4 (truth masked) | n/a | n/a | n/a | **4 of 4 with both baselines: the method reports +0.28 to +0.73 K where the truth is 0** |
| headroom | hours above stage max | 0 of 4 | n/a | n/a | n/a | 0 of 4 |
| saturation (0.3) | cooling energy | 4 of 4 | 4 / 4 | 4 of 4 / 4 of 4 | 0.04-0.11 / 0.04-0.08 | none |
| saturation | peak temperature | 4 of 4 | 4 / 4 | 5 of 6 / 6 of 6 | 0.13-0.46 / 0.04-0.30 | none |
| saturation | hours above stage max | 3 of 4 (1 to 5 h) | 3 / 1 | 1 of 6 / 3 of 6 | 0.5 / 0.5-1.0 | 1 of 1 (climatology) |

## Reading
* **Where the truth is large and the response is a smooth function of the weather, the data-based attribution works** in this synthetic setting: the energy outcomes get the right top player in 4 of 4 seasons in both regimes with normalised errors of 4 to 11 percent (cooling). The argument "data-based methods cannot explain this" is not supported for energy; it would be wrong to write it.
* **It invents an effect where the controller masks the perturbation.** At headroom the true reactive effect on the peak temperature is zero in all four seasons, and the surrogate (smooth, unable to represent the controller's hard hold at the set-point) reports 0.3 to 0.7 K, 6 to 14 times the 0.05 K materiality threshold, but small against the 9 K that the same perturbations add when the commands are held (PT-1). The hours above the maximum show no false effect. This is the one place where the re-simulation says something a data-based method gets wrong, and it is small.
* **Under saturation the temperature shows part of the effect and the data method follows it** for the peak (top player 4 of 4); for hours above the maximum the counts are 0 to 5 h and the method is unreliable (sign right 1 of 6 with the oracle baseline), a rate too small to read.
* **Heating** is the weakest outcome (total error 31 to 74 percent, signs 5 to 7 of 8): the cold wave and the nights make it a harder function, and the surrogate's error is larger.
* The two baselines differ little: the climatology (no reference run needed) did about as well as the oracle, so for this question the model, not the baseline, limits the accuracy.

## What it does not say
* The **replayed** question (what the same perturbations would do with the commands held) cannot be answered by any method that only sees data from the controlled system: its answer is a different system. That is what re-simulation provides and no data-only method can replicate; PT-5a does not test it, it follows from the definition.
* The candidate segments were given; the surrogate saw the exact outdoor forcing; one crop, one generator, four seasons per regime, a simple surrogate (not a tuned forecaster or a causal-discovery method). A result for this surrogate is not a statement about all data-based methods. Next: segments detected from the data, stronger surrogates, another crop.
* Occlusion works here because the exogenous forcing is observed. Perturbations not visible in any observed channel would be invisible to it; not tested.

## Exposure of benchmark seasons (disclosure)
The benchmark's own split (salt `gctsb-1`, group by crop and season) puts the seasons used in the earlier packages in these partitions: tomato 0, pepper 0 and lettuce 0 and 1 are TEST; tomato 1 and 2, pepper 1 and lettuce 2 are DEV. PT-1 (tomato 0), PT-2 (seeds 0 to 2 of three crops), PT-3 (seed 0 of three crops) and PT-4a (tomato 0) therefore looked at test-partition seasons while the effects line was in development. The effects line is not the benchmark's confirmatory run, but those seasons are exposed to design decisions and must not serve as confirmatory seasons; PT-5a and later use DEV seasons only, and the protocol freeze must list the exposed seasons.
