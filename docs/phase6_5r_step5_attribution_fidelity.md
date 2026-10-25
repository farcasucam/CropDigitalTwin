# Phase 6.5r, step 5: RQ3 (level L2), does the forecaster rank the factors as the simulated system does?

Development partition; synthetic data; truth of the simulated twin (the simplified model); exploratory, no quality claim. **TimesFM was not run** (the service was not used): the conclusions concern the lagged ridge, the only baseline that can use covariates.
Script: `manual_phase6_5r_attribution_fidelity.py`; report: `data/xai/attribution_fidelity_report.json` (hash 2bb476dd…). Function: `tsxai.forecast.ranking_fidelity`.

## 1. Design

Tomato greenhouse, without and with the climate controller, 8 seasons each (16 independent groups). Every scenario receives each probe factor (heat wave, cold wave, low and high radiation, wind, vent opening, shade screen, irrigation) as a separate 24-hour intervention at
the same cut-off. For each factor and target: the exact effect (paired runs) against the forecaster's effect (forecast under the intervened plan minus under the baseline plan, same past). Inside each (scenario, target) cell the factors are ranked by the magnitude of the integral of the effect on both sides.
Reading rule stated before the numbers (H3a, provisional): good for smooth factors, failing for threshold actuators and slow variables. Chance: Spearman 0; first-factor hit 1 over the number of factors.

## 2. Results (lagged ridge; 80 cells (scenario, target), all scored)

| | Mean Spearman (95 %) | First factor correct (95 %) | Chance of that hit | Sign agreement |
|---|---|---|---|---|
| all | 0.44 (0.36-0.52) | 0.35 (0.25-0.45) | 0.19 | 0.48 |
| controller off | 0.53 (0.43-0.63) | 0.40 | 0.20 | 0.49 |
| controller on | 0.34 (0.26-0.41) | 0.30 | 0.17 | 0.46 |

By target (16 cells each): heating energy ρ 0.61, indoor temperature ρ 0.61 (but the first factor is right only 0.125 of the time, below its 0.18 chance), relative humidity 0.45, vapour deficit 0.33, growth factor 0.18.
By factor, sign agreement of the integral: heat wave 0.71, cold wave 0.78, low radiation 0.53, high radiation 0.43, vent opening 0.35 (34 expressible of 74), **shade screen 0.00**; wind and irrigation have no material effect on any target (no pairs).
The seasonal naive forecaster cannot use covariates: sign 0.00 everywhere and nothing to rank.

## 3. Reading

* The ranking **carries some information** (mean ρ clearly above 0 and the first-factor hit above chance in the intervals), but it is **far from the provisional thresholds** (ρ ≥ 0.6 and sign ≥ 0.8 in the main factors): it does not justify presenting the forecaster's sensitivities as attributions of the world.
* **Sign is a coin flip (0.48)**: whatever the ranking carries, the forecaster does not tell the direction of the effect reliably. This agrees with the negative gate (6.3, 6.3e).
* **H3a is partly supported:** smooth thermal factors (heat, cold wave) are the best (0.71-0.78), radiation is at chance, the vent opening is worse (0.35) and the shade screen is 0.00. The shade screen's 0.00 is the earlier mechanism, not a bug: its covariate is constant in the context, so the ridge
  has nothing to learn from and predicts no response (a zero guess never agrees in sign). With the controller on the ranking is worse (0.34 against 0.53): the decision variables become the controller's outputs and the forecaster loses the plan variables it could express.
* The text layer of 6.4 must therefore keep forecaster-based sensitivities at the MODEL_ESTIMATED level and say that the ranking, not the direction, is the part with some support.

## 4. Limits

One baseline that uses covariates; one crop; one window and cut-off; 16 groups; the ranking uses magnitudes of one fixed-level probe, so a factor with a small probe can rank low for its size; no TimesFM, Chronos or boosting yet.
