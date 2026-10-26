# Phase 6.6 with real language models: OpenAI-compatible client, record/replay, first run on the Spark

Synthetic data, **four scenarios, one run per model, language and scenario (8 runs per model)**. Script: `manual_phase6_6_real_llm_test.py` (live, or `--replay` offline); report `data/xai/real_llm_report.json` (design v1, hash 664db87d…; the v1 counts of sections 2-3 are unchanged, `flagged_claims` was added afterwards) and `real_llm_report_v2.json` (design v2, hash 6cfd177e…, section 5); recorded answers `data/xai/llm_records/`.
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
| claims flagged by the verifier | 20 (77%) | 16 (55%) | 6 (8%) | 11 (28%) | 39 (71%) | 15 (44%) |
| violations | 35 | 21 | 11 | 24 | 229 | 25 |

Reading:
* **What clearly improved:** Qwen and Llama no longer lose a run (8 of 8 evaluable, none truncated, longest answer about 1.1k tokens) and OLMo's 229 violations (one run dumping dozens of declared numbers) fall to 25.
* **What did not:** the share of flagged claims is still high (44-55% for Qwen and OLMo, 28% for Llama), and for Llama it is *higher* than in v1 (28% against 8%), but v1's Llama figure comes from only 4 evaluable runs and the v1 claims inspected were close restatements of single facts (checked on one answer, not systematically), which are easy to get right; v2 asks for more synthesis. All 22 evaluable runs of v2 carry at least one violation.
* **OLMo still fails 2 of 8 (3 answers cut at 4096 tokens):** the cause is not the schema or the prompt: grammar-constrained decoding lets the model emit free whitespace and it loops on blank lines (82% of one answer is whitespace, a run of 5259 characters). The per-request vLLM options `disable_any_whitespace` and `whitespace_pattern` were accepted but had no effect on the output; the container-level setting would need recreating the `fgkb-*` containers, which are not this project's (not done, needs the user's permission).
* **Cost of the redesign, not measured:** v2 leaves facts without a claim. How many, and whether the dropped ones matter, is not yet measured.
* Qwen's most frequent rule is `RECOMMENDATION_UNCONFIRMED` (8 of 8 runs): it writes a recommendation although no effect is confirmed, a prompt-following failure the verifier catches.
* **Still not a ranking or a quality rate:** same limits as section 4 (8 runs, 4 synthetic scenarios, one prompt, no human audit). Whether the flagged claims are real errors is exactly what the manual audit of a sample (next step) must tell.
