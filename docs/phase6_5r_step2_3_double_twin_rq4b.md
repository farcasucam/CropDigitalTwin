# Phase 6.5r, steps 2 and 3: working-twin variants and RQ4b (what-if under mismatch)

Synthetic data; exploratory; **8 cases, no intervals**; both twins uncalibrated, EnergyPlus is not the real greenhouse; no quality claim. Scripts: `manual_phase6_5r_rq4b_mismatch.py`; report: `data/xai/rq4b_mismatch_report.json` (hash 3195f9b0…).

## 1. Step 2: the working twin and its variants

* The simplified greenhouse request accepts an optional `parameters` mapping (`greenhouse_backend.py`): overrides of nine placeholder values of the lumped model. Absent, nothing changes (requests and hashes of earlier runs are identical; tested).
  Refused with the EnergyPlus backend (the truth twin always runs nominal values), outside the greenhouse, for unknown names, non-positive or non-finite values, and fractions above one.
* `src/agri_twin/interfaces/xai_double_twin.py`: `variants(level)` (Latin hypercube, seeded, deterministic), `working_scenario` and `truth_scenario` (same labels, window and controller in both).
* **Finding that changes D15 (recorded as D19):** the greenhouse thermal parameters are all `PROVISIONAL_DEFAULT` and the parameter audit lists them with "uncertainty: none". **No declared ranges exist**, so "perturbed within the declared ranges" cannot be done
  literally. The mismatch levels are declared relative widths: 0 (nominal), small (±10 %), large (±30 %) over five parameters, seven variants per level. They are design conventions, not scientific uncertainty and not "plausible greenhouses".

## 2. Step 3: results (tomato greenhouse with the controller; cold wave on heating, heat wave on cooling; 4 seasons x 2 interventions = 8 cases; energy integral over 48 h)

| Level | Variant runs | Direction agrees with the truth | Median ratio working/truth (min–max) | Truth inside the variants' range | Claims "confirmed" / correct |
|---|---|---|---|---|---|
| 0 (nominal, 1 variant) | 8 | 8 of 8 | 1.86 (1.30–1.97) | 0 of 8 | 0 (too few variants) |
| small (±10 %, 7 variants) | 56 | 56 of 56 | 1.88 (1.28–1.95) | 0 of 8 | 8 / 8 |
| large (±30 %, 7 variants) | 56 | 56 of 56 | 1.86 (1.24–1.94) | 1 of 8 | 8 / 8 |

## 3. Reading (stated plainly)

* **The direction of the effect is robust**: every variant, at every level, has the truth's sign.
* **The size is not**: the structural difference (the simplified model overstates the energy effect about 1.9 times) dominates; varying five parameters by ±30 % moves the median effect by less than 2 %. The variants' spread **does not contain the truth** in 15 of 16 cases
  (small and large together): it is not an uncertainty interval for the magnitude. It only measures sensitivity to those parameters.
* **"k of n variants" is not calibration here.** All variants agreed in every case (7 of 7), so no case exercised the "not confirmed" branch, and "confirmed and correct 8/8" says only that a robust direction is correct. The claim of D15 that an ensemble gives
  *calibrated* evidence is **not supported by this experiment**: what the ensemble certifies is robustness of the direction to parametric perturbation. Calibration needs cases where the twins can disagree in direction, which this pair of interventions never produces.
* **Consequence for the semantic layer (6.4):** the wording of a confirmed effect no longer says "about X" but "direction confirmed in k of n variants; the size is not confirmed" (tsxai `effect:confirmed`, with the estimate and the variants' range given as an estimate).
* **Consequence for RQ4b/H4b:** a defensible hypothesis is "the direction of a what-if survives structural and parametric mismatch; the magnitude does not". The ratio working/truth (about 1.9 for these cases) is the figure to report with the mismatch level, with its limits.

## 4. Limits and next

Two interventions on one crop and one controller; the energy of a controller that reacts to the intervention (not a direct, open-loop effect); few cases; the same sign in all of them leaves the discriminating power of the ensemble untested.
Next: widen the interventions (ventilation, shading, radiation, wind, rain, CO2) to find cases where the direction can differ; then the fidelity of the forecaster's attribution (RQ3).
