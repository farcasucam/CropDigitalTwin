# Phase 6.2c: a truth that includes natural changes (G1b) and a chance baseline

Development pilot (22 dev scenarios, 130 series, tolerance 3). Synthetic data, truth of the simulated twin. Wide intervals; not the preregistered evaluation.
Reproduce: `python -u manual_phase6_2c_full_truth_test.py` (writes `data/xai/rq1c_pilot_report.json`). Code: `tsxai.analysis.natural` (`material_shifts`, `full_truth`, `random_detections`, `evaluate_full_truth`).

## Why

G1 lists interventions only. A detector that finds a real weather front was scored as a false positive, so the 5 % precision of phases 6.2/6.2b mixed detector errors with an incomplete truth.

## Definition

Every material level shift of the NOISE-FREE true series is a true change, whatever its cause. A shift is operational and independent of any detector: on the series minus its STL seasonal component, the difference between the mean of the next 6 and the previous 6 samples; local maxima of its absolute value above `threshold` x SD of the series (0.25, 0.5, 1.0; swept, not tuned), at least 6 apart. Each change is labelled INTERVENTION (material exact effect, G1/G2 unchanged), FORCING (a covariate's own true series shifts up to 6 samples before, 3 after) or NATURAL (neither). The intervention truth is always contained in the full truth.

The **chance baseline** places the same number of detections as the method at random on each series (20 draws, seeded by scenario and variable, at least `min_segment` apart) and scores them against the same truth.

## Results (stl_pelt, observation level "none" and "medium")

| Level | Threshold | True changes / series | Precision | Chance precision | Recall | Chance recall | F1 | Chance F1 (derived) |
|---|---|---|---|---|---|---|---|---|
| none | 0.25 | 15.4 | 0.49 | 0.26 | 0.72 | 0.38 | 0.58 | 0.31 |
| none | 0.5 | 7.1 | 0.27 | 0.13 | 0.86 | 0.42 | 0.41 | 0.20 |
| none | 1.0 | 3.2 | 0.12 | 0.06 | 0.87 | 0.43 | 0.21 | 0.11 |
| medium | 0.25 | 18.1 | 0.55 | 0.26 | 0.20 | 0.10 | 0.30 | 0.14 |
| medium | 1.0 | 8.0 | 0.19 | 0.07 | 0.16 | 0.06 | 0.17 | 0.06 |

- Composition of the truth (threshold 0.25): interventions 159 of 2359 true changes (6.7 %), forcing 1258 (53 %), natural 942 (40 %).
- Precision against the interventions alone stays at 0.046 (0.08 with medium sensor error): that figure measured the truth, not only the detector.
- Recall by cause is similar for every cause (none, threshold 0.25: intervention 0.71, forcing 0.83, natural 0.60): a detector does not tell why a series changed.
- Against the other methods (none, threshold 0.25, F1): stl_pelt 0.58, stl_binseg 0.57, z-score 0.46, raw PELT 0.37. The preregistered stopping rule (deseasonalised PELT must beat the z-score) is met under this truth.

## Reading

- Detection is about twice as good as chance in precision and recall, at every threshold and noise level. The signal is real and modest; the earlier 5 % was mostly the incomplete truth.
- Precision falls as the threshold rises because the detector reports many small shifts that a stricter truth no longer counts. The truth threshold is a convention and must be fixed in the preregistration before the test partition is scored.
- With medium sensor error recall drops to about 0.2: L1 on noisy real sensors would be weak.
- Detection says nothing about cause. Cause needs the host's event log, or covariate adjustment (6.2b, partial).

## Threats to validity

- The series come from a deterministic simulator forced by weather files; only the sensor error is random. The twin has no unmodelled disturbances, faults or operator actions, so these figures say nothing about real crops or plants.
- The truth depends on the shift definition (window 6, STL seasonal). A different definition changes the numbers, not the ordering of methods; this has been checked only across thresholds.
- Pilot size: 22 scenarios, one partition; intervals not computed here.
