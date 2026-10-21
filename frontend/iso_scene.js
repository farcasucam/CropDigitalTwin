"use strict";

/* Isometric scene renderer (Phase 5.41). Presentation only: it draws a SCENE_STATE and never computes climate,
 * growth or stress. The static structure is built once in configure(); update() rewrites attributes of persistent
 * nodes. Projection and SVG strings come from the vendored isokit (window.IsoKit). Geometry numbers come from the
 * API catalogue (Python is the single source). Non-linear scalings below are drawing aids, not model quantities. */
(function (root) {
  const K = root.IsoKit;
  const NS = "http://www.w3.org/2000/svg";
  const W = 760, H = 460;
  const clamp = (v, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));
  const lerp = (a, b, t) => a + (b - a) * t;
  const ease = (t) => 1 - (1 - clamp(t)) * (1 - clamp(t));  // fast-start easing for drawing
  const isNumber = (v) => typeof v === "number" && Number.isFinite(v);

  function el(tag, attrs, parent) {
    const node = document.createElementNS(NS, tag);
    for (const key in attrs || {}) node.setAttribute(key, attrs[key]);
    if (parent) parent.appendChild(node);
    return node;
  }

  // Deterministic low-discrepancy order (van der Corput) decides which plants are drawn as lost first.
  function lossRank(index) {
    let n = index + 1, f = 0.5, r = 0;
    while (n > 0) { r += f * (n & 1); n >>= 1; f /= 2; }
    return r;
  }

  const CROP_KINDS = {
    vine: { hmax: 2.4, rmax: 0.55, fruit: true },
    bush: { hmax: 1.0, rmax: 0.5, fruit: false },
    rosette: { hmax: 0.3, rmax: 0.32, fruit: false },
  };

  // One visual cue per stress variable: accumulated -> leaf hue; water -> droop/narrow/pale;
  // heat or cold -> coloured leaf edge; VPD -> dashed brown edge.
  function plantStyle(crop, lost) {
    if (lost) return { fill: "hsl(32 18% 38%)", stroke: "none", strokeWidth: 0, dash: "none", droop: 0, narrow: 1 };
    const cum = ease(crop.accumulated === null ? (crop.stress_max || 0) : crop.accumulated);
    const water = clamp(crop.water_stress || 0), heat = clamp(crop.heat_stress || 0), cold = clamp(crop.cold_stress || 0), vpd = clamp(crop.vpd_stress || 0);
    const thermal = Math.max(heat, cold), edge = Math.max(thermal, vpd);
    const hue = lerp(138, 38, cum), light = lerp(42, 33, cum) + 16 * water;
    return {
      fill: `hsl(${hue.toFixed(0)} ${lerp(52, 42, cum).toFixed(0)}% ${light.toFixed(0)}%)`,
      stroke: edge < 0.08 ? "none" : thermal >= vpd ? (heat >= cold ? "hsl(14 88% 46%)" : "hsl(212 80% 52%)") : "hsl(28 55% 26%)",
      strokeWidth: 0.4 + 1.8 * edge, dash: vpd > thermal && edge >= 0.08 ? "2.4 1.6" : "none",
      droop: water * 0.32, narrow: 1 - 0.5 * water,
    };
  }

  function plantShape(P, x, y, h, r, kind, droop) {
    const leaf = (z, rad) => K.pathOf([K.iso([x - rad, y, z], P), K.iso([x, y - rad, z], P), K.iso([x + rad, y, z], P), K.iso([x, y + rad, z], P)], true);
    const stem = K.pathOf([K.iso([x, y, 0], P), K.iso([x, y, h * (kind === "rosette" ? 0.35 : 0.9)], P)]);
    let leaves;
    if (kind === "rosette") leaves = leaf(h * 0.22, r * 1.1) + leaf(h * 0.38, r * 0.7);
    else if (kind === "bush") leaves = leaf(h * 0.35 - droop, r * 1.1) + leaf(h * 0.62 - droop, r * 1.0) + leaf(h * 0.88 - droop * 0.5, r * 0.7);
    else leaves = leaf(h * 0.4 - droop, r * 0.85) + leaf(h * 0.68 - droop, r * 0.95) + leaf(h * 0.95 - droop * 0.5, r * 0.65);
    return { stem, leaves };
  }

  function tempTint(t) {
    // blue below 18 C, neutral 18-28 C, red above; always paired with a numeric readout
    if (!isNumber(t)) return "none";
    if (t < 18) return `hsl(215 70% ${lerp(55, 80, clamp(t / 18)).toFixed(0)}%)`;
    if (t <= 28) return "hsl(150 25% 80%)";
    return `hsl(${lerp(35, 0, clamp((t - 28) / 10)).toFixed(0)} 80% ${lerp(78, 58, clamp((t - 28) / 10)).toFixed(0)}%)`;
  }

  const VIEWS = { ISOMETRIC: { azimuth: 45, elevation: 30, zoom: 1 }, TOP: { azimuth: 90, elevation: 84, zoom: 1 }, DETAIL: { azimuth: 45, elevation: 30, zoom: 1.8 } };

  /* layout: { span, spans, bays, pillar, gutter, profile:[[y,z]] } (profile relative to the gutter) or null for open field.
   * options: { view, cropKind, compact, field:{width,length,rowSpacing,plantSpacing} } */
  function create(svg) {
    let scene = null, serial = 0;
    function configure(layout, options) {
      serial += 1;
      svg.replaceChildren();
      svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
      svg.style.overflow = "hidden";
      scene = build(svg, layout, options, serial);
      return scene;
    }
    return { configure, update: (state, layers) => scene && scene.update(state, layers), setView: (k, x, y) => scene && scene.setView(k, x, y), parts: () => (scene ? scene.parts : {}), info: () => (scene ? scene.info : null) };
  }

  function build(svg, layout, options, serial) {
    const open = !layout;
    const view = VIEWS[options.view] || VIEWS.ISOMETRIC;
    const kind = CROP_KINDS[options.cropKind] || CROP_KINDS.bush;
    const compact = Boolean(options.compact);
    let L, Wd, zTop, gutter = 0;
    const rows = [], pillars = [], facets = [], ventFacets = [];
    let radiusCap = Infinity;  // a canopy never overlaps its neighbours in the drawing
    if (open) {
      const f = options.field;
      L = f.length; Wd = f.width; zTop = 1;
      const rowCount = Math.floor(Wd / f.rowSpacing), perRow = Math.floor(L / f.plantSpacing);
      const stride = Math.max(1, Math.ceil(perRow / (compact ? 12 : 22)));
      radiusCap = 0.45 * Math.min(f.rowSpacing, stride * f.plantSpacing);
      for (let r = 0; r < rowCount; r++) for (let p = 0; p < perRow; p += stride) rows.push({ x: (p + 0.5) * f.plantSpacing + (L - perRow * f.plantSpacing) / 2, y: (r + 0.5) * f.rowSpacing });
    } else {
      gutter = layout.gutter;
      const spans = layout.spans, span = layout.span, prof = layout.profile.map(([y, z]) => [y, z + gutter]);
      L = layout.bays * layout.pillar; Wd = span * spans; zTop = Math.max(...prof.map((p) => p[1]));
      let apex = 0; prof.forEach((p, i) => { if (p[1] > prof[apex][1]) apex = i; });
      const ventIndex = apex > 0 ? apex - 1 : 0;
      for (let s = 0; s < spans; s++) {
        const y0 = s * span;
        for (let i = 0; i < prof.length - 1; i++) {
          const f = { kind: "roof", pts: [[0, y0 + prof[i][0], prof[i][1]], [L, y0 + prof[i][0], prof[i][1]], [L, y0 + prof[i + 1][0], prof[i + 1][1]], [0, y0 + prof[i + 1][0], prof[i + 1][1]]] };
          facets.push(f);
          if (i === ventIndex) ventFacets.push({ facet: f, hinge: [y0 + prof[apex][0], prof[apex][1]], lower: [y0 + prof[i][0], prof[i][1]] });
        }
        for (const x of [0, L]) facets.push({ kind: "end", pts: [[x, y0, 0], [x, y0 + span, 0], ...prof.slice().reverse().map(([y, z]) => [x, y0 + y, z])] });
      }
      if (gutter > 0) for (const y of [0, Wd]) facets.push({ kind: "side", pts: [[0, y, 0], [L, y, 0], [L, y, gutter], [0, y, gutter]] });
      const rowsPerSpan = compact ? 3 : 4, step = compact ? 2.25 : 1.5;
      radiusCap = 0.45 * Math.min(step, (span * 0.72) / (rowsPerSpan - 1));
      for (let s = 0; s < spans; s++) for (let k = 0; k < rowsPerSpan; k++) {
        const y = s * span + span * (0.14 + 0.72 * (k / (rowsPerSpan - 1)));
        for (let x = step; x < L - 1; x += step) rows.push({ x, y });
      }
      if (gutter > 0) for (let i = 0; i <= layout.bays; i++) for (let s = 0; s <= spans; s++) pillars.push({ x: i * layout.pillar, y: s * span });
    }
    const pad = open ? 5 : 3;
    const P = K.fitProjection([[-pad, -pad, -0.3], [L + pad, -pad, -0.3], [L + pad, Wd + pad, -0.3], [-pad, Wd + pad, -0.3], [0, 0, zTop + 1], [L, Wd, zTop + 1], [0, Wd, zTop + 1], [L, 0, zTop + 1]],
      W, H - 70, { pad: 26, azimuth: view.azimuth, elevation: view.elevation });
    P.origin[1] += 36;

    const clipId = `scene-clip-${serial}`;
    const defs = el("defs", {}, svg);
    el("rect", { x: 0, y: 0, width: W, height: H, rx: 12 }, el("clipPath", { id: clipId }, defs));
    const sky = el("g", { class: "scene-sky" }, svg);
    const skyRect = el("rect", { x: 0, y: 0, width: W, height: H, rx: 12 }, sky);
    const sun = el("circle", { r: 11, class: "scene-sun" }, sky);
    const world = el("g", { "clip-path": `url(#${clipId})` }, svg);
    const body = el("g", { class: "scene-body" }, world);

    const soil = el("g", { class: "scene-soil" }, body);
    soil.innerHTML = K.solidSvg(K.slabOf({ x: -pad, y: -pad, w: L + pad * 2, d: Wd + pad * 2, r: 2 }, -0.3, 0.3, K.fitProjection ? P : P, 8, 0.4), { tone: "lo", crease: "faint", halo: true })
      + K.solidSvg(K.slabOf({ x: 0, y: 0, w: L, d: Wd, r: 0 }, 0, 0.02, P, 2), { tone: open ? "lo" : "faint", flat: true, crease: "none" });
    const plotTile = soil.lastChild;
    plotTile.classList.add("scene-plot");
    const wet = el("path", { class: "scene-wet", d: K.pathOf([[0, 0, 0.03], [L, 0, 0.03], [L, Wd, 0.03], [0, Wd, 0.03]].map((p) => K.iso(p, P)), true) }, soil);
    if (open) {
      const furrows = [];
      for (let r = 0; r < Math.floor(Wd / options.field.rowSpacing); r++) { const y = (r + 0.5) * options.field.rowSpacing; furrows.push(K.pathOf([K.iso([0, y, 0.02], P), K.iso([L, y, 0.02], P)])); }
      el("path", { class: "iso-line", "data-tone": "faint", d: furrows.join("") }, soil);
    }

    const structure = el("g", { class: "scene-structure" }, body);
    const cropGroup = el("g", { class: "scene-crop" }, body);
    const items = [];
    rows.forEach((pos, i) => items.push({ type: "plant", pos, i, depth: K.depthOf([pos.x, pos.y, 0], P) }));
    pillars.forEach((pos) => items.push({ type: "pillar", pos, depth: K.depthOf([pos.x, pos.y, gutter / 2], P) }));
    items.sort((a, b) => a.depth - b.depth);
    const plants = [];
    for (const it of items) {
      if (it.type === "pillar") {
        const holder = el("g", {}, structure);
        holder.innerHTML = K.solidSvg(K.cylinder(it.pos.x, it.pos.y, 0.12, 0, gutter, P, 12), { tone: "mid", crease: "none" });
      } else {
        const g = el("g", { class: "scene-plant" }, cropGroup);
        const stem = el("path", { class: "stem" }, g), leaves = el("path", { class: "leaves" }, g);
        const fruit = [0, 1, 2].map(() => el("circle", { class: "fruit", r: 1.7 }, g));
        plants.push({ stem, leaves, fruit, pos: it.pos, rank: lossRank(it.i) });
      }
    }

    const ribs = el("g", { class: "scene-ribs" }, body), screen = el("g", { class: "scene-screen" }, body);
    const hole = el("g", { class: "scene-hole" }, body), cover = el("g", { class: "scene-cover" }, body), flaps = el("g", { class: "scene-flaps" }, body);
    const edges = el("g", { class: "scene-edges" }, body), co2 = el("g", { class: "scene-co2" }, body);
    // invisible click targets above the cover: a plant stays selectable beneath a clickable cover
    const hits = el("g", { class: "scene-hits" }, body);
    for (const pl of plants) { const p = K.iso([pl.pos.x, pl.pos.y, kind.hmax * 0.3], P); el("circle", { cx: p[0].toFixed(1), cy: p[1].toFixed(1), r: compact ? 9 : 7 }, hits); }
    let screenPoly = null, screenEdge = null, screenZ = 0;
    if (!open) {
      const prof = layout.profile.map(([y, z]) => [y, z + gutter]), spans = layout.spans, span = layout.span;
      const ribD = [], seamD = [];
      for (let i = 0; i <= layout.bays; i++) for (let s = 0; s < spans; s++) ribD.push(K.pathOf(prof.map(([y, z]) => K.iso([i * layout.pillar, s * span + y, z], P))));
      el("path", { class: "iso-line", "data-tone": "mid", d: ribD.join("") }, ribs);
      prof.forEach(([y, z]) => { for (let s = 0; s < spans; s++) seamD.push(K.pathOf([K.iso([0, s * span + y, z], P), K.iso([L, s * span + y, z], P)])); });
      el("path", { class: "iso-line", "data-tone": "lo", d: seamD.join("") }, ribs);
      const centre = (f) => f.pts.reduce((a, p) => [a[0] + p[0] / f.pts.length, a[1] + p[1] / f.pts.length, a[2] + p[2] / f.pts.length], [0, 0, 0]);
      for (const f of facets.slice().sort((a, b) => K.depthOf(centre(a), P) - K.depthOf(centre(b), P))) {
        f.node = el("path", { d: K.pathOf(f.pts.map((p) => K.iso(p, P)), true) }, cover);
        if (f.kind !== "roof") el("path", { class: "iso-line", "data-tone": "lo", d: f.node.getAttribute("d") }, edges);
      }
      const gut = [];
      for (let s = 0; s <= spans; s++) gut.push(K.pathOf([K.iso([0, s * span, prof[0][1]], P), K.iso([L, s * span, prof[0][1]], P)]));
      el("path", { class: "iso-line", "data-tone": "hi", d: gut.join("") }, edges);
      ventFacets.forEach((v) => { v.hole = el("path", { d: v.facet.node.getAttribute("d") }, hole); v.flap = el("path", {}, flaps); v.flapEdge = el("path", { class: "iso-line", "data-tone": "mid" }, flaps); });
      screenPoly = el("path", { class: "scene-screen-sheet" }, screen); screenEdge = el("path", { class: "iso-line", "data-tone": "hi" }, screen);
      screenZ = gutter > 0 ? gutter - 0.35 : zTop * 0.6;
      for (let k = 0; k < 24; k++) el("circle", { class: "co2-dot", r: 2.2, cx: 0, cy: 0 }, co2);
    }

    // VPD haze: a translucent plane just above the canopy (not the whole canvas)
    const hazeZ = open ? 1.2 : Math.max(1.5, gutter * 0.6);
    const haze = el("path", { class: "scene-haze", d: K.pathOf([[0, 0, hazeZ], [L, 0, hazeZ], [L, Wd, hazeZ], [0, Wd, hazeZ]].map((p) => K.iso(p, P)), true), "pointer-events": "none" }, body);
    const rain = el("g", { class: "scene-rain", "clip-path": `url(#${clipId})`, "pointer-events": "none" }, svg);
    const hud = el("g", { class: "scene-hud", "pointer-events": "none" }, svg);
    if (options.hud === false) hud.style.display = "none";  // an HTML readout replaces the drawn one
    const RAIN_MAX = compact ? 240 : 560, GOLDEN = 0.61803398875;
    const streaks = [];
    for (let i = 0; i < RAIN_MAX; i++) {
      const path = el("path", { d: "M0 0" }, rain);
      path.dataset.x = (((i * GOLDEN) % 1) * (W + 120) - 60).toFixed(1);
      path.style.setProperty("--y0", ((((i * GOLDEN * 7.31) % 1) * H)).toFixed(0) + "px");
      streaks.push(path);
    }
    const drops = el("g", { class: "scene-irrigation", "pointer-events": "none" }, world);
    for (let k = 0; k < 10; k++) el("circle", { r: 2.4, cx: 0, cy: 0 }, drops);
    const lines = (parent, x, anchor) => {
      const text = el("text", { x, y: 26, class: "scene-hud-text", "text-anchor": anchor }, parent);
      return Array.from({ length: 6 }, (_, i) => el("tspan", { x, dy: i ? 15 : 0 }, text));
    };
    const outLines = lines(hud, 18, "start"), inLines = lines(hud, W - 18, "end");
    const banner = el("g", { class: "scene-banner" }, hud);
    el("rect", { x: 18, y: H - 38, width: 360, height: 24, rx: 4 }, banner);
    const bannerText = el("text", { x: 28, y: H - 21 }, banner);
    const note = el("text", { x: W - 18, y: H - 18, class: "scene-hud-text small", "text-anchor": "end" }, hud);

    const winding = { k: 1, x: 0, y: 0 };
    const baseZoom = view.zoom;
    function applyView() {
      const k = clamp(winding.k * baseZoom, 0.4, 6);
      const maxX = (k - 1) * W / 2 + 120, maxY = (k - 1) * H / 2 + 120;
      const x = clamp(winding.x * (W / 640), -maxX, maxX), y = clamp(winding.y * (W / 640), -maxY, maxY);
      body.setAttribute("transform", `translate(${(W / 2 + x).toFixed(1)} ${(H / 2 + y).toFixed(1)}) scale(${k.toFixed(3)}) translate(${-W / 2} ${-H / 2})`);
    }
    applyView();

    let lastPlantKey = "", lastRainKey = "", smoothSun = null;
    // `calm` (fast playback): day and night alternate faster than the eye can follow, so the sky shows the running mean of the light and a noon sun
    // instead of strobing. Presentation only; the state itself is untouched.
    function update(s, layers, calm) {
      layers = layers || {};
      const on = (name) => layers[name] !== false;
      const o = s.outdoor, ind = s.indoor, act = s.actuators, c = s.crop;
      // sky, sun, rain
      const rawSun = s.levels.radiation === null ? 0.5 : s.levels.radiation;
      smoothSun = calm && smoothSun !== null ? smoothSun + (rawSun - smoothSun) * 0.04 : rawSun;
      const sunLevel = smoothSun;
      skyRect.setAttribute("fill", `hsl(${lerp(228, 205, sunLevel).toFixed(0)} ${lerp(38, 70, sunLevel).toFixed(0)}% ${lerp(14, 90, sunLevel).toFixed(0)}%)`);
      skyRect.setAttribute("opacity", "0.55");
      const day = calm ? 0.5 : clamp((s.hour - 6) / 12);
      sun.setAttribute("cx", (80 + (W - 160) * day).toFixed(0)); sun.setAttribute("cy", (150 - 110 * Math.sin(Math.PI * day)).toFixed(0));
      sun.style.display = on("radiation") && s.levels.radiation !== null ? "" : "none";
      sun.setAttribute("r", (8 + 8 * sunLevel).toFixed(1)); sun.setAttribute("opacity", (0.25 + 0.75 * sunLevel).toFixed(2));
      const rainRate = on("water") && isNumber(o.rain_mm_h) ? o.rain_mm_h : 0;
      const intensity = clamp(rainRate / 10), shown = Math.round(RAIN_MAX * intensity * (2 - intensity));
      const dropLen = 10 + 14 * intensity, dur = 1.1 - 0.5 * intensity;
      const rainKey = `${shown}|${dropLen.toFixed(1)}|${dur.toFixed(2)}`;
      if (rainKey !== lastRainKey) {
      lastRainKey = rainKey;
      rain.style.setProperty("--fall", `${H + 40}px`); rain.style.setProperty("--dx", "0px");
      streaks.forEach((p, i) => {
        if (i >= shown) { p.style.display = "none"; return; }
        p.style.display = "";
        p.setAttribute("d", `M${p.dataset.x} 0l0 ${dropLen.toFixed(1)}`);
        p.setAttribute("opacity", (0.55 + 0.35 * intensity).toFixed(2));
        p.style.animationDuration = `${(dur * (0.85 + 0.3 * ((i * 0.37) % 1))).toFixed(2)}s`;
        p.style.animationDelay = `${(-(i / RAIN_MAX) * dur * 2).toFixed(2)}s`;
      });
      }
      skyRect.setAttribute("opacity", (0.55 + 0.25 * intensity).toFixed(2));
      drops.style.display = on("water") && s.irrigation ? "" : "none";
      if (on("water") && s.irrigation) Array.from(drops.children).forEach((d, k) => { const p = K.iso([(k + 0.5) * L / 10, Wd / 2, 0.4], P); d.setAttribute("cx", p[0].toFixed(1)); d.setAttribute("cy", p[1].toFixed(1)); });

      // soil wetness and haze
      cropGroup.style.display = on("crop") ? "" : "none";
      const wetLevel = on("water") && s.levels.soil_wetness !== null ? s.levels.soil_wetness : 0;
      wet.setAttribute("opacity", (0.35 * wetLevel).toFixed(2));
      plotTile.style.opacity = on("soil") ? "1" : "0.45";
      haze.setAttribute("fill", "hsl(38 40% 62%)"); haze.setAttribute("opacity", on("vpd") && s.levels.vpd !== null ? (0.4 * s.levels.vpd).toFixed(2) : "0");

      // plants: growth, stress, loss
      const growth = c.growth === null ? 0.4 : c.growth, loss = clamp(c.loss_fraction || 0);
      const key = [growth.toFixed(3), c.water_stress, c.heat_stress, c.cold_stress, c.vpd_stress, c.accumulated, c.stress_max, loss.toFixed(3), c.fruit_fraction, c.ripeness].join("|");
      if (key !== lastPlantKey) {
        lastPlantKey = key;
        const style = plantStyle(c, false), lostStyle = plantStyle(c, true), grow = ease(growth);
        plants.forEach((pl) => {
          const lost = pl.rank < loss, st = lost ? lostStyle : style;
          const h = lost ? Math.max(0.06, kind.hmax * 0.05) : Math.max(0.05, kind.hmax * grow);
          const r = lost ? 0.05 : Math.min(radiusCap, kind.rmax * (0.25 + 0.75 * grow) * st.narrow);
          const shape = plantShape(P, pl.pos.x, pl.pos.y, h, r, options.cropKind || "bush", h * st.droop);
          pl.stem.setAttribute("d", shape.stem); pl.stem.setAttribute("stroke", st.fill);
          pl.leaves.setAttribute("d", lost ? "" : shape.leaves); pl.leaves.setAttribute("fill", st.fill);
          pl.leaves.setAttribute("stroke", st.stroke); pl.leaves.setAttribute("stroke-width", (st.strokeWidth * 1.5).toFixed(2)); pl.leaves.setAttribute("stroke-dasharray", st.dash);
          const nFruit = kind.fruit && !lost && c.fruit_fraction !== null ? Math.round(3 * clamp(c.fruit_fraction * 4)) : 0;
          pl.fruit.forEach((f, k) => {
            if (k < nFruit) {
              const p = K.iso([pl.pos.x + (k - 1) * r * 0.5, pl.pos.y + 0.1, h * (0.45 + 0.1 * k)], P);
              f.setAttribute("cx", p[0].toFixed(1)); f.setAttribute("cy", p[1].toFixed(1));
              f.setAttribute("fill", `hsl(${lerp(95, 6, clamp(c.ripeness || 0)).toFixed(0)} 70% 48%)`); f.setAttribute("opacity", "1");
            } else f.setAttribute("opacity", "0");
          });
        });
      }

      if (!open) {
        const tint = on("temperature") && ind ? tempTint(ind.temp_c) : "none";
        cover.style.fill = tint === "none" ? "var(--anatomy-blue)" : tint;
        cover.style.fillOpacity = tint === "none" ? "0.08" : "0.16";
        const opening = clamp(act && isNumber(act.vent_opening) ? act.vent_opening : 0), ang = opening * 40 * Math.PI / 180;
        ventFacets.forEach((v) => {
          const vy = v.lower[0] - v.hinge[0], vz = v.lower[1] - v.hinge[1], mag = Math.hypot(vy, vz);
          let ny = -vz / mag, nz = vy / mag; if (nz < 0) { ny = -ny; nz = -nz; }
          const ly = v.hinge[0] + vy * Math.cos(ang) + ny * mag * Math.sin(ang), lz = v.hinge[1] + vz * Math.cos(ang) + nz * mag * Math.sin(ang);
          const d = K.pathOf([[0, ly, lz], [L, ly, lz], [L, v.hinge[0], v.hinge[1]], [0, v.hinge[0], v.hinge[1]]].map((p) => K.iso(p, P)), true);
          const opened = opening > 0.02;
          v.facet.node.style.display = opened ? "none" : ""; v.hole.style.display = opened ? "" : "none";
          v.flap.setAttribute("d", d); v.flapEdge.setAttribute("d", d); v.flap.style.display = v.flapEdge.style.display = opened ? "" : "none";
        });
        const dep = clamp(act && isNumber(act.screen_deployed) ? act.screen_deployed : 0), xs = L * dep;
        screen.style.display = dep > 0.01 ? "" : "none";
        if (dep > 0.01) {
          screenPoly.setAttribute("d", K.pathOf([[0, 0, screenZ], [xs, 0, screenZ], [xs, Wd, screenZ], [0, Wd, screenZ]].map((p) => K.iso(p, P)), true));
          screenEdge.setAttribute("d", K.pathOf([K.iso([xs, 0, screenZ], P), K.iso([xs, Wd, screenZ], P)]));
        }
        const dots = Array.from(co2.children), count = on("co2") && s.levels.co2 !== null ? 4 + Math.round(20 * s.levels.co2) : 0;
        dots.forEach((d, k) => {
          d.style.display = k < count ? "" : "none";
          if (k < count) { const p = K.iso([(((k * 53) % 100) / 100) * L, (((k * 29) % 100) / 100) * Wd, 0.5 + (((k * 17) % 70) / 70) * (zTop - 1)], P); d.setAttribute("cx", p[0].toFixed(1)); d.setAttribute("cy", p[1].toFixed(1)); }
        });
      }

      // readouts: unavailable values read "n/a", never zero
      const f1 = (v, u, d = 1) => (isNumber(v) ? `${v.toFixed(d)} ${u}` : "n/a");
      const clock = `${String(Math.floor(s.hour)).padStart(2, "0")}:${String(Math.round((s.hour % 1) * 60) % 60).padStart(2, "0")}`;
      outLines[0].textContent = open ? "OUTDOOR (crop sees it)" : "OUTDOOR";
      outLines[1].textContent = `T ${f1(o.temp_c, "C")}   RH ${f1(o.rh_pct, "%", 0)}`;
      outLines[2].textContent = `Rain ${f1(o.rain_mm_h, "mm/h")}   UTC ${clock}`;
      outLines[3].textContent = `Wind ${f1(o.wind_m_s, "m/s")}`;
      outLines[4].textContent = open ? `Rad ${f1(s.levels.radiation === null ? null : null, "")}` : "";
      outLines[4].textContent = "";
      if (open) {
        inLines[0].textContent = "OPEN FIELD"; inLines[1].textContent = "no thermal backend"; inLines[2].textContent = "";
        inLines[3].textContent = ""; inLines[4].textContent = "";
      } else {
        inLines[0].textContent = "INDOOR (model output)";
        inLines[1].textContent = `T ${f1(ind.temp_c, "C")}   RH ${f1(ind.rh_pct, "%", 0)}`;
        inLines[2].textContent = `CO2 ${f1(ind.co2_ppm, "ppm", 0)}   VPD ${f1(ind.vpd_kpa, "kPa", 2)}`;
        inLines[3].textContent = `Vents ${isNumber(act.vent_opening) ? `${(100 * act.vent_opening).toFixed(0)}%` : "n/a"}  Screen ${isNumber(act.screen_deployed) ? `${(100 * act.screen_deployed).toFixed(0)}%` : "n/a"}`;
        inLines[4].textContent = `Heat ${f1(act.heating_kw, "kW")}  Cool ${f1(act.cooling_kw, "kW")}`;
      }
      inLines[5].textContent = `Stage ${s.stage === null || s.stage === undefined ? "n/a" : s.stage}`;
      outLines[5].textContent = `LAI ${f1(c.lai, "")}`;
      banner.style.display = on("events") && s.events.length ? "" : "none";
      bannerText.textContent = s.events.length ? `EVENT ACTIVE: ${s.events.join(", ")}` : "";
      note.textContent = s.interpolated ? "visual interpolation" : "";
    }

    return {
      update,
      setView: (k, x, y) => { winding.k = k; winding.x = x; winding.y = y; applyView(); },
      parts: { crop: [hits], mirror: { crop: [cropGroup] }, ground: [plotTile], greenhouse: open ? [] : [cover, structure, edges, flaps] },
      info: { length: L, width: Wd, top: zTop, plants: plants.length, open },
    };
  }

  root.IsoScene = { create, VIEWS };
})(typeof window !== "undefined" ? window : globalThis);
