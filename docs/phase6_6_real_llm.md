# Phase 6.6 with real language models: OpenAI-compatible client, record/replay, first run on the Spark

Synthetic data, **four scenarios, one run per model, language and scenario (8 runs per model)**. Script: `manual_phase6_6_real_llm_test.py` (live, or `--replay` offline); report `data/xai/real_llm_report.json` (design v1, hash 13cf0a41…; the v1 counts of sections 2-3 are unchanged, `flagged_claims` was added afterwards) and `real_llm_report_v2.json` (design v2, hash e32ac33e…, section 5).
**Correction (2026-10-26):** the first version of `flagged_claims` also counted violations of recommendations and caveats, so the shares of flagged claims first written in sections 5 and 6 (43-55%) were inflated; the tables below carry the corrected counts (violations on real claim ids only); recorded answers `data/xai/llm_records/`.
Models (vLLM 26.09 containers `fgkb-*` on the Spark, temperature 0, seed 0, structured output by JSON Schema): Qwen2.5-7B-Instruct, Llama-3.1-8B-Instruct, Olmo-3-7B-Instruct.

## 1. What was built (in `tsxai`, standard library only)

* `tsxai.adapters.OpenAILanguageModel`: chat-completions client behind the `LanguageModel` port; typed errors, the URL is not part of the recorded model identity.
* `tsxai.llm.RecordingLanguageModel` / `RecordedLanguageModel`: every (prompt, answer) pair keyed by prompt hash; replay gives the identical bundle hash, an unknown prompt is an error.
* `explain(..., max_tokens=)` (default 2048, unchanged for the doubles); the retry no longer loses it.
* `bare_fact_id`: the prompt labels facts `[F:id]` and the models cite them as `F:id`; the parser strips only that label (a wrong id stays wrong).

## 2. What happened, in order (kept because each step changed the numbers)

1. **First run, 2048 tokens: 26 of 39 answers truncated** (`finish_reason=length`); the models write one claim per fact and the prompt takes 1.6-3.4k tokens. Not usable (`data/xai/llm_records_max2048/`).
2. **4096 tokens** (the most that always fits in the 8192 context): truncated final answers: Qwen 1, Llama 4, OLMo 1 of 8. Run in parallel (8 requests per model at once; decoding is bandwidth bound, so ~10 min per model instead of ~30).
3. **Id label:** with the strict parser, 93 (Llama), 82 (Qwen) and 346 (OLMo) violations, most of them `TRACE_UNKNOWN_FACT` caused by the `F:` label alone (`real_llm_report_strict_ids.json`). After stripping the label, offline on the same answers: **Llama 11, Qwen 35, OLMo 229**.

## 3. Result (normalized ids; counts, not rates; 8 runs per model)

| | Qwen2.5-7B | Llama-3.1-8B | Olmo-3-7B |
|---|---|---|---|
| final answer truncated | 1 | 4 | 1 |
| not parseable after one retry | 2 | 4 | 2 |
| runs with at least one violation | 6 | 4 | 6 |
| violations | 35 | 11 | 229 |
| claims written | 26 | 71 | 55 |
| fact ids cited with the `F:` label | 51 of 96 | 40 of 71 | 159 of 159 |

* The verifier does not stay silent on real answers (the double gave 0 and 9/9 planted classes): the rules that fire are number-not-in-fact, unit mismatch, causal and confirmation wording above the evidence, and recommendations without a confirmed effect.
* Violation counts are not comparable between models: Llama and OLMo write many more claims in some runs, and OLMo's 174 `NUMERIC_VALUE_MISMATCH` come from a few runs that declare dozens of numbers on a claim that cites a single fact (a real faithfulness error, verified on one case, not a format issue).
* Non-parseable answers are mostly truncation at 4096 tokens or a recommendation that cites claim ids that do not exist.

## 4. Limits

One run per cell, four synthetic scenarios, no repetitions, no intervals, no expert evaluation, one prompt. **Not a model ranking and not a quality or error rate**; D2 (model choice) is not decided by this. The label normalization is a decision of ours made after seeing the first run (D22); both reports are kept.
H5 and ablation A0-A4 are still not evaluated. The verifier checks consistency with the facts, not usefulness. Next: shorten or split the prompt (one claim per fact overflows the output budget), measure on more scenarios with repetitions, then RAG (D16) as product layer.

## 5. Output redesign (v2): short, bounded explanation

v1 asks for one claim per fact. v2 (`explain(..., design="v2")`, v1 stays the default so the doubles' hashes do not change) asks for at most 6 prioritized claims (confirmed effects, forecasts, threshold exceedances, largest changes), lets a claim cite several facts, asks for declared numbers only where the text carries them, and bounds the answer in the JSON Schema itself (claims 6, declared numbers 6 per claim, recommendations 3, caveats 4, at least one fact per claim), which the server enforces. Same models, same scenarios, 4096 tokens, 8 runs per model; recorded in `llm_records_v2/`, replay gives the identical report hash.

| | v1 Qwen | v2 Qwen | v1 Llama | v2 Llama | v1 OLMo | v2 OLMo |
|---|---|---|---|---|---|---|
| runs evaluable (of 8) | 6 | **8** | 4 | **8** | 6 | 6 |
| final answer truncated | 1 | **0** | 4 | **0** | 1 | 2 |
| claims written | 26 | 29 | 71 | 40 | 55 | 34 |
| claims flagged by the verifier | 13 (50%) | 5 (17%) | 0 (0%) | 7 (18%) | 34 (62%) | 9 (26%) |
| violations | 35 | 21 | 11 | 24 | 229 | 25 |

Reading:
* **What clearly improved:** Qwen and Llama no longer lose a run (8 of 8 evaluable, none truncated, longest answer about 1.1k tokens) and OLMo's 229 violations (one run dumping dozens of declared numbers) fall to 25.
* **What did not:** between 17% and 26% of the v2 claims are still flagged, and for Llama the share is *higher* than in v1 (18% against 0%), but v1's Llama figure comes from only 4 evaluable runs and the v1 claims inspected were close restatements of single facts (checked on one answer, not systematically), which are easy to get right; v2 asks for more synthesis. All 22 evaluable runs of v2 carry at least one violation (some on recommendations or caveats, not on claims).
* **OLMo still fails 2 of 8 (3 answers cut at 4096 tokens):** the cause is not the schema or the prompt: grammar-constrained decoding lets the model emit free whitespace and it loops on blank lines (82% of one answer is whitespace, a run of 5259 characters). The per-request vLLM options `disable_any_whitespace` and `whitespace_pattern` were accepted but had no effect on the output; the container-level setting would need recreating the `fgkb-*` containers, which are not this project's (not done, needs the user's permission).
* **Cost of the redesign, not measured:** v2 leaves facts without a claim. How many, and whether the dropped ones matter, is not yet measured.
* Qwen's most frequent rule is `RECOMMENDATION_UNCONFIRMED` (8 of 8 runs): it writes a recommendation although no effect is confirmed, a prompt-following failure the verifier catches.
* **Still not a ranking or a quality rate:** same limits as section 4 (8 runs, 4 synthetic scenarios, one prompt, no human audit). Whether the flagged claims are real errors is exactly what the manual audit of a sample (next step) must tell.

## 6. Own containers without free whitespace (`--server agritwin`)

The `fgkb-*` containers belong to the Spark's owner and could not be reconfigured; with the user's permission they were stopped (not removed: `docker start fgkb-qwen fgkb-llama fgkb-olmo` restores them) and three containers of this project were created: `agritwin-qwen` (8010), `agritwin-llama` (8011), `agritwin-olmo` (8012), same image, models and flags plus `--structured-outputs-config '{"backend": "xgrammar", "disable_any_whitespace": true}'` (the option needs the backend named; per request it had no effect). Weights come from the Hugging Face cache offline; no token is copied. The server configuration is part of every recorded model identity. Design v2, same scenarios, 8 runs per model; `llm_records_v2_agritwin/`, `real_llm_report_v2_agritwin.json` (hash e3747cbd…).

| | Qwen fgkb | Qwen agritwin | Llama fgkb | Llama agritwin | OLMo fgkb | OLMo agritwin |
|---|---|---|---|---|---|---|
| runs evaluable (of 8) | 8 | 8 | 8 | 7 | 6 | **8** |
| final answer truncated | 0 | 0 | 0 | 0 | 2 | **0** |
| claims written | 29 | 37 | 40 | 38 | 34 | 29 |
| claims flagged | 5 (17%) | 7 (19%) | 7 (18%) | 9 (24%) | 9 (26%) | 10 (34%) |

* **The whitespace loop was a server-side effect:** no answer is truncated, the largest whitespace share of an answer is 13% (against 82%) and the longest answer is 1.9k tokens. OLMo now answers 8 of 8.
* **One new failure, Llama:** one answer has repeated claim ids (`claim ids must be unique`), a model error, not an infrastructure one.
* **A warning about noise:** the only thing that changed for Qwen and Llama is the server's whitespace handling, yet their answers changed (Qwen wrote 29 claims and now 37) and the flagged share moved by 2 to 8 points (OLMo 26% to 34%, on 29-37 claims per model). Differences of that size between two configurations, or between models, must not be read as effects; this is a floor for the run-to-run variation of this measurement, not an estimate of it.
* Violations are now mostly `NUMBER_NOT_IN_FACT` (5-7 runs per model), `RECOMMENDATION_UNCONFIRMED` for Qwen (8 of 8 runs) and `OVERCLAIM_CONFIRMED` for OLMo (6 runs).
* Unchanged limits: 8 runs, 4 synthetic scenarios, one prompt, no human audit, not a ranking. The manual audit of a sample of flagged and unflagged claims is the next step and is what decides whether these flags are real errors.

## 7. Audit of the verifier on real claims (first pass, NOT independent)

Material: `manual_phase6_6_audit_sample.py` builds, from the design v2 / own-containers run, a sheet of **52 claims: all 26 claims the verifier flagged plus 26 random unflagged ones** (fixed seed, shuffled, the verifier's verdict hidden): `data/xai/audit/audit_blind.csv` (to be filled in by an auditor: columns `verdict`, `note`; codes OK, NUMBER, UNIT, OVERCLAIM, UNSUPPORTED, OTHER) and `audit_key.csv` (verifier verdicts). Of 104 claims in the 22 evaluable runs, 26 were flagged; only claims were audited, not summaries, caveats or recommendations.
`audit_assistant_firstpass.csv` holds the **assistant's own verdicts**. They are not an audit: one reader, who is also the author of the verifier and of the prompt, no second opinion, no agronomic expertise, a sample of 52. They are a first pass to find where the rules are wrong and to prepare the sheet; the figures below must be redone with an independent auditor.

| | claims | meaning |
|---|---|---|
| flagged, substantive error | 6 | wrong or invented number, or confirmation wording on observed facts |
| flagged, minor | 5 | rounding, a count the model derived, loose use of "confirmed" |
| flagged, error only in the declared numbers | 4 | the claim text is the fact, the declared number or unit is spurious |
| flagged, **verifier artifact** | **11** | the claim is faithful; the rule misreads it |
| not flagged, substantive error (**missed**) | 3 of 26 sampled | direction reversed, size said to be confirmed, an invented cause |
| not flagged, minor error (missed) | 2 of 26 | an unsupported hedge, a wrong declared unit |
| not flagged, OK | 21 of 26 | |

**Findings**
* **Part of the flags are the verifier's fault, and they are fixable:** 6 of the 11 artifacts are number formats (the Spanish answers write `5.88` where the fact has `5,88`; one model writes `−0.188` with a Unicode minus) and 5 are the unit rule, which only knows the fact's main unit (`133 h` inside a fact in degC, a sample index, a rate in degC/h). Without them the share of flagged claims would fall from 26 to about 15 of 104.
* **The verifier misses errors that no marker word reveals:** a direction reversed (the fact says "baja", the claim "aumenta"), the size of an effect called confirmed when the fact says only the direction is, and invented causes phrased as hedges ("suggesting possible heating system malfunctions", "potential external influences"). This is the paraphrase blind spot already named in section 3 of the double's document, now seen on real answers.
* **Rough reading, with a very wide uncertainty (n = 26 sampled unflagged, 3 misses):** of the substantive errors in the 104 claims the verifier would have caught about 6 and missed about 9 (3 of 26 sampled, scaled to the 78 unflagged). Of its 26 flags, 6 are substantive errors (23%), 15 are errors of any kind (58%) and 11 are artifacts (42%).
* **No claim about the models:** these are the verifier's precision and recall on a small sample, not an error rate of any model.

**Backlog for the verifier (not done)**: (1) match numbers regardless of decimal separator and minus sign; (2) accept for a declared number any unit that appears next to that number in the fact; (3) a direction check (rise/fall words against the fact's direction); (4) a check that a number of an effect is not called confirmed when the fact says the size is not; (5) for hedged speculation, a second check (an entailment or judge model) that must itself be evaluated on this sheet. Items 1-2 remove the artifacts, 3-4 are rules with known false-negative limits, 5 is research.
