# Phase 7 / PT-5c: a data-based method told the installation state

Status: DEVELOPMENT. Same episode as PT-5b (tomato, greenhouse, controller on, 336 h from hour 960, heat wave + radiation spell + cooling plant at 30 percent, four held-out DEV seasons 34, 35, 37, 38). Script `manual_phase7_pt5c_told_equipment.py`, report `data/xai/effects_pt5c_told_equipment.json`; reading rules (including the 0.7 to 1.3 "recovers" band) fixed in the script's docstring before the run.

## Question
PT-5b's method never observed the installation, so it could not attribute it (true by construction). Here the surrogate receives the cooling-capacity scale as a fifth input and is trained on 48 episodes in which the capacity varied (two per training season, natural random events, no re-simulation). The capacity player is occluded like the weather players (factual 0.3 vs nominal 1.0). Two training grids: SEEN (1, 0.7, 0.5, 0.3, 0.15) and UNSEEN (1, 0.7, 0.5, 0.15, 0.1: the evaluated 0.3 is an interpolation).

## Results (four seasons; counts and ranges)
Explained fraction = data total / true total; "recovers" = fraction in [0.7, 1.3] in at least 3 material cells.

| outcome (material cells) | grid | baseline | explained fraction | recovered | capacity share, data vs truth (0.395-0.5 for the peak) |
|---|---|---|---|---|---|
| peak temperature (4/4) | seen | oracle / climatology | 0.60-0.86 / 0.85-0.93 | 3/4 / 4/4 | 0.41-0.48 / 0.40-0.44 |
| peak temperature (4/4) | unseen | oracle / climatology | 0.63-0.99 / 0.95-1.09 | 3/4 / 4/4 | 0.43-0.56 / 0.40-0.45 |
| cooling energy (4/4) | seen | oracle / climatology | 0.74-0.91 / 0.84-0.91 | 4/4 / 4/4 | (true share 0.06-0.08) 0.08-0.11 / 0.02-0.05 |
| cooling energy (4/4) | unseen | oracle / climatology | 0.65-0.74 / 0.79-0.86 | 2/4 / 4/4 | 0.15 / 0.00-0.06 |
| hours above maximum (3/4; truth 1 to 5 h) | seen | oracle / climatology | 0-3.0 / 1.2-4.0 | 0/3 / 1/3 | 0-0.5 / 0.5 |
| hours above maximum (3/4) | unseen | oracle / climatology | 0-7.0 / 2.4-7.0 | 0/3 / 0/3 | 0-0.49 / 0.48-0.50 |

The sign of the capacity share agrees with the truth in every peak cell (8/8 per grid and baseline combination). Surrogate quality (relative RMSE over the series' standard deviation): temperature 0.08-0.10, cooling 0.39-0.59 (heating 0.9-1.3, not used here).

## Reading
* **A method that is told the state and trained on varied episodes recovers the peak effect and its split with the equipment**, including at a fault level it was not trained on (interpolation, unseen grid). PT-5b's result is therefore about observability and training data, not about data-based methods in general. The claim "data methods cannot attribute equipment faults" must not be written; "a method that does not observe the installation, or was never trained on episodes in which it varied, cannot" can.
* **Hours above the maximum are not recovered**: the truth is 1 to 5 h and the method reports 0 to 7 h (overstating up to 7 times). A threshold-count outcome with such small values is fragile in both directions.
* **Cooling energy is recovered but the capacity share is small and its estimate is noisy** (true share 6-8 percent; unseen grid sign disagrees in 2 of 4 cells with the climatology baseline).
* **What remains to the twin**: it supplies the varied-capacity training episodes (a real plant rarely has many with a recorded, varied fault) and the counterfactual truth to score the method. That points at the benchmark as the contribution, not at re-simulation beating data methods.

## What it does not say
One fault level and crop, a simple surrogate, episodes from the same generator as the evaluation (no distribution shift), candidate segments given, 48 training episodes, four seasons. Capacity-share ranges overlap the truth's, so equality is not shown.
