# Phase 6.2 - Deterministic analyzer and RQ1 pilot

Status: analyzer COMPLETE (software qualification); RQ1 evaluation is a DEVELOPMENT PILOT (22 scenarios), not the preregistered evaluation. The data are synthetic; truth is the truth of the simulated twin (uncalibrated crop model). Nothing here validates or calibrates anything.

## What was built (in `tsxai.analysis`, extra `analysis`: numpy, statsmodels, ruptures)

* `analyze_series` / `analyze_frame`: STL (period 24, robust) with the strength of trend and seasonality (Wang, Smith and Hyndman), PELT on the **deseasonalised** series (observed minus the STL seasonal component), a reported
  BIC-style penalty `k * log(n) * sigma^2`, an additive Holt-Winters baseline (smoothing parameters and SSE) and a z-score baseline.
* **Honest statuses:** `CONSTANT` (nothing to explain: no trend or change is invented), `TOO_SHORT` (fewer than two periods: no STL, the raw series is still searched), `INSUFFICIENT_DATA` (the longest gap-free run covers
  under half the series). Gaps are never filled.
* `attribute_changes`: a detected change is labelled `KNOWN_CAUSE` when a known event lies within the tolerance, else `NO_KNOWN_CAUSE`.
* `evaluate_rq1`: one-to-one matching with a tolerance, precision/recall/F1, location error, cluster bootstrap over crop-seasons, and `reference_alarm_rate` (detections per series on the intervention-free reference run).
* Noise model: `white` (the BIC penalty assumes independent noise) or `long_run` (default: the noise variance is inflated by `(1+phi)/(1-phi)` for the lag-1 autocorrelation `phi` of the residual).

## Findings of the development pilot (22 dev scenarios, 130 series, tolerance 3 samples, materiality 0.25 of the series SD)

1. **The first run was badly miscalibrated.** The STL residual of the twin's series has lag-1 autocorrelation between 0.7 and 0.98, and a white-noise penalty over-fits: ~39 "jumps" per intervention-free series.
2. **The long-run noise model helps but does not solve it.** At no sensor error: `stl_pelt` F1 0.086 (95 % interval 0.054-0.135) against 0.058 with white noise and 0.037 for raw PELT (0.023-0.055); false
   positives fall from 3990 to 2344 and the detections per intervention-free series from 37 to 22 (median 13.5).
3. **Precision stays near 5 % for every method.** The benchmark's truth lists interventions only, but the twin's series carry many natural changes (weather fronts, thermostat regimes), and all of them count as false positives.
   The reference-run alarm rate (13-22 detections per series for every STL-based method, 49 for raw PELT) shows how much of this is natural variation and over-fit rather than a defect of the scoring alone.
4. **Direction of H1a:** deseasonalising before PELT clearly beats raw PELT in false positives and recall; the F1 intervals only just separate. The residual-only variant is indistinguishable from `stl_pelt` here.
5. **The simple baseline is not clearly beaten.** The z-score baseline has F1 0.081 against 0.086 at no error and 0.119 against 0.134 at low error, with overlapping intervals. The preregistered stopping rule (if PELT/STL
   do not beat the z-score on the residual, the analyzer is simplified and that is reported) is therefore **open**, to be decided on the frozen evaluation.
6. **Degradation with sensor error (H1b):** F1 for `stl_pelt` goes 0.086 (none), 0.134 (low), 0.135 (medium), 0.090 (high). Recall falls from 0.71 to 0.19; the rise of F1 from none to low comes from fewer false
   positives, not better detection. Median location error is 0-2 samples.
7. Sensitivity (`stl_pelt`): F1 at no error is 0.077 / 0.086 / 0.099 for tolerance 2 / 3 / 6, and 0.088 / 0.086 for materiality 0.1 / 0.5.

## What this means for the design

A detector that only sees one series cannot tell an intervention from the weather. The useful step for explanation is to analyse what the **forcing does not explain**: regress the target on the known-future covariates
and look for shifts in the remainder. That is a follow-up (6.2b) to evaluate on the benchmark before the preregistered run, together with a truth that also lists natural changes. Until then, claims about change
detection in the twin are limited to what the numbers above show, on a small development pilot.

## Reproduce

`python -u manual_phase6_2_analyzer_test.py 30` (needs `pip install -e ../tsxai[analysis]`) writes `data/xai/gctsb_dev_pilot/` (development partition only; the test partition is never opened) and
`data/xai/rq1_pilot_report.json`. The analyzer cost is small; generating the scenarios takes about 15 s each.
