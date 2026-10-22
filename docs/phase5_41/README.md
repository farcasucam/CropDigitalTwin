# Phase 5.41: greenhouse typologies, EnergyPlus groundwork and the integrated isometric scene

Status: **IN PROGRESS (partial)**. The scene is integrated and tested in the real interface; the EnergyPlus backend is
selectable from the API (`greenhouse.backend = ENERGYPLUS`) as a per-run timeline; the interactive lock-step bridge remains a spike. No calibration, no real data, no biological
validation is claimed (see `docs/scientific-limitations.md`).

## What exists

| Item | Where | Classification |
|---|---|---|
| Typology geometry (6 Novagric typologies), evidence status per value | `domain/greenhouse_typology.py` | IMPLEMENTADA Y PROBADA |
| Manufacturer modularity rules, off-catalogue flagging, open-field spec | `domain/greenhouse_modularity.py` | IMPLEMENTADA Y PROBADA |
| Deterministic EnergyPlus 26.1 IDF per typology (single zone) | `infrastructure/greenhouse_idf.py` | IMPLEMENTADA CON LIMITACIONES |
| CSV -> EPW converter (derived direct/diffuse radiation, UTC, no gaps) | `infrastructure/epw_weather.py` | IMPLEMENTADA CON LIMITACIONES |
| Layout catalogue served by the API (`GET /api/greenhouse/catalogue`) | `application/greenhouse_catalogue.py`, `interfaces/frontend_api.py` | IMPLEMENTADA Y PROBADA |
| Isometric scene in the real spatial view (greenhouse and open field) | `frontend/iso_scene.js`, `scene_state.js`, vendored `vendor/isokit.*` | IMPLEMENTADA CON LIMITACIONES |
| EnergyPlus selectable as a greenhouse backend (per-run timeline, same checkpoints/what-if as the simplified model) | `application/greenhouse_backend.py`, `infrastructure/energyplus_timeline.py` | IMPLEMENTADA CON LIMITACIONES |
| Experiment bench (one screen: run, A/B scenes, presets, charts, comparison table) | `frontend/bench.html`, `bench.js`, `bench.css`, route `/bench` | IMPLEMENTADA CON LIMITACIONES |
| Interactive lock-step control of EnergyPlus (plugin bridge) | `docs/phase5_41/realtime_spike/` (spike only) | DISEÑADA PERO NO IMPLEMENTADA |
| Wind, cloud cover, outdoor humidity/rain in greenhouse mode in the scene | not served by the API | NO DISPONIBLE |
| Per-plant state, plant mortality count, fruit count | not modelled | NO DISPONIBLE |

## EnergyPlus as a backend

Request field `greenhouse: {backend: "ENERGYPLUS", layout: {typology, span_m, ridge_rise_m, gutter_height_m, pillar_spacing_m, n_spans, n_bays}}`.
Absent or `SIMPLIFIED`: the historical behaviour, with unchanged request, configuration, trajectory and checkpoint hashes. With `ENERGYPLUS`:

- Before each run, EnergyPlus (external process, no Python API needed, version 26.1.x) simulates the **whole campaign prefix up to the run end** with the
  weather the orchestrator would see (synthetic forcing plus events) and the commanded actuators; the orchestrator then reads the hourly result step by step
  through `EnergyPlusMicroclimateEngine`. A season takes about 12 s. EnergyPlus cannot restart from a checkpoint, so prefix, baseline and intervention all
  simulate from the campaign start; a test proves `prefix + resumed baseline == continuous run` exactly (this required per-timestep shadow calculation:
  EnergyPlus' default periodic shadows made results depend on the run length).
- `greenhouse` is part of the resume identity: a checkpoint never resumes under another backend or layout.
- Event mapping: weather events change the forced weather; `VENTILATION` sets a forced-vent schedule (fraction of the design air change rate); `SHADING` scales the
  solar input (an external-screen approximation); `CO2` is rejected. Passive venting opens above a provisional indoor threshold (24 C) while the outdoor air is cooler.
- `co2_ppm` is reported `NOT_SUPPORTED` (never a fabricated value); the crop does not feed back into EnergyPlus (no transpiration, no CO2 uptake), so humidity
  comes from the envelope and ventilation only.
- Detection: `ENERGYPLUS_EXECUTABLE`, `PATH`, then standard install folders; a different version is reported as unavailable with the reason.
- All envelope and thermal values are provisional placeholders: results are software qualification, not a prediction for a real greenhouse.

## Experiment bench (`/bench`)

One screen to experiment. Controls on the left (scenario, intervention with one-click event presets and editable event cards, greenhouse model and layout), the scene(s)
in the centre, a sticky time controller and synchronized charts below, and a comparison table.

- **One Run button** (Ctrl+Enter, optional auto-run): with no events it is a plain run; with events it runs baseline and intervention (the what-if endpoint) and shows
  both scenes side by side at the same instant, event bands on the charts, event ticks on the time slider and a table of peak/mean/final differences.
- Typical waits measured here: simplified model under 1 s for a month, about 3 s for a season what-if; EnergyPlus about 10 s for a month what-if.
- The setup persists in the browser (localStorage) and every API error is shown with its path.
- Differences are plain statistics of two simulated scenarios; they are not a causal or validated effect.
- The classic page stays at `/` for the full trajectory, availability catalogue and record/replay features; both pages link to each other.

## Architecture of the scene

`VisualState` (API series at a time position) -> `scene_state.js` (pure mapping) -> `iso_scene.js` (persistent SVG nodes).
`runtime.js` only orchestrates: it asks `ensureScene()` for the layout (catalogue), calls `update()` per frame and keeps the
existing controller, tooltips, keyboard access and detail panel. The scene never computes climate or growth; the static audit
(`static_audit_runtime`) covers both new modules and requires the vendored kit files.

Geometry stays in Python: the catalogue endpoint returns the manufacturer's modularity options and pre-built roof
cross-sections; the browser applies span count, bays and gutter height only.

## Variable -> visual mapping

Shown in the interface under "Variable -> visual mapping". Summary: LAI -> plant size (fixed drawing reference LAI 4);
accumulated stress -> leaf hue (relative to max(1, run maximum)); water stress -> droop/narrow/pale; heat or cold stress -> coloured leaf edge;
VPD stress -> dashed edge; frost damage -> share of plants drawn as lost; ventilation fraction -> roof vent flaps (up to 40 degrees);
shading fraction -> screen sheet; temperature -> cover tint (layer); precipitation (mm per step to mm/h) -> rain;
irrigation -> droplets; radiation -> sun and sky.

## Honest limits

- The simplified greenhouse model is a two-node lumped model of the SAME layout EnergyPlus simulates (floor area, volume and cover from the typology geometry; see
  `docs/phase5_44_greenhouse_consistency.md`): the layout changes its results too. Until phase 5.44 it had a 1 m2 exchange area and no geometry input.
- Layout and open-field dimensions are a visual schematic; values the manufacturer does not publish are provisional. The chosen layout is simulated by both greenhouse backends.
- `frost_damage` is drawn as "lost plants" proportionally; it is not a plant count. Plants are a drawn subset of the planting grid.
- Accumulated stress is shown relative to `max(1, run maximum)`, a drawing scale rather than a model threshold.
- Rain in greenhouse mode is `precipitation_mm` "reaching the crop", which is 0 indoors, so outdoor rain is not shown there.
- The EPW converter derives direct and diffuse radiation (Erbs) and assumes UTC and an end-of-hour convention.
- The IDF uses placeholder cover/ventilation/heating values; nothing is validated against a real greenhouse.

## Tests

`tests/test_greenhouse_idf.py`, `test_greenhouse_modularity.py`, `test_epw_weather.py`, `test_greenhouse_scene.py`, `test_energyplus_backend.py`, `test_bench.py` (EnergyPlus tests skip
when it is not installed) plus updated `test_visual_simulation.py` (new assets, audit tree). Real-interface checks were done by
driving headless Edge through the DevTools protocol (greenhouse and open-field runs, selection by click, wheel zoom, mobile width);
that driver is a scratch tool and is not part of the repository.

## Reproduce

```
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe -m agri_twin.interfaces.frontend_api --port 8765     # then open http://127.0.0.1:8765/
node docs\phase5_41\visual_prototype\vendor_kit.mjs                           # regenerates frontend/vendor/isokit.* from the kit
```
Open `http://127.0.0.1:8765/bench` for the experiment bench, or `/` for the classic workspace. In the classic interface: choose Environment (greenhouse or outdoor), add an event with its intensity, "Run what-if", then use the
"Greenhouse layout" panel, the view buttons, layers and the time controller.

## Spikes kept for reference

`energyplus_viability_spike.md`, `energyplus_realtime_options.md` (+ `realtime_spike/`), `novagric_typologies.md`, `visual_prototype/`.
