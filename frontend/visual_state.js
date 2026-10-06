"use strict";

/* Phase 5.40: SimulationSnapshot -> VisualState.
 * Pure presentation module (no DOM, no network, no clock). Every value comes from the API response;
 * scaling to [0, 1] uses only the extent of the returned series and is a drawing aid, not a model quantity.
 * Interpolation between two returned snapshots is exclusively visual and is flagged as such. */
(function (root) {
  const AVAILABLE = "AVAILABLE";
  const NOT_APPLICABLE = "NOT_APPLICABLE";
  const NOT_SUPPORTED = "NOT_SUPPORTED";
  const NOT_REQUESTED = "NOT_REQUESTED";
  const SOURCE = "MODEL OUTPUT";

  const GROUPS = [
    ["Current state", ["biomass_total_g_m2", "biomass_fruit_g_m2", "leaf_area_index", "maturity_index", "growth_factor"]],
    ["Environment", ["temperature_c", "outdoor_temperature_c", "relative_humidity_pct", "vpd_kpa"]],
    ["Water", ["soil_water_vwc_m3_m3", "root_zone_water_mm", "irrigation_mm", "precipitation_mm", "drainage_mm", "transpiration_mm", "evaporation_mm", "et0_mm"]],
    ["Radiation", ["radiation_w_m2"]],
    ["CO2", ["co2_ppm"]],
    ["Phenology", ["crop_stage", "maturity_index", "dormancy_released"]],
    ["Stress", ["water_stress", "heat_stress", "cold_stress", "vpd_stress", "radiation_stress", "frost_damage", "accumulated_stress"]],
    ["Chilling", ["chilling_accumulated", "dormancy_released"]],
    ["Greenhouse", ["greenhouse_ventilation_fraction", "greenhouse_shading_fraction", "greenhouse_heating_kw", "greenhouse_cooling_kw"]],
  ];
  const DETAIL_TARGETS = {
    crop: ["Current state", "Phenology", "Stress", "Chilling"],
    plot: ["Environment", "Radiation", "Water", "Events"],
    greenhouse: ["Environment", "CO2", "Radiation", "Greenhouse", "Events"],
    soil: ["Water"],
  };
  const LAYERS = ["crop", "soil", "water", "temperature", "radiation", "vpd", "co2", "events"];
  const LAYER_VARIABLE = { temperature: "temperature_c", radiation: "radiation_w_m2", vpd: "vpd_kpa", co2: "co2_ppm", water: "soil_water_vwc_m3_m3" };
  const OVERVIEW_VARIABLES = ["temperature_c", "relative_humidity_pct", "vpd_kpa", "radiation_w_m2", "co2_ppm", "soil_water_vwc_m3_m3",
    "transpiration_mm", "evaporation_mm", "irrigation_mm", "biomass_total_g_m2", "crop_stage"];

  function isNumber(value) { return typeof value === "number" && Number.isFinite(value); }

  /* Availability map {name: {availability, unit, reason}} from the API variable catalogue. */
  function catalogue(variables) {
    const map = {};
    for (const item of variables || []) map[item.name] = { availability: item.availability, unit: item.unit, reason: item.reason || null, description: item.description || "" };
    return map;
  }

  function extentOf(values) {
    let low = Infinity, high = -Infinity;
    for (const value of values) if (isNumber(value)) { if (value < low) low = value; if (value > high) high = value; }
    return low === Infinity ? null : { low, high };
  }

  function level(extent, value) {
    if (!extent || !isNumber(value)) return null;
    return extent.high === extent.low ? 0.5 : (value - extent.low) / (extent.high - extent.low);
  }

  function eventStatus(event, time) {
    if (time < event.start_simulation_time) return "FUTURE";
    return time < event.end_simulation_time ? "ACTIVE" : "FINISHED";
  }

  function describeVariable(name, ctx, position) {
    const info = ctx.catalogue[name];
    const timestamp = ctx.times[Math.floor(position)];
    if (!info) return { name, availability: NOT_REQUESTED, value: null, unit: null, timestamp, source: SOURCE, reason: "variable not requested from the API" };
    if (info.availability !== AVAILABLE) return { name, availability: info.availability, value: null, unit: info.unit, timestamp, source: SOURCE, reason: info.reason };
    const series = ctx.series[name];
    if (!series) return { name, availability: NOT_REQUESTED, value: null, unit: info.unit, timestamp, source: SOURCE, reason: "series not returned" };
    return { name, availability: AVAILABLE, value: series[Math.floor(position)], unit: info.unit, timestamp, source: SOURCE, reason: null };
  }

  /* position may be fractional: numeric indicators are then blended between the two neighbouring snapshots (visual only). */
  function buildVisualState(ctx, position, options = {}) {
    const index = Math.max(0, Math.min(ctx.times.length - 1, Math.floor(position)));
    const next = Math.min(ctx.times.length - 1, index + 1);
    const fraction = Math.max(0, Math.min(1, position - index));
    const blend = (name) => {
      const series = ctx.series[name];
      if (!series || !isNumber(series[index])) return null;
      return isNumber(series[next]) && fraction > 0 ? series[index] + (series[next] - series[index]) * fraction : series[index];
    };
    const time = ctx.times[index];
    const variables = {};
    const names = new Set([...Object.keys(ctx.catalogue)]);
    for (const name of names) variables[name] = describeVariable(name, ctx, index);
    const state = (name) => (variables[name] ? variables[name].availability : NOT_REQUESTED);
    const indicator = (name) => (state(name) === AVAILABLE ? level(ctx.extents[name], blend(name)) : null);
    const events = (ctx.events || []).map((event) => ({ ...event, status: eventStatus(event, time) }));
    const active = events.filter((event) => event.status === "ACTIVE");
    const activeTypes = new Set(active.map((event) => event.event_type));
    const greenhouse = ctx.environment === "greenhouse";
    return {
      kind: "VISUAL_STATE",
      time,
      index,
      interpolated: fraction > 0,
      branch: ctx.branch,
      environment: ctx.environment,
      stage: state("crop_stage") === AVAILABLE ? ctx.series.crop_stage[index] : null,
      variables,
      events,
      active_events: active,
      layers: {
        crop: { canopy_height: indicator("leaf_area_index"), biomass_fill: indicator("biomass_total_g_m2"), water_stress: blend("water_stress"), heat_stress: blend("heat_stress"), cold_stress: blend("cold_stress") },
        soil: { wetness: indicator("soil_water_vwc_m3_m3") },
        water: { rain: state("precipitation_mm") === AVAILABLE ? (blend("precipitation_mm") || 0) > 0 : null, irrigation: state("irrigation_mm") === AVAILABLE ? (blend("irrigation_mm") || 0) > 0 : null, wetness: indicator("soil_water_vwc_m3_m3") },
        temperature: { level: indicator("temperature_c") },
        radiation: { level: indicator("radiation_w_m2") },
        vpd: { level: indicator("vpd_kpa") },
        co2: { level: greenhouse ? indicator("co2_ppm") : null },
        events: { active: Array.from(activeTypes) },
      },
      greenhouse: {
        present: greenhouse,
        ventilation: greenhouse ? blend("greenhouse_ventilation_fraction") : null,
        shading: greenhouse ? blend("greenhouse_shading_fraction") : null,
        co2_availability: state("co2_ppm"),
        ventilation_event_active: activeTypes.has("VENTILATION"),
        shading_event_active: activeTypes.has("SHADING"),
        co2_event_active: activeTypes.has("CO2"),
      },
      options,
    };
  }

  function buildContext({ series, catalogue: cat, times, events, environment, branch }) {
    const extents = {};
    for (const name of Object.keys(series)) extents[name] = extentOf(series[name]);
    return { series, catalogue: cat, times, events, environment, branch, extents };
  }

  function groupRows(visual, group) {
    const names = GROUPS.find(([label]) => label === group);
    if (group === "Events") return visual.events.map((event) => ({ name: event.event_type, availability: AVAILABLE, value: event.status, unit: null, timestamp: event.start_simulation_time, source: "USER-DEFINED SYNTHETIC FORCING" }));
    return (names ? names[1] : []).map((name) => visual.variables[name] || { name, availability: NOT_REQUESTED, value: null, unit: null, timestamp: visual.time, source: SOURCE, reason: "variable not requested from the API" });
  }

  /* Chart click -> event start offset in whole hours after the checkpoint; null when the click is before the checkpoint or after the run. */
  function eventStartFromClick(clickSeconds, branchSeconds, endSeconds) {
    if (![clickSeconds, branchSeconds, endSeconds].every(isNumber)) return null;
    if (clickSeconds < branchSeconds || clickSeconds >= endSeconds) return null;
    return Math.round((clickSeconds - branchSeconds) / 3600);
  }

  /* Presentation clock: simulated hours advanced for an elapsed real time. Does not touch the simulation. */
  function advance(position, elapsedSeconds, hoursPerSecond, last) {
    const next = position + Math.max(0, elapsedSeconds) * hoursPerSecond;
    return { position: Math.min(last, next), finished: next >= last };
  }

  function stageSegments(stages) {
    const segments = [];
    let start = 0;
    for (let i = 1; i <= stages.length; i += 1) {
      if (i === stages.length || stages[i] !== stages[start]) { segments.push({ stage: stages[start], from: start, to: i - 1 }); start = i; }
    }
    return segments;
  }

  const api = { AVAILABLE, NOT_APPLICABLE, NOT_SUPPORTED, NOT_REQUESTED, GROUPS, DETAIL_TARGETS, LAYERS, LAYER_VARIABLE, OVERVIEW_VARIABLES, catalogue, buildContext, buildVisualState, eventStatus, groupRows, extentOf, level, eventStartFromClick, advance, stageSegments };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.VisualState = api;
})(typeof window !== "undefined" ? window : globalThis);
