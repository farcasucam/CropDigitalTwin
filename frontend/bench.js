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
  const MIN_AT_HOURS = 24;  // the what-if checkpoint needs at least one simulated day of history
  const CALM_SPEED = 24;    // from this speed on a day/night cycle is faster than the eye can follow: the sky stays steady
  const STORAGE_KEY = "agri-twin-bench-v1";
  const LAYERS = [["crop", "Crop"], ["soil", "Soil"], ["water", "Water"], ["temperature", "Temperature tint"], ["radiation", "Sun"], ["vpd", "VPD haze"], ["co2", "CO2"], ["events", "Events"]];
  const CHART_DEFAULT = ["temperature_c", "relative_humidity_pct", "greenhouse_ventilation_fraction", "heat_stress", "biomass_total_g_m2"];
  const LABELS = {
    temperature_c: "Crop air temperature", outdoor_temperature_c: "Outdoor temperature", relative_humidity_pct: "Relative humidity", vpd_kpa: "Vapour pressure deficit",
    radiation_w_m2: "Radiation at the crop", co2_ppm: "CO2", leaf_area_index: "Leaf area index", biomass_total_g_m2: "Total biomass", biomass_fruit_g_m2: "Fruit biomass",
    water_stress: "Water stress", heat_stress: "Heat stress", cold_stress: "Cold stress", vpd_stress: "VPD stress", accumulated_stress: "Accumulated stress",
    soil_water_vwc_m3_m3: "Soil water content", greenhouse_ventilation_fraction: "Vent opening", greenhouse_shading_fraction: "Shade screen",
    greenhouse_heating_kw: "Heating power", greenhouse_cooling_kw: "Cooling power", control_vent_opening: "Vent opening (command)", control_extractor_level: "Extractor speed (command)",
    control_electric_kw: "Electric power (estimate)", control_energy_kwh: "Energy per step (estimate)", control_energy_kwh_cumulative: "Energy, cumulative (estimate)", control_cost: "Energy cost per step (estimate)", control_cost_cumulative: "Energy cost, cumulative (estimate)", transpiration_mm: "Transpiration", irrigation_mm: "Irrigation", precipitation_mm: "Precipitation",
    nutrient_available_kg_ha: "Available nutrient pool", nutrient_applied_kg_ha: "Fertiliser offered (per step)", nutrient_extracted_kg_ha: "Nutrient uptake (per step)", nutrient_leached_kg_ha: "Nutrient leached (per step)", nutrient_status: "Nutrient status (pool / reserve)",
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
    { id: "fertilise", label: "Fertilise 20 kg/ha in total (demo value)", type: "FERTILIZATION", intensity: 20, hours: 24 },
    { id: "vents", label: "Vents fully open", type: "VENTILATION", intensity: 1, hours: 48 },
    { id: "shade", label: "Shade screen 60 %", type: "SHADING", intensity: 0.6, hours: 72 },
    { id: "co2", label: "CO2 boost", type: "CO2", intensity: 0.8, hours: 48 },
  ];
  // Events that belong together: one click adds all of them at the same start, each still editable on its own.
  const BUNDLES = [
    { id: "storm", label: "Storm: rain + overcast + cooling", parts: ["rain", "sundown", "cold_small"] },
    { id: "hotdry", label: "Hot, dry and sunny", parts: ["heat", "dry", "sunup"] },
  ];
  const BUNDLE_PARTS = { cold_small: { id: "cold_small", label: "Cooling −3 °C", type: "COLD_WAVE", intensity: 3, hours: 48, ramp: 6 } };

  const INTENSITY_UNITS = { HEAT_WAVE: "°C added", COLD_WAVE: "°C removed", RAIN: "mm/h", HIGH_RADIATION: "× radiation", LOW_RADIATION: "× radiation", WIND: "× wind",
    IRRIGATION: "mm per step", FERTILIZATION: "kg/ha in total, added to the pool", VENTILATION: "fraction of max", SHADING: "fraction of max", CO2: "fraction of max" };

  const bench = {
    caps: null, catalogue: null,
    config: { crop: "tomato", environment: "greenhouse", scenario: "BASE_SEASON", horizon: "month", backend: "SIMPLIFIED", layout: null, view: "ISOMETRIC", weatherSource: "SYNTHETIC_SEASONAL", plantingDate: null,
      control: { actuators: { shade: "OFF", vents: "OFF", extractors: "OFF", cooling: "OFF", heating: "OFF", irrigation: "OFF" }, equipment: {}, schedules: [] }, controlCharts: false,
      layers: { crop: true, soil: true, water: true, temperature: true, radiation: true, vpd: false, co2: false, events: true }, charts: CHART_DEFAULT.slice() },
    events: [], run: null, serial: 0, running: false, position: 0, playing: false, speed: 24, lastFrame: 0, lastReadout: 0,
    scenes: {}, charts: [], autoTimer: null, observers: [],
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
      const control = (saved.config || {}).control;
      if (control) bench.config.control = { actuators: { ...bench.config.control.actuators, ...(control.actuators || {}) }, equipment: control.equipment || {}, schedules: Array.isArray(control.schedules) ? control.schedules : [] };
      if (Array.isArray(saved.events)) bench.events = saved.events.filter((event) => isNumber(event.atHours));  // events saved before per-event dates are dropped
      if (SPEEDS.includes(saved.speed)) bench.speed = saved.speed;
    } catch { /* ignore corrupt storage */ }
  }

  // ---- derived configuration ---------------------------------------------------------------------------------
  const defaults = () => bench.caps.crop_defaults[bench.config.crop];
  // Real weather (local archive): the planting date is the user's; the synthetic cycle has a fixed one.
  const archive = () => ((bench.caps.weather_datasets || { crops: {} }).crops || {})[bench.config.crop];
  const localMode = () => bench.config.weatherSource === "LOCAL_ARCHIVE" && Boolean(archive() && archive().available && bench.config.plantingDate);
  const startMs = () => (localMode() ? Date.parse(`${bench.config.plantingDate}T00:00:00Z`) : Date.parse(defaults().start_time));
  function endMs() {
    const start = startMs();
    let cropEnd = Date.parse(defaults().end_time);
    if (localMode()) cropEnd = Math.min(start + archive().cycle_days * DAY, Date.parse(archive().last));  // the crop's cycle, or the downloaded years if they end first
    const days = { week: 7, month: 30, season: Infinity }[bench.config.horizon];
    return Math.min(cropEnd, start + days * DAY);
  }
  const horizonDays = () => Math.floor((endMs() - startMs()) / DAY);
  const horizonHours = () => Math.floor((endMs() - startMs()) / HOUR);
  // Every event owns its absolute start (hours since the cycle start). The fork point is the earliest event, never a shared slider.
  const branchHours = () => Math.max(MIN_AT_HOURS, bench.events.length ? Math.min(...bench.events.map((event) => event.atHours)) : MIN_AT_HOURS);
  const branchMs = () => startMs() + branchHours() * HOUR;
  const eventStartMs = (event) => startMs() + event.atHours * HOUR;
  const stamp = (ms) => iso(ms).slice(0, 16).replace("T", " ");
  const specFor = (type) => bench.caps.runtime.supported.find((item) => item.event_type === type);
  const backendInfo = (id) => bench.caps.greenhouse_backends.find((item) => item.id === id);

  function buildRequest() {
    const request = { crop: bench.config.crop, environment: bench.config.environment, scenario: bench.config.scenario, end_time: iso(endMs()),
      options: { include_trajectory: true, compute_trajectory_hash: false } };
    if (localMode()) request.weather = { source: "LOCAL_ARCHIVE", campaign_start: iso(startMs()) };
    if (bench.config.environment === "greenhouse") {
      const c = bench.config.layout;
      request.greenhouse = { backend: bench.config.backend, layout: { typology: c.typology, span_m: c.span, ridge_rise_m: c.rise, gutter_height_m: c.gutter, pillar_spacing_m: c.pillar, n_spans: c.spans, n_bays: c.bays } };
      const hvac = bench.config.hvac || {};
      if (bench.config.backend === "SIMPLIFIED" && bench.config.cropExchange) request.greenhouse.crop_exchange = true;
      if (bench.config.backend === "ENERGYPLUS" && isNumber(hvac.setpoint) && isNumber(hvac.capacity)) request.greenhouse.hvac = { cooling_setpoint_c: hvac.setpoint, cooling_capacity_w_m2: hvac.capacity };
    }
    const control = controlDocument();
    if (control) request.control = control;
    if (bench.config.et0Method === "PENMAN_MONTEITH_FAO56") {
      request.model_options = { et0_method: bench.config.et0Method };
      if (bench.config.environment === "greenhouse" && isNumber(bench.config.indoorWind) && bench.config.indoorWind > 0) request.model_options.indoor_wind_m_s = bench.config.indoorWind;
    }
    if (bench.config.co2Response === "LOG_RELATIVE_GAIN") {
      request.model_options = { ...(request.model_options || {}), co2_response: bench.config.co2Response };
      if (isNumber(bench.config.co2Gain)) request.model_options.co2_gain_per_doubling = bench.config.co2Gain;
    }
    return request;
  }
  function eventDocuments() {
    return bench.events.map((event) => {
      const document = { event_type: event.type, start_simulation_time: iso(eventStartMs(event)), duration_hours: event.hours };
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
    $("#crop").addEventListener("change", () => { bench.config.crop = $("#crop").value; refreshEnvironment(); ensurePlanting(); fitBranch(); renderWeather(); renderControl(); changed(); });
    $("#planting-date").addEventListener("change", () => { bench.config.plantingDate = $("#planting-date").value; ensurePlanting(); fitBranch(); renderWeather(); changed(); });
    $("#planting-year").addEventListener("change", () => { bench.config.plantingDate = `${$("#planting-year").value}-${archive().cycle_start_month_day}`; fitBranch(); renderWeather(); changed(); });
    renderWeather();
    $("#environment").addEventListener("change", () => { bench.config.environment = $("#environment").value; syncGreenhouseGroup(); pruneEvents(); renderEvents(); renderPresets(); renderControl(); changed(); });
    $("#scenario").addEventListener("change", () => { bench.config.scenario = $("#scenario").value; changed(); });
    $$("[data-horizon]").forEach((button) => button.addEventListener("click", () => { bench.config.horizon = button.dataset.horizon; fitBranch(); changed(); }));
    $$("[data-view]").forEach((button) => button.addEventListener("click", () => { bench.config.view = button.dataset.view; syncPressed("[data-view]", "view"); configureScenes(); renderFrame(true); save(); }));
    $("#run").addEventListener("click", () => void runExperiment());
    $("#autorun").addEventListener("change", save);
    fitBranch();
    syncPressed("[data-horizon]", "horizon");
    syncPressed("[data-view]", "view");
    $("#timeline").addEventListener("pointerdown", onTimelinePointer);
    $("#timeline").addEventListener("pointermove", (pointer) => {
      const bar = pointer.target.closest && pointer.target.closest(".tl-bar");
      if (bar && !pointer.buttons) showTip(bench.events[Number(bar.dataset.index)], pointer.clientX, pointer.clientY);
      else if (!pointer.buttons) hideTip();
    });
    $("#timeline").addEventListener("pointerleave", () => { if (!dragging) hideTip(); });
  }

  // ---- weather source and planting date ---------------------------------------------------------------------------
  function defaultPlanting() {
    const data = archive();
    if (!data || !data.available) return null;
    const monthDay = defaults().start_time.slice(5, 10), lastYear = Number(data.last.slice(0, 4)), firstYear = Number(data.first.slice(0, 4));
    for (let year = lastYear; year >= firstYear; year--) {
      const start = Date.parse(`${year}-${monthDay}T00:00:00Z`);
      if (start + data.cycle_days * DAY <= Date.parse(data.last) && start >= Date.parse(data.first)) return `${year}-${monthDay}`;
    }
    return `${firstYear}-${monthDay}`;
  }
  function ensurePlanting() {
    const data = archive();
    if (!data || !data.available) { if (bench.config.weatherSource === "LOCAL_ARCHIVE") bench.config.weatherSource = "SYNTHETIC_SEASONAL"; return; }
    const first = Date.parse(data.first), last = Date.parse(data.last), at = Date.parse(`${bench.config.plantingDate}T00:00:00Z`);
    const wrongDay = data.perennial && String(bench.config.plantingDate || "").slice(5, 10) !== data.cycle_start_month_day;
    if (!bench.config.plantingDate || !Number.isFinite(at) || at < first || at + DAY > last || wrongDay) bench.config.plantingDate = defaultPlanting();
  }
  function renderWeather() {
    const host = $("#weather-source"), data = archive();
    if (!host) return;
    host.replaceChildren();
    const options = [["SYNTHETIC_SEASONAL", "Synthetic cycle", true, "The crop's fixed synthetic season"], ["LOCAL_ARCHIVE", "Real weather", Boolean(data && data.available), data && data.available ? "Downloaded historical weather of the crop's growing area" : "No weather downloaded for this crop yet (see the note below)"]];
    for (const [id, text, enabled, title] of options) {
      const button = el("button", "", text);
      button.type = "button"; button.disabled = !enabled; button.title = title; button.setAttribute("aria-pressed", String(bench.config.weatherSource === id));
      button.addEventListener("click", () => { bench.config.weatherSource = id; ensurePlanting(); fitBranch(); renderWeather(); changed(); });
      host.append(button);
    }
    const local = localMode();
    if (local) loadClimate();
    $("#planting").hidden = !local;
    if (local) {
      $("#planting-date-field").hidden = data.perennial; $("#planting-year-field").hidden = !data.perennial;
      $("#planting-date").min = data.first.slice(0, 10); $("#planting-date").max = iso(Date.parse(data.last) - DAY).slice(0, 10); $("#planting-date").value = bench.config.plantingDate;
      const years = data.years.map((year) => [year, year]);
      setOptions($("#planting-year"), years, Number(bench.config.plantingDate.slice(0, 4)));
    }
    const note = $("#weather-note");
    if (!data) note.textContent = "";
    else if (!data.available) note.textContent = "No real weather is downloaded for this crop: python -m agri_twin.application.weather_datasets download --confirm-network";
    else if (local) {
      const truncated = Date.parse(`${bench.config.plantingDate}T00:00:00Z`) + data.cycle_days * DAY > Date.parse(data.last);
      note.textContent = `${data.label} (${data.latitude.toFixed(2)}, ${data.longitude.toFixed(2)}; approximate growing area). ${data.first.slice(0, 4)}–${data.last.slice(0, 4)}. `
        + `Modelled reanalysis used as forcing, not station data. A ${data.perennial ? "season" : "cycle"} lasts ${data.cycle_days} days${data.perennial ? ` and starts on ${data.cycle_start_month_day}` : ""}.${truncated ? " The data end before the cycle does: the run stops there." : ""}`;
    } else note.textContent = `Real weather is available for this crop: ${data.label}, ${data.first.slice(0, 4)}–${data.last.slice(0, 4)}.`;
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
    renderModelOptions();
    if (typeof renderResources === "function" && bench.caps) renderResources();
  }
  function syncPressed(selector, key) {
    $$(selector).forEach((button) => button.setAttribute("aria-pressed", String(button.dataset[key] === bench.config[key])));
  }
  function fitBranch() {
    const days = horizonDays(), total = horizonHours();

    for (const event of bench.events) {
      event.atHours = clamp(event.atHours, MIN_AT_HOURS, Math.max(MIN_AT_HOURS, total - 1));
      event.hours = clamp(event.hours, 1, Math.max(1, total - event.atHours));
    }
    syncPressed("[data-horizon]", "horizon");
    renderEvents(); renderTimeline();
    const start = startMs();
    $("#period").textContent = localMode()
      ? `Real weather ${iso(start).slice(0, 10)} → ${iso(endMs()).slice(0, 10)} · ${days} simulated days · reanalysis forcing, not station data`
      : `Synthetic cycle ${iso(start).slice(0, 10)} → ${iso(endMs()).slice(0, 10)} · ${days} simulated days · weather is synthetic forcing`;
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
      button.addEventListener("click", () => { bench.config.backend = info.id; pruneEvents(); renderBackend(); renderEvents(); renderPresets(); renderControl(); changed(); });
      group.append(button);
    }
    const info = backendInfo(bench.config.backend), hvac = bench.config.hvac || (bench.config.hvac = {});
    $("#backend-note").textContent = info.available ? info.note : info.reason;
    $("#hvac-box").hidden = bench.config.backend !== "ENERGYPLUS";
    $("#exchange-box").hidden = bench.config.backend !== "SIMPLIFIED";
    $("#crop-exchange").checked = Boolean(bench.config.cropExchange);
    $("#hvac-setpoint").value = isNumber(hvac.setpoint) ? String(hvac.setpoint) : "";
    $("#hvac-capacity").value = isNumber(hvac.capacity) ? String(hvac.capacity) : "";
  }
  const ET0_LABELS = { HARGREAVES_HISTORICAL: "Historical (temperature and radiation)", PENMAN_MONTEITH_FAO56: "FAO-56 Penman-Monteith (wind, humidity, pressure)" };
  function renderModelOptions() {
    const options = (bench.caps || {}).model_options, select = $("#et0-method");
    if (!options || !select) { if ($("#options-group")) $("#options-group").hidden = true; return; }
    setOptions(select, options.et0_methods.map((id) => [id, ET0_LABELS[id] || id]), bench.config.et0Method || options.default_et0_method);
    $("#indoor-wind-box").hidden = !(bench.config.et0Method === "PENMAN_MONTEITH_FAO56" && bench.config.environment === "greenhouse");
    $("#indoor-wind").value = isNumber(bench.config.indoorWind) ? String(bench.config.indoorWind) : "";
    $("#et0-note").textContent = bench.config.et0Method === "PENMAN_MONTEITH_FAO56"
      ? "FAO-56 hourly equation with the site of the weather location or plot (the local archive, or a plot with coordinates). Grass reference ET0, not calibrated; with it a WIND event changes evapotranspiration."
      : "The historical estimate has no wind, humidity or pressure term: a WIND event does not change it.";
  }
  const CO2_LABELS = { HISTORICAL_CAPPED: "Historical (no benefit above 420 ppm)", LOG_RELATIVE_GAIN: "Logarithmic gain from a cited source" };
  function renderCo2Options() {
    const options = (bench.caps || {}).model_options, select = $("#co2-response");
    if (!options || !select) return;
    setOptions(select, options.co2_responses.map((id) => [id, CO2_LABELS[id] || id]), bench.config.co2Response || options.default_co2_response);
    const log = bench.config.co2Response === "LOG_RELATIVE_GAIN";
    $("#co2-gain-box").hidden = !log;
    $("#co2-gain").value = isNumber(bench.config.co2Gain) ? String(bench.config.co2Gain) : "";
    $("#co2-note").textContent = log
      ? `Growth factor 1 at 420 ppm and +${Math.round(100 * options.co2_gain_per_doubling.default)} % at twice that, logarithmic (${options.co2_gain_per_doubling.source}). A generic C3 value, not specific to this crop and not calibrated.`
      : "Enrichment events raise the CO2 of the greenhouse but not the growth of the crop: the historical response is min(1, CO2/420).";
  }
  function bindModelOptions() {
    const select = $("#et0-method");
    if (!select) return;
    $("#co2-response").addEventListener("change", (event) => { bench.config.co2Response = event.target.value; renderCo2Options(); changed(); });
    $("#co2-gain").addEventListener("change", (event) => { bench.config.co2Gain = event.target.value === "" ? null : Number(event.target.value); changed(); });
    renderCo2Options();
    select.addEventListener("change", () => { bench.config.et0Method = select.value; renderModelOptions(); changed(); });
    $("#indoor-wind").addEventListener("change", (event) => { bench.config.indoorWind = event.target.value === "" ? null : Number(event.target.value); changed(); });
    renderModelOptions();
  }
  // ---- resources: prices and conversions, and the season results computed with them (server side, from the series of the run) ----------------------------------------
  const resources = () => { const r = bench.config.resources || (bench.config.resources = { waterFlat: null, waterYearly: [], heatingPrice: null, dryPct: {} }); r.waterYearly = r.waterYearly || []; r.dryPct = r.dryPct || {}; return r; };
  function equipmentDocument() { const out = {}; for (const [key, value] of Object.entries((bench.config.control || {}).equipment || {})) if (isNumber(value)) out[key] = value; return out; }
  function siteDocument() {
    const r = resources(), currency = tariffCurrency(), yearly = {}, crops = {};
    for (const item of r.waterYearly) if (Number.isInteger(item.year) && isNumber(item.price)) yearly[String(item.year)] = item.price;
    for (const [crop, pct] of Object.entries(r.dryPct)) if (isNumber(pct) && pct > 0) crops[crop] = { fruit_dry_matter_fraction: pct / 100 };
    const electricity = tariffDocument(); delete electricity.currency;
    return { equipment: equipmentDocument(), prices: { currency, electricity, heating_energy: isNumber(r.heatingPrice) ? { flat_per_kwh: r.heatingPrice } : null, water: { flat_per_m3: isNumber(r.waterFlat) ? r.waterFlat : null, yearly } }, crops };
  }
  function applySiteDocument(config) {
    const r = resources(), prices = config.prices || {}, water = prices.water || {};
    r.waterFlat = isNumber(water.flat_per_m3) ? water.flat_per_m3 : null;
    r.waterYearly = Object.entries(water.yearly || {}).map(([year, price]) => ({ year: Number(year), price }));
    r.heatingPrice = prices.heating_energy && isNumber(prices.heating_energy.flat_per_kwh) ? prices.heating_energy.flat_per_kwh : null;
    r.dryPct = {};
    for (const [crop, entry] of Object.entries(config.crops || {})) if (isNumber(entry.fruit_dry_matter_fraction)) r.dryPct[crop] = Math.round(entry.fruit_dry_matter_fraction * 10000) / 100;
    const t = tariff(), electricity = prices.electricity || {};
    if (prices.currency) t.currency = prices.currency;
    t.flat = isNumber(electricity.flat_per_kwh) ? electricity.flat_per_kwh : null;
    t.yearly = Object.entries(electricity.yearly || {}).map(([year, price]) => ({ year: Number(year), price }));
    t.bands = (electricity.time_of_day || []).map((b) => ({ from: b.from_hour, to: b.to_hour, mode: b.factor !== undefined ? "factor" : "price", value: b.factor !== undefined ? b.factor : b.price_per_kwh }));
    t.offset = electricity.utc_offset_hours || 0;
    const equipment = (config.equipment || {});
    for (const [key, value] of Object.entries(equipment)) if (isNumber(value)) bench.config.control.equipment[key] = value;
  }
  async function loadSiteResources(replace) {
    try {
      bench.site = await api("/api/site-resources");
      if (replace) { applySiteDocument(bench.site.configuration); renderTariff(); renderControl(); }
    } catch (error) { bench.site = null; }
    renderResources();
  }
  function renderResources() {
    const r = resources(), crop = bench.config.crop, box = $("#res-water");
    if (!box) return;
    box.value = isNumber(r.waterFlat) ? String(r.waterFlat) : "";
    $("#res-heating-price").value = isNumber(r.heatingPrice) ? String(r.heatingPrice) : "";
    $("#res-crop-label").textContent = `Dry matter of the fresh ${crop} (%)`;
    $("#res-dry").value = isNumber(r.dryPct[crop]) ? String(r.dryPct[crop]) : "";
    const host = $("#res-water-yearly");
    host.replaceChildren();
    r.waterYearly.forEach((item, index) => {
      const card = el("li", "event"), head = el("header"), remove = el("button", "", "Remove"); remove.type = "button";
      remove.addEventListener("click", () => { r.waterYearly.splice(index, 1); renderResources(); resourcesChanged(); });
      head.append(el("span", "", ""), remove); card.append(head);
      const grid = el("div", "grid2");
      for (const [text, key, props, integer] of [["Year", "year", { min: 2000, max: 2100, step: 1 }, true], [`Price (${tariffCurrency()}/m³)`, "price", { min: 0, step: "any" }, false]]) {
        const wrap = el("label", "", text), input = el("input"); input.type = "number"; Object.assign(input, props); input.value = isNumber(item[key]) ? String(item[key]) : "";
        input.addEventListener("change", () => { item[key] = input.value === "" ? null : integer ? Math.round(Number(input.value)) : Number(input.value); resourcesChanged(); });
        wrap.append(input); grid.append(wrap);
      }
      card.append(grid); host.append(card);
    });
    const defined = [r.waterFlat, r.heatingPrice, ...Object.values(r.dryPct)].filter(isNumber).length + r.waterYearly.length;
    $("#resources-summary").textContent = defined ? "defined" : "empty";
  }
  function resourcesChanged() { save(); renderResources(); if (bench.run) { bench.run.kpis = {}; renderSeason(); } }
  function bindResources() {
    const r = resources();
    $("#res-water").addEventListener("change", (event) => { r.waterFlat = event.target.value === "" ? null : Number(event.target.value); resourcesChanged(); });
    $("#res-heating-price").addEventListener("change", (event) => { r.heatingPrice = event.target.value === "" ? null : Number(event.target.value); resourcesChanged(); });
    $("#res-dry").addEventListener("change", (event) => { r.dryPct[bench.config.crop] = event.target.value === "" ? null : Number(event.target.value); resourcesChanged(); });
    $("#res-add-year").addEventListener("click", () => { r.waterYearly.push({ year: Number(iso(startMs()).slice(0, 4)) + 1, price: null }); renderResources(); });
    $("#res-load").addEventListener("click", () => loadSiteResources(true).then(resourcesChanged));
    $("#res-save").addEventListener("click", async () => {
      const note = $("#res-note");
      try { bench.site = await api("/api/site-resources", { method: "POST", body: JSON.stringify(siteDocument()) }); note.textContent = `Saved to src/site_resources.json (hash ${bench.site.content_hash.slice(0, 12)}).`; }
      catch (error) { note.textContent = `Not saved: ${error.message || error}`; }
      note.hidden = false;
    });
    loadSiteResources(!bench.config.resources);  // first visit: start from the saved site configuration
  }
  const SEASON_ROWS = [
    ["Yield", [["Fresh product (kg/m²)", (k) => k.yield.fresh_product_kg_m2, 3], ["Fresh product, unit (kg)", (k) => k.yield.fresh_product_kg, 0], ["Fresh product (t/ha)", (k) => k.yield.fresh_product_t_ha, 2], ["Fruit dry matter (g/m²)", (k) => k.yield.fruit_dry_matter_g_m2, 1]]],
    ["Water", [["Irrigation (mm)", (k) => k.water.irrigation_mm, 1], ["Irrigation, unit (m³)", (k) => k.water.irrigation_m3, 1], ["Drained share (%)", (k) => (k.water.drained_share === null ? null : k.water.drained_share * 100), 1], ["Product per m³ of irrigation (kg)", (k) => k.water.product_per_m3_irrigation_kg, 1]]],
    ["Energy", [["Input energy (kWh)", (k) => k.energy.input_kwh, 0], ["Input energy (kWh/m²)", (k) => k.energy.input_kwh_per_m2, 2], ["Energy per kg of product (kWh)", (k) => k.energy.kwh_per_kg_product, 2], ["Heating, thermal (kWh)", (k) => k.energy.heating_thermal_kwh, 0], ["Cooling, thermal (kWh)", (k) => k.energy.cooling_thermal_kwh, 0]]],
    ["Risk", [["Hours above the stage maximum", (k) => k.risk.hours_above_max_temp, 0], ["Hours below the stage minimum", (k) => k.risk.hours_below_min_temp, 0], ["Hours above critical heat", (k) => k.risk.hours_above_critical_heat, 0], ["Peak frost damage", (k) => k.risk.peak_frost_damage, 2]]],
    ["Cost of resources", [["Energy + water", (k) => k.cost.resource_cost, 0], ["Per m²", (k) => k.cost.resource_cost_per_m2, 3], ["Per kg of product", (k) => k.cost.resource_cost_per_kg_product, 3], ["Energy share (%)", (k) => (k.cost.energy_share === null ? null : k.cost.energy_share * 100), 0]]],
  ];
  async function seasonKpi(run, branch) {
    run.kpis = run.kpis || {};
    if (!run.kpis[branch]) {
      const series = run.series[branch];
      run.kpis[branch] = api("/api/kpis/season", { method: "POST", body: JSON.stringify({ crop: bench.config.crop, environment: run.environment, times: run.times, series, greenhouse: run.greenhouse || undefined, resources: siteDocument() }) });
    }
    return run.kpis[branch];
  }
  async function renderSeason() {
    const host = $("#season"), run = bench.run;
    if (!host || !run) { if (host) host.hidden = true; return; }
    const names = run.kind === "WHAT_IF" ? ["baseline", "intervention"] : ["baseline"], token = (renderSeason.token = (renderSeason.token || 0) + 1);
    let kpis;
    try { kpis = await Promise.all(names.map((name) => seasonKpi(run, name))); } catch (error) { run.kpis = {}; host.hidden = true; return; }
    if (token !== renderSeason.token || run !== bench.run) return;
    const body = $("#season-body"), compare = names.length === 2, table = el("table"), head = el("thead"), row = el("tr");
    for (const text of compare ? ["", "Baseline", "Intervention", "Δ"] : ["", "Run"]) row.append(el("th", "", text));
    head.append(row); table.append(head);
    const tbody = el("tbody");
    for (const [group, items] of SEASON_ROWS) {
      const title = el("tr"), cell = el("th", "group", group); cell.colSpan = compare ? 4 : 2; title.append(cell); tbody.append(title);
      for (const [label, getter, digits] of items) {
        const values = kpis.map((k) => { const v = getter(k); return isNumber(v) ? v : null; });
        if (values.every((v) => v === null) && group === "Energy" && label.startsWith("Heating") === false && kpis[0].energy.input_kwh === null && kpis[0].energy.heating_thermal_kwh === null) continue;
        const tr = el("tr"); tr.append(el("td", "", label));
        for (const v of values) tr.append(el("td", v === null ? "na" : "", v === null ? "n/a" : fmt(v, digits)));
        if (compare) { const delta = values[0] !== null && values[1] !== null ? values[1] - values[0] : null; tr.append(el("td", delta === null ? "na" : delta > 1e-9 ? "up" : delta < -1e-9 ? "down" : "", delta === null ? "n/a" : `${delta > 0 ? "+" : ""}${fmt(delta, digits)}`)); }
        tbody.append(tr);
      }
    }
    table.append(tbody);
    const missing = [...new Set(kpis.flatMap((k) => k.missing))], area = kpis[0].area;
    const notes = [`Per ${fmt(area.m2 || 0, 0)} m² (${area.source}).`, kpis[0].statement];
    if (kpis[0].plot_scaling) notes.push(`Scaled to the ${fmt(kpis[0].plot_scaling.plot_area_m2 / 10000, 2)} ha plot of the farm configuration: ×${fmt(kpis[0].plot_scaling.factor, 1)} (${kpis[0].plot_scaling.assumption}).`);
    if (missing.length) notes.push(`n/a until you define: ${missing.join("; ")}.`);
    body.replaceChildren(table, el("p", "season-note", notes.join(" ")));
    host.hidden = false;
  }
  function bindHvac() {
    $("#crop-exchange").addEventListener("change", (event) => { bench.config.cropExchange = event.target.checked; changed(); });
    for (const [id, key] of [["hvac-setpoint", "setpoint"], ["hvac-capacity", "capacity"]]) {
      $(`#${id}`).addEventListener("change", (event) => { (bench.config.hvac || (bench.config.hvac = {}))[key] = event.target.value === "" ? null : Number(event.target.value); changed(); });
    }
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
    const effect = bench.config.backend === "ENERGYPLUS" ? "The layout is simulated by EnergyPlus." : "The simplified model takes its floor area, volume and cover from this layout, like EnergyPlus.";
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
    for (const bundle of BUNDLES) {
      const parts = bundle.parts.map((id) => BUNDLE_PARTS[id] || PRESETS.find((preset) => preset.id === id));
      const button = el("button", "chip bundle", bundle.label);
      button.type = "button"; button.disabled = !parts.every(presetAllowed);
      button.title = button.disabled ? "Not available in this environment" : `Adds together: ${parts.map((part) => part.label).join(", ")}`;
      button.addEventListener("click", () => { parts.forEach((part) => addEvent(part, false)); eventsChanged(); });
      host.append(button);
    }
  }
  function pruneEvents() { bench.events = bench.events.filter((event) => presetAllowed({ type: event.type })); renderTimeline(); }
  function addEvent(preset, commit = true) {
    const total = horizonHours();
    // a new event starts where the playhead is (when a run is open) or a few days in, snapped to a whole day
    const head = bench.run ? Math.round((Date.parse(bench.run.times[Math.floor(bench.position)]) - startMs()) / HOUR) : Math.round(total * 0.3);
    const atHours = clamp(Math.round(head / 24) * 24, MIN_AT_HOURS, Math.max(MIN_AT_HOURS, total - 1));
    bench.events.push({ id: `${preset.id}-${bench.events.length + 1}-${bench.serial}`, type: preset.type, atHours, hours: clamp(preset.hours, 1, Math.max(1, total - atHours)), intensity: preset.intensity ?? 0, ramp: preset.ramp || 0 });
    if (commit) eventsChanged();
  }
  function eventsChanged() { renderEvents(); renderTimeline(); redrawCharts(); changed(); }
  // Plausibility of a cold or heat wave. With real weather it is judged against the climate of that date in the downloaded years: the daily mean the wave would
  // produce must stay inside the 5-95 % range seen on those dates. Without real weather it is relative to the run's OWN weather (no climatology exists):
  // a cold wave in the warmest third of the cycle, or a heat wave in its coolest third. Either way it is a hint, never a block; the cut-offs are conventions.
  bench.climate = {};
  function loadClimate() {
    const crop = bench.config.crop;
    if (!localMode() || crop in bench.climate) return;
    bench.climate[crop] = "pending";
    api(`/api/weather/climatology?crop=${encodeURIComponent(crop)}`).then((data) => { bench.climate[crop] = data; renderEvents(); renderTimeline(); }).catch(() => { bench.climate[crop] = null; });
  }
  const leapDay = (ms) => { const d = new Date(ms); return Math.round((Date.UTC(2000, d.getUTCMonth(), d.getUTCDate()) - Date.UTC(2000, 0, 1)) / DAY); };
  const runKey = () => `${bench.config.crop}|${localMode() ? "L" : "S"}|${startMs()}`;  // a run only describes the settings it was made with
  function baselineDailyMeans() {
    const series = bench.run && bench.run.configKey === runKey() && (bench.run.series.baseline.outdoor_temperature_c || bench.run.series.baseline.temperature_c);
    if (!series) return [];
    const daily = [];
    for (let day = 0; day * 24 < series.length; day++) { const chunk = series.slice(day * 24, day * 24 + 24).filter(isNumber); if (chunk.length) daily.push(chunk.reduce((a, b) => a + b, 0) / chunk.length); }
    return daily;
  }
  function plausibility(event) {
    if (!["COLD_WAVE", "HEAT_WAVE"].includes(event.type)) return null;
    const daily = baselineDailyMeans(), at = Math.floor((event.atHours + event.hours / 2) / 24);
    const climate = localMode() ? bench.climate[bench.config.crop] : null;
    if (climate && typeof climate === "object" && isNumber(event.intensity)) {
      const day = leapDay(eventStartMs(event) + (event.hours * HOUR) / 2), typical = daily.length ? daily[clamp(at, 0, daily.length - 1)] : climate.p50[day];
      const years = `${climate.years[0]}–${climate.years[climate.years.length - 1]}`;
      if (event.type === "COLD_WAVE" && typical - event.intensity < climate.p05[day]) return `Daily mean ${fmt(typical - event.intensity, 1)} °C would be below the 5 % lowest seen on this date in ${years} (${fmt(climate.p05[day], 1)} °C): unusual for the season.`;
      if (event.type === "HEAT_WAVE" && typical + event.intensity > climate.p95[day]) return `Daily mean ${fmt(typical + event.intensity, 1)} °C would be above the 5 % highest seen on this date in ${years} (${fmt(climate.p95[day], 1)} °C): unusual for the season.`;
      return null;
    }
    if (!daily.length) return null;
    const mean = daily[clamp(at, 0, daily.length - 1)], rank = daily.filter((value) => value <= mean).length / daily.length;
    if (event.type === "COLD_WAVE" && rank > 2 / 3) return `A cold wave here falls in the warmest third of this cycle (baseline ${fmt(mean, 1)} °C): unusual for the season.`;
    if (event.type === "HEAT_WAVE" && rank < 1 / 3) return `A heat wave here falls in the coolest third of this cycle (baseline ${fmt(mean, 1)} °C): unusual for the season.`;
    return null;
  }
  const eventInvalid = (event, spec, hasIntensity) => event.atHours < MIN_AT_HOURS || event.atHours + event.hours > horizonHours()
    || (hasIntensity && (event.intensity < spec.minimum || event.intensity > spec.maximum || (spec.minimum_exclusive && event.intensity <= spec.minimum)));
  function renderEvents() {
    const host = $("#events");
    host.replaceChildren();
    bench.events.forEach((event, index) => {
      const spec = specFor(event.type);
      const hasIntensity = spec && spec.maximum !== null && spec.maximum !== undefined && !(spec.minimum === 0 && spec.maximum === 0);
      const item = el("li", "event");
      const remaining = Math.max(1, horizonHours() - event.atHours);
      const invalid = eventInvalid(event, spec, hasIntensity);
      item.dataset.invalid = String(Boolean(invalid));
      const head = el("header");
      head.append(el("span", "", `${label(event.type.toLowerCase()).replace(/\b\w/g, (c) => c.toUpperCase())}`));
      const remove = el("button", "", "Remove");
      remove.type = "button";
      remove.addEventListener("click", () => { bench.events.splice(index, 1); eventsChanged(); });
      head.append(remove);
      item.append(head);
      const grid = el("div", "grid2");
      const field = (name, key, min, max, step, enabled = true) => {
        const wrap = el("label", "", name), input = el("input");
        input.type = "number"; input.min = String(min); input.step = String(step); if (max !== null) input.max = String(max);
        input.value = String(event[key]); input.disabled = !enabled;
        input.addEventListener("change", () => { event[key] = Number(input.value); eventsChanged(); });
        wrap.append(input); grid.append(wrap);
      };
      const when = el("label", "wide", "Starts (UTC)"), start = el("input");
      start.type = "datetime-local"; start.step = "3600"; start.min = iso(startMs() + MIN_AT_HOURS * HOUR).slice(0, 16); start.max = iso(endMs() - HOUR).slice(0, 16);
      start.value = iso(eventStartMs(event)).slice(0, 16);
      start.addEventListener("change", () => { const ms = Date.parse(`${start.value}:00Z`); if (Number.isFinite(ms)) { event.atHours = Math.round((ms - startMs()) / HOUR); eventsChanged(); } });
      when.append(start); grid.append(when);
      field("Duration (h)", "hours", 1, remaining, 1);
      if (hasIntensity) field(`Intensity (${INTENSITY_UNITS[event.type] || "value"})`, "intensity", spec.minimum, spec.maximum, spec.maximum <= 1 ? 0.05 : 0.5);
      if (spec && spec.ramp_supported) field("Ramp (h)", "ramp", 0, 168, 1);
      item.append(grid);
      item.append(el("div", "when", `${stamp(eventStartMs(event))} → ${stamp(eventStartMs(event) + event.hours * HOUR)} UTC${invalid ? " · outside the allowed range" : ""}`));
      const odd = plausibility(event);
      if (odd) item.append(el("div", "warn", `⚠ ${odd}`));
      host.append(item);
    });
  }

  // ---- intervention timeline ------------------------------------------------------------------------------------------
  // One bar per event on the cycle's own date axis. Drag a bar to move it, drag its edges to change the duration.
  const hueFor = (type) => Math.max(0, PRESETS.findIndex((preset) => preset.type === type)) * 33;
  function snapHours() { const days = horizonDays(); return days <= 10 ? 1 : days <= 45 ? 6 : 24; }
  function renderTimeline() {
    const axis = $("#tl-axis"), rows = $("#tl-rows");
    if (!axis || !bench.caps) return;
    const total = horizonHours(), days = horizonDays(), step = Math.max(1, Math.ceil(days / 8));
    axis.replaceChildren();
    for (let day = 0; day <= days; day += step) {
      const tick = el("span", "tl-tick", new Date(startMs() + day * DAY).toISOString().slice(5, 10));
      tick.style.left = `${(100 * day * 24) / total}%`;
      axis.append(tick);
    }
    rows.replaceChildren();
    const lock = el("div", "tl-lock"); lock.style.width = `${(100 * MIN_AT_HOURS) / total}%`; lock.title = "The first simulated day is history: events start after it";
    rows.append(lock);
    if (!bench.events.length) rows.append(el("p", "tl-empty", "No interventions yet. Add one from the list on the left, then drag its bar here."));
    const laneEnds = [], lanes = [];
    bench.events.map((event, index) => ({ event, index })).sort((a, b) => a.event.atHours - b.event.atHours).forEach(({ event, index }) => {
      let lane = laneEnds.findIndex((end) => end <= event.atHours);
      if (lane < 0) { lane = laneEnds.length; laneEnds.push(0); lanes.push(el("div", "tl-row")); rows.append(lanes[lane]); }
      laneEnds[lane] = event.atHours + Math.max(event.hours, total * 0.12);  // leave room for the name beside a narrow bar
      const row = lanes[lane], bar = el("div", "tl-bar");
      bar.append(el("span", "tl-label", label(event.type.toLowerCase()).replace(/\b\w/g, (c) => c.toUpperCase())));
      bar.dataset.index = String(index); bar.style.setProperty("--hue", String(hueFor(event.type))); bar.tabIndex = 0;
      const odd = plausibility(event);
      bar.classList.toggle("odd", Boolean(odd)); if (odd) bar.dataset.note = odd;
      const left = el("i", "tl-grip"), right = el("i", "tl-grip right");
      left.dataset.edge = "left"; right.dataset.edge = "right";
      bar.append(left, right);
      bar.addEventListener("keydown", (key) => {
        const delta = key.key === "ArrowRight" ? snapHours() : key.key === "ArrowLeft" ? -snapHours() : 0;
        if (!delta) return;
        key.preventDefault();
        if (key.shiftKey) placeEvent(event, { hours: event.hours + delta }, "resize"); else placeEvent(event, { atHours: event.atHours + delta }, "move");
        eventsChanged();
        const again = $(`.tl-bar[data-index="${index}"]`); if (again) again.focus();
      });
      row.append(bar); positionBar(bar, event);
    });
    movePlayhead();
    drawActuation();
  }
  function positionBar(bar, event) {
    const total = horizonHours();
    bar.style.left = `${(100 * event.atHours) / total}%`; bar.style.width = `${Math.max(0.8, (100 * event.hours) / total)}%`;
    bar.classList.toggle("narrow", (100 * event.hours) / total < 9);  // too short to hold its name: the name sits beside the bar
    bar.title = `${stamp(eventStartMs(event))} → ${stamp(eventStartMs(event) + event.hours * HOUR)} UTC${bar.dataset.note ? `\n⚠ ${bar.dataset.note}` : ""}`;
  }
  function placeEvent(event, next, mode) {
    const total = horizonHours();
    if (mode === "resize") event.hours = clamp(next.hours, 1, total - event.atHours);
    else event.atHours = clamp(next.atHours, MIN_AT_HOURS, Math.max(MIN_AT_HOURS, total - event.hours));
  }
  function onTimelinePointer(pointer) {
    const bar = pointer.target.closest(".tl-bar");
    if (!bar || pointer.button !== 0) return;
    const event = bench.events[Number(bar.dataset.index)], edge = pointer.target.dataset.edge || "";
    const track = $("#tl-rows").getBoundingClientRect(), total = horizonHours(), snap = snapHours();
    const origin = { x: pointer.clientX, atHours: event.atHours, hours: event.hours };
    bar.setPointerCapture(pointer.pointerId);
    pointer.preventDefault();
    dragging = true;
    const move = (now) => {
      const dh = Math.round(((now.clientX - origin.x) / track.width) * total / snap) * snap;
      if (edge === "right") placeEvent(event, { hours: origin.hours + dh }, "resize");
      else if (edge === "left") {
        const at = clamp(origin.atHours + dh, MIN_AT_HOURS, origin.atHours + origin.hours - 1);
        event.atHours = at; event.hours = origin.atHours + origin.hours - at;
      } else placeEvent(event, { atHours: origin.atHours + dh }, "move");
      positionBar(bar, event);
      showTip(event, now.clientX, now.clientY);
      scheduleBandRedraw();
    };
    const done = () => {
      bar.removeEventListener("pointermove", move); bar.removeEventListener("pointerup", done); bar.removeEventListener("pointercancel", done);
      dragging = false; hideTip(); eventsChanged();
    };
    bar.addEventListener("pointermove", move); bar.addEventListener("pointerup", done); bar.addEventListener("pointercancel", done);
    showTip(event, pointer.clientX, pointer.clientY);
  }
  // A tooltip that states what the bar represents: type, start, end and duration (shown on hover and while moving or resizing).
  let dragging = false, bandFrame = 0;
  function showTip(event, x, y) {
    const tip = $("#tl-tip");
    if (!tip) return;
    const start = eventStartMs(event), end = start + event.hours * HOUR, days = event.hours / 24;
    tip.replaceChildren(el("strong", "", label(event.type.toLowerCase()).replace(/\b\w/g, (c) => c.toUpperCase())),
      el("div", "", `Start  ${stamp(start)} UTC`), el("div", "", `End    ${stamp(end)} UTC`),
      el("div", "", `Duration  ${event.hours} h${event.hours >= 24 ? ` (${fmt(days, 1)} d)` : ""}`));
    const odd = plausibility(event);
    if (odd) tip.append(el("div", "tip-warn", `⚠ ${odd}`));
    tip.hidden = false;
    const box = tip.getBoundingClientRect();
    tip.style.left = `${clamp(x + 14, 4, window.innerWidth - box.width - 4)}px`;
    tip.style.top = `${clamp(y - box.height - 14, 4, window.innerHeight - box.height - 4)}px`;
  }
  function hideTip() { const tip = $("#tl-tip"); if (tip) tip.hidden = true; }
  function scheduleBandRedraw() {
    if (bandFrame) return;
    bandFrame = window.requestAnimationFrame(() => { bandFrame = 0; redrawCharts(); });
  }
  // scrubbing: pressing or dragging on the date axis (or the knob) moves the playhead
  function bindScrub() {
    const axis = $("#tl-axis"), knob = $("#tl-head .tl-knob");
    const toIndex = (clientX) => {
      const box = $("#tl-rows").getBoundingClientRect(), ms = startMs() + clamp((clientX - box.left) / box.width, 0, 1) * horizonHours() * HOUR;
      const t0 = Date.parse(bench.run.times[0]), step = (Date.parse(bench.run.times[1]) - t0) || HOUR;
      return clamp(Math.round((ms - t0) / step), 0, bench.run.times.length - 1);
    };
    const begin = (pointer) => {
      if (!bench.run || pointer.button !== 0) return;
      pointer.preventDefault(); stopPlayback();
      const target = pointer.currentTarget; target.setPointerCapture(pointer.pointerId);
      const move = (now) => seek(toIndex(now.clientX));
      const end = () => { target.removeEventListener("pointermove", move); target.removeEventListener("pointerup", end); target.removeEventListener("pointercancel", end); };
      target.addEventListener("pointermove", move); target.addEventListener("pointerup", end); target.addEventListener("pointercancel", end);
      move(pointer);
    };
    axis.addEventListener("pointerdown", begin);
    knob.addEventListener("pointerdown", begin);
  }
  function movePlayhead() {
    const head = $("#tl-head");
    if (!head) return;
    if (!bench.run) { head.hidden = true; return; }
    const hours = (Date.parse(bench.run.times[Math.floor(bench.position)]) - startMs()) / HOUR;
    head.hidden = false; head.style.left = `${clamp((100 * hours) / horizonHours(), 0, 100)}%`;
  }

  // ---- climate control ----------------------------------------------------------------------------------------------
  // Each actuator is OFF, AUTO (passive-first rules over the crop's stage thresholds) or SCHEDULE (daily window in a date range).
  // Equipment is the user's own site inventory: nothing is assumed, an empty field makes that actuator unavailable.
  const THRESHOLD_KEYS = {
    shade: ["optimal_max_w_m2", "photoinhibition_w_m2", "shading_reduction_pct"], vents: ["max_temp_c", "critical_heat_c"], extractors: ["max_temp_c", "critical_heat_c"],
    cooling: ["max_temp_c", "critical_heat_c"], heating: ["min_temp_c"], irrigation: ["vwc_optimal_min", "target_vwc_after_irrigation"],
  };
  // Illustrative only (not sourced) and sized to the chosen greenhouse: air-change rates as in the greenhouse models, powers per square metre of floor.
  const illustrativeEquipment = () => {
    const c = bench.config.layout, area = c ? c.span * c.spans * c.bays * c.pillar : 800;
    const round = (value) => Math.round(value * 10) / 10;
    return { vent_max_ach: 30, extractor_max_ach: 20, extractor_power_kw: round(0.03 * area), cooling_capacity_kw: round(0.45 * area), cooling_cop: 3, heating_capacity_kw: round(0.15 * area), heating_efficiency: 0.9, irrigation_max_mm_step: 3 };
  };
  const controlInfo = () => (bench.caps ? bench.caps.climate_control : undefined);  // absent when the page runs against a server started before climate control existed
  function controlAllowed(actuator) {
    if (bench.config.backend === "ENERGYPLUS" && actuator === "shade") return false;  // EnergyPlus gets shading as a scaling of the weather file fixed before the run
    return bench.config.environment === "greenhouse" || actuator === "irrigation";
  }
  function controlDocument() {
    if (!controlInfo()) return null;
    const control = bench.config.control, actuators = {};
    for (const info of controlInfo().actuators) if (controlAllowed(info.id) && control.actuators[info.id] !== "OFF") actuators[info.id] = control.actuators[info.id];
    if (!Object.keys(actuators).length) return null;
    const equipment = {};
    for (const [key, value] of Object.entries(control.equipment)) if (isNumber(value)) equipment[key] = value;
    const schedules = control.schedules.filter((item) => actuators[item.actuator] === "SCHEDULE");
    return { actuators, equipment, schedules };
  }
  function controlActive() { return Boolean(bench.caps && controlDocument()); }
  function renderControl() {
    const host = $("#control-actuators");
    if (!host || !bench.caps) return;
    if (!controlInfo()) {
      host.replaceChildren(el("p", "hint ctl-warn", "This server does not offer climate control: restart it (python -m agri_twin.interfaces.frontend_api) so it loads the current code."));
      for (const id of ["control-equipment", "control-schedules"]) $(`#${id}`).replaceChildren();
      $("#control-summary").textContent = "unavailable";
      return;
    }
    const control = bench.config.control, info = controlInfo(), blocked = bench.config.backend === "ENERGYPLUS";
    host.replaceChildren();
    for (const actuator of info.actuators) {
      const row = el("div", "ctl-row"), name = el("span", "ctl-name", actuator.label), badge = el("span", `ctl-badge ${actuator.layer.toLowerCase()}`, actuator.layer === "PASSIVE" ? "passive" : "uses energy");
      name.title = actuator.rule;
      const select = el("select"), allowed = controlAllowed(actuator.id);
      setOptions(select, info.modes.map((mode) => [mode, mode === "OFF" ? "Off" : mode === "AUTO" ? "Automatic" : "Schedule"]), allowed ? control.actuators[actuator.id] : "OFF");
      select.disabled = !allowed; select.setAttribute("aria-label", `${actuator.label} mode`);
      select.addEventListener("change", () => { control.actuators[actuator.id] = select.value; renderControl(); changed(); });
      row.append(name, badge, select); host.append(row);
    }
    const equipment = $("#control-equipment");
    equipment.replaceChildren();
    for (const item of info.equipment) {
      const used = controlAllowed(item.actuator) && control.actuators[item.actuator] !== "OFF";
      const wrap = el("label", used ? "" : "dim", `${item.label} (${item.unit})`), input = el("input");
      input.type = "number"; input.min = "0"; input.step = "any"; input.placeholder = "not defined";
      input.value = isNumber(control.equipment[item.id]) ? String(control.equipment[item.id]) : "";
      input.addEventListener("change", () => { control.equipment[item.id] = input.value === "" ? null : Number(input.value); renderControl(); changed(); });
      wrap.append(input); equipment.append(wrap);
    }
    renderSchedules();
    const notes = [];
    if (blocked) notes.push("EnergyPlus runs in lock-step with the controller (one hour at a time), so the controller looks ahead with a lumped model of the same greenhouse. The shade screen cannot be driven in EnergyPlus (use manual shading events or the simplified model); a run with events replays from its start.");
    {
      if (bench.config.environment !== "greenhouse") notes.push("Open field: only irrigation can be controlled.");
      for (const item of info.equipment) {
        const needed = controlAllowed(item.actuator) && control.actuators[item.actuator] !== "OFF" && !isNumber(control.equipment[item.id]);
        if (needed) notes.push(`${item.label} is not defined${/cop|efficiency|power/i.test(item.id) ? ": energy cannot be estimated" : ": that actuator stays unavailable"}.`);
      }
      const missing = new Set();
      for (const [stage, thresholds] of Object.entries(info.stage_thresholds[bench.config.crop] || {})) {
        for (const actuator of info.actuators) {
          if (controlAllowed(actuator.id) && control.actuators[actuator.id] === "AUTO" && THRESHOLD_KEYS[actuator.id].some((key) => thresholds[key] === null)) missing.add(`${actuator.label} in stage ${stage}`);
        }
      }
      if (missing.size) notes.push(`The crop catalogue has no thresholds for: ${[...missing].join("; ")}. Those rules do not act (nothing is invented).`);
    }
    $("#control-note").textContent = notes.join(" ");
    $("#control-note").hidden = !notes.length;
    $("#control-summary").textContent = controlActive() ? "on" : "off";
  }
  function renderSchedules() {
    const host = $("#control-schedules"), control = bench.config.control;
    host.replaceChildren();
    control.schedules.forEach((item, index) => {
      const card = el("li", "event ctl-schedule"), head = el("header");
      const remove = el("button", "", "Remove"); remove.type = "button";
      remove.addEventListener("click", () => { control.schedules.splice(index, 1); renderControl(); changed(); });
      const mode = control.actuators[item.actuator];
      head.append(el("span", "", `${controlInfo().actuators.find((a) => a.id === item.actuator).label}${mode === "SCHEDULE" ? "" : " (inactive: set it to Schedule)"}`), remove);
      card.append(head);
      const grid = el("div", "grid2");
      const field = (text, key, type, props = {}) => {
        const wrap = el("label", "", text), input = el("input"); input.type = type; Object.assign(input, props); input.value = String(item[key]);
        input.addEventListener("change", () => { item[key] = type === "number" ? Number(input.value) : input.value; renderControl(); changed(); });
        wrap.append(input); grid.append(wrap);
      };
      const select = el("label", "wide", "Actuator"), choice = el("select");
      setOptions(choice, controlInfo().actuators.map((a) => [a.id, a.label]), item.actuator);
      choice.addEventListener("change", () => { item.actuator = choice.value; renderControl(); changed(); });
      select.append(choice); grid.append(select);
      field("From (month-day)", "from_day", "text", { pattern: "[0-9]{2}-[0-9]{2}", placeholder: "06-15" });
      field("To (month-day)", "to_day", "text", { pattern: "[0-9]{2}-[0-9]{2}", placeholder: "09-15" });
      field("Every day from (UTC h)", "start_hour", "number", { min: 0, max: 23, step: 1 });
      field("until (UTC h)", "end_hour", "number", { min: 0, max: 24, step: 1 });
      field(item.actuator === "irrigation" ? "Amount (mm per step)" : "Level (0-1 of capacity)", "value", "number", { min: 0, max: item.actuator === "irrigation" ? 100 : 1, step: 0.05 });
      card.append(grid); host.append(card);
    });
  }
  // ---- energy price: a post-processing of the returned energy series (the tariff is not part of the simulation request) ----------------
  const tariff = () => { const t = bench.config.tariff || (bench.config.tariff = { currency: "EUR", flat: null, yearly: [], bands: [], offset: 0 }); t.yearly = t.yearly || []; t.bands = t.bands || []; return t; };
  const tariffCurrency = () => (tariff().currency || "EUR").trim() || "EUR";
  function tariffDocument() {
    const t = tariff(), doc = { currency: tariffCurrency() }, yearly = {};
    if (isNumber(t.flat)) doc.flat_per_kwh = t.flat;
    for (const item of t.yearly) if (Number.isInteger(item.year) && isNumber(item.price)) yearly[String(item.year)] = item.price;
    if (Object.keys(yearly).length) doc.yearly = yearly;
    const bands = t.bands.filter((b) => Number.isInteger(b.from) && Number.isInteger(b.to) && isNumber(b.value)).map((b) => ({ from_hour: b.from, to_hour: b.to, [b.mode === "factor" ? "factor" : "price_per_kwh"]: b.value }));
    if (bands.length) doc.time_of_day = bands;
    if (isNumber(t.offset) && t.offset) doc.utc_offset_hours = t.offset;
    return doc;
  }
  const tariffDefined = () => { const d = tariffDocument(); return d.flat_per_kwh !== undefined || Boolean(d.yearly) || (d.time_of_day || []).some((b) => b.price_per_kwh !== undefined); };
  const COST_NAMES = ["control_cost", "control_cost_cumulative"];
  let costSerial = 0;
  // Adds (or removes) the cost series of a run from its energy series; false when the tariff was rejected or superseded by a newer change.
  async function attachCost(run) {
    const serial = ++costSerial;
    run.variables = run.variables.filter((item) => !COST_NAMES.includes(item.name));
    for (const branch of ["baseline", "intervention"]) for (const name of COST_NAMES) delete run.series[branch][name];
    run.cost = null;
    if (!tariffDefined() || !run.series.baseline.control_energy_kwh) return true;
    const body = { tariff: tariffDocument(), time: run.times }, done = new Map();
    try {
      for (const branch of ["baseline", "intervention"]) {
        const series = run.series[branch];
        if (!done.has(series)) done.set(series, await api("/api/energy/cost", { method: "POST", body: JSON.stringify({ ...body, energy_kwh: series.control_energy_kwh }) }));
        if (serial !== costSerial) return false;
        series.control_cost = done.get(series).cost; series.control_cost_cumulative = done.get(series).cost_cumulative;
        (run.cost = run.cost || {})[branch] = done.get(series);
      }
    } catch (error) { showError(error); return false; }
    const unit = tariffCurrency();
    run.variables.push({ name: "control_cost", unit: `${unit}_per_step`, availability: "AVAILABLE" }, { name: "control_cost_cumulative", unit, availability: "AVAILABLE" });
    return true;
  }
  async function tariffChanged() {
    save();
    const note = $("#tariff-note"), run = bench.run;
    if (!run) { note.hidden = true; return; }
    if (!(await attachCost(run))) return;
    note.hidden = false;
    if (!run.series.baseline.control_energy_kwh) note.textContent = "This run has no estimated energy (climate control off or no efficiency defined): there is nothing to price.";
    else {
      const total = run.cost && run.cost.intervention ? run.cost.intervention.total_cost : null;
      note.textContent = isNumber(total) ? `Total estimated energy cost of this run: ${fmt(total)} ${tariffCurrency()}.` : tariffDefined() ? "Some steps have no price (a year or hour not covered by your tariff) or no estimable energy: the cost is not complete." : "Define a price to see the cost.";
    }
    const present = new Set(run.variables.map((item) => item.name));
    bench.config.charts = bench.config.charts.filter((name) => !COST_NAMES.includes(name) || present.has(name));
    buildChartPicks(); buildCharts(); renderDelta(); renderFrame(true);
  }
  function renderTariff() {
    const t = tariff();
    $("#tariff-flat").value = isNumber(t.flat) ? String(t.flat) : "";
    $("#tariff-currency").value = t.currency || "EUR";
    $("#tariff-offset").value = String(isNumber(t.offset) ? t.offset : 0);
    const rows = (host, items, build) => {
      host.replaceChildren();
      items.forEach((item, index) => {
        const card = el("li", "event"), head = el("header"), remove = el("button", "", "Remove"); remove.type = "button";
        remove.addEventListener("click", () => { items.splice(index, 1); renderTariff(); tariffChanged(); });
        head.append(el("span", "", ""), remove); card.append(head);
        const grid = el("div", "grid2"); build(item, grid); card.append(grid); host.append(card);
      });
    };
    const field = (grid, text, item, key, props, integer) => {
      const wrap = el("label", "", text), input = el("input"); input.type = "number"; Object.assign(input, props); input.value = isNumber(item[key]) ? String(item[key]) : "";
      input.addEventListener("change", () => { item[key] = input.value === "" ? null : integer ? Math.round(Number(input.value)) : Number(input.value); tariffChanged(); });
      wrap.append(input); grid.append(wrap);
    };
    rows($("#tariff-yearly"), t.yearly, (item, grid) => { field(grid, "Year", item, "year", { min: 2000, max: 2100, step: 1 }, true); field(grid, `Price (${tariffCurrency()}/kWh)`, item, "price", { min: 0, step: "any" }); });
    rows($("#tariff-bands"), t.bands, (item, grid) => {
      field(grid, "From (h)", item, "from", { min: 0, max: 23, step: 1 }, true); field(grid, "Until (h, exclusive)", item, "to", { min: 1, max: 24, step: 1 }, true);
      const kind = el("label", "", "Value is"), choice = el("select"); setOptions(choice, [["price", "an absolute price per kWh"], ["factor", "a factor on the price"]], item.mode || "price");
      choice.addEventListener("change", () => { item.mode = choice.value; renderTariff(); tariffChanged(); }); kind.append(choice); grid.append(kind);
      field(grid, item.mode === "factor" ? "Factor (x)" : `Price (${tariffCurrency()}/kWh)`, item, "value", { min: 0, step: "any" });
    });
  }
  function bindTariff() {
    const t = tariff();
    $("#tariff-flat").addEventListener("change", (event) => { t.flat = event.target.value === "" ? null : Number(event.target.value); tariffChanged(); });
    $("#tariff-currency").addEventListener("change", (event) => { t.currency = event.target.value; renderTariff(); tariffChanged(); });
    $("#tariff-offset").addEventListener("change", (event) => { t.offset = Number(event.target.value) || 0; tariffChanged(); });
    $("#add-year").addEventListener("click", () => { t.yearly.push({ year: Number(iso(startMs()).slice(0, 4)) + 1, price: null }); renderTariff(); });
    $("#add-band").addEventListener("click", () => { t.bands.push({ from: 0, to: 8, mode: "price", value: null }); renderTariff(); });
    renderTariff();
  }
  function bindControl() {
    bindTariff();
    bindHvac();
    bindResources();
    bindModelOptions();
    if (!controlInfo()) { renderControl(); return; }
    $("#add-schedule").addEventListener("click", () => {
      const scheduled = controlInfo().actuators.find((a) => bench.config.control.actuators[a.id] === "SCHEDULE") || controlInfo().actuators[0];
      bench.config.control.actuators[scheduled.id] = "SCHEDULE";
      bench.config.control.schedules.push({ actuator: scheduled.id, from_day: "06-15", to_day: "09-15", start_hour: 11, end_hour: 17, value: scheduled.id === "irrigation" ? 1 : 0.6 });
      renderControl(); changed();
    });
    $("#load-illustrative").addEventListener("click", () => { bench.config.control.equipment = illustrativeEquipment(); renderControl(); changed(); });
    $("#clear-equipment").addEventListener("click", () => { bench.config.control.equipment = {}; renderControl(); changed(); });
    renderControl();
  }
  // actuation tracks under the event bars: what the controller (or a manual event) really did, read from the returned series
  const TRACKS = [["Shade", "greenhouse_shading_fraction", 38], ["Vents", "control_vent_opening", 205], ["Extractors", "control_extractor_level", 275], ["HVAC cooling", "greenhouse_cooling_kw", 200], ["HVAC heating", "greenhouse_heating_kw", 15]];
  function drawActuation() {
    const canvas = $("#tl-actuation"), box = $("#tl-rows");
    if (!canvas) return;
    const run = bench.run, tracks = run ? TRACKS.filter(([, name]) => run.series.baseline[name] && controlActive()) : [];
    canvas.hidden = !tracks.length;
    if (!tracks.length) return;
    const width = Math.max(1, Math.floor(box.getBoundingClientRect().width)), height = tracks.length * 12, ratio = window.devicePixelRatio || 1;
    canvas.style.height = `${height}px`; canvas.width = Math.floor(width * ratio); canvas.height = Math.floor(height * ratio);
    const ctx = canvas.getContext("2d"); ctx.scale(ratio, ratio); ctx.clearRect(0, 0, width, height);
    const total = horizonHours(), t0 = Date.parse(run.times[0]), series = run.series.intervention;
    tracks.forEach(([text, name, hue], row) => {
      const values = series[name], top = Math.max(0, ...values.filter(isNumber)) || 1;
      ctx.fillStyle = `hsl(${hue} 15% 94%)`; ctx.fillRect(0, row * 12, width, 10);
      const columns = new Array(width).fill(0);
      values.forEach((value, index) => {
        if (!isNumber(value)) return;
        const x = Math.floor((((Date.parse(run.times[index]) - t0) / HOUR) / total) * width);
        if (x >= 0 && x < width) columns[x] = Math.max(columns[x], value / top);
      });
      columns.forEach((level, x) => { if (level > 0.02) { ctx.fillStyle = `hsl(${hue} 65% 45% / ${(0.25 + 0.75 * level).toFixed(2)})`; ctx.fillRect(x, row * 12, 1.5, 10); } });
      ctx.fillStyle = "#17352d"; ctx.font = "9px system-ui, sans-serif"; ctx.fillText(name.endsWith("_kw") ? `${text} (max ${fmt(top)} kW)` : text, 4, row * 12 + 8);
    });
  }


  // ---- running ----------------------------------------------------------------------------------------------------
  // Coherence between the settings and the data: the run remembers the exact request it was made with; whenever the settings now produce another one, the Run
  // button turns red and says what changed. Settings that only change the drawing (view, layers, chart choice and order) never count.
  function stable(value) {
    if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
    if (value && typeof value === "object") return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stable(value[key])}`).join(",")}}`;
    return JSON.stringify(value);
  }
  function runSignature() {
    try { return { request: buildRequest(), events: bench.events.length ? eventDocuments() : [], branch: bench.events.length ? iso(branchMs()) : null }; } catch { return null; }
  }
  const SETTING_NAMES = { crop: "crop", environment: "environment", scenario: "weather scenario", end_time: "period", weather: "weather source or planting date", greenhouse: "greenhouse model", control: "climate control", model_options: "evapotranspiration method" };
  function staleReasons(before, now) {
    const reasons = [];
    for (const key of Object.keys(SETTING_NAMES)) if (stable((before.request || {})[key]) !== stable((now.request || {})[key])) reasons.push(SETTING_NAMES[key]);
    if (stable(before.events) !== stable(now.events) || before.branch !== now.branch) reasons.push("interventions");
    return reasons;
  }
  function updateStale() {
    const run = bench.run, now = runSignature();
    const reasons = run && run.signature && now ? staleReasons(run.signature, now) : [];
    const stale = reasons.length > 0;
    const button = $("#run"), note = $("#stale-note");
    button.dataset.stale = String(stale || !run);  // red also before the first run: nothing on screen is data yet (no note, so the layout does not move)
    button.title = run ? "" : "No data yet: press Run";
    $("#run-label").textContent = stale ? "Run again" : "Run";
    note.hidden = !stale;
    if (stale) {
      note.textContent = `The data on screen come from the previous settings (changed: ${reasons.join(", ")}). Press Run to update them.`;
      setStatus("Settings changed: the data shown are out of date", "stale");
    } else if ($("#status").dataset.state === "stale") setStatus(run ? `Up to date · ${run.times.length} hourly steps` : "Ready", run ? "done" : "ready");
  }
  function changed() {
    save();
    updateStale();
    if (!bench.run) renderPreview();
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
    const signature = runSignature();
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
      data.signature = signature;
      data.greenhouse = request.greenhouse || null;
      await attachCost(data);
      adopt(data);
      updateStale();
      setStatus(`Done in ${data.seconds.toFixed(1)} s · ${data.times.length} hourly steps`, "done");
    } catch (error) {
      showError(error);
      setStatus("Run failed", "error");
      updateStale();
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
      await new Promise((resolve) => window.setTimeout(resolve, 120));  // the server is local: poll quickly instead of the advertised interval
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
    data.configKey = runKey();
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
    configureScenes();
    buildChartPicks();
    buildCharts();
    drawActuation();
    renderDelta();
    renderSeason();
    renderInfo();
    renderEvents(); renderTimeline();  // plausibility hints depend on the run's own weather
    renderFrame(true);
  }

  // ---- scenes -----------------------------------------------------------------------------------------------------
  const sceneEnvironment = () => (bench.run ? bench.run.environment : bench.config.environment);
  function sceneLayout() {
    if (sceneEnvironment() !== "greenhouse") return { layout: null };
    const c = bench.config.layout, entry = bench.catalogue.typologies[c.typology].profiles[`${c.span}|${c.rise}`];
    if (!entry) return null;
    return { layout: { span: c.span, spans: c.spans, bays: c.bays, pillar: c.pillar, gutter: c.gutter, profile: entry.profile } };
  }
  function configureScenes() {
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
    if (sceneEnvironment() !== "greenhouse") return "open field · no thermal backend";
    const c = bench.config.layout;
    return `${c.typology.replace(/_/g, " ").toLowerCase()} · ${(bench.run ? bench.run.backend : bench.config.backend) === "ENERGYPLUS" ? "EnergyPlus" : "simplified model"}`;
  }

  // ---- preview before the first run: the same 3D scene and the chosen charts, with no data -----------------------------------------------
  // Plant size is a drawing placeholder (a young crop); every number stays "n/a" until a run provides it.
  function previewState() {
    const greenhouse = bench.config.environment === "greenhouse";
    return { kind: "SCENE_STATE", time: null, hour: 12, interpolated: false, stage: null, environment: bench.config.environment,
      outdoor: { temp_c: null, rh_pct: null, radiation_w_m2: null, wind_m_s: null, wind_dir_deg: null, rain_mm_h: null },
      indoor: greenhouse ? { temp_c: null, rh_pct: null, vpd_kpa: null, co2_ppm: null, radiation_w_m2: null } : null,
      actuators: greenhouse ? { vent_opening: null, screen_deployed: null, heating_kw: null, cooling_kw: null, extractor_level: null } : null,
      crop: { growth: 0.3, lai: null, water_stress: null, heat_stress: null, cold_stress: null, vpd_stress: null, stress_max: null, accumulated: null, loss_fraction: null, fruit_fraction: null, ripeness: null },
      levels: { temperature: null, radiation: null, vpd: null, co2: null, soil_wetness: null }, rain: false, irrigation: false, events: [], comfort: null };
  }
  function renderPreview() {
    if (bench.run || !bench.caps) return;
    $("#scenes").hidden = false; $("#charts").hidden = false; $("#card-intervention").hidden = true;
    $("#title-baseline").textContent = "Preview · no data yet";
    configureScenes();
    renderFrame(true);
    buildChartPicks();
    buildCharts();
    updateStale();
  }

  function renderFrame(force) {
    if (!bench.run) {
      if (!bench.scenes.baseline || $("#scenes").hidden) return;
      const state = previewState();
      state.comfort = null;
      bench.scenes.baseline.update(state, bench.config.layers, false);
      renderReadout("baseline", state, null);
      return;
    }
    const run = bench.run, position = clamp(bench.position, 0, run.times.length - 1);
    const names = run.kind === "WHAT_IF" ? ["baseline", "intervention"] : ["baseline"];
    for (const name of names) {
      const ctx = bench.ctx[name];
      const visual = V.buildVisualState(ctx, position);
      const state = S.fromVisual(visual, ctx, position);
      state.comfort = (((bench.caps.climate_control || {}).stage_thresholds || {})[bench.config.crop] || {})[state.stage] || null;  // the stage's own range, from the crop catalogue
      bench.scenes[name].update(state, bench.config.layers, bench.playing && bench.speed >= CALM_SPEED);
      if (force || bench.lastReadoutTick) renderReadout(name, state, visual);
    }
    bench.lastReadoutTick = false;
    const index = Math.floor(position);
    $("#clock").textContent = `${run.times[index].slice(0, 16).replace("T", " ")} UTC${index === run.branchIndex && run.kind === "WHAT_IF" ? " · branch" : ""}`;
    moveCursors();
    movePlayhead();
  }

  function renderReadout(name, state, visual) {
    const host = $(`#read-${name}`);
    host.replaceChildren();
    const row = (title, value, unit) => { const wrap = el("div"); wrap.append(el("dt", "", title)); const dd = el("dd", isNumber(value) ? "" : "na", isNumber(value) ? `${fmt(value)}${unit ? ` ${unit}` : ""}` : "n/a"); wrap.append(dd); host.append(wrap); };
    // the banner slot always exists, so an event starting or ending never moves the rest of the page
    const banner = el("div", state.events.length ? "banner" : "banner idle"); banner.append(el("dt", "", state.events.length ? `EVENT ACTIVE: ${state.events.join(", ")}` : "No event active")); host.append(banner);
    row("Outdoor T", state.outdoor.temp_c, "°C");
    if (state.indoor) {
      row("Indoor T", state.indoor.temp_c, "°C"); row("Indoor RH", state.indoor.rh_pct, "%"); row("VPD", state.indoor.vpd_kpa, "kPa");
      row("CO2", state.indoor.co2_ppm, "ppm"); row("Vent opening", state.actuators.vent_opening === null ? null : state.actuators.vent_opening * 100, "%");
      row("Shade", state.actuators.screen_deployed === null ? null : state.actuators.screen_deployed * 100, "%"); row("Heating", state.actuators.heating_kw, "kW");
    } else { row("Humidity", state.outdoor.rh_pct, "%"); row("Radiation", state.outdoor.radiation_w_m2, "W/m²"); row("Rain", state.outdoor.rain_mm_h, "mm/h"); }
    const series = bench.run ? bench.run.series[name] : {}, at = Math.floor(bench.position);
    if (series.control_layer) {
      const value = (key) => (series[key] ? series[key][at] : null);
      row("Control layer", null, ""); host.lastChild.lastChild.textContent = value("control_layer") === "PASSIVE" ? "passive" : value("control_layer") === "ACTIVE" ? "energy" : "idle";
      row("Vent command", isNumber(value("control_vent_opening")) ? value("control_vent_opening") * 100 : null, "%");
      row("Extractors", isNumber(value("control_extractor_level")) ? value("control_extractor_level") * 100 : null, "%");
      row("HVAC cool+", isNumber(value("greenhouse_cooling_kw")) ? value("greenhouse_cooling_kw") - value("greenhouse_heating_kw") : null, "kW");  // negative: heating
      row("Energy (est.)", value("control_energy_kwh_cumulative"), "kWh");
      if (series.control_cost_cumulative) row("Cost (est.)", value("control_cost_cumulative"), tariffCurrency());
    }
    row("LAI", state.crop.lai, ""); row("Water stress", state.crop.water_stress, ""); row("Heat stress", state.crop.heat_stress, "");
    row("Stage", null, ""); host.lastChild.lastChild.textContent = state.stage || "n/a";
  }

  // ---- charts -------------------------------------------------------------------------------------------------------
  function availableNumeric() {
    return bench.run.variables.filter((item) => item.availability === "AVAILABLE" && bench.run.series.baseline[item.name] && typeof bench.run.series.baseline[item.name][0] === "number").map((item) => item.name);
  }
  const NON_NUMERIC = new Set(["crop_stage", "control_layer", "dormancy_released"]);
  // What can be charted: after a run, what that run returned; before it, what the API contract lists for this crop and environment.
  function chartCatalogue() {
    if (bench.run) return availableNumeric().map((name) => ({ name, unit: (bench.run.variables.find((item) => item.name === name) || {}).unit }));
    const greenhouse = bench.config.environment === "greenhouse", perennial = (bench.caps.perennial_crops || []).includes(bench.config.crop);
    return (bench.caps.variables || []).filter((item) => !NON_NUMERIC.has(item.name) && (item.scope === "ALL" || (item.scope === "GREENHOUSE" && greenhouse) || (item.scope === "PERENNIAL" && perennial) || (item.scope === "CONTROL" && controlActive())))
      .map((item) => ({ name: item.name, unit: item.unit }));
  }
  // The single way to show or hide a chart (the chip, the × and a rebuild all go through it), so a chip always says whether its chart is on screen.
  function setChart(name, on) {
    const at = bench.config.charts.indexOf(name);
    if (on && at < 0) bench.config.charts.push(name);
    if (!on && at >= 0) bench.config.charts.splice(at, 1);
    buildCharts(); save();
  }
  function refreshChartChips() {
    for (const chip of $$("#chart-picks .chip")) chip.setAttribute("aria-pressed", String(bench.config.charts.includes(chip.dataset.name)));
  }
  function buildChartPicks() {
    const host = $("#chart-picks"), names = chartCatalogue().map((item) => item.name);
    if (bench.run) bench.config.charts = bench.config.charts.filter((name) => names.includes(name));
    if (bench.run && controlActive() && !bench.config.controlCharts) {  // first run with control: show what it does
      for (const name of ["control_vent_opening", "greenhouse_cooling_kw", "greenhouse_heating_kw", "control_energy_kwh_cumulative"]) if (names.includes(name) && !bench.config.charts.includes(name)) bench.config.charts.push(name);
      bench.config.controlCharts = true;
    }
    if (!bench.config.chartsInit) {  // the default selection is made once; afterwards an empty selection is the user's choice
      if (!bench.config.charts.length) bench.config.charts = CHART_DEFAULT.filter((name) => names.includes(name)).slice(0, 4);
      bench.config.chartsInit = true;
    }
    host.replaceChildren();
    for (const name of names) {
      const chip = el("button", "chip", label(name));
      chip.type = "button"; chip.dataset.name = name;
      chip.setAttribute("aria-pressed", String(bench.config.charts.includes(name)));
      chip.addEventListener("click", () => setChart(name, !bench.config.charts.includes(name)));
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
    for (const observer of bench.observers) observer.disconnect();
    bench.observers = [];
    for (const chart of bench.charts) chart.plot.destroy();
    bench.charts = [];
    const host = $("#charts");
    host.replaceChildren();
    const live = Boolean(bench.run), run = bench.run, compare = live && run.kind === "WHAT_IF";
    // without a run the x axis spans the planned period and the plot is empty
    const seconds = live ? run.times.map((time) => Date.parse(time) / 1000) : [startMs() / 1000, endMs() / 1000];
    const catalogue = new Map(chartCatalogue().map((item) => [item.name, item]));
    const shown = bench.config.charts.filter((name) => catalogue.has(name));
    if (!shown.length) host.append(el("p", "charts-none", "No charts selected: pick values in the View panel."));
    for (const name of shown) {
      const info = catalogue.get(name);
      const card = el("div", "chart-card"), head = el("header");
      card.dataset.name = name;
      head.append(chartTools(card), el("strong", "", `${label(name)}${info && info.unit ? ` (${info.unit})` : ""}`));
      const value = el("span"); if (!live) value.textContent = "—";
      const close = el("button", "chart-close", "×"); close.type = "button"; close.title = "Remove this chart"; close.setAttribute("aria-label", `Remove the ${label(name)} chart`);
      close.addEventListener("click", () => setChart(name, false));
      head.append(value, close);
      const body = el("div", "chart-body"), cursor = el("div", "cursor-line");
      card.append(head, body); host.append(card);
      const width = Math.floor(body.getBoundingClientRect().width) || 380;
      const data = [seconds, live ? run.series.baseline[name] : [null, null]];
      const series = [{}, { label: compare ? "baseline" : "run", stroke: "#4d6a8a", width: 1.6 }];
      if (compare) { data.push(run.series.intervention[name]); series.push({ label: "intervention", stroke: "#c0561d", width: 1.6, dash: [6, 4] }); }
      if (!live) body.append(el("div", "chart-empty", "No data yet"));
      const flat = live && [data[1], ...(compare ? [data[2]] : [])].every((values) => values.every((item) => item === null || item === data[1].find(isNumber)));
      if (flat) body.append(el("div", "chart-empty", `Constant ${fmt(data[1].find(isNumber) ?? 0)} in this run`));
      const plot = new window.uPlot({
        width, height: 160, legend: { show: false }, series, scales: live ? { x: { time: true }, y: { range: (_u, low, high) => (high - low < 1e-9 ? [low - 1, high + 1] : window.uPlot.rangeNum(low, high, 0.1, true)) } } : { x: { time: true, range: () => [seconds[0], seconds[1]] }, y: { range: () => [0, 1] } }, cursor: { drag: { x: false, y: false } },
        axes: [{ stroke: "#5d6f68", grid: { stroke: "#e8eeea" } }, { stroke: "#5d6f68", size: 54, grid: { stroke: "#e8eeea" }, ...(live ? {} : { values: (_u, ticks) => ticks.map(() => "") }) }],
        hooks: { drawClear: [(u) => drawBands(u)] },
      }, data, body);
      body.append(cursor);
      plot.over.addEventListener("click", (event) => {
        if (!bench.run) return;
        const bounds = plot.over.getBoundingClientRect(), time = plot.posToVal(event.clientX - bounds.left, "x");
        stopPlayback(); seek(nearestIndex(seconds, time));
      });
      bench.charts.push({ name, plot, cursor, value, seconds, card, body });
      // The card width is only final after layout (scrollbars, grid reflow, side panel): follow it instead of measuring once.
      if (window.ResizeObserver) {
        const observer = new ResizeObserver(() => fitChart(bench.charts.find((chart) => chart.plot === plot)));
        observer.observe(body); bench.observers.push(observer);
      }
    }
    window.requestAnimationFrame(() => { bench.charts.forEach(fitChart); moveCursors(); });
    refreshChartChips();
    redrawCharts();
  }
  // Reordering: drag a chart by its handle onto another, or move it with the ‹ › buttons (keyboard and touch friendly). Only the DOM order changes; the plots are kept.
  function chartTools(card) {
    const tools = el("span", "chart-tools"), handle = el("button", "chart-handle", "⠿"), left = el("button", "", "‹"), right = el("button", "", "›");
    for (const [button, text] of [[handle, "Drag to reorder"], [left, "Move earlier"], [right, "Move later"]]) { button.type = "button"; button.title = text; button.setAttribute("aria-label", text); }
    left.addEventListener("click", () => moveChart(card, -1)); right.addEventListener("click", () => moveChart(card, 1));
    handle.addEventListener("pointerdown", () => { card.draggable = true; });  // the card is draggable only from its handle: the plot keeps its own mouse use
    handle.addEventListener("keydown", (key) => { if (key.key === "ArrowLeft" || key.key === "ArrowUp") { key.preventDefault(); moveChart(card, -1); } else if (key.key === "ArrowRight" || key.key === "ArrowDown") { key.preventDefault(); moveChart(card, 1); } });
    card.addEventListener("dragstart", (event) => { event.dataTransfer.effectAllowed = "move"; event.dataTransfer.setData("text/plain", card.dataset.name); card.classList.add("dragging"); bench.dragCard = card; });
    card.addEventListener("dragend", () => { card.classList.remove("dragging"); card.draggable = false; bench.dragCard = null; syncChartOrder(); });
    card.addEventListener("dragover", (event) => {
      const dragged = bench.dragCard;
      if (!dragged || dragged === card) return;
      event.preventDefault();
      const host = card.parentNode, cards = Array.from(host.children);
      host.insertBefore(dragged, cards.indexOf(dragged) < cards.indexOf(card) ? card.nextSibling : card);
    });
    card.addEventListener("drop", (event) => event.preventDefault());
    tools.append(handle, left, right);
    return tools;
  }
  function moveChart(card, delta) {
    const host = card.parentNode, cards = Array.from(host.children), at = cards.indexOf(card), target = cards[at + delta];
    if (!target) return;
    host.insertBefore(card, delta < 0 ? target : target.nextSibling);
    syncChartOrder();
    const again = card.querySelector(delta < 0 ? ".chart-tools button:nth-child(2)" : ".chart-tools button:nth-child(3)"); if (again) again.focus();
  }
  function syncChartOrder() {
    const order = Array.from($("#charts").children).map((card) => card.dataset.name).filter(Boolean);
    bench.config.charts = order;
    bench.charts.sort((a, b) => order.indexOf(a.name) - order.indexOf(b.name));
    save(); moveCursors();
  }
  function applyChartColumns() {
    const cols = bench.config.chartCols || "auto", host = $("#charts");
    if (host) host.style.setProperty("--cols", cols === "auto" ? "repeat(auto-fit, minmax(380px, 1fr))" : `repeat(${cols}, minmax(0, 1fr))`);
    const group = $("#chart-cols");
    group.replaceChildren();
    for (const value of ["auto", "1", "2", "3"]) {
      const button = el("button", "", value === "auto" ? "Auto" : value);
      button.type = "button"; button.setAttribute("aria-pressed", String(cols === value));
      button.addEventListener("click", () => { bench.config.chartCols = value; applyChartColumns(); save(); window.requestAnimationFrame(() => bench.charts.forEach(fitChart)); });
      group.append(button);
    }
  }
  function nearestIndex(seconds, time) {
    let low = 0, high = seconds.length - 1;
    while (low < high) { const middle = (low + high) >> 1; if (seconds[middle] < time) low = middle + 1; else high = middle; }
    return low;
  }
  function drawBands(u) {
    const ctx = u.ctx, area = u.bbox;
    // the bands ARE the bars of the timeline (same colour, same dates, moving with them), drawn behind the series so they never cover a line
    const bands = bench.events.map((event) => ({ from: eventStartMs(event) / 1000, to: (eventStartMs(event) + event.hours * HOUR) / 1000, hue: hueFor(event.type) }));
    ctx.save();
    for (const band of bands) {
      const x0 = u.valToPos(band.from, "x", true), x1 = u.valToPos(band.to, "x", true), width = Math.max(2, x1 - x0);
      ctx.fillStyle = `hsl(${band.hue} 55% 42% / .15)`;
      ctx.fillRect(x0, area.top, width, area.height);
      ctx.fillStyle = `hsl(${band.hue} 55% 42% / .75)`;
      ctx.fillRect(x0, area.top, width, 3);
    }
    if (bench.run && bench.run.kind === "WHAT_IF") {
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
  function fitChart(chart) {
    if (!chart) return;
    const width = Math.floor(chart.body.getBoundingClientRect().width);
    if (width > 0 && Math.abs(width - chart.plot.width) > 1) { chart.plot.setSize({ width, height: 160 }); moveCursors(); }
  }
  window.addEventListener("resize", () => { bench.charts.forEach(fitChart); renderTimeline(); drawActuation(); });

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
    bindScrub();
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
      ensurePlanting();
      buildSetup(); initLayout(); renderBackend(); renderPresets(); renderEvents(); bindTransport(); bindControl();
      $("#autorun").checked = false;
      applyChartColumns();
      renderPreview();
      $("#run").disabled = false;
      window.__bench = bench;  // handle for scripted checks
      if (bench.config.horizon === "season" || bench.events.length > 1) setStatus("Ready: press Run (a full season or several events takes a few seconds)", "ready");
      else void runExperiment();
    } catch (error) {
      showError(error);
      setStatus("Could not load the API", "error");
    }
  }
  init();
})();
