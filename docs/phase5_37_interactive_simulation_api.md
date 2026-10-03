# Phase 5.37 — Interactive simulation API and execution contract

## Result

```text
INTERACTIVE SIMULATION API READY            CANONICAL SIMULATION CONTRACT QUALIFIED
DETERMINISTIC EXECUTION QUALIFIED           CHECKPOINT / RESUME QUALIFIED
STRUCTURED ERROR CONTRACT QUALIFIED         PERFORMANCE OVERHEAD CHARACTERIZED
NO EQUATION, PARAMETER, ENGINE, CLOCK, SCHEDULER, REGISTRY OR STATE REPRESENTATION ADDED
REAL AGRICULTURAL DATA VERIFIED: NO    CALIBRATION PERFORMED: NO    BIOLOGICAL VALIDITY CLAIMED: NO
```

Phase 5.37 builds the application-level boundary a future frontend will call. It does not build the frontend, an HTTP server or a job queue. It performs no scientific validation, calibration or real-data ingestion, and it changes no physical equation.

## 1. Baseline

- **HEAD:** `22a2299` (Phase 5.36 committed); working tree clean.
- **Full regression:** 1102 passed, 12 skipped, 0 failed; 1114.74 s (pytest), 1116.98 s (wall).
- Run sequentially with `.venv` and `PYTHONDONTWRITEBYTECODE=1`.

## 2. Architecture

```text
FRONTEND (future)            -- JSON documents only
    |
InteractiveSimulationService -- validate, canonicalize, resolve, isolate, delegate, project
    |
build_campaign (5.32) -> ScenarioRunner.run -> CropDigitalTwinOrchestrator.step
    |
existing engines (phenology + dormancy controller, greenhouse, radiation growth, water, nutrients, climate stress)
```

The module is `src/agri_twin/application/interactive_simulation.py`. A frontend uses only plain JSON-compatible dictionaries, never internal classes. It never sees:
- `TwinState` classes, `ParameterRegistry` or `ParameterSet`;
- `PhenologyEngine` or `DormancyChillingController`;
- `WeatherEngine` or `ScenarioRunner`;
- repositories, checkpoint internals or engine details.

Each execution owns its `CampaignSpec`, `Scenario` and `ScenarioRunner`. As before, the runner creates the run's single `SimulationClock`. Nothing global is written.

The API reuses existing components and duplicates none of them:

| Concern | Existing component reused |
|---|---|
| crop/period/events/initial state | `build_campaign`, `campaign_cycle`, `_initial_state` (5.29/5.32) |
| weather | `seasonal_weather_factory` / `weather_configuration` + `WeatherEngine` (5.32) |
| dormancy / chilling | `canonicalize_request` → `canonicalize_dormancy_configuration` (5.34/5.35), `DormancyChillingController` |
| execution | `ScenarioRunner.run` → `CropDigitalTwinOrchestrator` |
| checkpoint | `checkpoint_payload` / `restore_checkpoint` / `resumed_scenario` (5.29) |
| observable state | `TwinState` via `twin_state_from_snapshot` |
| trajectory digest | `trajectory_hash` (5.29) |

## 3. API surface

```python
service = InteractiveSimulationService()
created  = service.create_simulation({"crop": "tomato", "environment": "outdoor"})   # CREATED, or SimulationApiError
response = service.start_simulation(created.simulation_id, listener=on_progress)     # COMPLETED / CANCELLED / FAILED
service.get_simulation(simulation_id)            # last SimulationResponse
service.get_simulation_progress(simulation_id)   # SimulationProgress
service.cancel_simulation(simulation_id)         # cooperative
service.get_simulation_result(simulation_id)     # SimulationResult (COMPLETED only; structured error otherwise)
service.resume_simulation({..., "checkpoint": response.checkpoint.to_dict()})
service.run_simulation(request, listener)        # create + start
plan_execution([request, ...])                   # mode classification, nothing executed
contract_description()                           # machine-readable contract
```

Execution is synchronous and in-process. A future HTTP layer or worker process would be an adapter over this class, not part of its core.

## 4. Canonical request (`SimulationRequest`)

| Field | Default (source) | Canonicalization / validation |
|---|---|---|
| `crop` | required | trimmed, lower case; one of the 7 configured crops → `UNSUPPORTED_CROP` |
| `variety` | `KNOWN_VARIETIES` (`RAF`, `Lamuyo`, `Monastrell`, `Suplum 26`, else `UNSPECIFIED`) | only the configured variety; others → `INVALID_CONFIGURATION` (never invented) |
| `plot` | the crop's synthetic plot (`SyntheticReferenceDatasetGenerator.DEFAULT_PLOTS`) | only that plot |
| `environment` | the plot's environment | `outdoor` / `greenhouse` (→ `passive_greenhouse`); greenhouse only for tomato, lettuce, pepper → `UNSUPPORTED_ENVIRONMENT` |
| `scenario` | `BASE_SEASON` | upper case; 12 mandatory + 2 supplementary 5.32 scenarios → `INVALID_SCENARIO` |
| `start_time` | campaign start (`campaign_cycle`) | must equal the campaign start, or the checkpoint time when resuming |
| `end_time` | campaign end | after the start, at or before the campaign end, and a whole number of 3600 s steps → `INVALID_TIME_RANGE` |
| `seed` | 532 (5.32) | non-negative integer |
| `weather` | `{"source": "SYNTHETIC_SEASONAL", "profile_overrides": {}}` | only the 5.32 generator; override keys must be keys of the 5.32 profile; values finite; the existing `WeatherConfiguration` validates the result |
| `dormancy` | `DEFAULT_DORMANCY_CONFIGURATION` | the single 5.34/5.35 canonicalization path (aliases, units, `SOFTWARE_TEST_ONLY` requirements, fallback) |
| `checkpoint` | none | see §8 |
| `options` | see below | unknown fields rejected |

Timestamps need an explicit offset; a naive timestamp is ambiguous and is rejected. They are normalized to UTC. Unknown fields at any level are rejected with the offending path. The canonical JSON uses sorted keys and compact separators. The request hash is the SHA-256 of that JSON and contains no execution timestamp. `canonicalize_request(request.to_dict()) == request`, so the canonical form round-trips.

Options:
- `progress_interval_steps` (default: from the execution mode);
- `require_requested_chilling_model`: an unparameterized Utah/Dynamic request then gives `MODEL_NOT_READY` instead of the STRICT fallback;
- `include_trajectory`;
- `compute_trajectory_hash` (default true);
- `variables`: a subset of the catalogue.

**Weather overrides** replace the effective values *after* the scenario shift, so the scenario shift does not reapply to an overridden key. The full effective profile is reported in `effective_configuration.weather.profile`. The forcing stays `SYNTHETIC_FORCING` and does not represent real climatology.

## 5. Canonical response (`SimulationResponse`)

Each part has its own field:

| Field | Content |
|---|---|
| `request` | the canonical request |
| `effective_configuration` | period, initial-state source, weather profile, scenario events, `dormancy.describe()`, chilling unit, `scenario_config_hash`; hashed as `configuration_hash` |
| `execution_status` | `CREATED` · `RUNNING` · `COMPLETED` · `CANCELLED` · `FAILED` |
| `plan` | execution mode and cost basis |
| `progress` | final progress |
| `result` | model result (see §9) |
| `diagnostics` | execution diagnostics (software/operational): termination, steps, events, execution path |
| `warnings` | categorized `CONFIGURATION` · `SOFTWARE` · `MODEL_BEHAVIOR`, never biological evidence |
| `errors` | structured errors |
| `hashes` | `request_hash`, `configuration_hash`, `resume_hash`, `trajectory_hash`, `result_hash`, `checkpoint_sha256` |
| `checkpoint` | resumable checkpoint at the last completed step |
| `scientific_status` | `REAL_VERIFIED = 0`, `CALIBRATION_PERFORMED = false`, `EXPERIMENTAL_VALIDATION_PERFORMED = false`, `BIOLOGICAL_VALIDITY_CLAIMED = false`, `FIELD_ACCURACY_CLAIMED = false`, `DATA_ASSIMILATION_IMPLEMENTED = false`, parameters `ENGINEERING_DEFAULTS_UNCALIBRATED` |
| `operational` | timings (excluded from every hash) |

`deterministic_dict()` holds everything except `operational`, and `response_hash` is its SHA-256.

## 6. Execution modes (no simulation run to decide)

The mode is derived from configuration only, using the Phase 5.36 single-plot upper cost of 0.47 ms per hourly step (advisory and machine-dependent).

| Mode | Rule | Examples |
|---|---|---|
| `INTERACTIVE` | one request, estimate ≤ 1 s | tomato 7 d (168 steps); lettuce full season (1008 steps) |
| `INTERACTIVE_WITH_PROGRESS` | one request, estimate ≤ 10 s | tomato full season (3744 steps, ≈ 1.8 s); grape (7656 steps) |
| `BACKGROUND` | more than one request (multi-plot / campaign) or estimate > 10 s | 7 crops; 8 scenarios |

`BACKGROUND` plans set `requires_background_executor`. No queue, worker, Celery, Redis or RabbitMQ is introduced. This phase only prepares the contract for one.

## 7. Progress and cancellation

**Progress** is reported through `SimulationProgress`. Its fields are:
- `total_steps`, `completed_steps` and `fraction`;
- `simulated_time` and `current_stage`;
- `current_state`, an existing `TwinState` dictionary;
- `elapsed_seconds`, which is operational and excluded from hashes.

The kind is `OPERATIONAL_PROGRESS_NOT_SCIENTIFIC_EVIDENCE`.
- An `INTERACTIVE` run emits only the final progress.
- A season run emits one event per simulated day (24 steps), plus the final one.

**How it works.** `ScenarioRunner.run` gained two optional keyword arguments, `phenology` and `observer`. The observer is called after each completed step and can stop the run at that step boundary (status `STOPPED`). With both arguments omitted the runner behaves exactly as before; a test checks this. One mechanism serves three purposes:
- progress emission;
- the horizon: a short run stops the *same* run, so a 7-day run is an exact prefix of the season, with no event clipping;
- cooperative cancellation.

**Cancellation** (`cancel_simulation`) sets a flag that the observer checks at the next step boundary. No thread, timer or second scheduler is involved. The orchestrator replaces its state atomically per step, so a stop leaves a consistent state at the last completed step.

The result of a cancellation is:
- **state:** `CANCELLED` with error `CANCELLATION_REQUESTED`, category `OPERATIONAL`. It is not a model or scientific failure.
- **partial result:** `complete: false`.
- **checkpoint:** a checkpoint at the last step, so the run can be resumed.

Cancelling at step *k* is deterministic: two runs give the same response.
- `cancel` before start → `CANCELLED` with no result or checkpoint.
- `get_simulation_result` on a cancelled run → `CANCELLATION_REQUESTED`.
- `cancel` or `start` on a terminal execution → `INVALID_REQUEST`.

## 8. Checkpoint / resume

The response checkpoint is a thin wrapper:

```text
{format: "agri_twin.checkpoint_payload/5.29", simulation_time, payload, sha256, resume_hash}
```

- `payload` is the unchanged Phase 5.29 `checkpoint_payload` (crop, soil and microclimate JSON).
- `sha256` detects altered or truncated payloads.
- `resume_hash` is the SHA-256 of what must match between the producer and the resume: crop, variety, environment, plot, scenario, seed, weather, effective dormancy, campaign start and timestep.

A resume restores the payload with `restore_checkpoint` and continues with `resumed_scenario`, both unchanged in behaviour.

**Finding fixed (minimal, existing helper).** `restore_checkpoint` rebuilt the crop as `CropGrowthState(**values)`. It could not restore a Utah/Dynamic `chilling_state` (Phase 5.35), which is serialized as a dict. It now calls the existing inverse `CropGrowthState.from_dict`. That is the same construction for Chilling Hours states (tested on existing snapshots), and Dynamic states now resume exactly.

**Qualified:** `full == partial + checkpoint + resume`. Every result series concatenates exactly, and the final state and final checkpoint payload are byte-identical. The cases are:
- tomato outdoor;
- lettuce greenhouse;
- tomato `HEAT_WAVE` (checkpoint before the window);
- peach with Chilling Hours;
- peach with Dynamic (`SOFTWARE_TEST_ONLY`);
- a run cancelled at step 100 and then resumed.

**Limitation, rejected rather than approximated.** A checkpoint strictly inside a *ramped* scenario event is rejected with `INVALID_CHECKPOINT`. `resumed_scenario` moves the event start to the restart time, which would re-anchor the ramp weights and break exact equivalence. This limitation already existed before the API.

## 9. Result contract (`SimulationResult`)

Each variable in the catalogue (36 entries) has:
- a name and a unit;
- the source field of the existing snapshot;
- an availability: `AVAILABLE`, `NOT_APPLICABLE` or `NOT_SUPPORTED`.

| Group | Variables | Availability |
|---|---|---|
| crop | stage, maturity, total/fruit biomass, LAI | all runs |
| water | VWC, root-zone water, irrigation, precipitation, drainage, transpiration, evaporation, ET0 (mm per step) | all runs (indoor precipitation is the model's 0) |
| climate | temperature, RH, VPD, radiation experienced by the crop | all runs |
| stress | water, heat, cold, VPD, radiation, frost, accumulated, growth factor | all runs |
| greenhouse | CO2, outdoor temperature, ventilation, shading, heating, cooling | `NOT_APPLICABLE` outdoors |
| dormancy | dormancy released, chill accumulated (unit of the effective model) | `NOT_APPLICABLE` for annual crops |
| not represented | canopy temperature, photosynthesis rate, fruit count, leaf water potential | `NOT_SUPPORTED` (no value fabricated) |

- **Series:** the trajectory is columnar (`time` plus one list per available variable), with one value per hourly step.
- **Totals:** `totals` are `math.fsum` sums of the per-step flux outputs.
- **Final state:** `final_state` is the existing `TwinState` dictionary.
- **No new variables:** no model variable was added for the UI.

## 10. Structured errors

| Code | Category | Examples (path) |
|---|---|---|
| `INVALID_REQUEST` | REQUEST | non-mapping, unknown field (`latitude`), naive/unparseable time (`end_time`), bad seed, unknown option/variable, unknown simulation id |
| `INVALID_CONFIGURATION` | CONFIGURATION | unconfigured variety/plot, unsupported weather source, unknown or invalid climate-profile key, invalid dormancy (`dormancy`) |
| `UNSUPPORTED_CROP` | CONFIGURATION | `crop` |
| `UNSUPPORTED_ENVIRONMENT` | CONFIGURATION | unknown environment, actuated greenhouse, greenhouse for a perennial |
| `INVALID_TIME_RANGE` | REQUEST | end before/at start, beyond campaign, partial step, start ≠ campaign start |
| `INVALID_SCENARIO` | CONFIGURATION | `scenario` |
| `INVALID_CHECKPOINT` | REQUEST | malformed, tampered (`checkpoint.sha256`), other configuration (`checkpoint.resume_hash`), inside a ramped event |
| `MODEL_NOT_READY` | CONFIGURATION | requested Utah/Dynamic without requirement and `require_requested_chilling_model` (`dormancy.chilling_model`) |
| `CANCELLATION_REQUESTED` | OPERATIONAL | cancelled run, result query on a cancelled run |
| `INTERNAL_EXECUTION_ERROR` | EXECUTION | model or runner exception (message kept verbatim), failing progress listener |

Each error carries a stable code, a human-readable message and the field path. Model errors are not hidden: the runner's exception message is passed through verbatim. The qualification report checks 41 error cases.

## 11. Determinism and immutability

**Determinism.** Each case runs twice in fresh services:
- tomato 7 d;
- lettuce greenhouse season;
- tomato `HEAT_WAVE` season;
- pepper greenhouse season;
- peach Dynamic season;
- tomato with a weather override.

Both runs give identical canonical JSON, request hash, effective configuration, configuration hash, trajectory hash, result hash and full deterministic response.

**Direct equivalence.** The API trajectory hash equals a direct `build_campaign` + `ScenarioRunner.run` run for:
- tomato outdoor;
- lettuce greenhouse;
- peach Dynamic.

In each case a 7-day API run is an exact prefix of the direct run.

**Immutability.** These are compared before and after executions, cancellations and resumes, and none changes:
- the `ParameterRegistry` hash;
- the per-crop `ParameterSet` hashes;
- the phenology profiles;
- the 5.32 weather profiles;
- the greenhouse configuration and profiles;
- the default dormancy configuration;
- the hashes of `src/*config*.json`, `crop_phenology.csv` and `config/app.json`.

In addition:
- request and checkpoint documents are not mutated;
- campaign definitions are unchanged;
- returned `TwinState` dictionaries are detached copies.

## 12. Performance (PERFORMANCE_MEASUREMENT, never hashed)

These are the minimum of 3 sequential repeats on the audit machine. "Direct" means `ScenarioRunner.run` with the same horizon observer.

| Case | Steps | Direct (s) | API simulation (s) | API overhead (s) | Overhead | + optional trajectory hash | `to_json` (s) | Response size |
|---|---|---|---|---|---|---|---|---|
| tomato outdoor 7 d | 168 | 0.052 | 0.054 | 0.006 | 11.9 % | 44.9 % | 0.004 | 76 kB |
| lettuce greenhouse season | 1008 | 0.347 | 0.331 | 0.007 | 1.9 % | 30.6 % | 0.024 | 434 kB |
| tomato outdoor season | 3744 | 1.226 | 1.200 | 0.040 | 3.3 % | 35.9 % | 0.081 | 1.3 MB |

The overhead splits as follows:
- **Canonicalization:** about 0.05 ms per request.
- **Preparation** (campaign, scenario, configuration): about 0.3 ms.
- **Result projection:** 1–22 ms.
- **Remainder of the overhead:** response hashing.

The existing Phase 5.29 `trajectory_hash` costs about 0.38 s per tomato season. It is **on by default** because it is the full-state reproducibility digest the determinism contract compares. A latency-sensitive frontend can set `compute_trajectory_hash: false`; `result_hash`, which covers every exposed value, is still computed. Nothing was optimized: the hash and the model core are unchanged.

## 13. Static audit

`static_audit_api` performs an AST scan of:
- `interactive_simulation.py`;
- the modified `scenarios.py` and `integrated_synthetic_validation.py`;
- the manual.

It finds none of the forbidden constructs:
- `datetime.now/utcnow/today`, `time.time` or `sleep`;
- global `random` or `numpy.random`;
- `requests`, `urllib`, `http` or `socket`;
- threading, multiprocessing or asyncio;
- queue or web frameworks;
- a new class named `*Engine`, `*Clock`, `*Scheduler`, `*Registry`, `*TwinState`, `*Orchestrator` or `*Runner`.

The project-wide Phase 5.29 audit is also clean. It scans 60 files and finds no violations, no duplicated core class and no missing core class: one engine, clock, scheduler, `ParameterRegistry`, `TwinState`, `WeatherEngine` and `PhenologyEngine` each.

The API module reads no clock at all, which keeps the Phase 5.36 rule that timing instrumentation stays out of `src/agri_twin`. Operational timings exist only when the caller injects a timer: the manual and tests pass `time.perf_counter`; without a timer, `operational.timings_seconds` is empty. Timings never enter a hash.

## 14. Changes to existing code

1. `ScenarioRunner.run(scenario, *, phenology=None, observer=None)` (`scenarios.py`). The arguments are optional and keyword-only, and the default path is unchanged. This is the only way to pass a dormancy configuration through the runner, and the hook used for progress, horizon and cancellation.
2. `restore_checkpoint` now delegates to `CropGrowthState.from_dict` (`integrated_synthetic_validation.py`). This is the bug fix described in §8; Chilling Hours restoration is unchanged.
3. Exports were added to `application/__init__.py`.

No equation, parameter, phenology requirement, weather/scenario semantics, timestep or historical artifact changed.

## 15. Artifacts and tests

- `tests/test_interactive_simulation.py`: 55 focused tests.
- `manual_phase5_37_interactive_simulation_api_test.py`: steps 1–15, then the qualification report; exit 0, `PASS`.
- `data/simulation/interactive_simulation_api_report.json` and `interactive_simulation_api_README.md`:
  - `software_result`: 13 sections, all PASS;
  - `performance_measurement`;
  - `scientific_evidence`: empty;
  - deterministic hash `74811542…7aac`, identical across rebuilds.

## 16. Limitations (documented, not hidden)

- **Start time:** `start_time` is fixed by the crop's synthetic cycle. A later start is possible only through a checkpoint.
- **Ramped events:** checkpoints inside ramped events are rejected (§8).
- **Weather sources:** only the Phase 5.32 synthetic generator is exposed. Local CSV and downloaded weather are not part of API 1.0.
- **Executor:** execution is synchronous. `BACKGROUND` is a classification; it does not yet have a background executor.
- **Mode estimate:** the cost estimate comes from one machine.
- **Greenhouse modes:** `actuated_greenhouse` is not exposed because there is no actuator schedule contract yet.
- **Varieties and plots:** there is one configured variety and plot per crop.

## 17. Regression after the changes

- **Full regression:** 1158 passed, 12 skipped, 0 failed; 1098.38 s (pytest), 1099.72 s (wall). This adds the 56 Phase 5.37 tests to the 1102 baseline tests.
- **First attempt:** 1 failed. The Phase 5.36 test `test_timing_instrumentation_stays_out_of_the_model` caught the API's default `time.perf_counter` timer, plus a comment naming the 5.36 artifact file. The fix was in the API, not the test: the API module now reads no clock, and callers inject the timer.
- **Whitespace:** `git diff --check` is clean, and the new files have no whitespace errors.
- **Bytecode:** no tracked `.pyc` changed.
