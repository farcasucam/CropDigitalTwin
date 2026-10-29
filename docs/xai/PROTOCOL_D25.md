# Confirmatory protocol D25 (freeze candidate 0.9)

Status: **FREEZE CANDIDATE.** Complete except the parameters listed in section 7, which step F1 fixes on the development partition only. Machine-readable twin of this document: `src/xai_protocol_d25.json`; check and freeze: `freeze_protocol_d25.py`. After the freeze, any change is a dated entry in section 10, never a silent edit. This protocol supersedes the core questions of `PREREGISTRATION.md` (written under D1-D24); that document's sections on the language-model arms, the verifier and the expert study are not replaced.

## 1. Question
Decision D25: the explanatory core is **interventional re-simulation of the twin**; data-based methods are evaluated by **their own object**; the text is deterministic and a language model is an optional renderer. The confirmatory question is: *under which information, training variation and context does a data-based method (TimesFM as the primary comparator) recover the effects of declared perturbations that the twin computes by re-simulation, and where does it not?* The claim is conditional; it does not presuppose that data-based methods fail.

## 2. Material
* Twin: `agri-twin-interactive/1`, simplified greenhouse backend (no EnergyPlus in the confirmatory run), benchmark design `gctsb-1` unchanged (`src/xai_benchmark_design.json`). Second domain: Tennessee Eastman through the third-party `tep` Python backend (commit in the JSON), host `src/process_twins/tennessee_eastman.py`.
* Partitions: by crop and season, salt `gctsb-1`, 30 percent test, 40 seasons. Test seasons (computed, checked by the script): tomato 0, 3, 5, 15, 20, 22, 29, 31, 32, 33, 36 (11); pepper 0, 3, 5, 7, 11, 13, 16, 19, 21, 23, 24, 25, 28, 31, 33, 35, 36, 39 (18); lettuce 0, 1, 3, 13, 14, 15, 19, 22, 24, 25, 30, 36, 38 (13); Tennessee Eastman noise seeds 3, 4, 6, 10, 13, 14, 18, 21, 23, 33 (10). The test partition is evaluated once.
* Exposure register (the `exposure` block of the JSON): test units that development packages or pilots already generated: tomato 0 (PT-1, 2, 2b, 2c, 3, 3b), pepper 0 and lettuce 0 (PT-2, 2b, 3, 3b), lettuce 1 (PT-2, 2b), tomato 33 (one scenario of the pilot bank, generated; its use to be confirmed), Tennessee Eastman seed 3 (PT-10a). They stay in the confirmatory set, are flagged, and every result is also reported without them. The script refuses to freeze if a bank manifest holds a test scenario that is not in the register.

## 3. Strata
S1 outdoor without controller; S2 greenhouse, controller off; S3 greenhouse, controller on (illustrative equipment of the design), truth under the reactive and the replayed policy; S4 Tennessee Eastman closed loop, truth under both policies. Primary agricultural stratum for the closed-loop question: S3.

## 4. Episodes and truth
Per test crop-season and stratum, two windows; per episode three perturbation players drawn without replacement by a seeded generator from the stratum's factor pool (inside the design's sampling ranges; the Tennessee Eastman IDV pool is fixed in F1, screening out disturbances that shut the plant down on development seeds). Reference: no perturbation. Truth: exact Shapley over the 8 coalitions, total effect, leave-one-out and interaction gap (`tsxai.effects`), exact **inside the simulator**. Excluded from the confirmatory set: fertilisation and nutrient players (not in the frozen design; exploratory only), the set-point as a player, EnergyPlus.

## 5. Comparators and estimands
* **TimesFM (primary, TF):** version 3.0 through the `tsxai` service (covariates native; non-commercial research licence acknowledged); variant 2.5 with XReg (TF25). The estimate of a coalition's effect is the forecast with its interventions given as known-future covariates minus the forecast without them; the controller's outputs are past-only covariates. The occlusion Shapley over the 8 coalitions uses that estimate as its valuation.
* Others: seasonal naive (SN), Holt-Winters (HW), lagged regression (LR), the domain-trained surrogate of PT-5a (DS, trained on development seasons only).
* **Object rule:** each estimate is compared with both truths of its stratum; the primary reading is the one the method's information supports (a forecaster not told the controller's reaction against the replayed truth, a trained closed-loop surrogate against the reactive truth). The assignment is declared in F1 and not chosen after seeing results.

## 6. Hypotheses and analysis
H1 sign agreement of the total-effect estimate; H2 Spearman of the occlusion shares against the exact shares; H3 relative error scaled by the materiality; H4 in S3 and S4, closeness to the replayed against the reactive truth; H5 (descriptive) share of cells where the net total understates the largest component; H6 contract checks (replay of the source reproduces the source in 100 percent of replayed queries; efficiency residual below 1e-9 of the total; identical hashes on repetition). The reference lines of the earlier preregistration (0.8 and 0.6) are lines on the interval, not decisions. Unit: episode clustered by crop and season (seed for Tennessee Eastman); cluster bootstrap, 10 000 resamples, seed 20261030; paired across comparators; Holm within each family over its strata and comparators; non-material cells counted and not scored; inviable runs reported with the reason; negative results reported with the same detail; unplanned analyses labelled exploratory.

## 7. Parameters fixed in F1 (development partition only)
Horizon and context length (agri), Tennessee Eastman window start (at least 2 h of context) and aggregation, the IDV pool, outcomes per stratum, materiality per outcome (starting from the PT-5 values: 1 kWh, 1 h, 0.05 K, 1 g per m2, 1 kPa, 0.1 C), factor pools, the object assignment, the TimesFM service image digest and the episode count per stratum from a development estimate of the interval width of H1 and H2 (minimum: every test crop-season with two windows). Each is written into the JSON with the date and the development evidence.

## 8. Procedure
F1 pilot of the whole pipeline on development seasons only, to fix section 7 and to find faults; F2 freeze: `freeze_protocol_d25.py --freeze` (refuses while any parameter is open or the register is incomplete), tag both repositories, record the container digest; F3 run on the test partition once, archive manifest, hashes and reports; F4 report everything, including unconfirmed hypotheses and the results without exposed units.

## 9. What will not be claimed
Validity against a real greenhouse, crop or plant; calibration or experimental validation of any model; novelty of combining interventions, Shapley values and re-simulation; that data-based methods cannot attribute in general (the claim is conditional on the stated information, training variation and stratum); that the generated text is understood better by people (the comprehension pilot is separate and pending).

## 10. Deviations
Empty until the freeze.
