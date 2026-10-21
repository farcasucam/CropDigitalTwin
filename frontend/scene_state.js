"use strict";

/* Scene state: VisualState (API series at a time position) -> the plain object the isometric scene draws.
 * Pure presentation module: no DOM, no network, no clock, no model equation. Every value is read from the API
 * series; the only arithmetic is a unit conversion (mm per step -> mm per hour), a ratio of two returned
 * quantities (fruit share of biomass) and drawing-range scaling to the extent of the returned series.
 * Unavailable variables stay null (never zero) so the scene can show them as unavailable. */
(function (root) {
  const AVAILABLE = "AVAILABLE";
  const isNumber = (value) => typeof value === "number" && Number.isFinite(value);
  // Drawing constant (not a model parameter): the leaf area index that fills the drawn canopy. Plants are scaled against it so a
  // young crop (LAI 0.1) is drawn small even inside a short window of the series.
  const LAI_DRAW_REFERENCE = 4;
  // same drawing-range scaling as VisualState.level: position inside the extent of the returned series
  function levelOf(extent, value) {
    if (!extent || !isNumber(value)) return null;
    return extent.high === extent.low ? 0.5 : (value - extent.low) / (extent.high - extent.low);
  }

  function hourOfDay(time) {
    // "2026-03-01T13:30:00+00:00" -> 13.5 (string slicing only; no Date object, no clock); malformed text -> noon
    const text = String(time), hh = text.slice(11, 13), mm = text.slice(14, 16);
    if (!/^\d\d$/.test(hh)) return 12;
    return Number(hh) + (/^\d\d$/.test(mm) ? Number(mm) / 60 : 0);
  }

  /* ctx: VisualState context (series, catalogue, extents, times). position may be fractional (visual blend only). */
  function fromVisual(visual, ctx, position) {
    const index = visual.index;
    const next = Math.min(ctx.times.length - 1, index + 1);
    const fraction = Math.max(0, Math.min(1, position - index));
    const available = (name) => ctx.catalogue[name] && ctx.catalogue[name].availability === AVAILABLE && Boolean(ctx.series[name]);
    const sample = (name) => {
      if (!available(name)) return null;
      const series = ctx.series[name];
      if (!isNumber(series[index])) return null;
      return isNumber(series[next]) && fraction > 0 ? series[index] + (series[next] - series[index]) * fraction : series[index];
    };
    const level = (name) => (available(name) ? levelOf(ctx.extents[name], sample(name)) : null);
    const greenhouse = ctx.environment === "greenhouse";
    const stepHours = ctx.times.length > 1 ? Math.max(1 / 60, (Date.parse(ctx.times[1]) - Date.parse(ctx.times[0])) / 3600000) : 1;
    const precipitation = sample("precipitation_mm");
    const fruit = sample("biomass_fruit_g_m2"), total = sample("biomass_total_g_m2");
    const stresses = ["water_stress", "heat_stress", "cold_stress", "vpd_stress"].map(sample).filter(isNumber);
    return {
      kind: "SCENE_STATE",
      time: visual.time,
      hour: hourOfDay(visual.time),
      interpolated: visual.interpolated,
      stage: visual.stage,
      environment: ctx.environment,
      outdoor: {
        temp_c: greenhouse ? sample("outdoor_temperature_c") : sample("temperature_c"),
        rh_pct: greenhouse ? null : sample("relative_humidity_pct"),
        radiation_w_m2: greenhouse ? null : sample("radiation_w_m2"),
        wind_m_s: null, wind_dir_deg: null,  // the API does not serialize wind: shown as unavailable
        rain_mm_h: isNumber(precipitation) ? precipitation / stepHours : null,
      },
      indoor: greenhouse ? {
        temp_c: sample("temperature_c"), rh_pct: sample("relative_humidity_pct"), vpd_kpa: sample("vpd_kpa"),
        co2_ppm: sample("co2_ppm"), radiation_w_m2: sample("radiation_w_m2"),
      } : null,
      actuators: greenhouse ? {
        vent_opening: visual.greenhouse.ventilation, screen_deployed: visual.greenhouse.shading,
        heating_kw: sample("greenhouse_heating_kw"), cooling_kw: sample("greenhouse_cooling_kw"),
        extractor_level: sample("control_extractor_level"),  // null unless a climate controller drove the run
      } : null,
      crop: {
        growth: isNumber(sample("leaf_area_index")) ? Math.min(1, Math.max(0, sample("leaf_area_index") / LAI_DRAW_REFERENCE)) : null,
        lai: sample("leaf_area_index"),
        water_stress: sample("water_stress"), heat_stress: sample("heat_stress"), cold_stress: sample("cold_stress"), vpd_stress: sample("vpd_stress"),
        stress_max: stresses.length ? Math.max(...stresses) : null,
        // shown relative to max(1, run maximum): a run without stress stays green instead of mapping to the middle of the scale
        accumulated: available("accumulated_stress") && isNumber(sample("accumulated_stress"))
          ? Math.min(1, Math.max(0, sample("accumulated_stress") / Math.max(1, ctx.extents.accumulated_stress ? ctx.extents.accumulated_stress.high : 1))) : null,
        loss_fraction: sample("frost_damage"),  // model frost damage fraction, drawn as lost plants (no mortality count exists)
        fruit_fraction: isNumber(fruit) && isNumber(total) && total > 0 ? Math.min(1, fruit / total) : null,
        ripeness: sample("maturity_index"),
      },
      levels: { temperature: level("temperature_c"), radiation: level("radiation_w_m2"), vpd: level("vpd_kpa"), co2: greenhouse ? level("co2_ppm") : null, soil_wetness: level("soil_water_vwc_m3_m3") },
      rain: visual.layers.water.rain, irrigation: visual.layers.water.irrigation,
      events: visual.active_events.map((event) => event.event_type),
    };
  }

  const CROP_SILHOUETTE = { tomato: "vine", cucumber: "vine", pepper: "vine", grape: "vine", lettuce: "rosette", peach: "bush", almond: "bush" };
  function silhouetteFor(crop) { return CROP_SILHOUETTE[crop] || "bush"; }

  const api = { fromVisual, hourOfDay, silhouetteFor };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.SceneState = api;
})(typeof window !== "undefined" ? window : globalThis);
