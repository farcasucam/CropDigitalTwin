# Phase 7 / nutrients: PT-9a, the same designs on pepper and lettuce

Status: DEVELOPMENT. Truth by re-simulation only, outdoors (no controller), four DEV seasons per crop (pepper 1, 2, 4, 6; lettuce 2, 4, 5, 6), window 336 h (pepper from hour 1500, lettuce from hour 336). Both nutrient models are uncalibrated (the reduced pool; the optional nitrogen model with unsourced placeholders): the question is whether the STRUCTURES found on tomato in PT-7a and PT-8a appear in other crops, not whether the sizes are right. Script `manual_phase7_pt9a_other_crops.py`, report `data/xai/effects_pt9a_other_crops.json`; the design and the reading rules are fixed in the script's docstring before the run.

## Results (counts and ranges; tomato from PT-7a and PT-8a for reference)
| structure | tomato | pepper | lettuce |
|---|---|---|---|
| Reduced model: compensation (dose positive, heat wave negative, net smaller than the largest share) | 4/4 | 4/4 | 4/4 |
| Reduced model: the early dose is worth more than the same late dose | 4/4, ratio 5.8 to 6.2 | 4/4, ratio 5.2 to 5.9 | 4/4, ratio 2.6 to 2.9 |
| Reduced model: interaction among the players (share of the sum of absolute shares) | 0.12 | 0.14 to 0.15 | 0.03 |
| Reduced model: size of the shares, heat wave / early dose / late dose (g/m2) | -49 / +25 / +4 | -38 to -33 / +21 to +24 / +4 | -4.1 to -2.2 / +0.26 to +0.29 / +0.10 |
| Nitrogen model: compensation of the heat wave by the dose | yes | 3/3 material seasons | **not present: the dose and the irrigation have share 0** |
| Nitrogen model: the extra irrigation raises the leached nitrogen | 4/4 | 4/4 | 4/4 |
| Nitrogen model: pairwise dose-irrigation interaction on the leaching is positive | 4/4 | 4/4 | 4/4 |
| Nitrogen model: interaction among the players on the leaching | 0.89 to 0.92 | 0.99 to 1.07 | 0.12 |

## Reading
* **The compensation and the timing carry over** to pepper and lettuce under the reduced model, with the same sign and order; the timing ratio is smaller for the short lettuce cycle (about 2.7, not 6): the benefit of a dose is the time left to profit from it, which is shorter in a 42-day crop.
* **Pepper reproduces the nitrogen-model picture** (compensation 3 of 3; the irrigation leaches the dose; the pairwise term positive; the leaching interaction close to 1).
* **Lettuce under the nitrogen model shows no nutrient effect on the biomass at all** (the dose and the irrigation have a share of exactly 0, the heat wave carries the whole effect). The crop is not nitrogen limited in this window under the placeholder demand curve: the soil pool starts at the state's default and a lettuce crop in a 336 h window never exhausts it. The leaching structure still appears (4 of 4), so a dose is still leached by an irrigation, but with no growth consequence. This is a property of the placeholders and the window, not of lettuce; it shows what a regime without nutrient limitation looks like to the explanation layer (the fertilisation player has no effect: an honest "no contribution" that must be reported as such).
* Nothing here is an agronomic statement; the sizes differ by crop because the biomasses do.

## What it does not say
Truth only (no data-based method), outdoor only, one generator, one window per crop, four seasons, uncalibrated models; the lettuce nitrogen-model cell says nothing about real lettuce.
