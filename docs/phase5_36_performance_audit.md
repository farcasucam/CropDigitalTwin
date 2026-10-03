# Phase 5.36 — Performance, latency and scalability audit

## Result

```text
PERFORMANCE BASELINE ESTABLISHED       BOTTLENECKS IDENTIFIED AND CLASSIFIED
SIMULATION COST SEPARATED FROM VALIDATION / REPORTING COST
OPTIMIZATIONS IMPLEMENTED AND VERIFIED (validation-suite and test infrastructure only)
NO MODEL EQUATION, PARAMETER, SEMANTIC, TIMESTEP OR TRAJECTORY CHANGED
REAL AGRICULTURAL DATA VERIFIED: NO    CALIBRATION PERFORMED: NO    BIOLOGICAL VALIDITY CLAIMED: NO
```

All timings are `PERFORMANCE_MEASUREMENT`, taken on the audit machine:
- Windows 10, Python 3.13.9, `.venv`, `PYTHONDONTWRITEBYTECODE=1`;
- sequential runs on a single thread;
- each value is the minimum of repeated runs.

Timings are machine-dependent. They are never hashed and are not contracts.

## 1. The two answers

**How long does the actual twin simulation take?** One crop and one plot cost 0.40–0.47 ms per hourly step, i.e. about 0.010–0.011 s per simulated day:

| Workload | Seconds |
|---|---|
| 7 days | 0.07–0.09 |
| full season (lettuce 42 d … grape 319 d) | 0.45–3.3 |
| tomato full season (156 d) | 1.2–1.7 |
| dormancy/chilling season (365 d, Chilling Hours / Utah / Dynamic) | 1.0–1.1 (0.12 ms/step) |

Initialization is negligible:
- `ParameterRegistry.from_repository` ≈ 12 ms;
- each configuration loader is ≤ 7 ms;
- engines, orchestrator and scenario construction are < 0.2 ms each.

**How long does the validation/reporting infrastructure take?** For the same tomato full-season campaign:

| Part | Before | After |
|---|---|---|
| simulation | 1.28 s | 1.19–1.28 s (code unchanged) |
| Phase 5.32 per-campaign evaluation | 0.60 s | 0.52–0.56 s |
| trajectory hashing | 0.36 s | 0.34–0.36 s |
| checkpoint/restart validation (3 restarts) | **14.69 s** | **2.19–2.28 s** (O1) |
| determinism replay | 1.29 s | 1.28–1.29 s |
| infrastructure total vs simulation | ≈ 13 × | ≈ 3.5 × |

Report serialization is negligible: `to_dict`, JSON, SHA-256 and the artifact write take about 3 ms per report. The cost of a phase report sits in its builder's own validation:
- a one-campaign Phase 5.32 report takes 3.4 s to build, of which 0.7 s is simulation;
- the phase manuals take 116–386 s, while one season of simulation takes 0.5–3.3 s.

## 2. Baseline (before any change)

- **HEAD:** `d2067ad` (Phase 5.35 committed); working tree clean.
- **Full regression:** 1069 passed, 12 skipped, 0 failed; 1338.72 s (pytest), 1341.06 s (wall).
- **Slowest 60 tests:** 1269 of 1339 s. The remaining ~1000 tests take about 70 s in total.

| Test file (slowest-60 entries) | Seconds | Cause |
|---|---|---|
| test_dormancy_chilling_framework.py | 238 | module fixture builds the full 5.33 report (169 s) + determinism rebuild (69 s) |
| test_scientific_readiness.py | 220 | 13 tests each re-ran the same deterministic evaluation (DUPLICATED_WORK) |
| test_seasonal_synthetic_campaign.py | 209 | module fixture builds the full 5.32 report |
| test_integrated_synthetic_validation.py | 171 | module fixture builds the 5.29 report |
| post-calibration / real validation / calibration / transferability / synthetic campaign | 35–92 each | per-test framework runs on different inputs |

Manual workloads (sequential runs, same order; all exit 0 before and after):

| Manual | Before (s) | After (s) | Note |
|---|---|---|---|
| 5.6 crop growth | 0.52 | 0.44 | unchanged code |
| 5.10 multi-plot | 0.90 | 0.93 | unchanged code |
| 5.20 readiness | 16.6 | 15.2 | unchanged code |
| 5.29 integrated | 259.0 | 237.5 | unchanged code (noise) |
| 5.30 greenhouse corrections | 1.9 | 1.6 | unchanged code |
| 5.31 greenhouse benchmarks | 5.4 | 4.9 | unchanged code |
| 5.32 seasonal campaigns | 385.6 | 299.2 | O1 |
| 5.33 dormancy/chilling | 230.2 | 122.8 | O2 |
| 5.34 chilling policy | 170.7 | 184.2 | unchanged code (noise, +8 %) |
| 5.35 chilling models | 116.1 | 126.8 | unchanged code (noise, +9 %) |
| total | 1186 | 993 | |

Run-to-run noise on unchanged workloads is about ±10 %. Only the 5.32 and 5.33 changes exceed it, and they match the code each optimization touched.

Every manual rewrites its historical artifact on each run, so all of them were restored to the committed versions.

The regenerated 5.32/5.33 artifacts differ from the committed ones only in fields unrelated to O1/O2:
- `execution_metadata` timings;
- the registry fingerprint and `implemented` flags, which were already stale since Phase 5.35;
- the static-audit scanned-file count.

Their restart, campaign, determinism and policy-matrix content is identical.

## 2a. Final regression (after) and noise

- **Full regression after the changes:** 1102 passed, 12 skipped, 0 failed; 1505.43 s (pytest), 1508.04 s (wall). It includes the 33 new tests in `test_performance_audit.py`.
- The total is *slower* than the 1339 s baseline. Files whose code did not change also slowed (5.29 integrated 126 → 161 s, scientific calibration 53 → 80 s in the durations report), and the machine had background load during the run. The regression total is therefore not evidence for or against any optimization.

Controlled re-run of the affected test files plus one unchanged control file, sequential, whole-file wall time:

| Test file | Baseline (slowest-60 sum, s) | After (whole file, s) | Reading |
|---|---|---|---|
| test_integrated_synthetic_validation.py (control, unchanged) | 170.5 | 181.7 | environment drift ≈ +7 % |
| test_scientific_readiness.py (O3) | 219.7 | 83.8 | improvement far beyond noise |
| test_seasonal_synthetic_campaign.py (O1) | 209.4 | 211.8 (earlier isolated run: 173) | within noise at file level |
| test_dormancy_chilling_framework.py (O2) | 238.3 | 280.4 | no file-level improvement; the fixture uses a reduced location set, so `policy_matrix` is a small share of it |

The baseline column sums only the slowest-60 entries, while the after column is whole-file wall time, so the comparison is approximate. Only O3 shows a file-level gain that is robust to this noise. The evidence for O1 and O2 is the isolated component measurements (§1, §7) and the 5.32/5.33 manual timings (§2), not test-file totals.

## 3. Framework

`src/agri_twin/application/performance_audit.py` (`PerformanceAuditSuite`) measures the existing components and reimplements nothing:
- **initialization:** configuration loaders, registry, engines, scenario, orchestrator, repository;
- **per-step components:** weather (base, event overlay, total), greenhouse, phenology, radiation growth, water, nutrients, climate stress, CO₂, state replacement, persistence, serialization, hashing;
- **benchmark matrix:** 23 workloads (§4);
- **cost separation:** simulation, validation, hashing, restart, persistence, replay;
- **reporting:** construction, `to_dict`, JSON, SHA-256, writing;
- **profiling:** cProfile of a simulation and of a validation workload;
- **scaling:** 5 axes plus a T×P grid;
- **frontend classification;**
- **optimization equivalence oracles;**
- **mutation and determinism checks.**

The regression slowest-test analysis in §2 comes from `pytest --durations`, not from this module.

`time.perf_counter` and `cProfile` are confined to this module as `PERFORMANCE_INSTRUMENTATION`. The only other `perf_counter` uses are the pre-existing metadata timers of three validation suites. No domain module or simulation step uses timing, and this is enforced by `test_timing_instrumentation_stays_out_of_the_model`.

Timings never enter configuration hashes or the report's `deterministic_hash`. That hash covers only deterministic content:
- workload descriptions and step counts;
- trajectory hashes;
- profiler call counts;
- scaling outputs;
- mutation and equivalence results.

## 4. Benchmark matrix (simulation only, after)

**Single plot, one crop:**

| Workload | Days | Steps | s | ms/step |
|---|---|---|---|---|
| small tomato outdoor | 7 | 168 | 0.09 | 0.53 |
| medium tomato outdoor full season | 156 | 3744 | 1.67 | 0.45 |
| tomato × 7 scenarios (HOT, COLD, DRY, HUMID, HEAT_WAVE, COLD_WAVE, HEAT_WAVE_WITH_DRYNESS) | 156 | 3744 each | 1.63–1.79 | 0.44–0.48 |
| lettuce / pepper / grape / peach / plum / apple outdoor | 42–319 | 1008–7656 | 0.45–3.30 | 0.40–0.45 |
| greenhouse tomato / lettuce / pepper | 156 / 42 / 194 | | 1.64 / 0.46 / 2.09 | 0.44–0.46 |
| chilling CH / Utah / Dynamic, peach | 365 | 8760 | 1.01–1.05 | 0.12 |

**Multiple plots or cycles:**

| Workload | Days | Steps | s | ms/step |
|---|---|---|---|---|
| multi-plot: 7 crops on one SimulationClock/Scheduler | 30 | 5040 | 1.93 | 0.38 |
| multi-cycle: lettuce × 3 | 3 × 42 | 3024 | 1.32 | 0.44 |

## 5. Profiling and bottlenecks

**Simulation** (tomato greenhouse full season, cProfile):

| Function | Share of time | Classification |
|---|---|---|
| `dataclasses._replace` | 14.8 % | STATE_MANAGEMENT |
| `CropGrowthState.__post_init__` | 13.9 % | VALIDATION |
| `getattr` (inside `__post_init__`) | 10.4 % | PYTHON_OVERHEAD |
| `math.isfinite` | 5.0 % | — |
| `WeatherEngine._wave` | 3.6 % | — |
| model engines | ~38 % in total | MODEL_COMPUTATION |

About 7 validated `CropGrowthState` copies are made per step. This is the invariant contract, so it was not changed (see §8).

**Validation** (Phase 5.32 evaluate + 3 restarts), before O1:
- `_numeric_fields`, `dataclasses.fields`, `isinstance`, `getattr` and the `fields` genexpr took about 70 %.
- The cause was `snapshot_numbers(b)` being rebuilt once per key for every compared snapshot: O(keys²) instead of O(keys).

After O1 these functions are no longer a dominant cost; their call count fell from 1 476 864 to 75 168.

**Per-step component costs** (isolated, µs per call):

| Component | µs |
|---|---|
| weather (base 51, with event overlay 66) | 66 |
| greenhouse | 28 |
| phenology | 21 |
| radiation growth (×2 per step) | 21 |
| nutrients | 26 |
| climate stress | 25 |
| water | 5 |
| state replacement | 17 |
| checkpoint payload | 79 |
| one-snapshot trajectory hash | 94 |
| repository save | 8 |

## 6. Duplicated-work audit

| Item | Decision |
|---|---|
| registry construction / parameter lookups (≈ 12 ms, per suite, not per step) | NECESSARY |
| configuration canonicalization (once per controller) | NECESSARY |
| hashing (validators / replays only, never per step) | SHOULD_REMAIN_EXPLICIT |
| JSON / `to_dict` (checkpoint and persistence validation only) | NECESSARY |
| `CropGrowthState` copies with re-validation | SHOULD_REMAIN_EXPLICIT (OPEN_PERFORMANCE_ARCHITECTURE) |
| filesystem writes (~2 ms per report, none during simulation) | NECESSARY |
| 5.33 determinism replay of its policy matrix | NECESSARY (determinism evidence) |
| identical weather regenerated 12× per location in 5.33 policy matrix | REDUNDANT → O2 |
| `snapshot_numbers` rebuilt per key in 5.32 restart | REDUNDANT → O1 |
| readiness tests re-evaluating the same deterministic report | REDUNDANT → O3 |
| phenology / greenhouse / invariant calculations in the step | NECESSARY (one call per engine per step) |

## 7. Optimizations (all outside the model; all proven equivalent)

Each optimization below states its scope, its change and its proof.

**O1 — Phase 5.32 `restart()` snapshot flattening.**
- *Scope:* validation only.
- *Change:* each compared snapshot is flattened once (`_max_abs_difference`), with the same keys, order, subtraction and `max`.
- *Proof:* restart rows are byte-identical to the pre-5.36 expression, kept as a verification oracle in the audit (`_reference_restart_difference`).
- *Measured effect:*
  - the comparison pass is 19–31× faster;
  - checkpoint/restart validation went from 14.69 s to 2.19 s on the same campaign;
  - `test_seasonal_synthetic_campaign.py` measured 173 s in one isolated run and 212 s in another (baseline 209 s), so the file-level effect is within noise (§2a).

**O2 — Phase 5.33 `policy_matrix` weather replay.**
- *Scope:* validation only.
- *Change:* each location's hourly series is generated once per call and replayed with the existing `ReplayedWeather` / `record_series`, the same pattern Phase 5.34 uses.
- *Proof:* all 90 policy-matrix rows are byte-identical to the live-weather loop (oracle) and to the committed Phase 5.33 artifact.
- *Measured effect:* the per-location policy matrix is 2.1× faster; all six locations take 33–35 s instead of about 74 s. The 5.33 test file shows no file-level gain (§2a).

**O3 — Readiness tests share one deterministic evaluation.**
- *Scope:* test infrastructure only.
- *Change:* the tests use module-scoped read-only fixtures. The determinism tests still compare against an independent fresh evaluation, and the mutation test evaluates on its own. No assertion changed.
- *Measured effect:* `test_scientific_readiness.py` went from 220 s to 77 s.

What did not change:
- **Benchmark outputs:** every benchmark-matrix workload produces the same steps and trajectory hash as the pre-optimization baseline (`data/performance/performance_baseline_reference.json`).
- **Simulation timings:** the after/before median ratio is 0.95. That is machine noise, not an improvement, because the simulation code is unchanged.
- **Historical artifacts:** no historical artifact needed regeneration.

## 8. OPEN_PERFORMANCE_ARCHITECTURE (documented, not redesigned)

- **IMMUTABLE_STATE_REVALIDATION**
  - *Evidence:* about 40 % of a campaign goes to `dataclasses.replace`, `CropGrowthState.__post_init__` and `getattr`.
  - *Why not changed:* reducing it would change the invariant contract.
- **VALIDATION_DOMINATES_SUITE_TIME**
  - *Evidence:* qualification suites re-run simulations as determinism, restart and replay evidence.
  - *Implication:* a frontend should call the simulation (orchestrator / `ScenarioRunner`), not the phase suites.
- **CROSS_ARTIFACT_FILESYSTEM_DEPENDENCY**
  - *Evidence:* Phase 5.34/5.35 reports embed hashes and rows of committed earlier artifacts. Re-running an earlier manual changes later artifacts (observed: running the 5.33 manual changed the `baseline_report_hash` field in the 5.35 artifact).

## 9. Scaling (measured, sequential)

| Axis | Points | Measured | R² |
|---|---|---|---|
| simulation_days | 15/30/60/120 d | LINEAR (≈ 0.011 s/day) | 0.999 |
| number_of_plots | 1/2/4/7 (15 d) | LINEAR (≈ 0.18 s/plot) | 0.995 |
| number_of_crops | 1/3/5/7 (15 d) | LINEAR | 0.999 |
| number_of_scenarios | 1/2/4/8 (15 d) | LINEAR | 0.9997 |
| number_of_cycles | 1–4 lettuce (15 d) | LINEAR | 0.996 |
| T × P grid | {15, 30} d × {1, 4} plots | consistent with O(T×P); s/plot-day CV 2–5 % | |

The theoretical structure is O(S × C × T × P): constant work per hourly step per plot, with independent campaigns and plots. The measurements agree.

## 10. Frontend readiness (advisory, technology-neutral, simulation only)

Bands: ≤ 1 s `INTERACTIVE`; ≤ 10 s `INTERACTIVE_WITH_PROGRESS`; ≤ 120 s `BACKGROUND_TASK`; above that `BATCH_ONLY`.

| Request | s | Class |
|---|---|---|
| one crop, one plot, short horizon (7 d) | 0.09 | INTERACTIVE |
| one crop, one plot, full season | 1.7 (0.5–3.3 by crop) | INTERACTIVE_WITH_PROGRESS (lettuce INTERACTIVE) |
| greenhouse tomato / lettuce / pepper, full season | 1.64 / 0.46 / 2.09 | WITH_PROGRESS / INTERACTIVE / WITH_PROGRESS |
| 7 plots, full season (estimate from measured s/plot-day) | ≈ 11 | BACKGROUND_TASK |
| 50 plots, full season (estimate) | ≈ 80 | BACKGROUND_TASK |
| phase qualification suites (5.29–5.35 manuals) | 116–386 | BATCH_ONLY |

Because simulation scales linearly with steps, a frontend can stream progress by simulated day: about 0.011 s per day per plot.

## 11. Limitations

- Timings come from one machine, are not portable, and are subject to background load. Tests assert no absolute runtime.
- cProfile inflates absolute times, so profiles are read through percentages and call counts.
- Multi-plot frontend figures for 7 and 50 plots are linear extrapolations from the measured seconds per plot-day.
- No optimization targeted the scientific model. Its dominant overhead (state re-validation) is documented as open.
