# Phase 5.39 – Interactive runtime simulation, climate events and isometric visualization

## Scope

Adds runtime events and what-if branches on top of the Phase 5.37 `InteractiveSimulationService` and a read-only
visualization in the 5.38 frontend. There is **no second engine**: a runtime event is converted into an existing
`ScenarioEvent`; the frontend only draws backend data and contains no scientific formulas.

Modules: `application/runtime_events.py` (contract, validation, `event_sequence_hash`),
`application/interactive_runtime.py` (`InteractiveRuntimeService`, `compare_branches`, `static_audit_runtime`),
`frontend/runtime.js`, runtime panel in `frontend/index.html`.

## Runtime events

Supported (all labelled `USER_DEFINED_EVENT` / `USER-DEFINED SYNTHETIC FORCING`):
HEAT_WAVE, COLD_WAVE, DRYNESS, RAIN, HIGH_RADIATION, LOW_RADIATION, WIND, IRRIGATION,
VENTILATION, SHADING, CO2. VENTILATION, SHADING and CO2 are greenhouse-only (`UNSUPPORTED_ENVIRONMENT` outdoors);
`ramp_hours` is accepted only for weather events.

Not supported: **WATER_STRESS** (the model has no independent forcing for it; water stress is an output driven by
irrigation/dryness/rain events). `GET /api/runtime/contract` lists both groups.

## Checkpoint-based application

1. Run the prefix up to `checkpoint_time` (hour-aligned, strictly inside the run) and take a checkpoint.
2. Resume the **baseline** branch (no events) and the **intervention** branch (events) from the same checkpoint.
3. `compare_branches` computes the differences from backend series only.

Events must start at or after the branch point and end by the campaign end, so past history is never modified
(`unchanged_before_first_event`). `POST /api/simulations/{id}/pause` stops cooperatively at a step boundary and returns
a checkpoint (status stays `CANCELLED`, termination `PAUSED`); resuming reproduces the uninterrupted trajectory.

## Determinism

`configuration_hash`, `event_sequence_hash` (order-sensitive), `effective_configuration_hash`, `trajectory_hash`, and a
`what_if_hash` combining them with the checkpoint digest. Timings and simulation IDs are excluded from every hash.

## Visualization

Renderer: **SVG isometric projection** (chosen over Three.js: offline, dependency-free, simple to audit).
Views: TOP, ISOMETRIC, DETAIL with pan/zoom/select. Time controller: play, pause, step ±, speed, jump to event,
jump to checkpoint (fixed UI refresh interval, no wall-clock in simulation logic).

Variable → visual mapping (lumped, no per-plant state; unavailable variables show `NOT_APPLICABLE`):
crop_stage → canopy colour (semantic stage palette); leaf_area_index → canopy height; biomass_total_g_m2 → canopy
footprint fill; soil_water_vwc_m3_m3 → soil tile tone (darker = wetter); water_stress / heat_stress → canopy overlay
opacity (backend value); precipitation_mm / irrigation_mm → rain streaks / irrigation droplets when > 0;
greenhouse_ventilation_fraction → roof vent width; greenhouse_shading_fraction → shade screen opacity;
temperature_c, co2_ppm, radiation_w_m2 → numeric read-out only. Scaling uses the extent of the returned series and is
purely visual.

## Static audit

`static_audit_runtime(root)` checks (AST) the two Python modules and (regex) `frontend/runtime.js`: no `exp/log/pow/sqrt`
or `**` in JS, no model terms, no `Date.now`/`new Date()`, no external libraries/WebSocket, no wall clock, no randomness,
plus the project-wide static audit.

## Verification

- `tests/test_interactive_runtime.py` (31 tests), `tests/test_interactive_simulation.py`, `tests/test_frontend_api.py`.
- `manual_phase5_39_interactive_runtime_test.py` → `data/frontend/interactive_runtime_report.json` and
  `interactive_runtime_README.md` (deterministic hash; performance recorded separately).
- Browser smoke on desktop/mobile (no horizontal overflow at 390 px).

## Limitations

Scientific status unchanged: REAL_VERIFIED = 0; CALIBRATION_PERFORMED, EXPERIMENTAL_VALIDATION_PERFORMED,
BIOLOGICAL_VALIDITY_CLAIMED, FIELD_ACCURACY_CLAIMED and DATA_ASSIMILATION_IMPLEMENTED are all false. What-if deltas are
software behaviour under synthetic forcing, not predictions. The view is lumped and schematic. The 5.37 service lock was
removed (the 5.37 audit forbids `threading`), so a service instance is not thread-safe.
