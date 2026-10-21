"use strict";

/* Experiment bench (Phase 5.41): configure, run, watch and compare on one screen.
 * Presentation only. Every number comes from the API (what-if or plain run); this file holds no model equation.
 * Summaries (peak, mean, final, difference) are plain statistics of the returned series. */
(function () {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const HOUR = 3600000, DAY = 86400000;
  const V = window.VisualState, S = window.SceneState;
  const SPEEDS = [1, 6, 24, 72, 168];
  const STORAGE_KEY = "agri-twin-bench-v1";
  const LAYERS = [["crop", "Crop"], ["soil", "Soil"], ["water", "Water"], ["temperature", "Temperature tint"], ["radiation", "Sun"], ["vpd", "VPD haze"], ["co2", "CO2"], ["events", "Events"]];
  const CHART_DEFAULT = ["temperature_c", "relative_humidity_pct", "greenhouse_ventilation_fraction", "heat_stress", "biomass_total_g_m2"];
  const LABELS = {
    temperature_c: "Crop air temperature", outdoor_temperature_c: "Outdoor temperature", relative_humidity_pct: "Relative humidity", vpd_kpa: "Vapour pressure deficit",
    radiation_w_m2: "Radiation at the crop", co2_ppm: "CO2", leaf_area_index: "Leaf area index", biomass_total_g_m2: "Total biomass", biomass_fruit_g_m2: "Fruit biomass",
    water_stress: "Water stress", heat_stress: "Heat stress", cold_stress: "Cold stress", vpd_stress: "VPD stress", accumulated_stress: "Accumulated stress",
    soil_water_vwc_m3_m3: "Soil water content", greenhouse_ventilation_fraction: "Vent opening", greenhouse_shading_fraction: "Shade screen",
    greenhouse_heating_kw: "Heating power", greenhouse_cooling_kw: "Cooling power", transpiration_mm: "Transpiration", irrigation_mm: "Irrigation", precipitation_mm: "Precipitation",
  };
  // quick events: defaults chosen inside the API limits; the contract still decides what is allowed
  const PRESETS = [
    { id: "heat", label: "Heat wave +8 °C", type: "HEAT_WAVE", intensity: 8, hours: 72, ramp: 6 },
    { id: "cold", label: "Cold wave −8 °C", type: "COLD_WAVE", intensity: 8, hours: 72, ramp: 6 },
    { id: "dry", label: "Dry spell", type: "DRYNESS", hours: 120 },
    { id: "rain", label: "Rain 5 mm/h", type: "RAIN", intensity: 5, hours: 48 },
    { id: "sunup", label: "Strong sun ×1.5", type: "HIGH_RADIATION", intensity: 1.5, hours: 72 },
    { id: "sundown", label: "Overcast ×0.5", type: "LOW_RADIATION", intensity: 0.5, hours: 72 },
    { id: "wind", label: "Windy ×3", type: "WIND", intensity: 3, hours: 48 },
    { id: "irrigate", label: "Irrigate 2 mm/step", type: "IRRIGATION", intensity: 2, hours: 24 },
    { id: "vents", label: "Vents fully open", type: "VENTILATION", intensity: 1, hours: 48 },
    { id: "shade", label: "Shade screen 60 %", type: "SHADING", intensity: 0.6, hours: 72 },
    { id: "co2", label: "CO2 boost", type: "CO2", intensity: 0.8, hours: 48 },
  ];

  const INTENSITY_UNITS = { HEAT_WAVE: "°C added", COLD_WAVE: "°C removed", RAIN: "mm/h", HIGH_RADIATION: "× radiation", LOW_RADIATION: "× radiation", WIND: "× wind",
    IRRIGATION: "mm per step", VENTILATION: "fraction of max", SHADING: "fraction of max", CO2: "fraction of max" };

  const bench = {
    caps: null, catalogue: null,
    config: { crop: "tomato", environment: "greenhouse", scenario: "BASE_SEASON", horizon: "month", backend: "SIMPLIFIED", layout: null, branchDay: null, view: "ISOMETRIC",
      layers: { crop: true, soil: true, water: true, temperature: true, radiation: true, vpd: false, co2: false, events: true }, charts: CHART_DEFAULT.slice() },
    events: [], run: null, serial: 0, running: false, position: 0, playing: false, speed: 24, lastFrame: 0, lastReadout: 0,
    scenes: {}, charts: [], autoTimer: null,
  };

  // ---- helpers ---------------------------------------------------------------------------------------------
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function setOptions(select, items, selected) {
    select.replaceChildren(...items.map(([value, label]) => { const option = el("option", "", label); option.value = String(value); return option; }));
    if (selected !== undefined && selected !== null) select.value = String(selected);
  }
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  const isNumber = (value) => typeof value === "number" && Number.isFinite(value);
  const iso = (ms) => new Date(ms).toISOString();
  function fmt(value, digits = 2) {
    if (!isNumber(value)) return "n/a";
    const magnitude = Math.abs(value);
    const text = value.toFixed(magnitude >= 1000 ? 0 : magnitude >= 100 ? 1 : digits);
    return text.includes(".") ? text.replace(/0+$/, "").replace(/\.$/, "") : text;
  }
  function label(name) { return LABELS[name] || name.replace(/_/g, " "); }

  async function api(path, options = {}) {
    const response = await fetch(path, { ...options, headers: { ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers } });
    const text = await response.text();
    let payload;
    try { payload = text ? JSON.parse(text) : {}; } catch { throw new Error(`The API returned invalid JSON (HTTP ${response.status}).`); }
    if (!response.ok) { const error = new Error("API request failed"); error.payload = payload; throw error; }
    return payload;
  }

  function showError(error) {
    const box = $("#error");
    box.replaceChildren();
    if (!error) { box.hidden = true; return; }
    const errors = error.payload && Array.isArray(error.payload.errors) ? error.payload.errors : [];
    if (errors.length) {
      for (const item of errors) box.append(el("div", "", `${item.code || "API_ERROR"}${item.path ? ` · ${item.path}` : ""} — ${item.message || ""}`));
    } else box.textContent = error.message || String(error);
    box.hidden = false;
  }
  function setStatus(text, stateName) { const node = $("#status"); node.textContent = text; node.dataset.state = stateName || ""; }

  // ---- persistence ------------------------------------------------------------------------------------------
  function save() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify({ config: bench.config, events: bench.events, speed: bench.speed })); } catch { /* storage may be unavailable */ }
  }
  function restore() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
      if (!saved) return;
      Object.assign(bench.config, saved.config || {});
      bench.config.layers = { ...bench.config.layers, ...((saved.config || {}).layers || {}) };
      if (Array.isArray(saved.events)) bench.events = saved.events;
      if (SPEEDS.includes(saved.speed)) bench.speed = saved.speed;
    } catch { /* ignore corrupt storage */ }
  }

  // ---- derived configuration ---------------------------------------------------------------------------------
  const defaults = () => bench.caps.crop_defaults[bench.config.crop];
  const startMs = () => Date.parse(defaults().start_time);
  function endMs() {
    const cropEnd = Date.parse(defaults().end_time), start = startMs();
    const days = { week: 7, month: 30, season: Infinity }[bench.config.horizon];
    return Math.min(cropEnd, start + days * DAY);
  }
  const horizonDays = () => Math.floor((endMs() - startMs()) / DAY);
  const branchMs = () => startMs() + bench.config.branchDay * DAY;
  const specFor = (type) => bench.caps.runtime.supported.find((item) => item.event_type === type);
  const backendInfo = (id) => bench.caps.greenhouse_backends.find((item) => item.id === id);

  function buildRequest() {
    const request = { crop: bench.config.crop, environment: bench.config.environment, scenario: bench.config.scenario, end_time: iso(endMs()),
      options: { include_trajectory: true, compute_trajectory_hash: false } };
    if (bench.config.environment === "greenhouse" && bench.config.backend === "ENERGYPLUS") {
      const c = bench.config.layout;
      request.greenhouse = { backend: "ENERGYPLUS", layout: { typology: c.typology, span_m: c.span, ridge_rise_m: c.rise, gutter_height_m: c.gutter, pillar_spacing_m: c.pillar, n_spans: c.spans, n_bays: c.bays } };
    }
    return request;
  }
  function eventDocuments() {
    return bench.events.map((event) => {
      const document = { event_type: event.type, start_simulation_time: iso(branchMs() + event.startHours * HOUR), duration_hours: event.hours };
      const spec = specFor(event.type);
      if (spec && spec.maximum !== null && spec.maximum !== undefined && !(spec.minimum === 0 && spec.maximum === 0)) document.intensity = event.intensity;
      if (spec && spec.ramp_supported && event.ramp > 0) document.ramp_hours = event.ramp;
      return document;
    });
  }

  // ---- setup panel -------------------------------------------------------------------------------------------
  function buildSetup() {
    const caps = bench.caps;
    setOptions($("#crop"), caps.crops.map((crop) => [crop, crop]), bench.config.crop);
    setOptions($("#scenario"), caps.scenarios.map((name) => [name, name.replace(/_/g, " ").toLowerCase()]), bench.config.scenario);
    refreshEnvironment();
    $("#crop").addEventListener("change", () => { bench.config.crop = $("#crop").value; refreshEnvironment(); fitBranch(); changed(); });
    $("#environment").addEventListener("change", () => { bench.config.environment = $("#environment").value; syncGreenhouseGroup(); pruneEvents(); renderEvents(); renderPresets(); changed(); });
    $("#scenario").addEventListener("change", () => { bench.config.scenario = $("#scenario").value; changed(); });
    $$("[data-horizon]").forEach((button) => button.addEventListener("click", () => { bench.config.horizon = button.dataset.horizon; fitBranch(); changed(); }));
    $$("[data-view]").forEach((button) => button.addEventListener("click", () => { bench.config.view = button.dataset.view; syncPressed("[data-view]", "view"); configureScenes(); renderFrame(true); save(); }));
    $("#branch").addEventListener("input", () => { bench.config.branchDay = Number($("#branch").value); updateBranchText(); renderEvents(); drawTicks(); redrawCharts(); });
    $("#branch").addEventListener("change", () => changed());
    $("#run").addEventListener("click", () => void runExperiment());
    $("#autorun").addEventListener("change", save);
    fitBranch();
    syncPressed("[data-horizon]", "horizon");
    syncPressed("[data-view]", "view");
  }

  function refreshEnvironment() {
    const crop = $("#crop").value, environments = bench.caps.crop_environments[crop];
    if (!environments.includes(bench.config.environment)) bench.config.environment = environments[0];
    setOptions($("#environment"), environments.map((name) => [name, name === "outdoor" ? "Open field" : "Greenhouse"]), bench.config.environment);
    syncGreenhouseGroup();
  }
  function syncGreenhouseGroup() {
    const greenhouse = bench.config.environment === "greenhouse";
    $("#greenhouse-group").hidden = !greenhouse;
    if (!greenhouse) bench.config.backend = "SIMPLIFIED";
    renderBackend();
  }
  function syncPressed(selector, key) {
    $$(selector).forEach((button) => button.setAttribute("aria-pressed", String(button.dataset[key] === bench.config[key])));
  }
  function fitBranch() {
    const days = horizonDays(), input = $("#branch");
    input.max = String(Math.max(1, days - 1));
    if (bench.config.branchDay === null || bench.config.branchDay > days - 1 || bench.config.branchDay < 1) bench.config.branchDay = Math.max(1, Math.round(days * 0.4));
    input.value = String(bench.config.branchDay);
    syncPressed("[data-horizon]", "horizon");
    updateBranchText();
    const start = startMs();
    $("#period").textContent = `Synthetic cycle ${iso(start).slice(0, 10)} → ${iso(endMs()).slice(0, 10)} · ${days} simulated days · weather is synthetic forcing`;
  }
  function updateBranchText() {
    $("#branch-out").textContent = `${bench.config.branchDay} of ${horizonDays()}`;
    $("#branch-date").textContent = `Branch point ${iso(branchMs()).slice(0, 16).replace("T", " ")} UTC; history before it is identical in both runs.`;
  }

  // greenhouse model + layout
  function renderBackend() {
    const group = $("#backend");
    group.replaceChildren();
    for (const info of bench.caps.greenhouse_backends) {
      const button = el("button", "", info.id === "ENERGYPLUS" && info.version ? `EnergyPlus ${info.version}` : info.label);
      button.type = "button";
      button.dataset.backend = info.id;
      button.disabled = !info.available;
      button.title = info.available ? info.note : info.reason;
      button.setAttribute("aria-pressed", String(bench.config.backend === info.id));
      button.addEventListener("click", () => { bench.config.backend = info.id; pruneEvents(); renderBackend(); renderEvents(); renderPresets(); changed(); });
      group.append(button);
    }
    const info = backendInfo(bench.config.backend);
    $("#backend-note").textContent = info.available ? info.note : info.reason;
  }
  function initLayout() {
    const cat = bench.catalogue;
    const names = Object.keys(cat.typologies);
    setOptions($("#layout-typology"), names.map((name) => [name, name.replace(/_/g, " ").toLowerCase()]));
    if (!bench.config.layout || !cat.typologies[bench.config.layout.typology]) resetLayout(names[0]);
    else fillLayout();
    $("#layout-typology").addEventListener("change", () => { resetLayout($("#layout-typology").value); changed(); configureScenes(); renderFrame(true); });
    for (const id of ["span", "rise", "gutter", "pillar", "spans", "bays"]) {
      $(`#layout-${id}`).addEventListener("change", () => {
        bench.config.layout[id] = Number($(`#layout-${id}`).value);
        describeLayout(); changed(); configureScenes(); renderFrame(true);
      });
    }
  }
  function resetLayout(typology) {
    const d = bench.catalogue.typologies[typology].default;
    bench.config.layout = { typology, span: d.span, rise: d.rise, gutter: d.gutter, pillar: d.pillar, spans: d.spans, bays: d.bays };
    fillLayout();
  }
  function fillLayout() {
    const layout = bench.config.layout, entry = bench.catalogue.typologies[layout.typology];
    $("#layout-typology").value = layout.typology;
    const tag = (listed) => (listed ? "" : " (provisional)");
    setOptions($("#layout-span"), entry.options.span.map((v) => [v, v]), layout.span);
    setOptions($("#layout-rise"), entry.options.rise.map((v) => [v, `${v}${tag(entry.listed.rise)}`]), layout.rise);
    setOptions($("#layout-gutter"), entry.options.gutter.map((v) => [v, `${v}${tag(entry.listed.gutter)}`]), layout.gutter);
    setOptions($("#layout-pillar"), entry.options.pillar.map((v) => [v, v]), layout.pillar);
    setOptions($("#layout-spans"), Array.from({ length: bench.catalogue.max_spans }, (_, i) => [i + 1, i + 1]), layout.spans);
    setOptions($("#layout-bays"), Array.from({ length: 15 }, (_, i) => [i + 2, i + 2]), layout.bays);
    describeLayout();
  }
  function describeLayout() {
    const layout = bench.config.layout, entry = bench.catalogue.typologies[layout.typology];
    const flags = [];
    if (!entry.listed.rise) flags.push("ridge rise");
    if (!entry.listed.gutter) flags.push("gutter height");
    const effect = bench.config.backend === "ENERGYPLUS" ? "The layout is simulated by EnergyPlus." : "With the simplified model the layout is only drawn; it does not change results.";
    $("#layout-note").textContent = `${(layout.span * layout.spans).toFixed(1)} × ${(layout.bays * layout.pillar).toFixed(1)} m. ${effect}${flags.length ? ` Provisional (not published): ${flags.join(", ")}.` : ""} Schematic, not a manufacturer drawing.`;
  }

  // ---- events ---------------------------------------------------------------------------------------------------
  function presetAllowed(preset) {
    const spec = specFor(preset.type);
    if (!spec) return false;
    if (spec.environments.startsWith("greenhouse only") && bench.config.environment !== "greenhouse") return false;
    if (bench.config.backend === "ENERGYPLUS" && preset.type === "CO2") return false;
    return true;
  }
  function renderPresets() {
    const host = $("#presets");
    host.replaceChildren();
    for (const preset of PRESETS) {
      const button = el("button", "chip", preset.label);
      button.type = "button";
      button.disabled = !presetAllowed(preset);
      if (button.disabled) button.title = bench.config.backend === "ENERGYPLUS" && preset.type === "CO2" ? "The EnergyPlus backend does not model CO2" : "Not available in this environment";
      button.addEventListener("click", () => addEvent(preset));
      host.append(button);
    }
  }
  function pruneEvents() { bench.events = bench.events.filter((event) => presetAllowed({ type: event.type })); }
  function addEvent(preset) {
    const remaining = Math.max(1, Math.floor((endMs() - branchMs()) / HOUR));
    bench.events.push({ id: `${preset.id}-${bench.events.length + 1}-${bench.serial}`, type: preset.type, startHours: 0, hours: Math.min(preset.hours, remaining), intensity: preset.intensity ?? 0, ramp: preset.ramp || 0 });
    renderEvents(); drawTicks(); redrawCharts(); changed();
  }
  function renderEvents() {
    const host = $("#events");
    host.replaceChildren();
    bench.events.forEach((event, index) => {
      const spec = specFor(event.type);
      const hasIntensity = spec && spec.maximum !== null && spec.maximum !== undefined && !(spec.minimum === 0 && spec.maximum === 0);
      const item = el("li", "event");
      const remaining = Math.max(1, Math.floor((endMs() - branchMs()) / HOUR));
      const invalid = event.startHours + event.hours > remaining || (hasIntensity && (event.intensity < spec.minimum || event.intensity > spec.maximum || (spec.minimum_exclusive && event.intensity <= spec.minimum)));
      item.dataset.invalid = String(Boolean(invalid));
      const head = el("header");
      head.append(el("span", "", `${label(event.type.toLowerCase()).replace(/\b\w/g, (c) => c.toUpperCase())}`));
      const remove = el("button", "", "Remove");
      remove.type = "button";
      remove.addEventListener("click", () => { bench.events.splice(index, 1); renderEvents(); drawTicks(); redrawCharts(); changed(); });
      head.append(remove);
      item.append(head);
      const grid = el("div", "grid2");
      const field = (name, key, min, max, step, enabled = true) => {
        const wrap = el("label", "", name), input = el("input");
        input.type = "number"; input.min = String(min); input.step = String(step); if (max !== null) input.max = String(max);
        input.value = String(event[key]); input.disabled = !enabled;
        input.addEventListener("change", () => { event[key] = Number(input.value); renderEvents(); drawTicks(); redrawCharts(); changed(); });
        wrap.append(input); grid.append(wrap);
      };
      field("Starts (h after branch)", "startHours", 0, remaining - 1, 1);
      field("Duration (h)", "hours", 1, remaining, 1);
      if (hasIntensity) field(`Intensity (${INTENSITY_UNITS[event.type] || "value"})`, "intensity", spec.minimum, spec.maximum, spec.maximum <= 1 ? 0.05 : 0.5);
      if (spec && spec.ramp_supported) field("Ramp (h)", "ramp", 0, 168, 1);
      item.append(grid);
      item.append(el("div", "when", `${iso(branchMs() + event.startHours * HOUR).slice(0, 16).replace("T", " ")} → ${iso(branchMs() + (event.startHours + event.hours) * HOUR).slice(0, 16).replace("T", " ")} UTC${invalid ? " · outside the allowed range" : ""}`));
      host.append(item);
    });
  }

  // ---- running ----------------------------------------------------------------------------------------------------
  function changed() {
    save();
    if (bench.run) setStatus("Settings changed since the last run", "stale");
    if ($("#autorun").checked) { window.clearTimeout(bench.autoTimer); bench.autoTimer = window.setTimeout(() => void runExperiment(), 700); }
  }

  async function runExperiment() {
    if (bench.running) return;
    const hasInvalid = $$(".event[data-invalid=\"true\"]").length > 0;
    if (hasInvalid) { showError(new Error("Fix the highlighted events before running.")); return; }
    showError(null);
    bench.running = true;
    const serial = ++bench.serial;
    $("#run").disabled = true;
    stopPlayback();
    const started = performance.now();
    try {
      const request = buildRequest();
      let data;
      if (bench.events.length) {
        setStatus(`Running baseline and intervention (${bench.config.backend === "ENERGYPLUS" ? "EnergyPlus" : "simplified"})…`, "running");
        data = adoptWhatIf(await api("/api/runtime/what-if", { method: "POST", body: JSON.stringify({ request, checkpoint_time: iso(branchMs()), events: eventDocuments() }) }));
      } else {
        setStatus("Running…", "running");
        data = await plainRun(request);
      }
      if (serial !== bench.serial) return;
      data.seconds = (performance.now() - started) / 1000;
      adopt(data);
      setStatus(`Done in ${data.seconds.toFixed(1)} s · ${data.times.length} hourly steps`, "done");
    } catch (error) {
      showError(error);
      setStatus("Run failed", "error");
    } finally {
      bench.running = false;
      $("#run").disabled = false;
    }
  }

  async function plainRun(request) {
    let response = await api("/api/simulations", { method: "POST", body: JSON.stringify(request) });
    response = await api(`/api/simulations/${encodeURIComponent(response.simulation_id)}/start`, { method: "POST", body: "{}" });
    while (["CREATED", "RUNNING"].includes(response.execution_status)) {
      const progress = response.progress;
      if (progress && progress.total_steps) setStatus(`Running… ${progress.completed_steps}/${progress.total_steps} steps`, "running");
      await new Promise((resolve) => window.setTimeout(resolve, bench.caps.poll_interval_ms || 500));
      response = await api(`/api/simulations/${encodeURIComponent(response.simulation_id)}`);
    }
    if (response.execution_status !== "COMPLETED") { const error = new Error("The run did not complete"); error.payload = { errors: response.errors }; throw error; }
    const trajectory = response.result.trajectory;
    const series = {};
    for (const key of Object.keys(trajectory)) if (key !== "time") series[key] = trajectory[key];
    return { kind: "RUN", times: trajectory.time, series: { baseline: series, intervention: series }, variables: response.result.variables, events: [], branchIndex: 0,
      environment: request.environment, backend: bench.config.backend, hashes: response.hashes, diagnostics: response.diagnostics, scientific: response.scientific_status, comparison: null };
  }

  function adoptWhatIf(result) {
    const prefix = result.prefix.result.trajectory, merged = {};
    for (const name of ["baseline", "intervention"]) {
      const branch = result.branches[name].response.result.trajectory;
      const last = prefix.time[prefix.time.length - 1];
      const keep = branch.time.map((time, index) => (time > last ? index : -1)).filter((index) => index >= 0);
      const series = {};
      for (const key of Object.keys(branch)) if (key !== "time") series[key] = (prefix[key] || []).concat(keep.map((index) => branch[key][index]));
      merged[name] = series;
      merged.time = prefix.time.concat(keep.map((index) => branch.time[index]));
    }
    const times = merged.time;
    return { kind: "WHAT_IF", times, series: { baseline: merged.baseline, intervention: merged.intervention }, variables: result.branches.baseline.response.result.variables,
      events: result.events, branchIndex: Math.max(0, times.findIndex((time) => time >= result.branch_point.simulation_time)), environment: bench.config.environment, backend: bench.config.backend,
      hashes: result.hashes, diagnostics: result.branches.intervention.response.diagnostics, scientific: result.scientific_status, comparison: result.comparison, statement: result.statement };
  }

  function adopt(data) {
    bench.run = data;
    const catalogue = V.catalogue(data.variables);
    bench.ctx = {};
    for (const name of ["baseline", "intervention"]) {
      bench.ctx[name] = V.buildContext({ series: data.series[name], catalogue, times: data.times, events: data.events, environment: data.environment, branch: name });
    }
    bench.position = data.kind === "WHAT_IF" ? data.branchIndex : 0;
    $("#empty").hidden = true;
    for (const id of ["scenes", "transport", "charts", "delta", "info"]) $(`#${id}`).hidden = false;
    const compare = data.kind === "WHAT_IF";
    $("#card-intervention").hidden = !compare;
    $("#title-baseline").textContent = compare ? "Baseline" : "Run";
    const slider = $("#slider");
    slider.max = String(data.times.length - 1);
    slider.value = String(Math.floor(bench.position));
    configureScenes();
    buildChartPicks();
    buildCharts();
    drawTicks();
    renderDelta();
    renderInfo();
    renderFrame(true);
  }

  // ---- scenes -----------------------------------------------------------------------------------------------------
  function sceneLayout() {
    if (bench.run.environment !== "greenhouse") return { layout: null };
    const c = bench.config.layout, entry = bench.catalogue.typologies[c.typology].profiles[`${c.span}|${c.rise}`];
    if (!entry) return null;
    return { layout: { span: c.span, spans: c.spans, bays: c.bays, pillar: c.pillar, gutter: c.gutter, profile: entry.profile } };
  }
  function configureScenes() {
    if (!bench.run) return;
    const description = sceneLayout();
    if (!description) { showError(new Error("No pre-built profile for this layout combination")); return; }
    const field = bench.catalogue.open_field;
    const options = { view: bench.config.view, cropKind: S.silhouetteFor(bench.config.crop), compact: window.innerWidth < 520, hud: false,
      field: { width: field.width, length: field.length, rowSpacing: field.row_spacing, plantSpacing: field.plant_spacing } };
    for (const name of ["baseline", "intervention"]) {
      if (!bench.scenes[name]) bench.scenes[name] = window.IsoScene.create($(`#svg-${name}`));
      bench.scenes[name].configure(description.layout, options);
    }
    $("#chip-baseline").textContent = chipText();
    $("#chip-intervention").textContent = chipText();
  }
  function chipText() {
    if (bench.run.environment !== "greenhouse") return "open field · no thermal backend";
    const c = bench.config.layout;
    return `${c.typology.replace(/_/g, " ").toLowerCase()} · ${bench.run.backend === "ENERGYPLUS" ? "EnergyPlus" : "simplified model"}`;
  }

  function renderFrame(force) {
    if (!bench.run) return;
    const run = bench.run, position = clamp(bench.position, 0, run.times.length - 1);
    const names = run.kind === "WHAT_IF" ? ["baseline", "intervention"] : ["baseline"];
    for (const name of names) {
      const ctx = bench.ctx[name];
      const visual = V.buildVisualState(ctx, position);
      const state = S.fromVisual(visual, ctx, position);
      bench.scenes[name].update(state, bench.config.layers);
      if (force || bench.lastReadoutTick) renderReadout(name, state, visual);
    }
    bench.lastReadoutTick = false;
    const index = Math.floor(position);
    $("#slider").value = String(index);
    $("#clock").textContent = `${run.times[index].slice(0, 16).replace("T", " ")} UTC${index === run.branchIndex && run.kind === "WHAT_IF" ? " · branch" : ""}`;
    moveCursors();
  }

  function renderReadout(name, state, visual) {
    const host = $(`#read-${name}`);
    host.replaceChildren();
    const row = (title, value, unit) => { const wrap = el("div"); wrap.append(el("dt", "", title)); const dd = el("dd", isNumber(value) ? "" : "na", isNumber(value) ? `${fmt(value)}${unit ? ` ${unit}` : ""}` : "n/a"); wrap.append(dd); host.append(wrap); };
    if (state.events.length) { const banner = el("div", "banner"); banner.append(el("dt", "", `EVENT ACTIVE: ${state.events.join(", ")}`)); host.append(banner); }
    row("Outdoor T", state.outdoor.temp_c, "°C");
    if (state.indoor) {
      row("Indoor T", state.indoor.temp_c, "°C"); row("Indoor RH", state.indoor.rh_pct, "%"); row("VPD", state.indoor.vpd_kpa, "kPa");
      row("CO2", state.indoor.co2_ppm, "ppm"); row("Vents", state.actuators.vent_opening === null ? null : state.actuators.vent_opening * 100, "%");
      row("Shade", state.actuators.screen_deployed === null ? null : state.actuators.screen_deployed * 100, "%"); row("Heating", state.actuators.heating_kw, "kW");
    } else { row("Humidity", state.outdoor.rh_pct, "%"); row("Radiation", state.outdoor.radiation_w_m2, "W/m²"); row("Rain", state.outdoor.rain_mm_h, "mm/h"); }
    row("LAI", state.crop.lai, ""); row("Water stress", state.crop.water_stress, ""); row("Heat stress", state.crop.heat_stress, "");
    row("Stage", null, ""); host.lastChild.lastChild.textContent = state.stage || "n/a";
  }

  // ---- charts -------------------------------------------------------------------------------------------------------
  function availableNumeric() {
    return bench.run.variables.filter((item) => item.availability === "AVAILABLE" && bench.run.series.baseline[item.name] && typeof bench.run.series.baseline[item.name][0] === "number").map((item) => item.name);
  }
  function buildChartPicks() {
    const host = $("#chart-picks"), names = availableNumeric();
    bench.config.charts = bench.config.charts.filter((name) => names.includes(name));
    if (!bench.config.charts.length) bench.config.charts = CHART_DEFAULT.filter((name) => names.includes(name)).slice(0, 4);
    host.replaceChildren();
    for (const name of names) {
      const chip = el("button", "chip", label(name));
      chip.type = "button";
      chip.setAttribute("aria-pressed", String(bench.config.charts.includes(name)));
      chip.addEventListener("click", () => {
        const at = bench.config.charts.indexOf(name);
        if (at >= 0) bench.config.charts.splice(at, 1); else bench.config.charts.push(name);
        chip.setAttribute("aria-pressed", String(at < 0)); buildCharts(); save();
      });
      host.append(chip);
    }
    const layers = $("#layers");
    layers.replaceChildren();
    for (const [key, text] of LAYERS) {
      const chip = el("button", "chip", text);
      chip.type = "button";
      chip.setAttribute("aria-pressed", String(bench.config.layers[key]));
      chip.addEventListener("click", () => { bench.config.layers[key] = !bench.config.layers[key]; chip.setAttribute("aria-pressed", String(bench.config.layers[key])); renderFrame(true); save(); });
      layers.append(chip);
    }
  }

  function buildCharts() {
    for (const chart of bench.charts) chart.plot.destroy();
    bench.charts = [];
    const host = $("#charts");
    host.replaceChildren();
    if (!bench.run) return;
    const run = bench.run, seconds = run.times.map((time) => Date.parse(time) / 1000), compare = run.kind === "WHAT_IF";
    for (const name of bench.config.charts) {
      const info = run.variables.find((item) => item.name === name);
      const card = el("div", "chart-card"), head = el("header");
      head.append(el("strong", "", `${label(name)}${info && info.unit ? ` (${info.unit})` : ""}`));
      const value = el("span"); head.append(value);
      const body = el("div", "chart-body"), cursor = el("div", "cursor-line");
      card.append(head, body); host.append(card);
      const width = Math.max(260, body.getBoundingClientRect().width || 380);
      const data = [seconds, run.series.baseline[name]];
      const series = [{}, { label: compare ? "baseline" : "run", stroke: "#4d6a8a", width: 1.6 }];
      if (compare) { data.push(run.series.intervention[name]); series.push({ label: "intervention", stroke: "#c0561d", width: 1.6, dash: [6, 4] }); }
      const plot = new window.uPlot({
        width, height: 160, legend: { show: false }, series, scales: { x: { time: true } }, cursor: { drag: { x: false, y: false } },
        axes: [{ stroke: "#5d6f68", grid: { stroke: "#e8eeea" } }, { stroke: "#5d6f68", size: 54, grid: { stroke: "#e8eeea" } }],
        hooks: { drawClear: [(u) => drawBands(u)] },
      }, data, body);
      body.append(cursor);
      plot.over.addEventListener("click", (event) => {
        const bounds = plot.over.getBoundingClientRect(), time = plot.posToVal(event.clientX - bounds.left, "x");
        stopPlayback(); seek(nearestIndex(seconds, time));
      });
      bench.charts.push({ name, plot, cursor, value, seconds, card });
    }
    redrawCharts();
  }
  function nearestIndex(seconds, time) {
    let low = 0, high = seconds.length - 1;
    while (low < high) { const middle = (low + high) >> 1; if (seconds[middle] < time) low = middle + 1; else high = middle; }
    return low;
  }
  function drawBands(u) {
    if (!bench.run) return;
    const ctx = u.ctx, area = u.bbox;
    const bands = bench.run.events.map((event) => ({ from: Date.parse(event.start_simulation_time) / 1000, to: Date.parse(event.end_simulation_time) / 1000, draft: false }))
      .concat(bench.run.kind === "WHAT_IF" ? [] : bench.events.map((event) => ({ from: (branchMs() + event.startHours * HOUR) / 1000, to: (branchMs() + (event.startHours + event.hours) * HOUR) / 1000, draft: true })));
    ctx.save();
    for (const band of bands) {
      const x0 = u.valToPos(band.from, "x", true), x1 = u.valToPos(band.to, "x", true);
      ctx.fillStyle = band.draft ? "rgba(120,120,120,.18)" : "rgba(192,86,29,.16)";
      ctx.fillRect(x0, area.top, Math.max(2, x1 - x0), area.height);
    }
    if (bench.run.kind === "WHAT_IF") {
      const x = u.valToPos(Date.parse(bench.run.times[bench.run.branchIndex]) / 1000, "x", true);
      ctx.strokeStyle = "rgba(23,53,45,.7)"; ctx.setLineDash([5, 4]); ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(x, area.top); ctx.lineTo(x, area.top + area.height); ctx.stroke();
    }
    ctx.restore();
  }
  function redrawCharts() { for (const chart of bench.charts) chart.plot.redraw(false); }
  function moveCursors() {
    if (!bench.run) return;
    const index = Math.floor(bench.position);
    for (const chart of bench.charts) {
      const x = chart.plot.valToPos(chart.seconds[index], "x"), over = chart.plot.over.getBoundingClientRect(), box = chart.cursor.parentNode.getBoundingClientRect();
      chart.cursor.style.left = `${(over.left - box.left + x).toFixed(1)}px`;
      chart.cursor.style.top = `${(over.top - box.top).toFixed(1)}px`;
      chart.cursor.style.height = `${over.height.toFixed(1)}px`;
      const base = bench.run.series.baseline[chart.name][index], inter = bench.run.series.intervention[chart.name][index];
      chart.value.textContent = bench.run.kind === "WHAT_IF" ? `${fmt(base)} | ${fmt(inter)}` : fmt(base);
    }
  }
  window.addEventListener("resize", () => { for (const chart of bench.charts) chart.plot.setSize({ width: Math.max(260, chart.card.querySelector(".chart-body").getBoundingClientRect().width), height: 160 }); moveCursors(); });

  // ---- comparison table and info -----------------------------------------------------------------------------------------
  function summarize(values, from) {
    const slice = values.slice(from).filter(isNumber);
    if (!slice.length) return null;
    return { peak: Math.max(...slice), mean: slice.reduce((a, b) => a + b, 0) / slice.length, final: slice[slice.length - 1] };
  }
  function renderDelta() {
    const host = $("#delta"), run = bench.run;
    host.replaceChildren();
    if (run.kind !== "WHAT_IF") { host.hidden = true; return; }
    host.hidden = false;
    const table = el("table"), head = el("thead"), headRow = el("tr");
    for (const text of ["From the branch point on", "Peak base", "Peak interv.", "Δ peak", "Mean base", "Mean interv.", "Δ mean", "Final base", "Final interv.", "Δ final"]) headRow.append(el("th", "", text));
    head.append(headRow); table.append(head);
    const body = el("tbody");
    for (const name of bench.config.charts) {
      const a = summarize(run.series.baseline[name], run.branchIndex), b = summarize(run.series.intervention[name], run.branchIndex);
      if (!a || !b) continue;
      const row = el("tr"); row.append(el("td", "", label(name)));
      for (const key of ["peak", "mean", "final"]) {
        row.append(el("td", "", fmt(a[key])), el("td", "", fmt(b[key])));
        const delta = b[key] - a[key], cell = el("td", delta > 1e-9 ? "up" : delta < -1e-9 ? "down" : "", `${delta > 0 ? "+" : ""}${fmt(delta)}`);
        row.append(cell);
      }
      body.append(row);
    }
    table.append(body);
    const note = el("p", "hint", "Plain statistics of the returned series; they describe two simulated scenarios, not a causal or validated effect. " + (run.comparison ? `Changed variables: ${run.comparison.variables_changed.length}.` : ""));
    host.append(table, note);
  }
  function renderInfo() {
    const run = bench.run, body = $("#info-body");
    body.replaceChildren();
    const diag = run.diagnostics && run.diagnostics.greenhouse_backend;
    const lines = [
      `Backend: ${run.backend === "ENERGYPLUS" && diag && typeof diag === "object" ? `EnergyPlus ${diag.energyplus_version} (${diag.classification})` : run.environment === "greenhouse" ? "simplified greenhouse model" : "open field (no thermal backend)"}`,
      `Run time: ${run.seconds.toFixed(2)} s on this machine (operational, not part of any hash)`,
      `Trajectory hash: ${run.hashes.trajectory_hash || run.hashes.intervention_trajectory_hash || "not computed (disabled for speed)"}`,
      "Scientific status: no real agricultural data verified, no calibration, no validation; weather and events are synthetic forcing.",
    ];
    if (diag && typeof diag === "object") lines.push(`EnergyPlus limits: ${diag.feedback}; CO2 ${diag.co2}.`);
    for (const line of lines) body.append(el("p", "", line));
  }

  // ---- time -------------------------------------------------------------------------------------------------------------
  function drawTicks() {
    const host = $("#ticks");
    host.replaceChildren();
    if (!bench.run) return;
    const n = bench.run.times.length - 1 || 1;
    const percent = (index) => `${(100 * clamp(index, 0, n)) / n}%`;
    if (bench.run.kind === "WHAT_IF") { const tick = el("div", "tick"); tick.style.left = percent(bench.run.branchIndex); tick.title = "Branch point"; host.append(tick); }
    for (const event of bench.run.events) {
      const a = bench.run.times.findIndex((time) => time >= event.start_simulation_time), b = bench.run.times.findIndex((time) => time >= event.end_simulation_time);
      const tick = el("div", "tick event"); tick.style.left = percent(a); tick.style.width = `${Math.max(0.6, (100 * (((b < 0 ? n : b) - a))) / n)}%`; tick.title = event.event_type; host.append(tick);
    }
  }
  function seek(position) {
    bench.position = clamp(position, 0, bench.run.times.length - 1);
    bench.lastReadoutTick = true;
    renderFrame(true);
  }
  function stopPlayback() { bench.playing = false; const button = $("#play"); button.textContent = "▶ Play"; button.setAttribute("aria-pressed", "false"); }
  function togglePlay() {
    if (!bench.run) return;
    if (bench.playing) { stopPlayback(); return; }
    if (bench.position >= bench.run.times.length - 1) bench.position = bench.run.kind === "WHAT_IF" ? bench.run.branchIndex : 0;
    bench.playing = true; bench.lastFrame = performance.now(); bench.lastReadout = bench.lastFrame;
    const button = $("#play"); button.textContent = "⏸ Pause"; button.setAttribute("aria-pressed", "true");
    window.requestAnimationFrame(frame);
  }
  function frame(timestamp) {
    if (!bench.playing) return;
    const step = V.advance(bench.position, Math.min(timestamp - bench.lastFrame, 250) / 1000, bench.speed, bench.run.times.length - 1);
    bench.lastFrame = timestamp; bench.position = step.position;
    if (timestamp - bench.lastReadout > 200) { bench.lastReadout = timestamp; bench.lastReadoutTick = true; }
    renderFrame(false);
    if (step.finished) { stopPlayback(); renderFrame(true); return; }
    window.requestAnimationFrame(frame);
  }
  function bindTransport() {
    setOptions($("#speed"), SPEEDS.map((value) => [value, value === 1 ? "1 h/s" : value % 24 === 0 ? `${value / 24} d/s` : `${value} h/s`]), bench.speed);
    $("#speed").addEventListener("change", () => { bench.speed = Number($("#speed").value); save(); });
    $("#play").addEventListener("click", togglePlay);
    $("#restart").addEventListener("click", () => { stopPlayback(); seek(0); });
    $("#back").addEventListener("click", () => { stopPlayback(); seek(Math.floor(bench.position) - 1); });
    $("#forward").addEventListener("click", () => { stopPlayback(); seek(Math.floor(bench.position) + 1); });
    $("#slider").addEventListener("input", (event) => { stopPlayback(); seek(Number(event.target.value)); });
    $("#to-branch").addEventListener("click", () => { stopPlayback(); seek(bench.run.branchIndex); });
    $("#to-event").addEventListener("click", () => {
      if (!bench.run.events.length) return;
      stopPlayback();
      const starts = bench.run.events.map((event) => bench.run.times.findIndex((time) => time >= event.start_simulation_time));
      const next = starts.find((index) => index > bench.position);
      seek(next === undefined ? starts[0] : next);
    });
    document.addEventListener("keydown", (event) => {
      if (event.ctrlKey && event.key === "Enter") { event.preventDefault(); void runExperiment(); return; }
      const tag = event.target.tagName;
      if (!bench.run || ["INPUT", "SELECT", "TEXTAREA"].includes(tag) || (event.key === " " && tag === "BUTTON")) return;
      if (event.key === " ") togglePlay();
      else if (event.key === "ArrowRight") { stopPlayback(); seek(Math.floor(bench.position) + 1); } else if (event.key === "ArrowLeft") { stopPlayback(); seek(Math.floor(bench.position) - 1); }
      else if (event.key === "Home") { stopPlayback(); seek(0); } else if (event.key === "End") { stopPlayback(); seek(bench.run.times.length - 1); } else return;
      event.preventDefault();
    });
  }

  // ---- start ------------------------------------------------------------------------------------------------------------
  async function init() {
    try {
      const [caps, catalogue] = await Promise.all([api("/api/capabilities"), api("/api/greenhouse/catalogue")]);
      bench.caps = caps; bench.catalogue = catalogue;
      restore();
      if (!caps.crops.includes(bench.config.crop)) bench.config.crop = caps.crops[0];
      buildSetup(); initLayout(); renderBackend(); renderPresets(); renderEvents(); bindTransport();
      $("#autorun").checked = false;
      $("#run").disabled = false;
      window.__bench = bench;  // handle for scripted checks
      setStatus("Ready", "ready");
      void runExperiment();
    } catch (error) {
      showError(error);
      setStatus("Could not load the API", "error");
    }
  }
  init();
})();
