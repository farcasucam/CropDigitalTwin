# Phase 6.4: semantic layer with evidence levels

Synthetic data (the simulated twin, exogenous weather as forcing); no quality claim. Framework: `tsxai.semantics` (sibling repo `tsxai`, standard library only). Host side: `semantic_pack` and `crop_stage` in
`src/agri_twin/interfaces/xai_adapter.py`, provisional conventions in `src/xai_semantics.json`. Acceptance script: `manual_phase6_4_semantics_test.py` (report `data/xai/semantics_report.json`, goldens in `data/xai/semantics_golden/`).

## 1. What it does

Numbers become **facts** and facts become Markdown a language model can read without raw arrays. A fact has a stable id (hash of its content, so Spanish and English share it), a kind, a variable, a window, a value with unit, and an
**evidence level** that bounds what the text may claim about the world:

| Level | Meaning | Wording | Example |
|---|---|---|---|
| OBSERVED | it is in the data | "observed" | a change was detected; a threshold was crossed; the controller switched on |
| ASSOCIATED | it coincides with something | "a coincidence, not a cause" | a shift at the sample of a known heat wave |
| MODEL_ESTIMATED | a model says so | "the model estimates" | a forecast; the forecaster's what-if effect |
| TWIN_CONFIRMED | the twin confirms the direction in a quorum of its perturbed variants | "confirmed in k of n variants of the twin" | reachable only with `twin_effects`; direction only, the magnitude stays an estimate |

## 2. Rules that keep it honest

* **Closed vocabulary without digits:** every number printed comes from the fact of its line, written one way (three significant figures). The traceability check rejects a line without an id, an unknown id, and any number the fact does not carry.
* **Thresholds only with a source:** crop thresholds are read from `crop_config.json` by crop and stage and carry their path (for example `tomato/establishment/stress_thresholds.min_temp_c`); a variable or a month with no catalogue value gets "threshold undefined", never an invented one.
  The ON threshold of the controller demand is the device's (D13).
* **An analysis that did not run is reported** (constant, insufficient data, too short): silence would read as "nothing changed".
* **Intervals:** the model's quantile interval is "nominal, not calibrated" unless an empirical coverage within 5 points of its level is supplied.
* **Condensing (D18):** small shifts, stable stretches, constant series, onsets and threshold exceedances beyond the longest are aggregated into one summary fact with its count, to respect the LLM context budget; the limits are provisional conventions.
* Conventions (noise factor 3, quorum 0.8, minimum 3 variants, listing limits) are **provisional design choices**, not values of the system.

## 3. Result on four scenarios (tomato outdoor, tomato greenhouse without controller with a heat wave, pepper greenhouse with controller, with controller and crop feedback)

* 30 / 40 / 61 / 32 facts; **traceability 100 % in Spanish and English** (lines and numbers); both languages share the fact ids; a second build and a second rendering are identical.
* With the heat wave (scenario 2): the detected shifts at the event are ASSOCIATED, the rest OBSERVED; the forecaster's what-if effect on the indoor temperature is MODEL_ESTIMATED ("up to 10.6 degC; no simulator check"); the exact effect of the truth twin
  (7.6 degC) is in the report for reference and **never enters the text**: the forecaster overestimates, and the text does not pretend otherwise.
* **Nothing is TWIN_CONFIRMED yet**: the working twin and its perturbed variants belong to phase 6.5r. The confirmed path is covered by the unit tests of `tsxai` (`tests/test_semantics.py`), not by this demonstration.
* Pepper in March has no stage in the crop catalogue: the text says so and applies no stage thresholds.

## 4. Limits

The vocabulary is generic and short; the closed trend vocabulary has no "accelerating" (no curvature yet); the noise factor and the listing limits are untuned conventions; one forecaster and one horizon; the text has not been read by a language model or an expert yet (that is 6.6-6.8 and the human study).
