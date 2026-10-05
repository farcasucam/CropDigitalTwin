"use strict";

const $ = (selector) => document.querySelector(selector);
const form = $("#configuration-form");
const state = {
  capabilities: null,
  response: null,
  request: null,
  planRevision: 0,
  pollTimer: 0,
  lastApiMs: null,
  serializationSeconds: null,
  renderMs: null,
};

const CHARTS = [
  { title: "Air temperature", names: ["temperature_c", "outdoor_temperature_c"] },
  { title: "Relative humidity", names: ["relative_humidity_pct"] },
  { title: "Vapour pressure deficit", names: ["vpd_kpa"] },
  { title: "Solar radiation", names: ["radiation_w_m2"] },
  { title: "Soil water content", names: ["soil_water_vwc_m3_m3"] },
  { title: "Water fluxes", names: ["irrigation_mm", "precipitation_mm", "drainage_mm", "transpiration_mm", "evaporation_mm"] },
  { title: "Biomass", names: ["biomass_total_g_m2", "biomass_fruit_g_m2"] },
  { title: "Stress indicators", names: ["water_stress", "heat_stress", "cold_stress", "vpd_stress", "radiation_stress"] },
];

const VARIABLE_LABELS = {
  crop_stage: "Crop stage",
  maturity_index: "Maturity index",
  biomass_total_g_m2: "Total biomass",
  biomass_fruit_g_m2: "Fruit biomass",
  leaf_area_index: "Leaf area index",
  soil_water_vwc_m3_m3: "Soil water content",
  root_zone_water_mm: "Root-zone water",
  irrigation_mm: "Irrigation",
  precipitation_mm: "Precipitation",
  drainage_mm: "Drainage",
  transpiration_mm: "Transpiration",
  evaporation_mm: "Evaporation",
  et0_mm: "Reference evapotranspiration",
  temperature_c: "Crop-environment temperature",
  relative_humidity_pct: "Relative humidity",
  vpd_kpa: "Vapour pressure deficit",
  radiation_w_m2: "Solar radiation",
  water_stress: "Water stress",
  heat_stress: "Heat stress",
  cold_stress: "Cold stress",
  vpd_stress: "VPD stress",
  radiation_stress: "Radiation stress",
  frost_damage: "Frost damage",
  accumulated_stress: "Accumulated stress",
  growth_factor: "Growth factor",
  co2_ppm: "Greenhouse CO₂",
  outdoor_temperature_c: "Outdoor temperature",
  greenhouse_ventilation_fraction: "Greenhouse ventilation",
  greenhouse_shading_fraction: "Greenhouse shading",
  greenhouse_heating_kw: "Greenhouse heating",
  greenhouse_cooling_kw: "Greenhouse cooling",
  dormancy_released: "Dormancy released",
  chilling_accumulated: "Accumulated chilling",
};

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function option(value, label) {
  const element = node("option", "", label);
  element.value = value;
  return element;
}

function replaceOptions(select, values, labelFor = (value) => value) {
  select.replaceChildren(...values.map((value) => option(value, labelFor(value))));
}

function setGlobalError(message) {
  const target = $("#global-error");
  target.hidden = !message;
  target.textContent = message || "";
}

function showApiError(container, payload) {
  container.replaceChildren();
  container.hidden = false;
  const errors = Array.isArray(payload?.errors) ? payload.errors : [];
  if (!errors.length) {
    container.textContent = "Request failed. No structured error was returned.";
    return;
  }
  for (const item of errors) {
    const entry = node("div");
    const title = node("strong", "", `${item.code || "API_ERROR"}${item.path ? ` · ${item.path}` : ""}`);
    const message = node("span", "", item.message || "The API returned an error without a message.");
    entry.append(title, message);
    container.append(entry);
  }
}

async function api(path, options = {}) {
  const started = performance.now();
  const response = await fetch(path, {
    ...options,
    headers: { ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers },
  });
  const text = await response.text();
  let payload;
  try {
    payload = text ? JSON.parse(text) : {};
  } catch {
    throw new Error(`The API returned invalid JSON (HTTP ${response.status}).`);
  }
  state.lastApiMs = performance.now() - started;
  const serialized = response.headers.get("X-Serialization-Seconds");
  state.serializationSeconds = serialized === null ? null : Number(serialized);
  if (!response.ok) {
    const error = new Error("API request failed");
    error.payload = payload;
    error.status = response.status;
    throw error;
  }
  return payload;
}

function currentRequest() {
  const crop = $("#crop").value;
  const defaults = state.capabilities.crop_defaults[crop];
  const request = {
    crop,
    variety: $("#variety").value,
    environment: $("#environment").value,
    plot: $("#plot").value,
    scenario: $("#scenario").value,
    end_time: $("#horizon").value === "season"
      ? defaults.end_time
      : new Date(Date.parse(defaults.start_time) + 7 * 24 * 60 * 60 * 1000).toISOString(),
    options: {
      include_trajectory: true,
      compute_trajectory_hash: $("#trajectory-hash").checked,
    },
  };
  if ($("#use-dormancy").checked && defaults.dormancy_applicable) {
    request.dormancy = {
      start_policy: "DORMANCY_STATE",
      chilling_model: $("#chilling-model").value,
      fallback_policy: "STRICT",
    };
  }
  return request;
}

async function refreshPlan() {
  if (!state.capabilities || !$("#crop").value || !$("#environment").value) return;
  const revision = ++state.planRevision;
  try {
    const planned = await api("/api/plan", {
      method: "POST",
      body: JSON.stringify(currentRequest()),
    });
    if (revision !== state.planRevision) return;
    $("#execution-mode").textContent = planned.plan.mode;
    $("#execution-estimate").textContent = `${Number(planned.plan.estimated_seconds).toFixed(3)} s · advisory`;
    $("#plan-basis").textContent = planned.plan.basis;
    const defaults = state.capabilities.crop_defaults[$("#crop").value];
    $("#period-summary").textContent =
      `${planned.request.start_time} → ${planned.request.end_time} · ${planned.plan.total_steps} hourly steps`;
    $("#simulate-button").disabled = false;
    $("#error-panel").hidden = true;
    $("#error-panel").replaceChildren();
    updateDormancyText();
    state.plannedRequest = planned.request;
  } catch (error) {
    if (revision !== state.planRevision) return;
    $("#execution-mode").textContent = "Configuration rejected";
    $("#execution-estimate").textContent = "—";
    $("#plan-basis").textContent = "";
    $("#simulate-button").disabled = true;
    if (error.payload) showApiError($("#error-panel"), error.payload);
    else setGlobalError(error.message);
  }
}

function updateEnvironmentOptions() {
  const crop = $("#crop").value;
  const supported = state.capabilities.crop_environments[crop] || [];
  const defaults = state.capabilities.crop_defaults[crop];
  replaceOptions($("#environment"), supported);
  $("#environment").value = supported.includes(defaults.default_environment)
    ? defaults.default_environment
    : supported[0] || "";
}

function updateCropConfiguration() {
  const crop = $("#crop").value;
  const defaults = state.capabilities.crop_defaults[crop];
  replaceOptions($("#variety"), state.capabilities.crop_varieties[crop]);
  $("#variety").value = defaults.variety;
  replaceOptions($("#plot"), [defaults.plot]);
  updateEnvironmentOptions();
  const dormancy = Boolean(defaults.dormancy_applicable);
  $("#use-dormancy").disabled = !dormancy;
  if (!dormancy) $("#use-dormancy").checked = false;
  $("#dormancy-options").hidden = !dormancy;
  $("#chilling-model").disabled = !$("#use-dormancy").checked;
  updateDormancyText();
  void refreshPlan();
}

function updateDormancyText() {
  const target = $("#dormancy-status");
  if (!$("#use-dormancy").checked) {
    target.textContent = "Dormancy is not overridden; the canonical backend default applies.";
    return;
  }
  target.textContent = "The requested model is sent unchanged. Requested/effective model and fallback status come from the API response.";
}

function updateExecution(response) {
  state.response = response;
  const status = response.execution_status;
  const pill = $("#status-pill");
  pill.dataset.status = status;
  pill.textContent = status || "UNKNOWN";
  $("#simulation-id").textContent = response.simulation_id || "—";
  $("#simulated-time").textContent = response.progress?.simulated_time || "—";
  $("#current-stage").textContent = response.progress?.current_stage || "—";
  const total = response.progress?.total_steps || 0;
  const completed = response.progress?.completed_steps || 0;
  const fraction = total ? Math.min(1, completed / total) : 0;
  $("#progress-bar").value = fraction;
  $("#progress-text").textContent = total
    ? `${completed.toLocaleString()} / ${total.toLocaleString()} steps · ${(fraction * 100).toFixed(1)}%`
    : status || "Not started";
  $("#cancel-button").disabled = !["CREATED", "RUNNING"].includes(status);
  const checkpoint = response.checkpoint;
  const cropDefault = state.capabilities.crop_defaults[state.request?.crop];
  $("#resume-button").disabled = !(status === "CANCELLED" && checkpoint && cropDefault
    && Date.parse(checkpoint.simulation_time) < Date.parse(cropDefault.end_time));
  $("#checkpoint-info").textContent = checkpoint
    ? `Checkpoint returned by API · simulated time ${checkpoint.simulation_time} · payload preserved unchanged.`
    : "No checkpoint has been returned.";
  const dormancy = response.effective_configuration?.dormancy;
  if (dormancy) {
    $("#dormancy-status").textContent =
      `Requested: ${dormancy.requested_chilling_model} · Effective: ${dormancy.effective_chilling_model} · Fallback applied: ${dormancy.fallback_applied ? "YES" : "NO"}.`;
  }
  $("#error-panel").hidden = true;
  $("#error-panel").replaceChildren();
  if (Array.isArray(response.errors) && response.errors.length) {
    showApiError($("#error-panel"), { errors: response.errors });
  }
  $("#result-section").hidden = !response.result;
  if (response.result) {
    const renderStarted = performance.now();
    renderResult(response);
    state.renderMs = performance.now() - renderStarted;
    renderPerformance(response);
  }
}

function renderResult(response) {
  const result = response.result;
  const request = response.request || {};
  const plan = response.plan || {};
  $("#result-classification").textContent = plan.mode || "Unknown execution class";
  const summary = [
    ["Crop", request.crop],
    ["Variety", request.variety],
    ["Environment", request.environment],
    ["Scenario", request.scenario],
    ["Period", `${result.start || request.start_time || "—"} → ${result.end || "—"}`],
    ["Execution status", response.execution_status],
    ["Execution class", plan.mode],
    ["Completed", result.complete ? "Complete" : "Partial (cancelled)"],
  ];
  const list = $("#result-summary");
  list.replaceChildren();
  for (const [label, value] of summary) {
    list.append(node("dt", "", label), node("dd", "", value ?? "—"));
  }
  $("#configuration-hash").textContent = response.hashes?.configuration_hash || "—";
  $("#trajectory-hash").textContent = response.hashes?.trajectory_hash || "Unavailable";
  $("#hash-setting").textContent = request.options?.compute_trajectory_hash === false ? "DISABLED" : "ENABLED";
  renderFinalState(result);
  renderAvailability(result);
  renderCharts(result);
  renderStages(result);
  renderWarnings(response.warnings || []);
  $("#scientific-statement").textContent = response.scientific_status?.statement || "";
}

function formatValue(value) {
  if (typeof value === "number") return Number.isFinite(value) ? value.toLocaleString(undefined, { maximumFractionDigits: 4 }) : "Unavailable";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (value === null || value === undefined) return "Unavailable";
  return String(value);
}

function renderFinalState(result) {
  const body = $("#final-state");
  body.replaceChildren();
  const trajectory = result.trajectory;
  const variables = result.variables || [];
  for (const variable of variables) {
    if (variable.availability !== "AVAILABLE") continue;
    const series = trajectory?.[variable.name];
    if (!Array.isArray(series) || !series.length) continue;
    const row = node("tr");
    row.append(
      node("th", "", VARIABLE_LABELS[variable.name] || variable.name),
      node("td", "", formatValue(series[series.length - 1])),
      node("td", "", variable.unit || "—"),
    );
    body.append(row);
  }
  if (!body.children.length) {
    const row = node("tr");
    const cell = node("td", "", "No available trajectory values were returned.");
    cell.colSpan = 3;
    row.append(cell);
    body.append(row);
  }
}

function renderAvailability(result) {
  const container = $("#availability-list");
  container.replaceChildren();
  for (const variable of result.variables || []) {
    const item = node("article", "availability-item");
    item.append(node("strong", "", VARIABLE_LABELS[variable.name] || variable.name));
    const reason = variable.reason || variable.description || variable.source || "";
    item.append(node("small", "", reason));
    const stateTag = node("span", "availability-state", variable.availability || "UNKNOWN");
    stateTag.dataset.state = variable.availability || "UNKNOWN";
    item.append(stateTag);
    container.append(item);
  }
}

function chartSvg(name, values, times, unit) {
  const width = 640;
  const height = 210;
  const left = 52;
  const right = 18;
  const top = 15;
  const bottom = 29;
  const numeric = values.map(Number);
  const min = Math.min(...numeric);
  const max = Math.max(...numeric);
  const pad = min === max ? Math.max(1, Math.abs(min) * 0.05) : (max - min) * 0.06;
  const low = min - pad;
  const high = max + pad;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const x = (index) => left + (numeric.length <= 1 ? 0 : index * plotWidth / (numeric.length - 1));
  const y = (value) => top + (high - value) * plotHeight / (high - low);
  const points = numeric.map((value, index) => `${index ? "L" : "M"}${x(index).toFixed(2)},${y(value).toFixed(2)}`).join(" ");
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `${name}: ${numeric.length} reported API samples, ${formatValue(min)} to ${formatValue(max)} ${unit}`);
  const desc = document.createElementNS(svg.namespaceURI, "desc");
  desc.textContent = `Trajectory of ${name}; all ${numeric.length} values are plotted in API order without interpolation.`;
  svg.append(desc);
  const axis = document.createElementNS(svg.namespaceURI, "path");
  axis.setAttribute("class", "chart-axis");
  axis.setAttribute("d", `M${left},${top}V${height - bottom}H${width - right}`);
  svg.append(axis);
  const line = document.createElementNS(svg.namespaceURI, "path");
  line.setAttribute("class", "chart-line");
  line.setAttribute("d", points);
  svg.append(line);
  const yLabel = document.createElementNS(svg.namespaceURI, "text");
  yLabel.setAttribute("x", "4");
  yLabel.setAttribute("y", "13");
  yLabel.setAttribute("fill", "#64766e");
  yLabel.setAttribute("font-size", "11");
  yLabel.textContent = unit || "";
  svg.append(yLabel);
  const markerCount = Math.min(numeric.length, 90);
  const stride = Math.max(1, Math.ceil(numeric.length / markerCount));
  for (let index = 0; index < numeric.length; index += stride) {
    const marker = document.createElementNS(svg.namespaceURI, "circle");
    marker.setAttribute("class", "chart-marker");
    marker.setAttribute("cx", x(index));
    marker.setAttribute("cy", y(numeric[index]));
    marker.setAttribute("r", "3");
    marker.setAttribute("tabindex", "0");
    marker.setAttribute("aria-label", `${name}, ${times?.[index] || `sample ${index + 1}`}: ${formatValue(numeric[index])} ${unit || ""}`);
    const title = document.createElementNS(svg.namespaceURI, "title");
    title.textContent = `${times?.[index] || `sample ${index + 1}`}: ${formatValue(numeric[index])} ${unit || ""}`;
    marker.append(title);
    svg.append(marker);
  }
  return svg;
}

function renderCharts(result) {
  const container = $("#chart-grid");
  container.replaceChildren();
  const trajectory = result.trajectory;
  if (!trajectory) {
    container.append(node("p", "field-help", "The API did not include a trajectory for this result."));
    return;
  }
  const availability = new Map((result.variables || []).map((item) => [item.name, item]));
  let chartCount = 0;
  for (const chart of CHARTS) {
    const names = chart.names.filter((name) => availability.get(name)?.availability === "AVAILABLE"
      && Array.isArray(trajectory[name]) && trajectory[name].length
      && trajectory[name].every((value) => typeof value === "number" && Number.isFinite(value)));
    if (!names.length) continue;
    for (const name of names) {
      const variable = availability.get(name);
      const title = names.length > 1 ? `${chart.title} · ${VARIABLE_LABELS[name] || name}` : chart.title;
      const card = node("article", "chart-card");
      card.append(node("h3", "", title));
      card.append(node("p", "", `${variable.description || variable.name} · ${variable.unit || "unit not specified"}`));
      const wrap = node("div", "chart-wrap");
      wrap.append(chartSvg(title, trajectory[name], trajectory.time || [], variable.unit));
      card.append(wrap);
      const caption = node("div", "chart-caption");
      caption.append(node("span", "", trajectory.time?.[0] || "First API sample"));
      caption.append(node("span", "", trajectory.time?.[trajectory.time.length - 1] || "Last API sample"));
      card.append(caption);
      container.append(card);
      chartCount += 1;
    }
  }
  if (!chartCount) container.append(node("p", "field-help", "No charted variables are AVAILABLE for this result."));
}

function renderStages(result) {
  const list = $("#stage-timeline");
  list.replaceChildren();
  const trajectory = result.trajectory;
  const stages = trajectory?.crop_stage;
  if (!Array.isArray(stages) || !stages.length) {
    list.append(node("li", "", "No stage trajectory was returned."));
    return;
  }
  let previous;
  let stageStart = 0;
  const segments = [];
  for (let index = 0; index <= stages.length; index += 1) {
    const stage = stages[index];
    if (index === 0) {
      previous = stage;
      continue;
    }
    if (stage !== previous) {
      segments.push({ stage: previous, start: trajectory.time?.[stageStart], end: trajectory.time?.[index - 1] });
      previous = stage;
      stageStart = index;
    }
  }
  for (const segment of segments) {
    const item = node("li");
    item.append(node("strong", "", String(segment.stage)));
    item.append(node("span", "", `${segment.start || "—"} → ${segment.end || "—"}`));
    list.append(item);
  }
}

function renderWarnings(warnings) {
  const list = $("#warnings-list");
  list.replaceChildren();
  if (!warnings.length) {
    list.append(node("li", "", "No warnings reported."));
    return;
  }
  for (const warning of warnings) {
    list.append(node("li", "", `${warning.category || "WARNING"} · ${warning.code || "—"}: ${warning.message || ""}`));
  }
}

function renderPerformance(response) {
  const container = $("#performance-metrics");
  container.replaceChildren();
  const modelTime = response.operational?.timings_seconds?.simulation_seconds;
  const metrics = [
    ["MODEL_TIME", typeof modelTime === "number" ? `${(modelTime * 1000).toFixed(2)} ms` : "Not reported"],
    ["API_TIME", state.lastApiMs === null ? "Not measured" : `${state.lastApiMs.toFixed(2)} ms (last call)`],
    ["SERIALIZATION_TIME", state.serializationSeconds === null ? "Not measured" : `${(state.serializationSeconds * 1000).toFixed(3)} ms`],
    ["FRONTEND_RENDER_TIME", state.renderMs === null ? "Not measured" : `${state.renderMs.toFixed(2)} ms`],
  ];
  for (const [label, value] of metrics) {
    const wrapper = node("div");
    wrapper.append(node("dt", "", label), node("dd", "", value));
    container.append(wrapper);
  }
}

async function poll(simulationId) {
  window.clearTimeout(state.pollTimer);
  try {
    const response = await api(`/api/simulations/${encodeURIComponent(simulationId)}`);
    updateExecution(response);
    if (["CREATED", "RUNNING"].includes(response.execution_status)) {
      state.pollTimer = window.setTimeout(() => void poll(simulationId), state.capabilities.poll_interval_ms);
    }
  } catch (error) {
    if (error.payload) showApiError($("#error-panel"), error.payload);
    else setGlobalError(error.message);
  }
}

async function launch(request, resume = false) {
  setGlobalError("");
  $("#error-panel").hidden = true;
  $("#result-section").hidden = true;
  state.request = request;
  try {
    let response;
    if (resume) {
      response = await api("/api/simulations/resume", {
        method: "POST",
        body: JSON.stringify(request),
      });
    } else {
      response = await api("/api/simulations", {
        method: "POST",
        body: JSON.stringify(request),
      });
      updateExecution(response);
      response = await api(`/api/simulations/${encodeURIComponent(response.simulation_id)}/start`, {
        method: "POST",
        body: "{}",
      });
    }
    updateExecution(response);
    if (["CREATED", "RUNNING"].includes(response.execution_status)) {
      state.pollTimer = window.setTimeout(() => void poll(response.simulation_id), state.capabilities.poll_interval_ms);
    }
  } catch (error) {
    if (error.payload) showApiError($("#error-panel"), error.payload);
    else setGlobalError(error.message);
  }
}

async function cancelCurrent() {
  const simulationId = state.response?.simulation_id;
  if (!simulationId || !["CREATED", "RUNNING"].includes(state.response.execution_status)) return;
  $("#cancel-button").disabled = true;
  try {
    const response = await api(`/api/simulations/${encodeURIComponent(simulationId)}/cancel`, {
      method: "POST",
      body: "{}",
    });
    updateExecution(response);
    if (["CREATED", "RUNNING"].includes(response.execution_status)) {
      state.pollTimer = window.setTimeout(() => void poll(simulationId), state.capabilities.poll_interval_ms);
    }
  } catch (error) {
    $("#cancel-button").disabled = false;
    if (error.payload) showApiError($("#error-panel"), error.payload);
    else setGlobalError(error.message);
  }
}

async function resumeCurrent() {
  const response = state.response;
  if (!response?.checkpoint || !state.request) return;
  const request = { ...state.request, checkpoint: response.checkpoint };
  delete request.start_time;
  await launch(request, true);
}

async function initialize() {
  try {
    state.capabilities = await api("/api/capabilities");
    $("#api-version").textContent = state.capabilities.api_version || "Unknown";
    $("#adapter-note").textContent = state.capabilities.execution_adapter || "";
    replaceOptions($("#crop"), state.capabilities.crops);
    replaceOptions($("#scenario"), state.capabilities.scenarios);
    replaceOptions($("#chilling-model"), state.capabilities.chilling_models);
    $("#crop").addEventListener("change", updateCropConfiguration);
    $("#environment").addEventListener("change", () => void refreshPlan());
    $("#scenario").addEventListener("change", () => void refreshPlan());
    $("#horizon").addEventListener("change", () => void refreshPlan());
    $("#trajectory-hash").addEventListener("change", () => void refreshPlan());
    $("#use-dormancy").addEventListener("change", () => {
      $("#chilling-model").disabled = !$("#use-dormancy").checked;
      updateDormancyText();
      void refreshPlan();
    });
    $("#chilling-model").addEventListener("change", () => void refreshPlan());
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      void launch(currentRequest());
    });
    $("#cancel-button").addEventListener("click", () => void cancelCurrent());
    $("#resume-button").addEventListener("click", () => void resumeCurrent());
    updateCropConfiguration();
  } catch (error) {
    setGlobalError(error.payload ? JSON.stringify(error.payload) : error.message);
  }
}

void initialize();
