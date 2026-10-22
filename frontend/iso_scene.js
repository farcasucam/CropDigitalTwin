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

  // Hand-inked look (own implementation): warm paper, ink-brown lines, three flat tones per face (light / mid / dark by the way a face meets the light),
  // a heavy silhouette, a flat blue cast shadow and a slight hand wobble on the static line work only. All of it is built once in configure(); update() never touches it.
  const INK = "#231e16", PAPER = "#f6f1e6", SHADOW = "#41538f";
  const PALETTE = {
    "--anatomy-paper": "#f6f1e6", "--anatomy-face": "#fffaf0", "--anatomy-top": "#fffdf7", "--anatomy-lit-top": "#fffdf7", "--anatomy-lit-shade": "#efe9da",
    "--anatomy-shade-0": "#d6cdb8", "--anatomy-shade-1": "#e0d8c5", "--anatomy-shade-2": "#e9e2d2", "--anatomy-shade-3": "#f1ebdd",
    "--anatomy-hi": INK, "--anatomy-mid": "#4a4132", "--anatomy-lo": "#6d614c", "--anatomy-faint": "#cbc1aa", "--anatomy-weight": "1.1px",
  };
  const LIGHT = (() => { const v = [0.35, -0.55, 0.76], n = Math.hypot(...v); return v.map((x) => x / n); })();  // from the upper left of the drawing
  function hull2(points) {  // convex hull (monotone chain) of [x, y] points
    const p = points.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    if (p.length < 3) return p;
    const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    const lower = [], upper = [];
    for (const q of p) { while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], q) <= 0) lower.pop(); lower.push(q); }
    for (const q of p.slice().reverse()) { while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], q) <= 0) upper.pop(); upper.push(q); }
    return lower.slice(0, -1).concat(upper.slice(0, -1));
  }
  const sub3 = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const cross3 = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  function toneBand(points, centre) {  // 2 = lit, 1 = mid, 0 = dark: by the angle between the (outward) face normal and the light
    let n = cross3(sub3(points[1], points[0]), sub3(points[2], points[1]));
    const len = Math.hypot(...n) || 1; n = n.map((x) => x / len);
    const mid = points.reduce((a, q) => [a[0] + q[0] / points.length, a[1] + q[1] / points.length, a[2] + q[2] / points.length], [0, 0, 0]);
    if (n[0] * (mid[0] - centre[0]) + n[1] * (mid[1] - centre[1]) + n[2] * (mid[2] - centre[2]) < 0) n = n.map((x) => -x);
    const d = n[0] * LIGHT[0] + n[1] * LIGHT[1] + n[2] * LIGHT[2];
    return d > 0.55 ? 2 : d > 0.15 ? 1 : 0;
  }

  const CROP_KINDS = {
    vine: { hmax: 2.4, rmax: 0.55, fruit: true },
    bush: { hmax: 1.0, rmax: 0.5, fruit: false },
    rosette: { hmax: 0.3, rmax: 0.32, fruit: false },
  };

  // Phenology: the stage name decides the plant's life state (seedling, leafy and flowering, fruiting, senescent / dormant). Names come from the crop catalogue.
  function lifeStage(stage) {
    const name = String(stage || "");
    if (name.includes("dormancy") || name.includes("senescence")) return { name: "dormant", leaves: 0.5, flowers: false, senescence: 0.85 };
    if (name.includes("yield") || name.includes("maturation")) return { name: "fruiting", leaves: 1, flowers: false, senescence: 0.12 };
    if (name.includes("vegetative")) return { name: "flowering", leaves: 1, flowers: true, senescence: 0 };
    if (name.includes("establishment")) return { name: "seedling", leaves: 0.55, flowers: false, senescence: 0 };
    return { name: "unknown", leaves: 0.85, flowers: false, senescence: 0 };
  }

  // One visual cue per stress variable: accumulated and senescence -> leaf hue towards yellow-brown; water -> droop, narrow, pale;
  // heat -> orange-red leaf edge; cold -> blue-violet leaf and edge; VPD -> dashed brown edge.
  function plantStyle(crop, lost, life) {
    if (lost) return { fill: "hsl(32 18% 38%)", stroke: "none", strokeWidth: 0, dash: "none", droop: 0, narrow: 1, suffering: 0 };
    const cum = ease(Math.max(crop.accumulated === null ? (crop.stress_max || 0) : crop.accumulated, life.senescence));
    const water = clamp(crop.water_stress || 0), heat = clamp(crop.heat_stress || 0), cold = clamp(crop.cold_stress || 0), vpd = clamp(crop.vpd_stress || 0);
    const thermal = Math.max(heat, cold), edge = Math.max(thermal, vpd);
    let hue = lerp(138, 38, cum);
    if (cold > heat && cold > 0.1) hue = lerp(hue, 205, Math.min(0.75, cold));
    if (heat > 0.1 && heat >= cold) hue = lerp(hue, 28, Math.min(0.7, heat));  // scorched towards orange-brown
    const light = lerp(40, 33, cum) + 24 * water;
    return {
      fill: `hsl(${hue.toFixed(0)} ${lerp(54, 26, Math.max(cum, water)).toFixed(0)}% ${light.toFixed(0)}%)`,
      stroke: edge < 0.08 ? "hsl(105 35% 16%)" : thermal >= vpd ? (heat >= cold ? "hsl(14 88% 46%)" : "hsl(232 70% 56%)") : "hsl(28 55% 26%)",
      strokeWidth: edge < 0.08 ? 0.45 : 0.5 + 2.6 * edge, dash: vpd > thermal && edge >= 0.08 ? "2.4 1.6" : "none",
      droop: water * 0.9, narrow: 1 - 0.45 * water - 0.2 * heat, suffering: Math.max(water, heat, cold, vpd),
    };
  }

  // A leaf is a pointed blade from the stem outwards: two quadratic curves from the base to the tip. `lift` is the tip height above the base (negative: hanging).
  function leafPath(P, x, y, z, angle, length, lift, slenderness) {
    const b = K.iso([x, y, z], P), t = K.iso([x + Math.cos(angle) * length, y + Math.sin(angle) * length, z + lift], P);
    const dx = t[0] - b[0], dy = t[1] - b[1], n = Math.hypot(dx, dy) || 1, w = n * slenderness;
    const mx = (b[0] + t[0]) / 2 - (dy / n) * w, my = (b[1] + t[1]) / 2 + (dx / n) * w, nx = (b[0] + t[0]) / 2 + (dy / n) * w, ny = (b[1] + t[1]) / 2 - (dx / n) * w;
    const f = (v) => v.toFixed(1);
    return `M${f(b[0])} ${f(b[1])}Q${f(mx)} ${f(my)} ${f(t[0])} ${f(t[1])}Q${f(nx)} ${f(ny)} ${f(b[0])} ${f(b[1])}Z`;
  }

  /* look: { leaves (0..1 of the full foliage), droop (0..~0.9), narrow, flowers (bool), bare (bool), turn (rank-based rotation) }.
   * Returns the stem path, the leaf path and the anchor points of fruit and flowers. */
  function plantShape(P, x, y, h, r, kind, look) {
    const turn = look.turn * Math.PI * 2, GOLD = 2.39996;
    let leaves = "", stem = "";
    const fruitAt = [], flowerAt = [];
    const slender = 0.3 * look.narrow;
    if (kind === "rosette") {
      // a rosette: leaves spiral out of the heart; inner ones stand up, outer ones lie out and hang with water stress
      const n = Math.max(4, Math.round(13 * look.leaves));
      for (let i = 0; i < n; i++) {
        const ring = i / n, len = r * (0.45 + 0.65 * ring) * (0.9 + 0.2 * look.narrow), lift = len * (0.95 - 0.7 * ring) - h * look.droop * ring;
        leaves += leafPath(P, x, y, h * 0.06 + h * 0.1 * (1 - ring), turn + i * GOLD, len, lift, 0.34 * look.narrow);
      }
      stem = K.pathOf([K.iso([x, y, 0], P), K.iso([x, y, h * 0.12], P)]);
    } else if (kind === "bush") {
      // a tree: trunk with branches; a crown of leaf clusters; bare in dormancy
      const top = h * 0.5;
      stem = K.pathOf([K.iso([x, y, 0], P), K.iso([x, y, top], P)]);
      for (let i = 0; i < 4; i++) {
        const a = turn + i * (Math.PI / 2) + 0.4, ex = x + Math.cos(a) * r * 0.55, ey = y + Math.sin(a) * r * 0.55;
        stem += K.pathOf([K.iso([x, y, top * 0.82], P), K.iso([ex, ey, h * 0.78], P)]);
      }
      if (!look.bare) {
        const n = Math.max(3, Math.round(8 * look.leaves));
        for (let i = 0; i < n; i++) {
          const a = turn + i * GOLD, ring = 0.35 + 0.65 * ((i % 3) / 2), len = r * 0.8 * ring + r * 0.15;
          leaves += leafPath(P, x + Math.cos(a) * r * 0.3, y + Math.sin(a) * r * 0.3, h * (0.62 + 0.3 * ((i * 0.37) % 1)), a, len, len * (0.25 - look.droop * 0.7), 0.5 * look.narrow);
        }
      }
      for (let k = 0; k < 4; k++) {
        const a = turn + k * 1.7;
        fruitAt.push([x + Math.cos(a) * r * 0.6, y + Math.sin(a) * r * 0.6, h * (0.62 + 0.08 * k)]);
        flowerAt.push([x + Math.cos(a + 0.8) * r * 0.55, y + Math.sin(a + 0.8) * r * 0.55, h * (0.7 + 0.06 * k)]);
      }
    } else {
      // a vine: a straight stem with leaves up it, trusses of fruit hanging low, flowers at the top
      stem = K.pathOf([K.iso([x, y, 0], P), K.iso([x, y, h * 0.96], P)]);
      const n = Math.max(3, Math.round(10 * look.leaves));
      for (let i = 0; i < n; i++) {
        const t = (i + 0.5) / n, len = r * (1.05 - 0.4 * t), a = turn + i * GOLD;
        leaves += leafPath(P, x, y, h * (0.16 + 0.8 * t), a, len, len * (0.5 - look.droop * 1.1), slender);
      }
      for (let k = 0; k < 4; k++) {
        const a = turn + k * 1.9;
        fruitAt.push([x + Math.cos(a) * r * 0.55, y + Math.sin(a) * r * 0.55, h * (0.28 + 0.1 * k)]);
        flowerAt.push([x + Math.cos(a + 1) * r * 0.45, y + Math.sin(a + 1) * r * 0.45, h * (0.82 + 0.05 * k)]);
      }
    }
    return { stem, leaves, fruitAt, flowerAt };
  }

  // Temperature colour. With `comfort` (the stage's own min/max and critical heat/frost from the crop catalogue): green inside the comfortable range,
  // blue below it and orange to red above it, deepest at the critical value. Without it a generic scale is used. Always paired with a numeric readout.
  function tempTint(t, comfort) {
    if (!isNumber(t)) return "none";
    if (comfort && isNumber(comfort.min_temp_c) && isNumber(comfort.max_temp_c)) {
      if (t < comfort.min_temp_c) {
        const span = isNumber(comfort.critical_frost_c) && comfort.critical_frost_c < comfort.min_temp_c ? comfort.min_temp_c - comfort.critical_frost_c : 8;
        return `hsl(${lerp(205, 228, clamp((comfort.min_temp_c - t) / span)).toFixed(0)} 75% ${lerp(72, 48, clamp((comfort.min_temp_c - t) / span)).toFixed(0)}%)`;
      }
      if (t <= comfort.max_temp_c) return "hsl(140 40% 70%)";
      const span = isNumber(comfort.critical_heat_c) && comfort.critical_heat_c > comfort.max_temp_c ? comfort.critical_heat_c - comfort.max_temp_c : 6, k = clamp((t - comfort.max_temp_c) / span);
      return `hsl(${lerp(42, 2, k).toFixed(0)} 85% ${lerp(68, 50, k).toFixed(0)}%)`;
    }
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
      for (const name in PALETTE) svg.style.setProperty(name, PALETTE[name]);
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

    const clipId = `scene-clip-${serial}`, wobbleId = `scene-wobble-${serial}`;
    const defs = el("defs", {}, svg);
    // a slight hand wobble, applied to static line work only (never to anything update() redraws)
    const wobble = el("filter", { id: wobbleId, filterUnits: "userSpaceOnUse", x: -30, y: -30, width: W + 60, height: H + 60 }, defs);
    el("feTurbulence", { type: "fractalNoise", baseFrequency: "0.035", numOctaves: "2", seed: "7", result: "n" }, wobble);
    el("feDisplacementMap", { in: "SourceGraphic", in2: "n", scale: "1.7", xChannelSelector: "R", yChannelSelector: "G" }, wobble);
    el("rect", { x: 0, y: 0, width: W, height: H, rx: 12 }, el("clipPath", { id: clipId }, defs));
    const sky = el("g", { class: "scene-sky" }, svg);
    const skyRect = el("rect", { x: 0, y: 0, width: W, height: H, rx: 12, fill: PAPER }, sky);
    const overcast = el("rect", { x: 0, y: 0, width: W, height: H, rx: 12, fill: "hsl(215 28% 38%)", opacity: 0 }, sky);
    const sun = el("circle", { r: 11, class: "scene-sun" }, sky);
    const world = el("g", { "clip-path": `url(#${clipId})` }, svg);
    const body = el("g", { class: "scene-body" }, world);

    const soil = el("g", { class: "scene-soil" }, body);
    soil.innerHTML = K.solidSvg(K.slabOf({ x: -pad, y: -pad, w: L + pad * 2, d: Wd + pad * 2, r: 2 }, -0.3, 0.3, K.fitProjection ? P : P, 8, 0.4), { tone: "lo", crease: "faint", halo: false })
      + K.solidSvg(K.slabOf({ x: 0, y: 0, w: L, d: Wd, r: 0 }, 0, 0.02, P, 2), { tone: open ? "lo" : "faint", flat: true, crease: "none" });
    const plotTile = soil.lastChild;
    plotTile.classList.add("scene-plot");
    // the air around the greenhouse, tinted by the outdoor temperature (a ring of ground under and around the plot)
    const outdoorAir = el("path", { class: "scene-outdoor-air", "pointer-events": "none", d: K.pathOf([[-pad, -pad, 0.31], [L + pad, -pad, 0.31], [L + pad, Wd + pad, 0.31], [-pad, Wd + pad, 0.31]].map((p) => K.iso(p, P)), true) }, soil);
    soil.insertBefore(outdoorAir, plotTile);
    // the flat blue cast shadow of the greenhouse on the ground (fixed direction: a moving shadow would flash at fast playback)
    if (!open) {
      const s0 = K.iso([0, 0, 0], P);
      let best = [1, 0], score = -Infinity;
      for (let a = 0; a < 360; a += 45) {
        const v = [Math.cos((a * Math.PI) / 180), Math.sin((a * Math.PI) / 180)], s1 = K.iso([v[0], v[1], 0], P), value = (s1[0] - s0[0]) + 0.35 * (s1[1] - s0[1]);
        if (value > score) { score = value; best = v; }
      }
      const prof = layout.profile.map(([y, z]) => [y, z + gutter]), cast = [[0, 0], [L, 0], [L, Wd], [0, Wd]], k = 0.8;
      for (let s = 0; s < layout.spans; s++) for (const [y, z] of prof) for (const x of [0, L]) cast.push([x + best[0] * z * k, s * layout.span + y + best[1] * z * k]);
      el("path", { class: "scene-cast-shadow", "pointer-events": "none", fill: SHADOW, "fill-opacity": "0.34", stroke: "none", d: K.pathOf(hull2(cast).map(([x, y]) => K.iso([x, y, 0.31], P)), true) }, soil);
      soil.insertBefore(soil.lastChild, plotTile);
    }
    // ink: a heavy silhouette round the ground slab and a finer outline of the plot
    const slabCorners = [[-pad, -pad], [L + pad, -pad], [L + pad, Wd + pad], [-pad, Wd + pad]];
    const soilInk = el("g", { class: "scene-soil-ink", "pointer-events": "none", filter: `url(#${wobbleId})` }, soil);
    el("path", { fill: "none", stroke: INK, "stroke-width": "2.6", "stroke-linejoin": "round", d: K.pathOf(hull2(slabCorners.flatMap(([x, y]) => [K.iso([x, y, 0.3], P), K.iso([x, y, -0.3], P)])), true) }, soilInk);
    el("path", { fill: "none", stroke: INK, "stroke-width": "1.3", "stroke-linejoin": "round", d: K.pathOf([[0, 0], [L, 0], [L, Wd], [0, Wd]].map(([x, y]) => K.iso([x, y, 0.03], P)), true) }, soilInk);
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
        const flower = [0, 1, 2, 3].map(() => el("circle", { class: "flower", r: 1.5 }, g));
        const fruit = [0, 1, 2, 3].map(() => el("circle", { class: "fruit", r: 2 }, g));
        plants.push({ stem, leaves, fruit, flower, pos: it.pos, rank: lossRank(it.i) });
      }
    }

    const ribs = el("g", { class: "scene-ribs" }, body), screen = el("g", { class: "scene-screen" }, body);
    const hole = el("g", { class: "scene-hole" }, body), cover = el("g", { class: "scene-cover" }, body), flaps = el("g", { class: "scene-flaps" }, body);
    const toneG = el("g", { class: "scene-tone", "pointer-events": "none" }, body);
    body.insertBefore(toneG, flaps);
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
        const band = toneBand(f.pts, [L / 2, Wd / 2, zTop / 2]);
        if (band !== 1) f.tone = el("path", { d: f.node.getAttribute("d"), fill: band === 2 ? "#ffffff" : INK, "fill-opacity": band === 2 ? "0.3" : "0.17", stroke: "none" }, toneG);
        if (f.kind !== "roof") el("path", { class: "iso-line", "data-tone": "lo", d: f.node.getAttribute("d") }, edges);
      }
      const gut = [];
      for (let s = 0; s <= spans; s++) gut.push(K.pathOf([K.iso([0, s * span, prof[0][1]], P), K.iso([L, s * span, prof[0][1]], P)]));
      el("path", { class: "iso-line", "data-tone": "hi", d: gut.join("") }, edges);
      ventFacets.forEach((v) => { v.hole = el("path", { d: v.facet.node.getAttribute("d") }, hole); v.flap = el("path", {}, flaps); v.flapEdge = el("path", { class: "iso-line", "data-tone": "mid" }, flaps); });
      // heavy silhouette of the whole structure, drawn over everything it holds
      const ink = el("g", { class: "scene-ink", "pointer-events": "none", filter: `url(#${wobbleId})` }, body);
      for (let s = 0; s < spans; s++) {  // one silhouette per span: the gutters between spans stay drawn, nothing floats across the arches
        const outline = [];
        for (const [y, z] of prof) for (const x of [0, L]) outline.push(K.iso([x, s * span + y, z], P));
        for (const x of [0, L]) for (const y of [s * span, (s + 1) * span]) outline.push(K.iso([x, y, 0], P));
        el("path", { fill: "none", stroke: INK, "stroke-width": "2.6", "stroke-linejoin": "round", d: K.pathOf(hull2(outline), true) }, ink);
      }
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
    // climate strip (always visible): the two temperatures as colour chips and the actuators that are acting
    const strip = el("g", { class: "scene-climate", "pointer-events": "none" }, svg);
    const chips = ["out", "in"].map((name, i) => {
      const g = el("g", { transform: `translate(14 ${12 + i * 24})` }, strip);
      const swatch = el("rect", { width: 20, height: 20, rx: 5, stroke: "rgba(0,0,0,.25)" }, g);
      const text = el("text", { x: 27, y: 14.5, class: "scene-climate-text" }, g);
      return { g, swatch, text };
    });
    const stressChip = (() => {
      const g = el("g", { transform: "translate(14 62)" }, strip), swatch = el("rect", { width: 20, height: 20, rx: 5, stroke: "rgba(0,0,0,.25)" }, g);
      return { g, swatch, text: el("text", { x: 27, y: 14.5, class: "scene-climate-text" }, g) };
    })();
    const pills = ["Vents", "Screen", "Fans", "Cooling", "Heating"].map((label, i) => {
      const g = el("g", { transform: `translate(14 ${88 + i * 20})` }, strip);
      const back = el("rect", { width: 66, height: 17, rx: 8.5 }, g), text = el("text", { x: 33, y: 12.4, "text-anchor": "middle", class: "scene-pill-text" }, g);
      text.textContent = label;
      return { back, text, passive: i < 2 };
    });
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

    let lastPlantKey = "", lastRainKey = "", smoothSun = null, smoothOut = null, smoothIn = null;
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
      // The background stays one calm colour: day and night is shown by the small sun marker, never by flashing the whole scene.
      skyRect.setAttribute("opacity", "1");
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
      overcast.setAttribute("opacity", (0.2 * intensity).toFixed(2));  // rain greys the paper a little
      drops.style.display = on("water") && s.irrigation ? "" : "none";
      if (on("water") && s.irrigation) Array.from(drops.children).forEach((d, k) => { const p = K.iso([(k + 0.5) * L / 10, Wd / 2, 0.4], P); d.setAttribute("cx", p[0].toFixed(1)); d.setAttribute("cy", p[1].toFixed(1)); });

      // soil wetness and haze
      cropGroup.style.display = on("crop") ? "" : "none";
      const wetLevel = on("water") && s.levels.soil_wetness !== null ? s.levels.soil_wetness : 0;
      wet.setAttribute("opacity", (0.35 * wetLevel).toFixed(2));
      plotTile.style.opacity = on("soil") ? "1" : "0.45";
      haze.setAttribute("fill", "hsl(38 40% 62%)"); haze.setAttribute("opacity", on("vpd") && s.levels.vpd !== null ? (0.4 * s.levels.vpd).toFixed(2) : "0");

      // plants: growth, stress, loss
      const growth = c.growth === null ? 0.4 : c.growth, loss = clamp(c.loss_fraction || 0), life = lifeStage(s.stage);
      const bearsFruit = options.cropKind !== "rosette";
      const key = [growth.toFixed(3), c.water_stress, c.heat_stress, c.cold_stress, c.vpd_stress, c.accumulated, c.stress_max, loss.toFixed(3), c.fruit_fraction, c.ripeness, life.name].join("|");
      if (key !== lastPlantKey) {
        lastPlantKey = key;
        const style = plantStyle(c, false, life), lostStyle = plantStyle(c, true, life), grow = ease(growth);
        const bare = options.cropKind === "bush" && life.name === "dormant";
        plants.forEach((pl) => {
          const lost = pl.rank < loss, st = lost ? lostStyle : style;
          const h = lost ? Math.max(0.06, kind.hmax * 0.05) : Math.max(0.05, kind.hmax * grow);
          const r = lost ? 0.05 : Math.min(radiusCap, kind.rmax * (0.25 + 0.75 * grow) * st.narrow);
          const shape = plantShape(P, pl.pos.x, pl.pos.y, h, r, options.cropKind || "bush", { leaves: life.leaves * (0.35 + 0.65 * grow), droop: st.droop, narrow: st.narrow, bare, turn: pl.rank });
          pl.stem.setAttribute("d", shape.stem); pl.stem.setAttribute("stroke", bare ? "hsl(28 30% 30%)" : "hsl(100 30% 28%)");
          pl.leaves.setAttribute("d", lost ? "" : shape.leaves); pl.leaves.setAttribute("fill", st.fill);
          pl.leaves.setAttribute("stroke", st.stroke); pl.leaves.setAttribute("stroke-width", (st.strokeWidth * 0.7).toFixed(2)); pl.leaves.setAttribute("stroke-dasharray", st.dash);
          const nFruit = kind.fruit && bearsFruit && !lost && c.fruit_fraction !== null ? Math.round(4 * clamp(c.fruit_fraction * 4)) : 0;
          const nFlower = bearsFruit && !lost && life.flowers && !bare ? 3 : 0;
          const place = (nodes, count, points, fill) => nodes.forEach((node, k) => {
            if (k < count) {
              const p = K.iso(points[k], P);
              node.setAttribute("cx", p[0].toFixed(1)); node.setAttribute("cy", p[1].toFixed(1)); node.setAttribute("fill", fill(k)); node.setAttribute("opacity", "1");
            } else node.setAttribute("opacity", "0");
          });
          place(pl.fruit, nFruit, shape.fruitAt, () => `hsl(${lerp(95, 6, clamp(c.ripeness || 0)).toFixed(0)} 70% 48%)`);
          place(pl.flower, nFlower, shape.flowerAt, (k) => (options.cropKind === "bush" ? "hsl(335 70% 86%)" : k % 2 ? "hsl(48 95% 58%)" : "hsl(52 90% 68%)"));
        });
      }

      const comfort = s.comfort || null;
      // at fast playback the daily temperature swing would flash the tints: they follow a running mean there (the numbers stay exact)
      smoothOut = calm && smoothOut !== null && isNumber(o.temp_c) ? smoothOut + (o.temp_c - smoothOut) * 0.04 : o.temp_c;
      smoothIn = calm && smoothIn !== null && ind && isNumber(ind.temp_c) ? smoothIn + (ind.temp_c - smoothIn) * 0.04 : (ind ? ind.temp_c : null);
      const outTint = on("temperature") ? tempTint(smoothOut, comfort) : "none";
      outdoorAir.style.fill = outTint === "none" ? "transparent" : outTint; outdoorAir.style.fillOpacity = outTint === "none" ? "0" : "0.38";
      const inTemp = open ? o.temp_c : (ind ? ind.temp_c : null);
      chips[0].swatch.setAttribute("fill", tempTint(smoothOut, comfort) === "none" ? "#ccc" : tempTint(smoothOut, comfort));
      chips[0].text.textContent = `Outdoor ${isNumber(o.temp_c) ? o.temp_c.toFixed(1) : "n/a"} °C`;
      const shownIn = open ? smoothOut : smoothIn;
      chips[1].swatch.setAttribute("fill", tempTint(shownIn, comfort) === "none" ? "#ccc" : tempTint(shownIn, comfort));
      chips[1].text.textContent = `${open ? "Crop (open field)" : "Indoor"} ${isNumber(inTemp) ? inTemp.toFixed(1) : "n/a"} °C`;
      const live = [act && isNumber(act.vent_opening) && act.vent_opening > 0.02, act && isNumber(act.screen_deployed) && act.screen_deployed > 0.01,
        act && isNumber(act.extractor_level) && act.extractor_level > 0.02, act && isNumber(act.cooling_kw) && act.cooling_kw > 0.05, act && isNumber(act.heating_kw) && act.heating_kw > 0.05];
      pills.forEach((pill, k) => {
        pill.back.style.fill = !live[k] ? "rgba(255,255,255,.55)" : pill.passive ? "hsl(145 45% 38%)" : k === 4 ? "hsl(14 80% 48%)" : "hsl(205 75% 46%)";
        pill.text.style.fill = live[k] ? "#fff" : "#6b7a74"; pill.back.style.opacity = open ? "0" : "1"; pill.text.style.opacity = open ? "0" : "1";
      });
      // how the crop is doing: the worst of the four stresses, in words and in colour (green: none, red: severe)
      const stresses = [["water", c.water_stress], ["heat", c.heat_stress], ["cold", c.cold_stress], ["VPD", c.vpd_stress]].filter(([, v]) => isNumber(v));
      const worst = stresses.reduce((a, b) => (b[1] > a[1] ? b : a), ["", 0]), sev = clamp(worst[1]);
      stressChip.swatch.setAttribute("fill", `hsl(${lerp(120, 0, ease(sev)).toFixed(0)} 65% ${lerp(62, 48, sev).toFixed(0)}%)`);
      stressChip.text.textContent = !stresses.length ? "Stress n/a" : sev < 0.05 ? "No stress" : `Stress: ${worst[0]} ${(100 * sev).toFixed(0)}%`;
      strip.style.display = on("temperature") || on("events") ? "" : "none";
      if (!open) {
        const tint = on("temperature") && ind ? tempTint(smoothIn, comfort) : "none";
        cover.style.fill = tint === "none" ? "var(--anatomy-blue)" : tint;
        cover.style.fillOpacity = tint === "none" ? "0.08" : "0.3";
        const opening = clamp(act && isNumber(act.vent_opening) ? act.vent_opening : 0), ang = opening * 40 * Math.PI / 180;
        ventFacets.forEach((v) => {
          const vy = v.lower[0] - v.hinge[0], vz = v.lower[1] - v.hinge[1], mag = Math.hypot(vy, vz);
          let ny = -vz / mag, nz = vy / mag; if (nz < 0) { ny = -ny; nz = -nz; }
          const ly = v.hinge[0] + vy * Math.cos(ang) + ny * mag * Math.sin(ang), lz = v.hinge[1] + vz * Math.cos(ang) + nz * mag * Math.sin(ang);
          const d = K.pathOf([[0, ly, lz], [L, ly, lz], [L, v.hinge[0], v.hinge[1]], [0, v.hinge[0], v.hinge[1]]].map((p) => K.iso(p, P)), true);
          const opened = opening > 0.02;
          v.facet.node.style.display = opened ? "none" : ""; v.hole.style.display = opened ? "" : "none"; if (v.facet.tone) v.facet.tone.style.display = opened ? "none" : "";
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
