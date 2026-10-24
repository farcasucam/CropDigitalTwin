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

## Second domain: the PLC-controlled reactor (`tsxai/examples/reactor_g1b_pilot.py`)

Same analysis, same default configuration, 38 dev scenarios, 114 series (a simulated teaching reactor, one sample per minute, no daily cycle).

- Precision against interventions alone is again low (0.08): interventions are 273 of 2281 true changes (12 %). The incomplete-truth effect is not specific to the twin.
- Natural changes are NOT rare here (1964, about 20 per series at threshold 0.25), against the expectation that the PI loop would hold the state steady. Cause not verified; the shift definition uses windows of 6 samples, which are 6 minutes here and 6 hours in the twin, so it is probably scale-dependent.
- `stl_pelt` (threshold 0.25, none): precision 0.77 against 0.30 for chance, but recall 0.16 (interventions 0.15, against 0.71 in the twin). The z-score baseline is as good (F1 0.31 against 0.27): the ranking of methods found on the twin does not transfer.
- Raw PELT reaches recall 0.91 by detecting almost everything; its chance baseline has recall 0.78, so its F1 (0.58) is barely above chance (about 0.51).
- Conclusion: the numbers are domain-dependent. What holds in both domains: detection beats chance, and the intervention-only truth understates detection. The analyzer's parameters are in samples, not in time units, so the two domains are not comparable until the configuration is expressed in time (open item).

## Time scale declared by the host, chance-corrected skill (follow-up on the reactor)

The analyzer measured everything in samples; a sample is an hour in the twin and a minute in the reactor. `tsxai.core.TimeScale` lets a host declare the sample length, the dominant cycle (or none) and the shortest event worth reporting; `AnalyzerConfig.for_time_scale` derives the period, the minimum segment and `TimeScale.tolerance` (half the shortest event) from it. With the hourly/daily scale the result is exactly the default configuration (same hash), so the twin's numbers do not change. The reactor declares 1 minute, no cycle, events of 20 minutes (its dilution time is 20 to 50 minutes); that value was chosen after seeing a diagnostic, not blind.

Diagnostic before the change (stl_pelt, none, threshold 0.5): the matching tolerance matters (intervention recall 0.15 at 3 samples, 0.30 at 10) but the noise model matters more (long-run: 487 detections, recall 0.22, precision 0.63; white: 2792 detections, recall 0.64, precision 0.33). Neither noise model is right for both: it is an operating-point trade-off that the domain changes.

Two measures were added to every cell: `skill` (precision and recall corrected for chance, 0 = random placement, 1 = perfect) and `saturated` (random placement already reaches precision above 0.5). The analysis now records `method_used` when a different detector ran than the configured one.

| Reactor, level none | Truth threshold | Precision / chance | Recall / chance | Skill P / R |
|---|---|---|---|---|
| declared scale (raw PELT: no cycle, so every STL method and the z-score fall back to it) | 0.25 | 0.66 / 0.59 | 0.95 / 0.76 | 0.17 / 0.77 (saturated) |
| declared scale | 1.0 | 0.33 / 0.31 | 0.91 / 0.76 | 0.03 / 0.61 |
| hourly defaults in samples | 0.25 | 0.77 / 0.30 | 0.16 / 0.06 | 0.67 / 0.11 |
| hourly defaults in samples | 1.0 | 0.39 / 0.13 | 0.30 / 0.10 | 0.30 / 0.23 |

For comparison, the twin (stl_pelt, none, threshold 0.25): skill about 0.31 precision / 0.55 recall (derived from the table above).

Reading:
- Declaring the time scale makes the detector over-detect on the reactor (recall skill high, precision skill near zero); the hourly defaults in samples under-detect (the reverse). Neither is a good operating point, and no single configuration serves both domains.
- Without a cycle, "STL + PELT", "BinSeg", "z-score" and "raw PELT" are not four methods: the method comparison is only meaningful for domains with a declared cycle.
- The truth is not invariant to scale: with the declared scale the reactor has 212 natural changes against 1964 with the default window (threshold 0.25). Any cross-domain claim must fix the shift definition in physical time before the test partition is scored.
- Consequence for the plan: report the power curve and precision-recall trade-off per domain, and choose the operating point with a rule fixed in advance (for example a target false-alarm rate on a reference period), not one tuned on the truth.
