# Phase 6.2b: power, precision-recall sweep, alternative detectors and covariate adjustment

Development pilot (22 dev scenarios, tolerance 3, materiality 0.25). Synthetic data, truth of the simulated twin. Wide intervals; not the preregistered evaluation.
Reproduce: `python -u manual_phase6_2b_adjusted_analysis_test.py` (writes `data/xai/rq1b_pilot_report.json`).

## Results (level "none" unless stated)

| Question | Result |
|---|---|
| Minimum detectable effect (power >= 0.8, >= 5 changes per bin) | not reached by stl_pelt, stl_binseg, stl_cusum, z-score; white-noise PELT only at 16+ natural sigmas; raw PELT at 2-4 (but with ~49 detections per reference series) |
| Power of stl_pelt by effect bin (0-1 / 2-4 / 4-8 / 8-16 / 16+) | 0.20 / 0.50 / 0.25 / 0.68 / 0.76 (non-monotonic: bins are small) |
| CUSUM / BinSeg vs PELT | no better; power within a few points of stl_pelt in every bin |
| Penalty sweep (k 0.5..64) | precision 0.046 -> 0.058, recall 0.71 -> 0.54; AUPRC 0.009. Raising the penalty does not fix precision |
| Covariate adjustment (short lags) | unexplained detections 1662 -> 731 (-56 %), but decision changes kept 32 -> 27 of 46 and forcing changes still detected 23 of 48 |
| Longer lags (up to 24 h) | unexplained 654 (-61 %), decision kept 23 of 46, forcing still detected 19 of 48 |
| Medium sensor error | adjustment helps little (553 -> 550 short, 424 long); median R^2 falls 0.86 -> 0.45 |

## Reading

- Precision stays near 5 % whatever the detector or penalty: most detections are natural changes of the twin that the truth (interventions only) does not list. This is a limit of the truth definition and of single-series detection, not only of the detector.
- Covariate adjustment halves the unexplained detections but costs recall of the decisions we want to keep, and does not remove all forcing changes. It is a partial, not a clean, separation.
- Alternative detectors give no gain, so the detector is not the bottleneck.
- The preregistered stopping rule (STL/PELT must beat the z-score baseline) is not clearly met: z-score has lower power but similar F1.

## Consequences for the plan

1. Do not claim L1 as a reliable event detector; report the power curve and abstention instead.
2. Attribution (L2) and counterfactuals (L3) are evaluated against the exact G2 effects, independent of L1.
3. Where the host has an event log (the twin), use it for known causes; keep detection for deployments without one.
4. Open: a truth that also lists natural changes (G1b) and BOCPD were not implemented; both would change the precision figure but not the conclusions above.
