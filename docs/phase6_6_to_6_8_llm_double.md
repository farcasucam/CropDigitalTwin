# Phases 6.6-6.8 with a language-model double: structured explanation, deterministic verifier, minimal pipeline

Synthetic data; **no real language model was used**: a double that reads the facts in its prompt stands in for it. Nothing here is a quality result of an explanation or of a model. Scripts: `manual_phase6_7_verifier_double_test.py`; report: `data/xai/verifier_double_report.json` (hash 9845be70…).
Framework (tsxai, standard library only): `tsxai.llm` (the explanation schema), `tsxai.verify` (the verifier), `tsxai.report` (the pipeline and its hashed bundle), `tsxai.testing.llm_doubles` (the doubles).

## 1. What was built

* **Explanation schema** (`tsxai.llm`): summary, claims (id, text, cited fact ids, declared numbers with unit, confidence), recommendations (action, supporting claims, `blocked_by`), caveats; JSON Schema for structured output; a malformed answer is an `ExplanationError` with its reason.
* **Verifier** (`tsxai.verify`): closed rules, all deterministic. A claim must cite known facts; every number in its text and every declared number must be one of the cited facts' numbers with the right unit; a claim can be no stronger than the **weakest** evidence level of the facts it cites
  (causal or confirmation wording only at the twin-confirmed level, unless negated); forbidden claims (pack phrases, and any claim of validation against the real system); a recommendation needs verified claims at the twin-confirmed level, otherwise it is blocked with the reason or removed.
  The facts' own rendered wording always stands inside a claim; what the model adds must obey the rules. Corrections: REMOVED, REWRITTEN with the facts' wording, BLOCKED; the corrected explanation passes the verifier again.
* **Pipeline** (`tsxai.report.explain`): facts to Markdown (never raw arrays), a fixed system prompt in Spanish or English, structured output, one retry with the reason on a malformed answer, verification, and a bundle that hashes the facts, the pack, the prompt, the answer and the verdict.
* **Doubles:** `FaithfulWriter` (one claim per fact, with the fact's wording; a recommendation only for a twin-confirmed effect) and `PlantedErrorWriter` (the faithful writer plus one planted defect of a known class, with the ground truth of what was planted).

## 2. Results on the four scenarios (Spanish and English: 8 runs)

* **Faithful writer: 0 violations in 8 runs** (no false positive); identical bundle hash on repetition; recommendations only where a twin-confirmed effect exists.
* **Planted defects: 8 of 8 caught for each of the 9 classes** (claim without facts, invented fact id, distorted number, wrong unit, causal wording, confirmation wording, forbidden claim, claim of validation in the real system, recommendation on an unconfirmed estimate), each flagged on its own claim with the expected rule,
  nothing else flagged, and the correction itself passes the verifier.
* The heat-wave scenario carries a what-if effect **confirmed in 7 of 7 variants of the working twin** (small mismatch): peaks of 7.59-7.65 degC, against the forecaster's estimate of 10.6 degC. The text reports the estimate and the variants' range as an estimate and confirms only the direction; the estimate lies outside the range,
  which is the overestimation the earlier gate measured, visible to the reader. (Here the working twin and the truth of the bank are the same simplified model, so this agreement is circular; the EnergyPlus truth is the independent check of 6.5r.)

## 3. Reading and limits

* **This is a coverage test of the rules, not a measure of a model.** The planted defects are the verifier's own known classes, so a perfect detection was expected; a real model fails in subtler ways (a true sentence that omits a caveat, a plausible unit conversion, a paraphrase that shifts the evidence level, a wrong but fluent causal story).
  The rate of such errors, and what the verifier misses of them, can only be measured with real models and, for usefulness, with experts.
* The verifier checks consistency with the facts, not that the facts are the right ones, and not that a true statement is useful or complete. Paraphrases that avoid the marker words (causal or confirmation) are a known blind spot of a rule-based check.
* H5 (numeric faithfulness and causal over-claim rate) and the ablation arms A0-A4 are **not evaluated**: they need real models, repetitions and at least two LLMs.
* Next: the three LLM containers of the Spark are stopped (they are not this project's: permission is needed to start them) and the access by SSH key is ready; then the double is replaced by an OpenAI-compatible client with record/replay, and the same verifier runs on real answers.
