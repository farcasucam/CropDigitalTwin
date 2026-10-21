# Phase 5.40 audit: immersive interactive UX (read-only)

Scope: read-only audit before implementing an "immersive interactive UX". No code was changed. Date: 2026-10-20. Branch `main`, HEAD `5157727`.

## 0. Key finding: Phase 5.40 already exists

`docs/architecture/PHASES.md:60` already lists **5.40 "Interactive visual simulation and isometric model view"** as `IN VERIFICATION` (100 focused tests; SVG isometric view, vendored uPlot, layers, event timeline, delta comparison, record/replay). Files: `docs/phase5_40_interactive_visual_simulation.md`, `manual_phase5_40_visual_simulation_test.py`, `tests/test_visual_simulation.py`, `frontend/visual.js`, `frontend/visual_state.js`, `src/agri_twin/application/runtime_replay.py`. The doc says closure needs "the full regression and browser evidence" (`docs/phase5_40_interactive_visual_simulation.md:3`). An "immersive UX" delivery should therefore be numbered **5.41** (or explicitly extend 5.40 after closing it). Phase 5.39 is COMPLETE (PHASES.md:59), 5.38 COMPLETE (:58), 5.37 (:57), 5.36 (:56).

Phase docs: `docs/phase5_36_performance_audit.md` (279 lines), `phase5_37_interactive_simulation_api.md` (330), `phase5_38_frontend_simulation.md` (197), `phase5_39_interactive_runtime_and_visualization.md` (70), `phase5_40_interactive_visual_simulation.md` (46). Reports under `data/frontend/` (`interactive_frontend_report.json`, `interactive_runtime_report.json`, `visual_simulation_report.json`).

## 1. Reusable existing

### Frontend (all vanilla JS, no build step)
- `frontend/index.html` (303 lines): config form (crop/variety/environment/plot/scenario/horizon/dormancy), run status, results, chart grid (`#chart-grid`, :172), runtime section (`#runtime-section`, :206) with pause, branch slider, event form (:213-231), `#iso-wrap`/`#iso-svg` (`viewBox 0 0 640 380`, :271). Scripts loaded with `defer` and cache-bust query strings (:10-14).
- `frontend/app.js` (729 lines): capabilities load, request build, create/start/poll (`poll_interval_ms`), cancel/resume, result rendering.
- `frontend/runtime.js` (648 lines): event editor (`addEvent` :98, `whatIfDocument` :123), what-if render (:203), time controller/play loop via `requestAnimationFrame` (`playFrame` :293, `togglePlay` :325), stage timeline (:225), **`renderIso` :377-485 (SVG, full redraw per frame via `svg.replaceChildren()`)**, readout/detail, part selection/tooltips (:524-540), iso bindings (:563).
- `frontend/visual_state.js` (162 lines): pure `SimulationSnapshot -> VisualState` (no DOM/clock); layer list (`LAYERS` :27), groups, availability labelling; NOT_APPLICABLE/NOT_SUPPORTED stay `null`. Good reusable data layer for any renderer.
- `frontend/visual.js` (333 lines): uPlot small multiples, event overlay regions, checkpoint line, play-head, click-to-add-event (`placeFromClick` :83), event table, delta table, record/replay buttons.
- `frontend/styles.css` (246 lines).
- Current iso scene (`runtime.js:377-485`): soil slab coloured by wetness, 5x6 grid of boxes (3x3 on narrow screens) whose height = `8 + 44 * LAI-indicator`, stage colour band, stress tint overlays, rain/irrigation markers, temperature/water/VPD overlays, greenhouse as a single gable box (roof 110, ridge 140, walls +- 90) with shading overlay, vent strip, CO2 dots, sun glyph, "EVENT ACTIVE" banner. Geometry is generic and fixed, **not typology-aware**.

### Server / API
- `src/agri_twin/interfaces/frontend_api.py` (396 lines): stdlib `ThreadingHTTPServer`, loopback only (`serve` :361, rejects non-loopback hosts), whitelist static file map (`_static` :305; **a new asset must be added to this dict**), CSP `default-src 'self'` (no inline eval, no remote). Routes: GET `/api/capabilities`, `/api/runtime/contract`, `/api/simulations/{id}[/progress|/result]`; POST `/api/plan`, `/api/simulations`, `.../start|cancel|pause`, `/api/simulations/resume`, `/api/runtime/preview|what-if|record|replay`. Simulation runs in a daemon worker thread (`start` :133, `_run` :149).
- Launchers: `tools/run_frontend.py` (current, injects `perf_counter` timer, default `127.0.0.1:8765`) and `tools/run_phase5_38_frontend.py` (legacy name). Also `python -m agri_twin.interfaces.frontend_api` (`main` :384).
- Tests: `tests/test_frontend_api.py` (539 lines), `tests/test_visual_simulation.py` (455 lines; Node-based JS tests, skipped if `node` missing; node exists at `C:\Program Files\nodejs\node`), `tests/test_interactive_runtime.py` (232), `tests/test_interactive_simulation.py`. Manual: `manual_phase5_37/38/39/40_*_test.py`.
- Static audit `static_audit_runtime` (`interactive_runtime.py`, ~:210-270) greps the runtime JS for forbidden patterns: scientific formulas (`Math.exp/log/pow/sqrt`, `**`), model terms, `Date.now`, **`import`/`require`/`three.js`/`THREE.` (rule `external_library_in_javascript`)**, WebSocket/EventSource/XHR, `Worker`, `Math.random`, remote fetch, remote assets in html/css. **Any Three.js adoption would need to amend this audit and its tests deliberately.** Note it also forbids `Math.random` and wall clock in JS (relevant for particle effects: must be deterministic hash-based).

### Simulation service (5.37 / 5.39)
- `application/interactive_simulation.py` (1763 lines): `InteractiveSimulationService` with `create_simulation` (:804), `start_simulation` (:911), `run_simulation` (:826), `pause_simulation` (:887), `cancel_simulation` (:883), `resume_simulation` (:819), progress via observer callback at step boundaries (`observer` inside `start_simulation`). Time step fixed at 1 h (`TIMESTEP_SECONDS`).
- Checkpoint = existing 5.29 payload wrapper (`SimulationCheckpoint` :326; `format, simulation_time, payload, sha256, resume_hash`); full == partial + resume is byte-identical (PHASES.md:57).
- **Pause semantic**: not a suspended state; pause = cooperative stop at step boundary, status `CANCELLED` / termination `PAUSED`, returns checkpoint; resume = new execution from that checkpoint (`interactive_simulation.py:887-895`).
- **Execution model is batch**: `ScenarioRunner.run` executes the whole horizon in one call (worker thread); the frontend only receives full trajectories (`project_result` :1072) at the end plus coarse `completed_steps/total` progress. The "time controller / play-head" replays an already computed trajectory (`docs/phase5_40...:7-8`). There is no step-by-step live stream, no websocket/SSE, and no way to inject an event into a running simulation.
- `application/interactive_runtime.py` (284 lines): `InteractiveRuntimeService.preview_events` and `what_if`: runs prefix to `checkpoint_time` (must be strictly inside the run, whole hour), then resumes **baseline (no events)** and **intervention (events)** from the same checkpoint; `compare_branches` reports final/max-abs deltas per variable, `unchanged_before_first_event`. Hashes: prefix/baseline/intervention trajectory hashes, event-sequence hash, `what_if_hash`. Cost: 3 backend runs per what-if (prefix + 2 branches).
- `application/runtime_events.py`: 11 supported event types (`SPECS`): HEAT_WAVE, COLD_WAVE (offset degC, ramp ok), DRYNESS (no intensity), RAIN (mm/h), HIGH_RADIATION, LOW_RADIATION (multiplier), WIND (multiplier), IRRIGATION (mm/step), and greenhouse-only VENTILATION, SHADING, CO2 (fraction 0-1, no ramp). Fields: `event_id, event_type, start_simulation_time, duration_hours (whole h), intensity, ramp_hours, parameters, source`. Events must start at or after the branch point on a whole step, end before campaign end, `source` must be `USER_DEFINED_EVENT`; classification USER_DEFINED_SYNTHETIC_FORCING. `WATER_STRESS` is explicitly NOT_SUPPORTED (output, not forcing). Greenhouse events on outdoor runs -> `UNSUPPORTED_ENVIRONMENT`.
- `application/runtime_replay.py`: record/replay session with `session_hash`, 5-check MATCH/MISMATCH, rejects tampered/unknown fields.
- Scenario baseline vs intervention: only via what-if branching (one intervention set per call). Multi-intervention comparison (A/B/C) is "prepared for, not implemented" (`docs/phase5_40...:46`).

## 2. Partially implemented

- **Greenhouse visualization**: generic box with ventilation (single strip), shading overlay, CO2 dots; no typology, no per-actuator differentiation, no heating/cooling visual (the variables `greenhouse_heating_kw`/`greenhouse_cooling_kw` exist in the API catalogue, `interactive_simulation.py:276-279`, but the iso scene does not draw them).
- **Plant visual**: "canopy height" is `indicator("leaf_area_index")` (`visual_state.js:103`), i.e. a normalised LAI proxy, not a height; `biomass_fill` from total biomass. Labelled as drawing aid; must stay labelled.
- **Event editing**: form + click on chart to place; no drag of events on a timeline, no direct manipulation in the scene, no per-event ramp visual.
- **Time controller**: play/pause/speed (0.25-50 simulated h per real second), seek, jump to event - all over precomputed data.
- **Responsiveness**: 60 fps measured at 50x with Playwright at 1280 px and emulated 390 px (`docs/phase5_40...:34-37`); this was measured with the current ~30-plant SVG scene.
- **Records/replay**: data only (no screenshots/video).

## 3. New functionality needed (for an immersive UX)

1. A **scene data contract** (frontend-only, pure module like `visual_state.js`) separating: model outputs (from API), geometry/typology (config, see section 5), and decorative/visual-only elements (flagged as non-model).
2. **Typology-aware structure renderer** (parametric from config; no Novagric data exists in repo).
3. **Per-actuator visuals**: windows/vents (ventilation_fraction), shade screen (shading_fraction), heating/cooling (kW), CO2 (ppm), misting/fogging (see limitations: not in API catalogue), fans (not modelled).
4. **Camera/navigation** (orbit/pan/zoom/preset views) and picking, with keyboard/touch accessibility equivalents.
5. **Incremental rendering** (update attributes instead of `replaceChildren` per frame) and level-of-detail for many plants.
6. **Live/step stream** if "immersion" implies real-time interaction: needs either progress snapshots exposed during the run or chunked run-to-checkpoint-then-resume stepping (feasible on the existing checkpoint contract: run segments `[t0,t1]`, resume from each checkpoint; this respects the architecture but multiplies API calls and checkpoint payload transfer). A new push transport would conflict with the static audit rule `second_transport_in_javascript` and needs a decision.
7. Event authoring directly on the timeline/scene (drag start/duration), multi-event undo, A/B comparison of more than one intervention.
8. Tests: Node-based pure-module tests for the new scene module, audit rule updates, accessibility checks, browser smoke (Playwright was used manually; no Playwright test in repo `tests/`).
9. Docs + PHASES row + `manual_phase5_41_*` per the project pattern.

## 4. Physical backend limitations (verified)

- **EnergyPlus 26.1.0 IS installed but NOT usable by the project as configured**: `C:\EnergyPlusV26-1-0\` contains `energyplus.exe` (runs: `EnergyPlus, Version 26.1.0-6f2e40d102`), `Energy+.idd`, `WeatherData`, `ExampleFiles`, `pyenergyplus/` and a bundled `python312.dll`. It is not on PATH and `ENERGYPLUS_EXECUTABLE`/`ENERGYPLUS_IDD` are unset, so `detect_energyplus()` returns `UNAVAILABLE`. With both env vars set it returns **`INCOMPATIBLE`** ("executable found but pyenergyplus is not importable"): `.venv` is Python 3.13.9 while EnergyPlus ships Python 3.12 bindings (`pyenergyplus` would have to be added to `sys.path` and matched to cp312, or the runner changed). No EnergyPlus simulation was executed in this audit. The template IDF declares `Version 23.1` while the installed runtime is 26.1 (needs the EnergyPlus VersionUpdater/ConvertInputFormat or a re-authored template; not verified). `tests/test_energyplus_greenhouse.py` uses fake runners, so no test exercises a real run. **eppy 0.6.7 is installed** (`detect_eppy()` -> AVAILABLE) but only builds IDF variants (`eppy_greenhouse.py`, whitelisted fields `_FIELD_MAP` :122-128: ventilation_ach, solar_transmission, heating/cooling supply temperature, shading fraction); the IDD is needed to load the template.
- **Backend not selectable in the interactive path**: `CropDigitalTwinOrchestrator.__init__` hardcodes `self.greenhouse = GreenhouseMicroclimateEngine()` (`application/orchestrator.py:74`), a subclass of `SimplifiedGreenhouseModel` (`domain/greenhouse.py:311,556`). `EnergyPlusGreenhouseModel` implements the `GreenhousePhysicalModel` contract (`energyplus_greenhouse.py:190`) but nothing in `interactive_simulation.py` selects it. The API never exposes a backend choice.
- **Simplified model** (lumped single-zone): config = volume, solar transmission, ACH, heat loss W/K, thermal mass, orientation, shading, CO2 baseline, mode (`GreenhouseConfiguration` :59-70). The geometry (typology, roof shape, vent area/position) has **no effect** on physics; it cannot differentiate Novagric typologies. Any typology-dependent visual would be decorative unless parameters map onto these lumped values with a traceable source.
- **Actuator state** (`GreenhouseActuatorState` :85-92): heating_kw, cooling_kw, ventilation_ach, shading_fraction, co2_supply_ppm, misting_mm_h. Mapping: windows/vents -> ventilation (ACH, no side/roof split), screens -> shading_fraction (single screen, no thermal/shade distinction), heating, cooling, CO2, fogging -> `misting_mm_h`. **Fans: no separate actuator.** Runtime events expose only VENTILATION, SHADING, CO2 (greenhouse); heating, cooling, misting are accepted by `ScenarioRunner._actuators` (`scenarios.py:251-256`) but are **not** user runtime events and misting/co2_supply/heating are not in the API `VARIABLES` catalogue (only `greenhouse_heating_kw`, `greenhouse_cooling_kw`, ventilation, shading, `co2_ppm`).
- Greenhouse scientific status: configuration profiles are `evidence_status: PENDING_SITE_INVENTORY`, `requires_calibration: true`, all numeric fields `null` (`src/growth_model_config.json:32-34`; actuators :37-44). Everything is synthetic forcing; no validation.
- Checkpoints/state: `MicroclimateState` includes `ventilation_fraction` etc. but a what-if with greenhouse runs costs 3 backend simulations; step cost 0.40-0.47 ms/step, season 0.5-3.3 s (PHASES.md:56), so segment-by-segment stepping is affordable.

## 5. Decisions needing evidence / config

- **Novagric typologies**: a case-insensitive search of the repo (excluding `.venv`, `.git`) found **no** references to Novagric, Multitunel Capilla, Gotico, Tropical-Asimetrico, Grande LUX, Raspa y Amagado or Tunel. `src/growth_model_config.json` only has three generic greenhouse modes (`outdoor`, `passive_greenhouse`, `actuated_greenhouse`) with null geometry. `src/farm_config.json` plots have crop/area/coordinates/irrigation/soil but **no structure type or dimensions** (plot_12010 `T01-T04-GH` and plot_40811 `P05-P08-GH2` carry "GH" only in the code string). Therefore: typology dimensions (span, ridge/gutter height, vent geometry, cover, screens) require documented sources supplied by the user (manufacturer datasheets) and must be stored in config with `evidence_status`, never invented. Until then, render a clearly labelled "schematic, not to scale" typology or keep the generic one.
- Whether typology should influence physics (it currently cannot): requires a calibrated mapping to ACH/heat loss/transmission; out of scope without data.
- Plant geometry (height, fruits): no model variable; any visualization must be flagged "illustrative".
- Real-time stepping vs replay of precomputed data; number (naming) of phase (5.40 vs 5.41).
- Whether to relax the static audit rule forbidding `THREE.`/imports (only if Three.js is chosen).
- Whether heating/cooling/misting/fans should become runtime events (backend change, requires tests/hash updates and a spec change in `runtime_events.py`).
- Accessibility baseline for 3D/canvas content (keyboard parity, text alternative; `fixing-accessibility`-style review).

## 6. Variables actually available

From `VARIABLES` in `interactive_simulation.py:243-290` (all serialized in `trajectory`; availability AVAILABLE / NOT_APPLICABLE / NOT_SUPPORTED per crop/environment):

| Group | Variables (unit) |
|---|---|
| Crop | crop_stage, maturity_index, biomass_total_g_m2, **biomass_fruit_g_m2**, leaf_area_index |
| Soil/water | soil_water_vwc_m3_m3, root_zone_water_mm, irrigation_mm, precipitation_mm, drainage_mm, transpiration_mm, evaporation_mm, et0_mm |
| Environment | temperature_c, relative_humidity_pct, vpd_kpa, radiation_w_m2 (all as experienced by the crop) |
| Stress | water/heat/cold/vpd/radiation stress, frost_damage, accumulated_stress, growth_factor |
| Greenhouse only | co2_ppm, outdoor_temperature_c, greenhouse_ventilation_fraction, greenhouse_shading_fraction, greenhouse_heating_kw, greenhouse_cooling_kw |
| Perennials only | dormancy_released, chilling_accumulated |
| **Not represented (NOT_SUPPORTED, never fabricated)** | canopy_temperature_c, photosynthesis_rate_umol_m2_s, **fruit_count**, leaf_water_potential_mpa |

Domain-level availability that the API does **not** serialize: `WeatherState` has wind_speed_m_s, wind_direction_deg, rain_rate_mm_h, pressure_hpa (`domain/models.py:34-41`) but the API exposes no wind speed/direction or pressure series (only effects via et0/VPD; WIND event exists). `MicroclimateState` has `par_umol_m2_s`, `wind_speed_m_s`, soil temperature (`SoilState.soil_temperature_c`) - not serialized. `final_state` (twin state dict) is returned but only as a snapshot.
**Unavailable**: plant height (only an LAI proxy in the UI), number of fruits, per-plant data, canopy temperature, leaf-level fluxes, wind direction effect on vents, condensation, individual window positions, screen types, fan state, misting state in API, actual energy use time series in API (`actuator_consumption_kwh` exists in `GreenhouseMicroclimateResult` but not in the catalogue).
Dormancy/phenology: `crop_stage` string with semantic stage colours (`runtime.js` STAGE_COLORS).

## 7. Offline constraints, dependencies, tests, baseline

- Offline/local: server binds loopback only; CSP `default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'` (`frontend_api.py:327`); remote assets/CDN forbidden by the static audit (`REMOTE_ASSET`); Open-Meteo/OSM only user-initiated (map link). No `inline script` allowed by CSP (`default-src 'self'` blocks inline scripts/styles unless the HTML uses only external files; inline `style=` attributes are blocked too, SVG presentation attributes are fine; `element.style.x = ...` via JS is allowed).
- Existing graphics dependencies: **only uPlot 1.6.32 (MIT)** in `frontend/vendor/` (`uPlot.iife.min.js`, `uPlot.min.css`, `uPlot.LICENSE`). No Three.js, no canvas code, no WebGL.
- Frontend tests: pytest + Node for pure JS modules; no headless-browser test in repo. Node present locally; Playwright was used manually per docs (not verified installed here).
- Test baseline: `python -m pytest -q -x` with `.venv` python was started once. Previously recorded baseline: **1264 passed / 12 skipped / 0 failed** (PHASES.md:59) and 5.40 adds 100 focused tests. This audit's run: see section 9.
- Environment note: `.venv` python version recorded in section 9.

## 8. Git state

- Branch `main`; working tree was clean at the start (`git status` empty, HEAD `5157727 feat: Enhance interactive runtime features and frontend integration`).
- 136 `.pyc` files are tracked (no `.gitignore`); running pytest modifies tracked `tests/__pycache__/*.pyc` files (e.g. `test_chilling_policy`, `test_dormancy_chilling_framework`, `test_scientific_readiness`), producing diff noise. Recommend adding a `.gitignore` and `git rm --cached` of pyc in a separate cleanup commit before 5.41.
- Uncommitted from the audit: only this document (`docs/phase5_40_audit.md`, untracked) plus the untracked `.claude/` directory.

## 9. Test run result

`.venv\Scripts\python.exe -m pytest -q -x` (Python 3.13.9): **1364 passed, 12 skipped, 0 failed in 1186.78 s (19 min 47 s)**. The run modified tracked `.pyc` files; they were restored with `git checkout` afterwards. The run also created 12 untracked `*.pyc` files (new test/module bytecode; left in place). An untracked `.claude/` directory also appeared in `git status` (not created by this audit's commands).

## 10. Recommended graphics technology

**Recommendation: keep native SVG for the main scene; do not adopt Three.js for the next increment; use Canvas 2D only for dense, decorative layers if profiling demands it.**

Justification:
1. Scene content is small and schematic: ~30 plants, one structure, a handful of overlays. SVG already holds 60 fps at 50x in the measured Chromium runs.
2. Accessibility and testability: SVG nodes carry `role`, `tabindex`, `aria-label` (`runtime.js:387-394`), keyboard focus and tooltips already work; Node-based tests and the static audit are written for it. A WebGL canvas loses all of this and needs a parallel DOM layer.
3. Offline/CSP/audit: Three.js would add a ~600 KB+ vendored file (plus OrbitControls as a module, which conflicts with the "no import" audit rule and the classic `defer` script loading), require changing `_static`'s whitelist, the audit and its tests, and a licence/version record. All feasible, but none is justified by present needs.
4. Honesty guardrails: a 3D "realistic" greenhouse with fruits/plant height would visually claim data the model does not have (height, fruit_count are NOT_SUPPORTED). Stylised SVG makes the schematic nature obvious.
5. Typology schematics (tunnel, gothic, asymmetric, flat-roof "raspa y amagado", multi-span) are parametric polygons: well suited to SVG with the existing isometric `projection()`.
6. Where Three.js would pay off: orbit camera, many plants (>2k nodes), realistic lighting/shadows driven by radiation. If later desired, vendor a pinned `three.module.min.js` (MIT, record version + licence + SHA-256 in `frontend/vendor/`), serve locally via the whitelist, load as a module with an import map pointing to local files only, relax the audit only for the new file with an explicit rule, keep `visual_state.js` as the data layer and an SVG/DOM fallback with equivalent text readout, and state "illustrative, not a plant model" in the UI.
7. Performance hygiene for SVG: stop rebuilding the whole tree each frame (update attributes of persistent nodes), cap nodes, use `requestAnimationFrame` throttling, and use deterministic pseudo-random placement (hash of index; `Math.random` is forbidden by the audit).

Suggested next-step order: (1) close 5.40 verification (full regression + browser evidence), (2) clean pycache/.gitignore, (3) define typology config schema with `evidence_status` (user-supplied sources), (4) SVG scene refactor to persistent nodes + per-actuator visuals, (5) optional segment-wise stepping for live feel, (6) docs/PHASES row/manual test as 5.41.
