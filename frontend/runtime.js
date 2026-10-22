"use strict";

/* Phase 5.39-5.41 runtime panel: event editor, what-if branches, timeline and read-only spatial view
 * (scene drawn by iso_scene.js from scene_state.js).
 * Presentation only. Every number shown comes from the API; this file contains no model equation.
 * Scaling to a drawing range uses the extent of the returned series and is purely visual. */

const NS = "http://www.w3.org/2000/svg";
const rt = {
  contract: null, events: [], result: null, series: {}, times: [], branchIndex: 0, index: 0,
  view: "ISOMETRIC", pan: { x: 0, y: 0 }, zoom: 1, playing: false, selected: null, lastRenderMs: null, running: false,
  position: 0, environment: "outdoor", catalogue: {}, ctx: {}, layers: { crop: true, soil: true, water: true, temperature: false, radiation: false, vpd: false, co2: false, events: true },
  fps: null, fpsLog: [], lastDraw: 0, lastReadout: 0, lastCursor: 0, hover: null,
  scene: null, sceneKey: "", greenhouse: null,
};
const SPEEDS = [0.25, 0.5, 1, 2, 5, 10, 50];
const DRAW_INTERVAL_MS = 12;
const READOUT_INTERVAL_MS = 250;
const CURSOR_INTERVAL_MS = 100;
const READOUT_VARIABLES = ["temperature_c", "relative_humidity_pct", "vpd_kpa", "radiation_w_m2", "co2_ppm", "soil_water_vwc_m3_m3", "transpiration_mm",
  "evaporation_mm", "irrigation_mm", "biomass_total_g_m2", "leaf_area_index", "water_stress", "heat_stress", "greenhouse_ventilation_fraction", "greenhouse_shading_fraction"];

const MAPPING = [
  ["leaf_area_index", "Plant height and canopy size, against a fixed drawing reference of LAI 4 (young crops stay small)"],
  ["accumulated_stress", "Leaf hue green to yellow to brown, relative to max(1, run maximum)"],
  ["water_stress", "Drooping, narrower and paler leaves (backend value)"],
  ["heat_stress / cold_stress", "Orange-red / blue leaf edge (backend value)"],
  ["vpd_stress", "Dashed brown leaf edge (backend value)"],
  ["frost_damage", "Share of plants drawn as lost (the model has no mortality count)"],
  ["biomass_fruit_g_m2 / biomass_total_g_m2 / maturity_index", "Fruit dots and ripeness colour (vine silhouette only)"],
  ["soil_water_vwc_m3_m3", "Soil wetness overlay, scaled to the returned series"],
  ["precipitation_mm / irrigation_mm", "Rain streaks (mm per step converted to mm per hour) / irrigation droplets"],
  ["greenhouse_ventilation_fraction", "Roof vent flaps, up to 40 degrees open (greenhouse only)"],
  ["greenhouse_shading_fraction", "Screen sheet deployed along the length (greenhouse only)"],
  ["temperature_c", "Cover tint blue to red (greenhouse); numeric readout in both modes"],
  ["radiation_w_m2", "Sun disc and sky brightness, scaled to the returned series"],
  ["vpd_kpa", "Haze above the canopy, scaled to the returned series"],
  ["co2_ppm", "CO2 markers (greenhouse only)"],
  ["events", "Banner while an event is active at the displayed time"],
  ["not served by the API", "Wind, cloud cover, outdoor humidity and outdoor rain in greenhouse mode are shown as n/a"],
];

function svgEl(tag, attrs = {}, text) {
  const element = document.createElementNS(NS, tag);
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value);
  if (text !== undefined) element.textContent = text;
  return element;
}

function runtimeError(payload, message) {
  const box = $("#runtime-error");
  if (payload) showApiError(box, payload);
  else if (message) { box.textContent = message; box.hidden = false; } else box.hidden = true;
}

function crop() { return state.capabilities.crop_defaults[$("#crop").value]; }
function hourMs() { return 3600 * 1000; }

function refreshBranchRange() {
  const defaults = crop();
  const start = Date.parse(defaults.start_time);
  const end = Date.parse(defaults.end_time);
  const days = Math.max(2, Math.floor((end - start) / (24 * hourMs())));
  const range = $("#branch-range");
  range.max = String(days - 1);
  range.value = String(Math.min(Number(range.value) || 10, days - 1));
  updateBranchLabel();
}

function branchTime() {
  const days = Number($("#branch-range").value);
  return new Date(Date.parse(crop().start_time) + days * 24 * hourMs()).toISOString();
}

function updateBranchLabel() {
  $("#branch-label").textContent = `simulation time ${branchTime()} (day ${$("#branch-range").value})`;
}

function selectedSpec() {
  return rt.contract.supported.find((item) => item.event_type === $("#event-type").value);
}

function updateEventForm() {
  const spec = selectedSpec();
  const environment = $("#environment").value;
  const allowed = spec.environments.includes(environment);
  const input = $("#event-intensity");
  const hasIntensity = spec.minimum !== null && spec.minimum !== undefined && spec.maximum !== null && spec.maximum !== undefined;
  input.disabled = !hasIntensity;
  $("#event-intensity-label").textContent = hasIntensity ? `Intensity (${spec.intensity_unit})` : "Intensity (none)";
  if (hasIntensity) {
    input.min = spec.minimum; input.max = spec.maximum;
    input.value = input.value || "";
  } else input.value = "";
  $("#event-ramp").disabled = !spec.ramp_supported;
  if (!spec.ramp_supported) $("#event-ramp").value = "0";
  const range = hasIntensity
    ? ` Accepted range ${spec.minimum_exclusive ? ">" : "≥"} ${spec.minimum} to ${spec.maximum} (${spec.bound_note}).`
    : "";
  $("#event-help").textContent = `${spec.summary}. Environments: ${spec.environments}.${range}${allowed ? "" : ` Not available in ${environment}.`}`;
  $("#event-add").disabled = !allowed;
}

function addEvent() {
  const spec = selectedSpec();
  const startOffset = Number($("#event-start").value);
  const start = new Date(Date.parse(branchTime()) + startOffset * hourMs()).toISOString();
  const event = { event_type: spec.event_type, start_simulation_time: start, duration_hours: Number($("#event-duration").value) };
  if (!$("#event-intensity").disabled && $("#event-intensity").value !== "") event.intensity = Number($("#event-intensity").value);
  if (!$("#event-ramp").disabled && Number($("#event-ramp").value) > 0) event.ramp_hours = Number($("#event-ramp").value);
  rt.events.push(event);
  renderEventList();
}

function renderEventList() {
  const list = $("#event-list");
  list.replaceChildren();
  rt.events.forEach((event, index) => {
    const item = node("li", "", `${event.event_type} · ${event.start_simulation_time} · ${event.duration_hours} h${event.intensity !== undefined ? ` · intensity ${event.intensity}` : ""}${event.ramp_hours ? ` · ramp ${event.ramp_hours} h` : ""} `);
    const remove = node("button", "link-button", "Remove");
    remove.type = "button";
    remove.addEventListener("click", () => { rt.events.splice(index, 1); renderEventList(); });
    item.append(remove);
    list.append(item);
  });
  if (rt.result) window.Visual.refreshEvents();
}

function whatIfDocument() {
  const request = currentRequest();
  request.options = { include_trajectory: true, compute_trajectory_hash: true };
  return { request, checkpoint_time: branchTime(), events: rt.events };
}

async function previewEvents() {
  runtimeError();
  const box = $("#preview-box");
  box.hidden = true;
  try {
    const preview = await api("/api/runtime/preview", { method: "POST", body: JSON.stringify(whatIfDocument()) });
    box.replaceChildren(node("strong", "", `Preview · ${preview.events.length} event(s) · USER_DEFINED_EVENT · ${preview.classification}`));
    for (const event of preview.events) {
      const affected = event.affected_variables.map((item) => `${item.variable} (${item.availability})`).join(", ");
      box.append(node("p", "", `${event.event_type}: ${event.start_simulation_time} → ${event.end_simulation_time}, ${event.duration_hours} h, `
        + `intensity ${event.intensity ?? "n/a"} ${event.intensity_unit ?? ""}, ramp ${event.ramp_hours ?? 0} h. Supported: ${event.support}. `
        + `Affected variables: ${affected}. Requires checkpoint/resume: ${event.requires_checkpoint ? "yes" : "no"}. Creates a new branch: ${event.creates_new_branch ? "yes" : "no"}.`));
    }
    box.append(node("p", "field-help", `${preview.consequences}. Only the future from ${preview.branch_point} is affected; history is not modified.`));
    box.hidden = false;
  } catch (error) {
    if (error.payload) runtimeError(error.payload); else runtimeError(null, error.message);
  }
}

async function runWhatIf(event) {
  event.preventDefault();
  if (rt.running) return;
  rt.running = true;
  runtimeError();
  $("#whatif-run").disabled = true;
  stopPlayback();
  try {
    const started = performance.now();
    const result = await api("/api/runtime/what-if", { method: "POST", body: JSON.stringify(whatIfDocument()) });
    const apiMs = performance.now() - started;
    rt.result = result;
    prepareSeries();
    const renderStarted = performance.now();
    renderWhatIf();
    rt.lastRenderMs = performance.now() - renderStarted;
    renderRuntimePerf(apiMs);
  } catch (error) {
    if (error.payload) runtimeError(error.payload); else runtimeError(null, error.message);
  } finally {
    rt.running = false;
    $("#whatif-run").disabled = false;
  }
}

function branchTrajectory(name) {
  return rt.result.branches[name].response.result.trajectory;
}

function prepareSeries(environment) {
  const prefix = rt.result.prefix.result.trajectory;
  rt.series = {};
  for (const name of ["baseline", "intervention"]) {
    const branch = branchTrajectory(name);
    const lastPrefix = prefix.time[prefix.time.length - 1];
    const keep = branch.time.map((t, i) => (t > lastPrefix ? i : -1)).filter((i) => i >= 0);
    const merged = { time: prefix.time.concat(keep.map((i) => branch.time[i])) };
    for (const key of Object.keys(branch)) {
      if (key === "time") continue;
      merged[key] = (prefix[key] || []).concat(keep.map((i) => branch[key][i]));
    }
    rt.series[name] = merged;
  }
  rt.times = rt.series.baseline.time;
  rt.branchIndex = rt.times.findIndex((t) => t >= rt.result.branch_point.simulation_time);
  rt.index = Math.max(0, rt.branchIndex);
  rt.position = rt.index;
  rt.environment = environment || $("#environment").value;
  rt.catalogue = VisualState.catalogue(rt.result.branches.baseline.response.result.variables);
  for (const name of ["baseline", "intervention"]) {
    rt.ctx[name] = VisualState.buildContext({ series: rt.series[name], catalogue: rt.catalogue, times: rt.times, events: rt.result.events, environment: rt.environment, branch: name });
  }
}

function renderWhatIf() {
  const result = rt.result;
  $("#whatif-result").hidden = false;
  const comparison = result.comparison;
  $("#whatif-summary").textContent =
    `Branch point ${result.branch_point.simulation_time} · changed variables: ${comparison.variables_changed.join(", ") || "none"} · `
    + `history before the first event unchanged: ${comparison.unchanged_before_first_event ? "yes" : "NO"} · ${result.statement}`;
  renderTimeline();
  setupController();
  renderIso();
  renderReadout();
  window.Visual.render();
  $("#iso-mapping").replaceChildren(...MAPPING.map(([name, text]) => node("li", "", `${name}: ${text}`)));
  $("#whatif-provenance").textContent = JSON.stringify({
    provenance_classes: result.provenance_classes,
    branches: Object.fromEntries(Object.entries(result.branches).map(([name, branch]) => [name, branch.provenance])),
    hashes: result.hashes, what_if_hash: result.what_if_hash, scientific_status: result.scientific_status,
  }, null, 2);
}

function stageColor(stage) { return STAGE_COLORS[stage] || UNKNOWN_STAGE_COLOR; }

function renderTimeline() {
  const host = $("#timeline");
  host.replaceChildren();
  const width = 760, left = 70, right = 12, rows = ["Stages", "Events", "Irrigation", "Water stress", "Markers"];
  const height = 16 + rows.length * 26 + 22;
  const n = rt.times.length;
  const x = (i) => left + (i / (n - 1)) * (width - left - right);
  const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "Timeline of stages, events, irrigation and checkpoint" });
  rows.forEach((label, r) => svg.append(svgEl("text", { x: 4, y: 28 + r * 26, "font-size": 10, fill: "#64766e" }, label)));
  const stages = rt.series.intervention.crop_stage || [];
  let start = 0;
  for (let i = 1; i <= stages.length; i += 1) {
    if (i === stages.length || stages[i] !== stages[start]) {
      const color = stageColor(stages[start]);
      svg.append(svgEl("rect", { x: x(start), y: 16, width: Math.max(1, x(i - 1) - x(start)), height: 18, fill: color.band, stroke: color.border }));
      start = i;
    }
  }
  const indexOf = (time) => Math.max(0, Math.min(n - 1, rt.times.findIndex((t) => t >= time)));
  for (const event of rt.result.events) {
    const a = x(indexOf(event.start_simulation_time));
    const b = x(indexOf(event.end_simulation_time));
    svg.append(svgEl("rect", { x: a, y: 42, width: Math.max(3, b - a), height: 18, fill: "#c0561d", opacity: 0.75 }));
    svg.append(svgEl("text", { x: a + 2, y: 55, "font-size": 9, fill: "#fff" }, event.event_type));
  }
  (rt.series.intervention.irrigation_mm || []).forEach((value, i) => {
    if (value > 0) svg.append(svgEl("line", { x1: x(i), x2: x(i), y1: 70, y2: 84, stroke: "#2a78b5" }));
  });
  (rt.series.intervention.water_stress || []).forEach((value, i) => {
    if (typeof value === "number" && value > 0) svg.append(svgEl("rect", { x: x(i), y: 96, width: Math.max(1, x(1) - x(0)), height: 16, fill: "#a3342b", opacity: Math.min(1, value) }));
  });
  svg.append(svgEl("path", { d: `M${x(rt.branchIndex)},122 l-5,10 h10 z`, fill: "#123b2c" }));
  svg.append(svgEl("text", { x: x(rt.branchIndex) + 8, y: 131, "font-size": 10, fill: "#123b2c" }, "checkpoint / intervention point"));
  const cursor = svgEl("line", { id: "timeline-cursor", x1: x(rt.index), x2: x(rt.index), y1: 10, y2: 136, stroke: "#17352d", "stroke-width": 1.5 });
  svg.append(cursor);
  host.append(svg, node("p", "", "Stage colours follow the semantic palette; water-stress opacity equals the backend value; irrigation ticks mark hours where the backend irrigation_mm > 0."));
  rt.timelineX = x;
}

function activeEvents(time) {
  return rt.result.events.filter((event) => time >= event.start_simulation_time && time < event.end_simulation_time);
}

function setupController() {
  const slider = $("#tc-slider");
  slider.max = String(rt.times.length - 1);
  slider.value = String(rt.index);
}

function speedHoursPerSecond() { return Number($("#tc-speed").value); }

function stopPlayback() {
  rt.playing = false;
  $("#tc-play").textContent = "▶ Play";
  $("#tc-play").setAttribute("aria-pressed", "false");
}

function seek(position) {
  rt.position = Math.max(0, Math.min(rt.times.length - 1, position));
  rt.index = Math.floor(rt.position);
  $("#tc-slider").value = String(rt.index);
  renderIso();
  const cursor = $("#timeline-cursor");
  if (cursor && rt.timelineX) { cursor.setAttribute("x1", rt.timelineX(rt.position)); cursor.setAttribute("x2", rt.timelineX(rt.position)); }
  renderReadout();
  window.Visual.cursor(rt.position);
}

function playFrame(timestamp) {
  if (!rt.playing) return;
  const elapsed = timestamp - rt.lastDraw;
  if (elapsed >= DRAW_INTERVAL_MS) {
    const step = VisualState.advance(rt.position, Math.min(elapsed, 250) / 1000, speedHoursPerSecond(), rt.times.length - 1);
    rt.lastDraw = timestamp;
    rt.position = step.position;
    rt.index = Math.floor(rt.position);
    renderIso();
    rt.frames += 1;
    if (timestamp - rt.fpsStart >= 1000) {
      rt.fps = (rt.frames * 1000) / (timestamp - rt.fpsStart);
      rt.fpsLog.push(Number(rt.fps.toFixed(1)));
      rt.frames = 0; rt.fpsStart = timestamp;
      $("#fps-meter").textContent = `${rt.fps.toFixed(0)} fps (display only)`;
    }
    if (timestamp - rt.lastReadout >= READOUT_INTERVAL_MS) {
      rt.lastReadout = timestamp;
      $("#tc-slider").value = String(rt.index);
      renderReadout();
    }
    if (timestamp - rt.lastCursor >= CURSOR_INTERVAL_MS) {
      rt.lastCursor = timestamp;
      window.Visual.cursor(rt.position);
      const cursor = $("#timeline-cursor");
      if (cursor && rt.timelineX) { cursor.setAttribute("x1", rt.timelineX(rt.position)); cursor.setAttribute("x2", rt.timelineX(rt.position)); }
    }
    if (step.finished) { stopPlayback(); seek(rt.times.length - 1); return; }
  }
  window.requestAnimationFrame(playFrame);
}

function togglePlay() {
  if (!rt.result) return;
  if (rt.playing) { stopPlayback(); seek(rt.position); return; }
  if (rt.position >= rt.times.length - 1) rt.position = 0;
  rt.playing = true;
  $("#tc-play").textContent = "⏸ Pause";
  $("#tc-play").setAttribute("aria-pressed", "true");
  rt.frames = 0;
  rt.fpsStart = performance.now();
  rt.lastDraw = rt.fpsStart;
  rt.lastReadout = rt.fpsStart;
  rt.lastCursor = rt.fpsStart;
  window.requestAnimationFrame(playFrame);
}

function jumpToEvent() {
  if (!rt.result.events.length) return;
  const starts = rt.result.events.map((event) => rt.times.findIndex((t) => t >= event.start_simulation_time));
  const next = starts.find((i) => i > rt.index);
  seek(next === undefined ? starts[0] : next);
}

function currentVisual() {
  return VisualState.buildVisualState(rt.ctx[$("#iso-branch").value], rt.position);
}

const PART_LABELS = { crop: "Crop", plot: "Plot", soil: "Soil", greenhouse: "Greenhouse" };

function describeLayer(visual, layer) {
  const name = VisualState.LAYER_VARIABLE[layer];
  if (!name) return null;
  const info = visual.variables[name];
  if (!info) return `${layer}: not available`;
  if (info.availability !== VisualState.AVAILABLE) return `${layer}: ${info.availability}${info.reason ? ` (${info.reason})` : ""}`;
  return `${layer}: ${formatValue(info.value)} ${info.unit || ""}`.trim();
}

/* Layout (visual schematic): geometry comes from /api/greenhouse/catalogue; the lumped greenhouse model derives its volume, floor and cover areas from the same layout. */
function sceneDescription() {
  if (rt.environment !== "greenhouse") return { layout: null, key: "open-field" };
  const gh = rt.greenhouse;
  if (!gh || !gh.catalogue || !gh.choice) return null;
  const choice = gh.choice;
  const entry = gh.catalogue.typologies[choice.typology].profiles[`${choice.span}|${choice.rise}`];
  if (!entry) return null;
  return { layout: { span: choice.span, spans: choice.spans, bays: choice.bays, pillar: choice.pillar, gutter: choice.gutter, profile: entry.profile }, key: JSON.stringify(choice), kind: entry.kind };
}

function ensureScene() {
  const description = sceneDescription();
  const compact = window.innerWidth < 520;
  const cropKind = SceneState.silhouetteFor($("#crop").value);
  const key = [rt.environment, rt.view, compact, cropKind, description ? description.key : "pending"].join("#");
  if (rt.scene && rt.sceneKey === key) return true;
  if (!description) return false;
  if (!rt.scene) rt.scene = IsoScene.create($("#iso-svg"));
  const field = rt.greenhouse && rt.greenhouse.catalogue ? rt.greenhouse.catalogue.open_field : null;
  rt.scene.configure(description.layout, { view: rt.view, cropKind, compact, field: field ? { width: field.width, length: field.length, rowSpacing: field.row_spacing, plantSpacing: field.plant_spacing } : null });
  rt.sceneKey = key;
  return true;
}

function decorateParts(visual, layers) {
  const parts = rt.scene.parts();
  const labelled = [["crop", parts.crop], [layers.soil ? "soil" : "plot", parts.ground], ["greenhouse", parts.greenhouse]];
  for (const [id, elements] of labelled) {
    for (const shape of elements || []) {
      shape.setAttribute("data-part", id);
      shape.setAttribute("tabindex", "0");
      shape.setAttribute("role", "button");
      shape.setAttribute("aria-label", `${PART_LABELS[id]} at ${visual.time}: press Enter for details`);
      shape.setAttribute("class", `${shape.getAttribute("class") || ""}`.replace(/\s*\b(iso-part|selected)\b/g, "") + ` iso-part${rt.selected === id ? " selected" : ""}`);
    }
    for (const shape of (parts.mirror && parts.mirror[id]) || []) shape.classList.toggle("iso-selected", rt.selected === id);
  }
}

function renderIso() {
  const started = performance.now();
  if (!rt.result) return;
  syncLayoutVisibility();
  const visual = currentVisual();
  if (!ensureScene()) {
    $("#layout-note").textContent = "Greenhouse catalogue not loaded yet; the spatial view is waiting for it.";
    return;
  }
  rt.scene.update(SceneState.fromVisual(visual, rt.ctx[$("#iso-branch").value], rt.position), rt.layers);
  rt.scene.setView(rt.zoom, rt.pan.x, rt.pan.y);
  decorateParts(visual, rt.layers);
  rt.visual = visual;
  if (rt.focusPart) {
    const target = $("#iso-svg").querySelector(`[data-part="${rt.focusPart}"]`);
    rt.focusPart = null;
    if (target) target.focus();
  }
  rt.lastRenderMs = performance.now() - started;
  const perf = $("#perf-render");
  if (perf) perf.textContent = `${rt.lastRenderMs.toFixed(1)} ms`;
}

function syncLayoutVisibility() {
  $("#layout-panel").hidden = !(rt.environment === "greenhouse" && rt.greenhouse && rt.greenhouse.catalogue);
}

async function loadGreenhouseCatalogue() {
  try {
    const catalogue = await api("/api/greenhouse/catalogue");
    rt.greenhouse = { catalogue, choice: null };
    const names = Object.keys(catalogue.typologies);
    replaceOptions($("#layout-typology"), names, (value) => value.replace(/_/g, " ").toLowerCase());
    resetLayout(names[0]);
    for (const id of ["typology", "span", "rise", "gutter", "pillar", "spans", "bays"]) {
      $(`#layout-${id}`).addEventListener("change", () => (id === "typology" ? resetLayout($("#layout-typology").value) : readLayout()));
    }
    if (rt.result) renderIso();
  } catch (error) {
    rt.greenhouse = { catalogue: null, error: error.message };
    runtimeError(null, `Greenhouse catalogue unavailable: ${error.message}`);
  }
}

function resetLayout(typology) {
  const cat = rt.greenhouse.catalogue, entry = cat.typologies[typology], d = entry.default;
  rt.greenhouse.choice = { typology, span: d.span, rise: d.rise, gutter: d.gutter, pillar: d.pillar, spans: d.spans, bays: d.bays };
  $("#layout-typology").value = typology;
  const provisional = (listed) => (listed ? "" : " (provisional)");
  replaceOptions($("#layout-span"), entry.options.span.map(String), (v) => v);
  replaceOptions($("#layout-rise"), entry.options.rise.map(String), (v) => `${v}${provisional(entry.listed.rise)}`);
  replaceOptions($("#layout-gutter"), entry.options.gutter.map(String), (v) => `${v}${provisional(entry.listed.gutter)}`);
  replaceOptions($("#layout-pillar"), entry.options.pillar.map(String), (v) => v);
  replaceOptions($("#layout-spans"), Array.from({ length: cat.max_spans }, (_, i) => String(i + 1)), (v) => v);
  replaceOptions($("#layout-bays"), Array.from({ length: 15 }, (_, i) => String(i + 2)), (v) => v);
  for (const [id, value] of [["span", d.span], ["rise", d.rise], ["gutter", d.gutter], ["pillar", d.pillar], ["spans", d.spans], ["bays", d.bays]]) $(`#layout-${id}`).value = String(value);
  describeLayout();
  if (rt.result) renderIso();
}

function readLayout() {
  const choice = rt.greenhouse.choice;
  for (const id of ["span", "rise", "gutter", "pillar", "spans", "bays"]) choice[id] = Number($(`#layout-${id}`).value);
  describeLayout();
  renderIso();
}

function describeLayout() {
  const cat = rt.greenhouse.catalogue, choice = rt.greenhouse.choice, entry = cat.typologies[choice.typology];
  const flags = [];
  if (!entry.listed.rise) flags.push("ridge rise is provisional (not published)");
  if (!entry.listed.gutter) flags.push("gutter/eave height is provisional (not published)");
  $("#layout-note").textContent = `${cat.statement}${flags.length ? ` Provisional here: ${flags.join("; ")}.` : ""} `
    + `${(choice.span * choice.spans).toFixed(1)} m x ${(choice.bays * choice.pillar).toFixed(1)} m.`;
}

function renderReadout() {
  if (!rt.visual) return;
  const visual = rt.visual;
  $("#tc-time").textContent = `${visual.time}${visual.interpolated ? " (interpolated display)" : ""}`;
  const readout = $("#iso-readout");
  readout.replaceChildren();
  const rows = [["Time (UTC)", visual.time], ["Stage", visual.stage ?? "NOT_AVAILABLE"], ["Active events", visual.active_events.map((e) => e.event_type).join(", ") || "none"]];
  if (rt.selected) rows.unshift(["Selected", `${PART_LABELS[rt.selected]} (read-only)`]);
  for (const name of READOUT_VARIABLES) {
    const info = visual.variables[name];
    if (!info) continue;
    if (info.availability === VisualState.NOT_APPLICABLE && (name.startsWith("greenhouse_") || name === "co2_ppm") && rt.environment !== "greenhouse") continue;
    rows.push([VARIABLE_LABELS[name] || name, info.availability === VisualState.AVAILABLE ? `${formatValue(info.value)} ${info.unit || ""}`.trim() : info.availability]);
  }
  for (const [name, value] of rows) { const wrap = node("div"); wrap.append(node("dt", "", name), node("dd", "", formatValue(value))); readout.append(wrap); }
  const status = visual.active_events.length ? `Event active: ${visual.active_events.map((e) => e.event_type).join(", ")}.` : "No active event.";
  const layerText = Object.keys(rt.layers).filter((layer) => rt.layers[layer]).map((layer) => describeLayer(visual, layer)).filter(Boolean).join(" · ");
  $("#layer-status").textContent = `${status} ${layerText}`;
  window.Visual.refreshDetail();
}

function renderRuntimePerf(apiMs) {
  const host = $("#runtime-perf");
  host.replaceChildren();
  const seconds = rt.result.operational.timings_seconds;
  const total = (key) => Object.values(seconds).reduce((sum, part) => sum + (part[key] || 0), 0);
  const items = [
    ["API round trip", `${apiMs.toFixed(0)} ms`],
    ["Backend simulation (3 segments)", `${(total("simulation_seconds") * 1000).toFixed(0)} ms`],
    ["Backend result projection", `${(total("result_projection_seconds") * 1000).toFixed(0)} ms`],
    ["Last render", `${(rt.lastRenderMs ?? 0).toFixed(1)} ms`],
    ["Display FPS (last playback)", rt.fpsLog.length ? `${rt.fpsLog[rt.fpsLog.length - 1]} fps` : "not played yet"],
    ["SVG nodes / charts", `${$("#iso-svg").querySelectorAll("*").length} / ${window.Visual.chartCount()}`],
  ];
  for (const [name, value] of items) { const wrap = node("div"); const dd = node("dd", "", value); if (name === "Last render") dd.id = "perf-render"; wrap.append(node("dt", "", name), dd); host.append(wrap); }
  host.append(node("p", "field-help", "Operational timings: machine-dependent, excluded from every hash. Presentation refresh is independent of the simulation step."));
}

function tooltipFor(partId) {
  const target = { crop: "crop", plot: "plot", soil: "soil", greenhouse: "greenhouse" }[partId];
  const rows = [];
  for (const group of VisualState.DETAIL_TARGETS[target]) {
    for (const row of VisualState.groupRows(rt.visual, group)) {
      if (row.availability === VisualState.AVAILABLE && row.unit !== null && rows.length < 5) rows.push(`${VARIABLE_LABELS[row.name] || row.name}: ${formatValue(row.value)} ${row.unit}`);
    }
  }
  return [`${PART_LABELS[partId]} · ${rt.visual.time}`, ...rows, "MODEL OUTPUT"];
}

function selectPart(id) {
  rt.selected = id;
  rt.focusPart = id;
  $("#detail-target").value = { crop: "crop", plot: "plot", soil: "soil", greenhouse: "greenhouse" }[id];
  renderIso();
  renderReadout();
}

function bindController() {
  $("#tc-play").addEventListener("click", togglePlay);
  $("#tc-back").addEventListener("click", () => { stopPlayback(); seek(rt.index - 1); });
  $("#tc-fwd").addEventListener("click", () => { stopPlayback(); seek(rt.index + 1); });
  $("#tc-restart").addEventListener("click", () => { stopPlayback(); seek(0); });
  $("#tc-event").addEventListener("click", () => { stopPlayback(); jumpToEvent(); });
  $("#tc-checkpoint").addEventListener("click", () => { stopPlayback(); seek(rt.branchIndex); });
  $("#tc-slider").addEventListener("input", (event) => { stopPlayback(); seek(Number(event.target.value)); });
  $("#iso-wrap").addEventListener("keydown", (event) => {
    const part = event.target.closest?.("[data-part]");
    if (part && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); selectPart(part.dataset.part); return; }
    if (!rt.result) return;
    if (event.key === "k") togglePlay();
    else if (event.key === "ArrowRight") { stopPlayback(); seek(rt.index + 1); } else if (event.key === "ArrowLeft") { stopPlayback(); seek(rt.index - 1); }
    else if (event.key === "Home") { stopPlayback(); seek(0); } else if (event.key === "End") { stopPlayback(); seek(rt.times.length - 1); } else return;
    event.preventDefault();
  });
  document.querySelectorAll("[data-layer]").forEach((box) => box.addEventListener("change", () => { rt.layers[box.dataset.layer] = box.checked; renderIso(); renderReadout(); }));
}

function bindIso() {
  const svg = $("#iso-svg");
  const tooltip = $("#iso-tooltip");
  replaceOptions($("#tc-speed"), SPEEDS.map(String), (value) => `${value}×`);
  $("#tc-speed").value = "10";
  document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => {
    rt.view = button.dataset.view;
    document.querySelectorAll("[data-view]").forEach((b) => { b.classList.toggle("active", b === button); b.setAttribute("aria-pressed", String(b === button)); });
    renderIso();
  }));
  $("#iso-reset").addEventListener("click", () => { rt.pan = { x: 0, y: 0 }; rt.zoom = 1; rt.selected = null; renderIso(); renderReadout(); });
  $("#iso-zoom-in").addEventListener("click", () => { rt.zoom = Math.min(3, rt.zoom * 1.2); renderIso(); });
  $("#iso-zoom-out").addEventListener("click", () => { rt.zoom = Math.max(0.4, rt.zoom / 1.2); renderIso(); });
  $("#iso-branch").addEventListener("change", () => { renderIso(); renderReadout(); });
  let drag = null;
  svg.addEventListener("pointerdown", (event) => { drag = { x: event.clientX, y: event.clientY, moved: false, part: event.target.closest?.("[data-part]") }; svg.setPointerCapture(event.pointerId); });
  svg.addEventListener("pointermove", (event) => {
    if (drag) {
      const factor = 640 / svg.getBoundingClientRect().width;
      const dx = (event.clientX - drag.x) * factor, dy = (event.clientY - drag.y) * factor;
      if (Math.abs(dx) + Math.abs(dy) > 2) drag.moved = true;
      if (drag.moved) { rt.pan.x += dx; rt.pan.y += dy; drag.x = event.clientX; drag.y = event.clientY; if (!rt.playing) renderIso(); }
      tooltip.hidden = true;
      return;
    }
    const part = rt.visual ? event.target.closest?.("[data-part]") : null;
    if (!part) { tooltip.hidden = true; return; }
    const box = svg.getBoundingClientRect();
    tooltip.replaceChildren(...tooltipFor(part.dataset.part).map((line, i) => node(i ? "div" : "strong", "", line)));
    tooltip.style.left = `${Math.min(event.clientX - box.left + 12, box.width - 190)}px`;
    tooltip.style.top = `${event.clientY - box.top + 12}px`;
    tooltip.hidden = false;
  });
  svg.addEventListener("pointerleave", () => { tooltip.hidden = true; });
  svg.addEventListener("pointerup", () => {
    if (drag && !drag.moved && drag.part) selectPart(drag.part.dataset.part);
    drag = null;
  });
  svg.addEventListener("wheel", (event) => { event.preventDefault(); rt.zoom = Math.max(0.4, Math.min(3, rt.zoom * (event.deltaY < 0 ? 1.1 : 0.9))); if (!rt.playing) renderIso(); }, { passive: false });
}

function initRuntime() {
  rt.contract = state.capabilities.runtime;
  if (!rt.contract) return;
  replaceOptions($("#event-type"), rt.contract.supported.map((item) => item.event_type));
  $("#event-type").addEventListener("change", updateEventForm);
  $("#environment").addEventListener("change", updateEventForm);
  $("#crop").addEventListener("change", refreshBranchRange);
  $("#branch-range").addEventListener("input", updateBranchLabel);
  $("#event-add").addEventListener("click", addEvent);
  $("#event-preview").addEventListener("click", () => void previewEvents());
  $("#whatif-form").addEventListener("submit", (event) => void runWhatIf(event));
  bindController();
  window.Visual.init(rt);
  $("#pause-button").addEventListener("click", () => void pauseCurrent());
  bindIso();
  void loadGreenhouseCatalogue();
  refreshBranchRange();
  updateEventForm();
}

async function pauseCurrent() {
  const simulationId = state.response?.simulation_id;
  if (!simulationId) return;
  $("#pause-button").disabled = true;
  try {
    const response = await api(`/api/simulations/${encodeURIComponent(simulationId)}/pause`, { method: "POST", body: "{}" });
    updateExecution(response);
    if (["CREATED", "RUNNING"].includes(response.execution_status)) {
      state.pollTimer = window.setTimeout(() => void poll(simulationId), state.capabilities.poll_interval_ms);
    }
  } catch (error) {
    if (error.payload) showApiError($("#error-panel"), error.payload); else setGlobalError(error.message);
  }
}

window.adoptRuntimeResult = (result, environment) => {
  stopPlayback();
  rt.result = result;
  prepareSeries(environment);
  renderWhatIf();
};
window.initRuntime = initRuntime;
window.onRuntimeExecution = (response) => {
  $("#pause-button").disabled = !["CREATED", "RUNNING"].includes(response.execution_status);
};
if (state.capabilities) initRuntime();
