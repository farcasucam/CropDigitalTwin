# Phase 5.40 – Interactive visual simulation

Status: see `data/frontend/visual_simulation_report.json` (closure requires the full regression and browser evidence).

## Scope
Presentation only. The frontend consumes the 5.37–5.39 API output (`SimulationSnapshot`) and draws it. No new science,
engine, clock or scheduler; no equation or parameter was changed. Play/pause/speed (0.25–50 simulated h per real second)
only move a play-head over the already computed trajectory.

## Renderer decision
- **Isometric view: native SVG** (no Three.js). A stylised row of plants, soil slab, and for greenhouses the structure,
  vent, shade and CO2 markers. It is not a plant model: per-plant geometry is never fabricated.
- **Charts: vendored uPlot 1.6.32 (MIT)** in `frontend/vendor/` (licence in `uPlot.LICENSE`); served locally, no CDN, CSP `default-src 'self'`.

## SimulationSnapshot → VisualState
`frontend/visual_state.js` is a pure module (no DOM, network or clock). NOT_APPLICABLE and NOT_SUPPORTED variables
stay `null` and are labelled; they are never replaced by zeros. Scaling to [0, 1] uses only the extent of the returned
series. Interpolation between snapshots is visual only and flagged (`interpolated`).

## Features
Layers (crop, soil, water, temperature, radiation, VPD, CO2, events); zoom/pan/hover/select; DETAIL panel (value, unit,
timestamp, availability, source `MODEL OUTPUT`); small-multiple charts with event regions, checkpoint line and
play-head; click a chart to add an event; event table; baseline-vs-intervention Δ table; keyboard control on the view
(k play/pause, arrows step, Home/End).

## Record / replay
`POST /api/runtime/record` returns a session (configuration, seed, event sequence, checkpoints, hashes, final-state
hash, `session_hash`) – never screenshots. `POST /api/runtime/replay` re-runs it and reports `MATCH`/`MISMATCH` over
five checks; tampered or unknown-field sessions are rejected. The session hash is stable under a JavaScript JSON
round trip (integral floats are normalised).

## Determinism
Trajectory hashes are computed in the backend and do not depend on the renderer, speed or layers.

## Measured in the browser (Playwright, Chromium desktop, 50× speed)
- 1280 px: 60 fps; 390 px viewport: 60 fps (emulated width, not a physical phone).
- No horizontal overflow at 1280, 768 and 390 px.
- Browser record → replay returned `REPLAY MATCH`.

## Audit
`static_audit_runtime` covers `runtime_replay.py`, `visual_state.js`, `visual.js`, the vendored library files, remote
assets, `Worker`/`Math.random` and remote `fetch`.

## Not claimed
REAL_VERIFIED = 0; CALIBRATION_PERFORMED = false; EXPERIMENTAL_VALIDATION_PERFORMED = false;
BIOLOGICAL_VALIDITY_CLAIMED = false; FIELD_ACCURACY_CLAIMED = false; DATA_ASSIMILATION_IMPLEMENTED = false.
Multi-crop, multi-plot, actuators, comparative scenarios and real data are prepared for, not implemented.