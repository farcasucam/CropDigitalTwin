"use strict";

/* Phase 5.40 visual layer: uPlot charts with event regions, event timeline table, baseline/intervention delta table,
 * DETAIL panel and RECORD/REPLAY controls. Presentation only: every value comes from the API response and
 * the only arithmetic here is pixel/time conversion. No model equation, no clock, no scheduler. */

window.Visual = (function () {
  const V = window.VisualState;
  const vis = { rt: null, charts: [], selected: new Set(["temperature_c", "soil_water_vwc_m3_m3", "biomass_total_g_m2", "crop_stage"]), placing: false, horizon: "full", stageLabels: [], position: 0 };
  const CHART_HEIGHT = 170;
  const SERIES_COLORS = { baseline: "#4d6a8a", intervention: "#c0561d" };

  function seconds(time) { return Date.parse(time) / 1000; }

  function drafts() {
    const rt = vis.rt;
    const applied = new Set(rt.result.events.map((event) => `${event.event_type}|${Date.parse(event.start_simulation_time)}|${event.duration_hours}`));
    return rt.events.filter((event) => !applied.has(`${event.event_type}|${Date.parse(event.start_simulation_time)}|${event.duration_hours}`));
  }

  function chartNames() {
    const rt = vis.rt;
    return V.OVERVIEW_VARIABLES.filter((name) => rt.series.baseline[name]);
  }

  function unitOf(name) { return vis.rt.catalogue[name]?.unit || ""; }

  function buildStageLabels() {
    const labels = [];
    for (const branch of ["baseline", "intervention"]) for (const stage of vis.rt.series[branch].crop_stage || []) if (stage !== null && !labels.includes(stage)) labels.push(stage);
    vis.stageLabels = labels;
  }

  function numeric(name, values) {
    return name === "crop_stage" ? values.map((stage) => (stage === null || stage === undefined ? null : vis.stageLabels.indexOf(stage))) : values;
  }

  function horizonRange() {
    const rt = vis.rt;
    const first = seconds(rt.times[0]), last = seconds(rt.times[rt.times.length - 1]);
    const checkpoint = seconds(rt.times[rt.branchIndex]);
    const day = 86400;
    if (vis.horizon === "checkpoint") return [checkpoint, last];
    if (vis.horizon === "window") return [Math.max(first, checkpoint - 3 * day), Math.min(last, checkpoint + 7 * day)];
    if (vis.horizon === "last7") return [Math.max(first, last - 7 * day), last];
    return [first, last];
  }

  function drawOverlay(u) {
    const rt = vis.rt;
    if (!rt || !rt.result) return;
    const { ctx } = u;
    const { left, top, width, height } = u.bbox;
    const clampX = (value) => Math.max(left, Math.min(left + width, u.valToPos(value, "x", true)));
    const now = vis.positionTime;
    ctx.save();
    ctx.beginPath();
    ctx.rect(left, top, width, height);
    ctx.clip();
    const regions = rt.result.events.map((event) => ({ event, draft: false })).concat(drafts().map((event) => ({ event: { ...event, end_simulation_time: new Date(Date.parse(event.start_simulation_time) + event.duration_hours * 3600000).toISOString() }, draft: true })));
    for (const { event, draft } of regions) {
      const a = clampX(seconds(event.start_simulation_time)), b = clampX(seconds(event.end_simulation_time));
      const future = !draft && event.start_simulation_time > rt.times[Math.floor(rt.position)];
      if (!draft && !future) { ctx.fillStyle = "rgba(192,86,29,0.18)"; ctx.fillRect(a, top, Math.max(2, b - a), height); }
      ctx.setLineDash(draft || future ? [6, 4] : []);
      ctx.strokeStyle = draft ? "#6b6b6b" : "#c0561d";
      ctx.lineWidth = 1.5 * devicePixelRatio;
      ctx.strokeRect(a, top, Math.max(2, b - a), height);
    }
    ctx.setLineDash([4, 3]);
    ctx.strokeStyle = "#123b2c";
    ctx.lineWidth = 1.5 * devicePixelRatio;
    const checkpointX = clampX(seconds(rt.times[rt.branchIndex]));
    ctx.beginPath(); ctx.moveTo(checkpointX, top); ctx.lineTo(checkpointX, top + height); ctx.stroke();
    ctx.setLineDash([]);
    ctx.strokeStyle = "#17352d";
    ctx.lineWidth = 2 * devicePixelRatio;
    const headX = clampX(now);
    ctx.beginPath(); ctx.moveTo(headX, top); ctx.lineTo(headX, top + height); ctx.stroke();
    ctx.restore();
  }

  function placeFromClick(clickSeconds) {
    const rt = vis.rt;
    const hours = V.eventStartFromClick(clickSeconds, seconds(branchTime()), seconds(rt.times[rt.times.length - 1]));
    const status = document.querySelector("#chart-status");
    if (hours === null) { status.textContent = "Click rejected: events can only start at or after the checkpoint and before the end of the run."; return; }
    document.querySelector("#event-start").value = String(hours);
    addEvent();
    status.textContent = `Event added from the chart: starts ${hours} h after the checkpoint (${rt.events[rt.events.length - 1].start_simulation_time}). Run what-if to apply it.`;
    refreshEvents();
  }

  function stageAxis() {
    return {
      splits: () => vis.stageLabels.map((_, i) => i),
      values: (_u, splits) => splits.map((value) => vis.stageLabels[value] || ""),
      size: 120,
    };
  }

  function destroyCharts() {
    for (const chart of vis.charts) chart.u.destroy();
    vis.charts = [];
  }

  function chartWidth(host) { return Math.max(260, Math.floor(host.clientWidth || 640)); }

  function buildCharts() {
    const rt = vis.rt;
    const host = document.querySelector("#charts");
    destroyCharts();
    host.replaceChildren();
    buildStageLabels();
    const x = rt.times.map(seconds);
    for (const name of chartNames().filter((item) => vis.selected.has(item))) {
      const wrap = node("figure", "chart-item");
      const base = rt.series.baseline[name], other = rt.series.intervention[name];
      const last = base.length - 1;
      wrap.setAttribute("role", "img");
      wrap.setAttribute("aria-label", `${VARIABLE_LABELS[name] || name}: final baseline ${base[last]}, final intervention ${other[last]}`);
      wrap.append(node("figcaption", "", `${VARIABLE_LABELS[name] || name}${unitOf(name) ? ` (${unitOf(name)})` : ""} · MODEL OUTPUT`));
      const target = node("div", "chart-canvas");
      wrap.append(target);
      host.append(wrap);
      const options = {
        width: chartWidth(host),
        height: CHART_HEIGHT,
        tzDate: (stamp) => uPlot.tzDate(new Date(stamp * 1000), "UTC"),
        cursor: { sync: { key: "twin", scales: ["x", null] }, drag: { x: true, y: false } },
        scales: { x: { time: true } },
        series: [
          {},
          { label: "baseline", stroke: SERIES_COLORS.baseline, width: 1.6, spanGaps: true },
          { label: "intervention", stroke: SERIES_COLORS.intervention, width: 1.6, dash: [5, 3], spanGaps: true },
        ],
        axes: [{ stroke: "#64766e", grid: { stroke: "#e3ebe5" } }, name === "crop_stage" ? { stroke: "#64766e", grid: { stroke: "#e3ebe5" }, ...stageAxis() } : { stroke: "#64766e", grid: { stroke: "#e3ebe5" }, size: 56 }],
        hooks: {
          draw: [drawOverlay],
          ready: [(u) => u.over.addEventListener("click", () => { if (vis.placing && u.cursor.left >= 0) placeFromClick(u.posToVal(u.cursor.left, "x")); })],
        },
      };
      const u = new uPlot(options, [x, numeric(name, base), numeric(name, other)], target);
      vis.charts.push({ name, u });
    }
    applyHorizon();
  }

  function applyHorizon() {
    if (!vis.charts.length) return;
    const [min, max] = horizonRange();
    for (const chart of vis.charts) chart.u.setScale("x", { min, max });
  }

  function cursor(position) {
    const rt = vis.rt;
    if (!rt || !rt.result) return;
    vis.position = position;
    const index = Math.floor(position);
    const next = Math.min(rt.times.length - 1, index + 1);
    vis.positionTime = seconds(rt.times[index]) + (position - index) * (seconds(rt.times[next]) - seconds(rt.times[index]));
    for (const chart of vis.charts) chart.u.redraw(false, false);
    renderEventTable();
  }

  function renderEventTable() {
    const rt = vis.rt;
    const host = document.querySelector("#event-table");
    if (!rt || !rt.result) return;
    const time = rt.times[Math.floor(rt.position)];
    const body = node("tbody");
    const environmentsOf = (type) => String(rt.contract.supported.find((item) => item.event_type === type)?.environments ?? "");
    const rows = rt.result.events.map((event) => ({ event, status: `${V.eventStatus(event, time)} (applied)` }))
      .concat(drafts().map((event) => ({ event: { ...event, end_simulation_time: "" }, status: "DRAFT (not applied)" })));
    for (const { event, status } of rows) {
      const row = node("tr");
      for (const text of [event.event_type, environmentsOf(event.event_type), event.start_simulation_time, `${event.duration_hours} h`, event.intensity === undefined || event.intensity === null ? "n/a" : String(event.intensity), status]) row.append(node("td", "", text));
      body.append(row);
    }
    if (!rows.length) { const row = node("tr"); const cell = node("td", "", "No events defined."); cell.colSpan = 6; row.append(cell); body.append(row); }
    const head = node("thead");
    const headRow = node("tr");
    for (const label of ["Type", "Environment", "Start (UTC)", "Duration", "Intensity", `Status at ${time}`]) headRow.append(node("th", "", label));
    head.append(headRow);
    const table = node("table", "data-table");
    table.append(node("caption", "", "Event timeline (USER-DEFINED SYNTHETIC FORCING)"), head, body);
    host.replaceChildren(table);
  }

  function refreshEvents() {
    for (const chart of vis.charts) chart.u.redraw(false, false);
    renderEventTable();
  }

  function renderDelta() {
    const rt = vis.rt;
    const comparison = rt.result.comparison.variables;
    const names = V.OVERVIEW_VARIABLES.concat(rt.result.comparison.variables_changed.filter((name) => !V.OVERVIEW_VARIABLES.includes(name)));
    const body = node("tbody");
    for (const name of names) {
      const row = node("tr");
      const info = rt.catalogue[name];
      const entry = comparison[name];
      let cells;
      if (entry && info && info.availability === V.AVAILABLE) {
        const numericRow = typeof entry.final_baseline === "number";
        cells = [VARIABLE_LABELS[name] || name, info.unit || "", formatValue(entry.final_baseline), formatValue(entry.final_intervention),
          numericRow ? formatValue(entry.delta_final) : (entry.identical ? "same" : `${entry.final_baseline} → ${entry.final_intervention}`),
          numericRow ? formatValue(entry.max_abs_delta) : "n/a", entry.first_difference_time || (entry.identical ? "no difference" : "n/a")];
      } else {
        cells = [VARIABLE_LABELS[name] || name, info?.unit || "", "—", "—", info ? info.availability : "NOT_REQUESTED", "—", info?.reason || "not comparable"];
      }
      for (const text of cells) row.append(node("td", "", text));
      body.append(row);
    }
    const head = node("thead");
    const headRow = node("tr");
    for (const label of ["Variable", "Unit", "Baseline (final)", "Intervention (final)", "Δ final", "max |Δ|", "First difference"]) headRow.append(node("th", "", label));
    head.append(headRow);
    const table = node("table", "data-table");
    table.append(node("caption", "", "Baseline vs intervention (values from the API comparison; NOT_APPLICABLE / NOT_SUPPORTED variables are not compared)"), head, body);
    document.querySelector("#delta-table").replaceChildren(table);
  }

  function refreshDetail() {
    const rt = vis.rt;
    const host = document.querySelector("#detail-panel");
    if (!rt || !rt.visual || !host) return;
    const target = document.querySelector("#detail-target").value;
    host.replaceChildren();
    for (const group of V.DETAIL_TARGETS[target]) {
      const rows = V.groupRows(rt.visual, group);
      if (!rows.length) continue;
      const body = node("tbody");
      for (const row of rows) {
        const tr = node("tr");
        const available = row.availability === V.AVAILABLE;
        const value = group === "Events" ? row.value : (available ? formatValue(row.value) : "—");
        const state = available ? "AVAILABLE" : `${row.availability}${row.reason ? ` — ${row.reason}` : ""}`;
        for (const text of [VARIABLE_LABELS[row.name] || row.name, value, available ? row.unit || "" : "", row.timestamp || "", state, row.source]) tr.append(node("td", "", text));
        body.append(tr);
      }
      const head = node("thead");
      const headRow = node("tr");
      for (const label of ["Variable", "Value", "Unit", "Timestamp", "Availability", "Source"]) headRow.append(node("th", "", label));
      head.append(headRow);
      const table = node("table", "data-table");
      table.append(node("caption", "", `${group} · ${target}`), head, body);
      host.append(table);
    }
  }

  function renderVariableChoices() {
    const rt = vis.rt;
    const host = document.querySelector("#chart-variables");
    host.replaceChildren();
    for (const name of V.OVERVIEW_VARIABLES) {
      const info = rt.catalogue[name];
      const available = Boolean(rt.series.baseline[name]);
      const label = node("label", "check");
      const box = node("input");
      box.type = "checkbox";
      box.checked = available && vis.selected.has(name);
      box.disabled = !available;
      box.addEventListener("change", () => { if (box.checked) vis.selected.add(name); else vis.selected.delete(name); buildCharts(); });
      label.append(box, document.createTextNode(` ${VARIABLE_LABELS[name] || name}${available ? "" : ` (${info ? info.availability : "NOT_REQUESTED"})`}`));
      host.append(label);
    }
  }

  function render() {
    const rt = vis.rt;
    vis.positionTime = seconds(rt.times[Math.floor(rt.position)]);
    renderVariableChoices();
    buildCharts();
    renderEventTable();
    renderDelta();
    refreshDetail();
  }

  function setRecordStatus(text) { document.querySelector("#replay-verdict").textContent = text; }

  async function recordSession() {
    runtimeError();
    try {
      const response = await api("/api/runtime/record", { method: "POST", body: JSON.stringify(whatIfDocument()) });
      document.querySelector("#session-json").value = JSON.stringify(response.session, null, 2);
      setRecordStatus(`Recorded session ${response.session.session_hash}. It stores configuration, event sequence, seed, checkpoints and hashes (not screenshots).`);
      window.adoptRuntimeResult(response.result, response.session.document.request.environment);
    } catch (error) {
      if (error.payload) runtimeError(error.payload); else runtimeError(null, error.message);
    }
  }

  async function replaySession() {
    runtimeError();
    let session;
    try { session = JSON.parse(document.querySelector("#session-json").value); } catch (error) { runtimeError(null, `The session text is not valid JSON: ${error.message}`); return; }
    try {
      const response = await api("/api/runtime/replay", { method: "POST", body: JSON.stringify(session) });
      const checks = Object.entries(response.checks).map(([name, ok]) => `${name.replaceAll("_", " ")}: ${ok ? "yes" : "NO"}`).join(" · ");
      setRecordStatus(`REPLAY ${response.status} · ${checks} · session hash ${response.session_hash}`);
      window.adoptRuntimeResult(response.result, session.document.request.environment);
    } catch (error) {
      if (error.payload) runtimeError(error.payload); else runtimeError(null, error.message);
    }
  }

  function init(rt) {
    vis.rt = rt;
    document.querySelector("#chart-horizon").addEventListener("change", (event) => { vis.horizon = event.target.value; applyHorizon(); });
    document.querySelector("#chart-reset").addEventListener("click", applyHorizon);
    document.querySelector("#chart-place").addEventListener("change", (event) => {
      vis.placing = event.target.checked;
      document.querySelector("#chart-status").textContent = vis.placing ? "Click inside a chart, after the checkpoint, to add the event currently defined in the form." : "";
    });
    document.querySelector("#detail-target").addEventListener("change", refreshDetail);
    document.querySelector("#session-record").addEventListener("click", () => void recordSession());
    document.querySelector("#session-replay").addEventListener("click", () => void replaySession());
    let pending = false;
    window.addEventListener("resize", () => {
      if (pending) return;
      pending = true;
      window.requestAnimationFrame(() => {
        pending = false;
        const host = document.querySelector("#charts");
        for (const chart of vis.charts) chart.u.setSize({ width: chartWidth(host), height: CHART_HEIGHT });
      });
    });
  }

  return { init, render, cursor, refreshDetail, refreshEvents, chartCount: () => vis.charts.length };
}());
