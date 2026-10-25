# Phase 6.5r, step 1: feasibility of the truth twin on EnergyPlus and first measure of the structural mismatch

Synthetic data; exploratory; no quality claim; the controller's equipment is illustrative (phase 5.46). Script: `manual_phase6_5r_energyplus_feasibility.py`; report: `data/xai/energyplus_feasibility_report.json` (hash 8ced5021…).
Scenario: tomato, greenhouse, climate controller on, lock-step EnergyPlus 26.1 (truth twin) against the simplified model (working twin at parameter-mismatch level 0), window of 240 hours, 4 seasons.

## 1. Feasibility (decision D15: EnergyPlus for the energy series)

* The paired run (baseline and one intervention) **completes on EnergyPlus with the controller in lock-step** in all 8 cases and is **deterministic** (the baseline's trajectory hash repeats).
* **Cost:** about 12 s per paired run (10-16 s; the wall time is a measurement of this machine, not a result), because a run from a checkpoint replays the campaign prefix. A benchmark of 1000 scenarios with 3 interventions each is therefore
  in the order of 10 hours of one core: feasible, to be parallelised across processes (each run is independent).
* Consequence for the design: the truth twin on EnergyPlus is viable for the energy series; the working twin's ensemble (simplified, about 1 s per run) is cheap.

## 2. Structural mismatch between the two twins at the same parameters

Effect of a 24-hour intervention over the next 48 hours (probe level of the benchmark) on the controller's energy, integral in kWh:

| Season | Cold wave on heating: truth / working (ratio) | Heat wave on cooling: truth / working (ratio) |
|---|---|---|
| 0 | 365 / 693 (1.90) | 239 / 311 (1.30) |
| 1 | 367 / 694 (1.89) | 148 / 292 (1.97) |
| 2 | 341 / 623 (1.83) | 342 / 531 (1.55) |
| 3 | 338 / 615 (1.82) | 275 / 532 (1.94) |

* **Direction agrees in 8 of 8 cases; size does not**: the simplified model overstates the effect on energy by a factor of 1.3 to 2.0 (heating about 1.8-1.9, cooling 1.3-2.0, with more spread).
* So "mismatch level 0" (same parameters, different structure) is **not** a zero mismatch, as D15 anticipated: the structure alone already separates the twins. Parameter perturbations (small, large) add to that.
* This is a measurement of the structural difference, not a validation of either twin: both are uncalibrated models and EnergyPlus is not the real greenhouse.

## 3. Reading for the next steps

* The twin evidence level of 6.4 (direction confirmed in k of n variants) is meaningful here: the direction is robust to the structural mismatch, while the magnitude is not. This supports the rule of 6.4 that a confirmed effect fixes the **direction** only, and reports the magnitude as a range.
* The quantity to explain with the working twin is better stated as direction plus order of magnitude; RQ4b should report the ratio working/truth as a function of the mismatch level.

## 4. Next in 6.5r

1. Working-twin ensemble: perturb the parameters within the ranges declared by the parameter audit (uncertainty ensemble of 5.23), n variants, SIMPLIFIED backend.
2. Mismatch levels 0 / small / large and the measure of RQ4b (sign agreement, ratio, k-of-n calibration) against the EnergyPlus truth, on the development partition.
3. Fidelity of the forecaster's attribution against the truth (RQ3), with no causal language.
