# Visual prototype: state-driven isometric SVG scene

Spike, not wired into the app. Open `demo-light.html` (or `demo-dark.html`) in a browser; no server or network needed.
Everything on the page is driven by sliders: **demo state, not simulation output**. The scene only draws the state it is given.

Drawing uses `iso-kit.mjs` from https://github.com/wheresryan22/anatomy (MIT, `ANATOMY_LICENSE_MIT.txt`; unmodified copy).
Geometry comes from Python: `export_catalogue.py` writes `catalogue.json` (manufacturer modularity rules plus pre-baked
cross-section profiles from `span_profile`), so the browser holds no second copy of the geometry equations.

Rebuild (from the repo root, PowerShell):

```
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe -I docs\phase5_41\visual_prototype\export_catalogue.py docs\phase5_41\visual_prototype\catalogue.json
cd docs\phase5_41\visual_prototype; node build_demo.mjs light; node build_demo.mjs dark
```
`shot.sh <name> "<hash params>"` renders a state with headless Edge, e.g. `typology=TUNEL&span=9.6&rise=5&vent=0.8`.
Any slider key can be passed in the URL hash, so a state can be shared as a link.

## What the scene shows and which model variable should drive it

| Visual | Demo input | Intended source (not connected yet) | Available in the model today |
|---|---|---|---|
| Plant height / canopy | LAI | `CropState.leaf_area_index` | yes |
| Plant colour, wilting | cumulative / water stress | `CropState.cumulative_stress`, `water_stress` | yes |
| Plant loss | cumulative stress > 0.8 | derived from `cumulative_stress` | **no mortality variable**; shown as a derived indicator, labelled as such |
| Fruit dots and ripeness | fruit fraction, ripeness | fruit biomass / total, stage | fruit biomass only; no fruit count |
| Roof vent flaps | vent opening 0-1 | `MicroclimateState.ventilation_fraction` or the vent schedule | yes (EnergyPlus: schedule value) |
| Screen sheet | screen deployed 0-1 | `shading_fraction` | yes; screens are not described by the manufacturer pages |
| Cover tint, indoor panel | indoor T, RH, CO2 | `MicroclimateState` | T and RH yes; CO2 shown `n/a` (not modelled by EnergyPlus here) |
| Sky, sun, rain, wind arrow | outdoor T, RH, radiation, wind, rain | `WeatherState` | yes; no cloud cover variable, so no clouds are drawn |
| Heater | kW | `MicroclimateState.heating_kw` | yes |
| Open field | system switch | orchestrator `greenhouse_mode="outdoor"` | exists; no EnergyPlus involved |

## Modularity

The structure panel offers the options the manufacturer lists per typology (width, gutter height, ridge rise, pillar
spacing). Spans and bays are free (limited to 20 spans, a provisional limit); length = bays x pillar spacing. A value that is not a
listed option is accepted by `configure_greenhouse` but tagged `USER_SUPPLIED` and reported as off-catalogue; the demo
UI only offers listed options plus provisional defaults where nothing is published. Taller tunnels (rise above half the span) are drawn as an ogival arch.

## Limits of the prototype

- Painter's order is a plain depth sort; no depth audit. Vents are roof flaps only (no side roll-up). Screens deploy along the length only.
- The vent flap is the facet next to the apex; real window position and area are not published.
- Plant shapes are three generic silhouettes; plants are a subset of the real planting grid (greenhouse: one every 1.5 m).
- No interaction by clicking elements yet, no cut-away view.
- The runtime is a plain script but is not yet whitelisted in `frontend_api._static` or `RUNTIME_AUDITED_JS`; the static audit
  forbids `Math.random`, `Date.now`, imports and remote assets (the scene uses none of them).

## Rain, stress legibility and view controls (added)

- **Rain**: up to 560 streaks in a screen-space layer. Count, length, speed and slant follow rain rate (10 mm/h = heavy) and wind;
  the sky greys while it rains. Positions come from a golden-ratio sequence (deterministic, no `Math.random`) and the layer is
  clipped by a rounded `clipPath` identical to the canvas, so nothing is drawn outside it. `prefers-reduced-motion` stops the animation.
- **Stress cues**, one per variable so they can be told apart: cumulative stress = leaf hue green -> yellow -> brown;
  water stress = drooping, narrower, paler leaves; temperature stress = orange-red leaf edge; VPD stress = dashed brown edge.
- **Plant inspector** (top of the side panel): one large plant in the current state next to a healthy reference with the same LAI,
  plus the four stress values. It uses the same shape and style code as the scene.
- **Zoom and pan** of the scene layer (HUD stays fixed): mouse wheel, drag, `+`/`-`/arrows/`0` on the focused canvas, double-click to reset,
  or buttons. `zoom=2.6` in the URL hash presets it.
- Reference captures: `state_*.png` (default, hot with vents and screen, stress zoom, plant loss, heavy rain, light rain, open field, dark theme).
