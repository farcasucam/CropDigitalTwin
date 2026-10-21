// Builds demo.html: kit core + scene runtime + catalogue (from Python) + controls, as one standalone page.
import { readFileSync, writeFileSync } from "node:fs";

const here = (name) => new URL(`./${name}`, import.meta.url);
const kitSource = readFileSync(here("iso-kit.mjs"), "utf8").replace(/^export /gm, "").replaceAll("</script", "<\\/script");
const runtime = readFileSync(here("scene_runtime.js"), "utf8");
const catalogue = readFileSync(here("catalogue.json"), "utf8");
const css = kitSource.match(/const ISO_CSS = `([\s\S]*?)`;/)[1];

const KIT_EXPORTS = "cameraOf, iso, depthOf, pathOf, fitProjection, slabOf, cylinder, solidSvg, lineSvg";
const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Greenhouse scene demo</title><style>${css}
*{box-sizing:border-box}body{margin:0;background:var(--anatomy-page);color:var(--anatomy-text);font:13px/1.5 ui-sans-serif,system-ui,"Segoe UI",sans-serif}
main{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:18px;max-width:1280px;margin:18px auto;padding:0 16px}
@media(max-width:980px){main{grid-template-columns:1fr}}
.card{background:var(--anatomy-card);border-radius:14px;box-shadow:var(--anatomy-lift);padding:12px}
.banner{grid-column:1/-1;font:11px/1.4 var(--anatomy-mono);letter-spacing:.05em;text-transform:uppercase;color:var(--anatomy-muted)}
.banner b{color:var(--anatomy-red)}
fieldset{border:0;border-top:1px solid var(--anatomy-faint);margin:10px 0 0;padding:8px 0 0}
legend{font:10px var(--anatomy-mono);letter-spacing:.08em;text-transform:uppercase;color:var(--anatomy-muted);padding-right:6px}
label{display:grid;grid-template-columns:118px 1fr 52px;align-items:center;gap:6px;margin:3px 0;font-size:12px}
label output{font:11px var(--anatomy-mono);text-align:right;color:var(--anatomy-strong)}
select{grid-column:2/4;width:100%;background:var(--anatomy-card);color:var(--anatomy-strong);border:1px solid var(--anatomy-faint);border-radius:6px;padding:3px}
input[type=range]{width:100%}
.note{font-size:11px;color:var(--anatomy-muted);margin:6px 0 0}.flag{color:var(--anatomy-red)}
.sky rect{stroke:none}.sun{stroke:none}.hud-text{font:11px var(--anatomy-mono);fill:var(--anatomy-strong)}
.wind{stroke:var(--anatomy-strong);fill:none;stroke-linecap:round}.rain path{stroke:hsl(205 90% 82%);stroke-width:1.3;fill:none;stroke-linecap:round;transform:translateY(var(--y0,0));animation:fall 1s linear infinite}
@keyframes fall{from{transform:translate(0,-60px)}to{transform:translate(var(--dx,0px),var(--fall,500px))}}
@media (prefers-reduced-motion:reduce){.rain path{animation:none}}
#inspector{display:block;width:100%;height:auto}#inspector .stem{fill:none;stroke-width:2}#inspector .leaves{stroke:none;fill-opacity:.9}
.inspect-ground{fill:var(--anatomy-faint);stroke:var(--anatomy-lo);stroke-width:.6}.bar-track{fill:var(--anatomy-faint)}.bar-fill{fill:var(--anatomy-mid)}
.hud-text.small{font-size:9px;letter-spacing:.06em}.hud-text.tiny{font-size:8px}
.zoom{display:flex;gap:6px;margin:8px 0 0}.zoom button{background:var(--anatomy-card);color:var(--anatomy-strong);border:1px solid var(--anatomy-faint);border-radius:6px;padding:2px 10px;cursor:pointer}
.cover path{stroke:none;fill-opacity:.16}.hole path{fill:var(--anatomy-faint);fill-opacity:.55;stroke:none}
.flaps path:first-child,.flaps path{fill:var(--anatomy-blue);fill-opacity:.2}.flaps .iso-line{fill:none}
.screen-sheet{fill:var(--anatomy-hi);fill-opacity:.28;stroke:none}
.plant .stem{stroke-width:1.2;fill:none}.plant .leaves{stroke:none;fill-opacity:.85}
.soil .iso-fill{fill:hsl(30 30% 72%)}
</style></head><body class="iso" data-theme="__THEME__"><main>
<div class="banner"><b>Demo state</b>: every value below comes from these controls, not from a simulation. The scene only draws the state it is given.</div>
<div class="card"><svg id="scene" class="iso-svg" role="img" aria-label="Isometric greenhouse scene. Scroll or +/- to zoom, drag or arrows to pan, double-click or 0 to reset"></svg><div class="zoom"><button id="zin" aria-label="Zoom in">+</button><button id="zout" aria-label="Zoom out">-</button><button id="zreset">Reset view</button><span class="note">wheel/drag, +/-, arrows, double-click</span></div><p class="note" id="status"></p></div>
<div class="card"><svg id="inspector" role="img" aria-label="Plant inspector: current plant against a healthy reference"></svg><div id="panel"></div></div></main>
<script>
${kitSource}
const K = { ${KIT_EXPORTS} };
${runtime}
const CATALOGUE = ${catalogue};
const params = new URLSearchParams(location.hash.slice(1));
const state = { system: "GREENHOUSE", typology: "MULTITUNEL_CAPILLA", spans: 3, bays: 6, span: null, rise: null, gutter: null, pillar: null, cropKind: "vine", azimuth: 45,
  hour: 13, o_temp: 24, o_rh: 55, o_solar: 700, o_wind: 3, o_dir: 270, o_rain: 0, i_temp: 30, i_rh: 62, vent: 0, screen: 0, heater: 0, lai: 2.4, water: 0.1, temp: 0, vpd: 0, cum: 0.1, fruit: 0.5, ripe: 0.4 };
for (const [k, v] of params) state[k] = isNaN(Number(v)) ? v : Number(v);
const panel = document.getElementById("panel");
let scene = null, plantCard = null;
document.getElementById("zin").onclick = () => scene && scene.zoom(1.3);
document.getElementById("zout").onclick = () => scene && scene.zoom(1 / 1.3);
document.getElementById("zreset").onclick = () => scene && scene.resetView();
const ranges = [["Time (h)", "hour", 0, 23.9, 0.1], ["Outdoor T (C)", "o_temp", -5, 45, 0.5], ["Outdoor RH (%)", "o_rh", 10, 100, 1], ["Solar (W/m2)", "o_solar", 0, 1000, 10], ["Wind (m/s)", "o_wind", 0, 20, 0.5], ["Wind from (deg)", "o_dir", 0, 359, 5], ["Rain (mm/h)", "o_rain", 0, 15, 0.5],
  ["Indoor T (C)", "i_temp", 0, 45, 0.5], ["Indoor RH (%)", "i_rh", 10, 100, 1], ["Roof vents", "vent", 0, 1, 0.05], ["Screen deployed", "screen", 0, 1, 0.05], ["Heater (kW)", "heater", 0, 40, 1],
  ["LAI", "lai", 0, 4, 0.1], ["Water stress", "water", 0, 1, 0.05], ["Temperature stress", "temp", 0, 1, 0.05], ["VPD stress", "vpd", 0, 1, 0.05], ["Cumulative stress", "cum", 0, 1, 0.02], ["Fruit fraction", "fruit", 0, 1, 0.05], ["Fruit ripeness", "ripe", 0, 1, 0.05]];
function select(name, key, options, onchange) {
  const l = document.createElement("label"); l.innerHTML = "<span>" + name + "</span>";
  const s = document.createElement("select");
  options.forEach(([v, t]) => { const o = document.createElement("option"); o.value = v; o.textContent = t; if (String(state[key]) === String(v)) o.selected = true; s.appendChild(o); });
  s.onchange = () => { state[key] = isNaN(Number(s.value)) ? s.value : Number(s.value); onchange(); }; l.appendChild(s); return l;
}
function buildPanel() {
  panel.innerHTML = "";
  const f0 = document.createElement("fieldset"); f0.innerHTML = "<legend>Cultivation</legend>";
  f0.appendChild(select("System", "system", [["GREENHOUSE", "Greenhouse (thermal backend)"], ["OPEN_FIELD", "Open field (no EnergyPlus)"]], () => { remount(); buildPanel(); }));
  f0.appendChild(select("Crop silhouette", "cropKind", [["vine", "Vine (tomato-like)"], ["bush", "Bush"], ["rosette", "Rosette (lettuce-like)"]], remount));
  f0.appendChild(select("View", "azimuth", [[45, "SE corner"], [135, "SW corner"], [225, "NW corner"], [315, "NE corner"]], remount));
  panel.appendChild(f0);
  if (state.system === "GREENHOUSE") {
    const cat = CATALOGUE[state.typology], d = cat.default;
    if (state.span == null) { state.span = d.span; state.rise = d.rise; state.gutter = d.gutter; state.pillar = d.pillar; }
    const f1 = document.createElement("fieldset"); f1.innerHTML = "<legend>Structure (manufacturer modularity)</legend>";
    f1.appendChild(select("Typology", "typology", Object.keys(CATALOGUE).map((k) => [k, k.replace(/_/g, " ").toLowerCase()]), () => { const c = CATALOGUE[state.typology].default; Object.assign(state, { span: c.span, rise: c.rise, gutter: c.gutter, pillar: c.pillar, spans: c.spans, bays: c.bays }); remount(); buildPanel(); }));
    f1.appendChild(select("Span width (m)", "span", cat.options.span.map((v) => [v, v]), remount));
    f1.appendChild(select("Ridge rise (m)", "rise", cat.options.rise.map((v) => [v, v + (cat.listed.rise ? "" : " (provisional)")]), remount));
    f1.appendChild(select("Gutter height (m)", "gutter", cat.options.gutter.map((v) => [v, v + (cat.listed.gutter ? "" : " (provisional)")]), remount));
    f1.appendChild(select("Pillar spacing (m)", "pillar", cat.options.pillar.map((v) => [v, v]), remount));
    f1.appendChild(select("Spans (modules)", "spans", Array.from({ length: 12 }, (_, i) => [i + 1, i + 1]), remount));
    f1.appendChild(select("Bays along length", "bays", Array.from({ length: 16 }, (_, i) => [i + 2, i + 2]), remount));
    panel.appendChild(f1);
  }
  const f2 = document.createElement("fieldset"); f2.innerHTML = "<legend>State (demo)</legend>";
  ranges.forEach(([name, key, lo, hi, step]) => {
    if (state.system === "OPEN_FIELD" && ["i_temp", "i_rh", "vent", "screen", "heater"].includes(key)) return;
    const l = document.createElement("label"), out = document.createElement("output");
    l.innerHTML = "<span>" + name + "</span>"; const r = document.createElement("input");
    Object.assign(r, { type: "range", min: lo, max: hi, step, value: state[key] }); out.textContent = state[key];
    r.oninput = () => { state[key] = Number(r.value); out.textContent = r.value; refresh(); }; l.appendChild(r); l.appendChild(out); f2.appendChild(l);
  });
  panel.appendChild(f2);
  const n = document.createElement("p"); n.className = "note"; n.id = "notes"; panel.appendChild(n);
}
function remount() {
  let cfg;
  if (state.system === "OPEN_FIELD") cfg = { system: "OPEN_FIELD", cropKind: state.cropKind, azimuth: state.azimuth, field: { width: 12, length: 12, rowSpacing: 0.75, plantSpacing: 0.3 } };
  else {
    const cat = CATALOGUE[state.typology], key = state.span + "|" + state.rise, prof = cat.profiles[key] || cat.profiles[Object.keys(cat.profiles)[0]];
    const missing = !cat.profiles[key];
    cfg = { system: "GREENHOUSE", typology: state.typology, cropKind: state.cropKind, azimuth: state.azimuth, spans: state.spans, bays: state.bays, span: state.span, gutter: state.gutter, pillar: state.pillar, profile: prof.profile, profileKind: prof.kind };
    const flags = [];
    if (!cat.listed.rise) flags.push("ridge rise is provisional (not published)");
    if (!cat.listed.gutter) flags.push("gutter/eave height is provisional (not published)");
    if (prof.off_catalogue.length) flags.push("off-catalogue: " + prof.off_catalogue.join(", "));
    if (missing) flags.push("ERROR: no pre-baked profile for " + key + "; showing another");
    cfg.flags = flags;
  }
  scene = GreenhouseScene.mount(document.getElementById("scene"), cfg);
  plantCard = GreenhouseScene.inspector(document.getElementById("inspector"), state.cropKind);
  const g = scene.geometry, st = document.getElementById("status");
  st.innerHTML = state.system === "OPEN_FIELD" ? "Open field 12 x 12 m, schematic. " + scene.plantCount + " plants drawn (subset of the planting grid)."
    : cfg.typology.replace(/_/g, " ").toLowerCase() + ": " + g.width.toFixed(1) + " x " + g.length.toFixed(1) + " m, " + cfg.profileKind.toLowerCase().replace("_", " ") + ". <span class='flag'>" + (cfg.flags.length ? cfg.flags.join("; ") + "." : "") + "</span> Parametric schematic, not a manufacturer drawing.";
  if (state.zoom > 1) scene.zoom(state.zoom);
  refresh();
}
function refresh() {
  if (!scene) return;
  scene.update({ hour: state.hour, forcing_label: "(demo)", backend_label: "(demo)",
    outdoor: { temp_c: state.o_temp, rh_pct: state.o_rh, solar_w_m2: state.o_solar, wind_m_s: state.o_wind, wind_dir_deg: state.o_dir, rain_mm_h: state.o_rain },
    indoor: { temp_c: state.i_temp, rh_pct: state.i_rh, co2_ppm: null },
    actuators: { vent_opening: state.vent, screen_deployed: state.screen, heater_kw: state.heater },
    crop: { lai: state.lai, lai_max: 4, water_stress: state.water, temperature_stress: state.temp, vpd_stress: state.vpd, cumulative_stress: state.cum, fruit_fraction: state.fruit, fruit_ripeness: state.ripe } });
  plantCard.update({ lai: state.lai, lai_max: 4, water_stress: state.water, temperature_stress: state.temp, vpd_stress: state.vpd, cumulative_stress: state.cum, fruit_fraction: state.fruit, fruit_ripeness: state.ripe });
  const notes = document.getElementById("notes");
  if (notes) notes.innerHTML = "Plant loss is a <b>derived indicator</b> (cumulative stress above 0.8 removes plants in a fixed order). The crop model has no mortality variable. CO2 shows n/a because the backend does not model it.";
}
buildPanel(); remount();
</script></body></html>`;
const theme = process.argv[2] || "light";
writeFileSync(here(`demo-${theme}.html`), html.replace("__THEME__", theme));
console.log("written demo-" + theme + ".html");
