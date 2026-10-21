/* Scene runtime (prototype). Presentation only: it draws a state, it never computes climate or growth.
 * Needs the inlined kit as `K` (iso, depthOf, pathOf, fitProjection, slabOf, cylinder, solidSvg, lineSvg).
 * Static structure is built once in mount(); update(state) only rewrites attributes of persistent nodes. */
const SVGNS = "http://www.w3.org/2000/svg";
const clamp = (v, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));
const lerp = (a, b, t) => a + (b - a) * t;

function el(tag, attrs, parent) {
  const node = document.createElementNS(SVGNS, tag);
  for (const k in attrs || {}) node.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(node);
  return node;
}

// Deterministic low-discrepancy order (van der Corput): decides which plants are lost first, no randomness.
function lossRank(index) {
  let n = index + 1, f = 0.5, r = 0;
  while (n > 0) { r += f * (n & 1); n >>= 1; f /= 2; }
  return r;
}

// Distinct visual cue per stress variable so they can be told apart:
//   cumulative stress -> leaf hue green -> yellow -> brown;  water stress -> droop, narrower and paler leaves;
//   temperature stress -> orange-red leaf edge;  VPD stress -> dashed brown leaf edge.
function plantStyle(c, lost) {
  if (lost) return { fill: "hsl(32 18% 38%)", stroke: "none", strokeWidth: 0, dash: "none", droop: 0, narrow: 1 };
  const cum = clamp(c.cumulative_stress), water = clamp(c.water_stress), temp = clamp(c.temperature_stress || 0), vpd = clamp(c.vpd_stress || 0);
  const hue = lerp(138, 38, Math.pow(cum, 0.7)), sat = lerp(52, 42, cum), light = lerp(42, 33, cum) + 16 * water;
  const edge = Math.max(temp, vpd);
  return {
    fill: `hsl(${hue.toFixed(0)} ${sat.toFixed(0)}% ${light.toFixed(0)}%)`,
    stroke: edge < 0.08 ? "none" : temp >= vpd ? "hsl(14 88% 46%)" : "hsl(28 55% 26%)",
    strokeWidth: 0.4 + 1.8 * edge, dash: vpd > temp && edge >= 0.08 ? "2.4 1.6" : "none",
    droop: water * 0.32, narrow: 1 - 0.5 * water,
  };
}

function tempColour(t) {
  // blue below 10 C, neutral 18-28 C, red above 36 C; always paired with a numeric readout
  if (t == null) return "none";
  if (t < 18) return `hsl(215 70% ${lerp(55, 80, clamp((t - 0) / 18)).toFixed(0)}%)`;
  if (t <= 28) return "hsl(150 25% 80%)";
  return `hsl(${lerp(35, 0, clamp((t - 28) / 10)).toFixed(0)} 80% ${lerp(78, 58, clamp((t - 28) / 10)).toFixed(0)}%)`;
}

function plantShape(P, x, y, h, r, kind, droop) {
  // world-space diamonds keep the isometric look; kind only changes silhouette parameters
  const leaf = (z, rad) => K.pathOf([K.iso([x - rad, y, z], P), K.iso([x, y - rad, z], P), K.iso([x + rad, y, z], P), K.iso([x, y + rad, z], P)], true);
  const stem = K.pathOf([K.iso([x, y, 0], P), K.iso([x, y, h * (kind === "rosette" ? 0.35 : 0.9)], P)]);
  let leaves;
  if (kind === "rosette") {
    leaves = leaf(h * 0.22, r * 1.1) + leaf(h * 0.38, r * 0.7);
  } else if (kind === "bush") {
    leaves = leaf(h * 0.35 - droop, r * 1.1) + leaf(h * 0.62 - droop, r * 1.0) + leaf(h * 0.88 - droop * 0.5, r * 0.7);
  } else {
    leaves = leaf(h * 0.4 - droop, r * 0.85) + leaf(h * 0.68 - droop, r * 0.95) + leaf(h * 0.95 - droop * 0.5, r * 0.65);
  }
  return { stem, leaves };
}

const CROP_KINDS = {
  vine: { hmax: 2.4, rmax: 0.55, fruit: true },
  bush: { hmax: 1.0, rmax: 0.5, fruit: false },
  rosette: { hmax: 0.3, rmax: 0.32, fruit: false },
};

function mount(svg, cfg) {
  svg.innerHTML = "";
  const W = 760, H = 460;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.style.overflow = "hidden";  // rain and sky stay inside the figure
  const open = cfg.system === "OPEN_FIELD";
  const kind = CROP_KINDS[cfg.cropKind] || CROP_KINDS.vine;

  // ---- geometry ----
  let L, Wd, rows = [], pillars = [], facets = [], ventFacets = [], zTop, gutter = 0;
  const spans = cfg.spans || 1;
  if (open) {
    L = cfg.field.length; Wd = cfg.field.width; zTop = 1;
    const rowCount = Math.floor(Wd / cfg.field.rowSpacing), perRow = Math.floor(L / cfg.field.plantSpacing);
    const stride = Math.max(1, Math.ceil(perRow / 22));
    for (let r = 0; r < rowCount; r++) {
      for (let p = 0; p < perRow; p += stride) rows.push({ x: (p + 0.5) * cfg.field.plantSpacing + (L - perRow * cfg.field.plantSpacing) / 2, y: (r + 0.5) * cfg.field.rowSpacing });
    }
  } else {
    gutter = cfg.gutter;
    const span = cfg.span, prof = cfg.profile.map(([y, z]) => [y, z + gutter]);
    L = cfg.bays * cfg.pillar; Wd = span * spans; zTop = Math.max(...prof.map((p) => p[1]));
    let apex = 0; prof.forEach((p, i) => { if (p[1] > prof[apex][1]) apex = i; });
    const ventIndex = apex > 0 ? apex - 1 : 0;
    for (let s = 0; s < spans; s++) {
      const y0 = s * span;
      for (let i = 0; i < prof.length - 1; i++) {
        const f = { kind: "roof", span: s, index: i, pts: [[0, y0 + prof[i][0], prof[i][1]], [L, y0 + prof[i][0], prof[i][1]], [L, y0 + prof[i + 1][0], prof[i + 1][1]], [0, y0 + prof[i + 1][0], prof[i + 1][1]]] };
        facets.push(f);
        if (i === ventIndex) {
          const hinge = prof[apex], lower = prof[i === apex ? i + 1 : i];
          ventFacets.push({ facet: f, hinge: [y0 + hinge[0], hinge[1]], lower: [y0 + lower[0], lower[1]] });
        }
      }
      for (const x of [0, L]) facets.push({ kind: "end", pts: [[x, y0, 0], [x, y0 + span, 0], ...prof.slice().reverse().map(([y, z]) => [x, y0 + y, z])] });
    }
    if (gutter > 0) for (const y of [0, Wd]) facets.push({ kind: "side", pts: [[0, y, 0], [L, y, 0], [L, y, gutter], [0, y, gutter]] });
    // rows: 4 per span, plants every 1.5 m (rendered subset of the real planting density)
    for (let s = 0; s < spans; s++) for (let k = 0; k < 4; k++) {
      const y = s * span + span * (0.14 + 0.72 * (k / 3));
      for (let x = 1.5; x < L - 1; x += 1.5) rows.push({ x, y });
    }
    if (gutter > 0) for (let i = 0; i <= cfg.bays; i++) for (let s = 0; s <= spans; s++) pillars.push({ x: i * cfg.pillar, y: s * span });
  }
  const az = cfg.azimuth == null ? 45 : cfg.azimuth;
  const pad = open ? 5 : 3;
  const P = K.fitProjection([[-pad, -pad, -0.3], [L + pad, -pad, -0.3], [L + pad, Wd + pad, -0.3], [-pad, Wd + pad, -0.3], [0, 0, zTop + 1], [L, Wd, zTop + 1], [0, Wd, zTop + 1], [L, 0, zTop + 1]], W, H - 70, { pad: 26, azimuth: az });
  P.origin[1] += 36;

  // ---- static layers ----
  const defs = el("defs", {}, svg), clipId = "scene-clip-" + (mount.count = (mount.count || 0) + 1);
  el("rect", { x: 0, y: 0, width: W, height: H, rx: 12 }, el("clipPath", { id: clipId }, defs));
  const sky = el("g", { class: "sky" }, svg);
  const skyRect = el("rect", { x: 0, y: 0, width: W, height: H, rx: 12 }, sky);
  const body = el("g", {}, el("g", { "clip-path": `url(#${clipId})` }, svg));
  const ground = el("g", {}, body);
  ground.innerHTML = K.solidSvg(K.slabOf({ x: -pad, y: -pad, w: L + pad * 2, d: Wd + pad * 2, r: 2 }, -0.3, 0.3, P, 8, 0.4), { tone: "lo", crease: "faint", halo: true })
    + K.solidSvg(K.slabOf({ x: 0, y: 0, w: L, d: Wd, r: 0 }, 0, 0.02, P, 2), { tone: open ? "lo" : "faint", flat: true, crease: "none" });
  if (open) {
    ground.lastChild.classList.add("soil");
    const furrows = [];
    for (let r = 0; r < Math.floor(Wd / cfg.field.rowSpacing); r++) { const y = (r + 0.5) * cfg.field.rowSpacing; furrows.push(K.pathOf([K.iso([0, y, 0.02], P), K.iso([L, y, 0.02], P)])); }
    el("path", { class: "iso-line", "data-tone": "faint", d: furrows.join("") }, ground);
  }

  const interior = el("g", {}, body);
  const items = [];
  rows.forEach((pos, i) => items.push({ type: "plant", pos, i, depth: K.depthOf([pos.x, pos.y, 0], P) }));
  pillars.forEach((pos) => items.push({ type: "pillar", pos, depth: K.depthOf([pos.x, pos.y, gutter / 2], P) }));
  items.sort((a, b) => a.depth - b.depth);
  const plants = [];
  for (const it of items) {
    if (it.type === "pillar") {
      const holder = el("g", {}, interior);
      holder.innerHTML = K.solidSvg(K.cylinder(it.pos.x, it.pos.y, 0.12, 0, gutter, P, 12), { tone: "mid", crease: "none" });
    } else {
      const g = el("g", { class: "plant" }, interior);
      const stem = el("path", { class: "stem" }, g), leaves = el("path", { class: "leaves" }, g);
      const fruit = [0, 1, 2].map(() => el("circle", { class: "fruit", r: 1.7 }, g));
      plants.push({ g, stem, leaves, fruit, pos: it.pos, rank: lossRank(it.i) });
    }
  }

  const ribs = el("g", { class: "ribs" }, body), screen = el("g", { class: "screen" }, body);
  const hole = el("g", { class: "hole" }, body), cover = el("g", { class: "cover" }, body), flaps = el("g", { class: "flaps" }, body);
  const edge = el("g", { class: "edges" }, body), rain = el("g", { class: "rain", "clip-path": `url(#${clipId})` }, svg), hud = el("g", { class: "hud" }, svg);
  const coverPaths = [];
  if (!open) {
    const prof = cfg.profile.map(([y, z]) => [y, z + gutter]);
    const ribD = [], seamD = [];
    const stations = cfg.bays;
    for (let i = 0; i <= stations; i++) for (let s = 0; s < spans; s++) ribD.push(K.pathOf(prof.map(([y, z]) => K.iso([i * cfg.pillar, s * cfg.span + y, z], P))));
    el("path", { class: "iso-line", "data-tone": "mid", d: ribD.join("") }, ribs);
    prof.forEach(([y, z]) => { for (let s = 0; s < spans; s++) seamD.push(K.pathOf([K.iso([0, s * cfg.span + y, z], P), K.iso([L, s * cfg.span + y, z], P)])); });
    el("path", { class: "iso-line", "data-tone": "lo", d: seamD.join("") }, ribs);
    const sorted = facets.slice().sort((a, b) => depthOfFacet(a) - depthOfFacet(b));
    function depthOfFacet(f) { const c = f.pts.reduce((a, p) => [a[0] + p[0] / f.pts.length, a[1] + p[1] / f.pts.length, a[2] + p[2] / f.pts.length], [0, 0, 0]); return K.depthOf(c, P); }
    for (const f of sorted) {
      const path = el("path", { d: K.pathOf(f.pts.map((p) => K.iso(p, P)), true) }, cover);
      f.node = path;
      if (f.kind !== "roof") el("path", { class: "iso-line", "data-tone": "lo", d: path.getAttribute("d") }, edge);
    }
    const gut = [];
    for (let s = 0; s <= spans; s++) gut.push(K.pathOf([K.iso([0, s * cfg.span, prof[0][1]], P), K.iso([L, s * cfg.span, prof[0][1]], P)]));
    el("path", { class: "iso-line", "data-tone": "hi", d: gut.join("") }, edge);
    ventFacets.forEach((v) => { v.hole = el("path", { d: v.facet.node.getAttribute("d") }, hole); v.flap = el("path", {}, flaps); v.flapEdge = el("path", { class: "iso-line", "data-tone": "mid" }, flaps); });
    var screenPoly = el("path", { class: "screen-sheet" }, screen), screenEdge = el("path", { class: "iso-line", "data-tone": "hi" }, screen);
    var screenZ = gutter > 0 ? gutter - 0.35 : zTop * 0.6;
  }
  // Rain: screen-space streaks. Positions follow a golden-ratio sequence (deterministic, no random); negative animation
  // delays spread them over the whole height at any instant. Count, speed, length and slant follow the state.
  const RAIN_MAX = 560, GOLDEN = 0.61803398875;
  const streaks = Array.from({ length: RAIN_MAX }, (_, i) => {
    const x = ((i * GOLDEN) % 1) * (W + 120) - 60, y0 = ((i * GOLDEN * 7.31) % 1) * H;
    const path = el("path", { d: "M0 0" }, rain);
    path.dataset.x = x.toFixed(1); path.style.setProperty("--y0", y0.toFixed(0) + "px");
    return path;
  });

  const hudOut = el("text", { x: 18, y: 26, class: "hud-text" }, hud), hudIn = el("text", { x: W - 18, y: 26, class: "hud-text", "text-anchor": "end" }, hud);
  const hudLine = (parent, n) => Array.from({ length: n }, (_, i) => el("tspan", { x: parent.getAttribute("x"), dy: i ? 15 : 0 }, parent));
  const outLines = hudLine(hudOut, 5), inLines = hudLine(hudIn, 5);
  const sun = el("circle", { r: 11, class: "sun" }, sky);
  const windArrow = el("path", { class: "wind" }, hud);

  function update(s) {
    const o = s.outdoor, ind = s.indoor, a = s.actuators || {}, c = s.crop;
    // sky and sun
    const solar = clamp((o.solar_w_m2 || 0) / 900);
    const wet = clamp((o.rain_mm_h || 0) / 3);
    skyRect.setAttribute("fill", `hsl(${lerp(228, 205, solar).toFixed(0)} ${(lerp(38, 70, solar) * (1 - 0.6 * wet)).toFixed(0)}% ${(lerp(14, 90, solar) * (1 - 0.4 * wet)).toFixed(0)}%)`);
    const day = clamp((s.hour - 6) / 12);
    sun.setAttribute("cx", (80 + (W - 160) * day).toFixed(0)); sun.setAttribute("cy", (150 - 110 * Math.sin(Math.PI * day)).toFixed(0));
    sun.setAttribute("opacity", (0.2 + 0.8 * solar).toFixed(2)); sun.setAttribute("fill", solar > 0.02 ? "hsl(45 95% 60%)" : "hsl(220 15% 75%)");
    // rain: intensity 0..1 from mm/h (10 mm/h = heavy); slant follows the wind blowing towards screen-right/left
    const intensity = clamp((o.rain_mm_h || 0) / 10), shown = Math.round(RAIN_MAX * Math.pow(intensity, 0.7));
    const windTo = ((o.wind_dir_deg || 0) + 180) * Math.PI / 180, slant = Math.sin(windTo) * clamp((o.wind_m_s || 0) / 12) * 18;
    const dropLen = 10 + 14 * intensity, dur = 1.1 - 0.5 * intensity;
    rain.style.setProperty("--dx", (slant * ((H + 40) / dropLen)).toFixed(0) + "px"); rain.style.setProperty("--fall", (H + 40) + "px");
    streaks.forEach((p, i) => {
      if (i >= shown) { p.style.display = "none"; return; }
      p.style.display = "";
      p.setAttribute("d", `M${p.dataset.x} 0l${slant.toFixed(1)} ${dropLen.toFixed(1)}`);
      p.setAttribute("opacity", (0.55 + 0.35 * intensity).toFixed(2));
      p.style.animationDuration = (dur * (0.85 + 0.3 * ((i * 0.37) % 1))).toFixed(2) + "s";
      p.style.animationDelay = (-(i / RAIN_MAX) * dur * 2).toFixed(2) + "s";
    });
    skyRect.setAttribute("opacity", (0.55 + 0.25 * intensity).toFixed(2));
    // wind arrow: points where the wind blows to (direction given as meteorological "from")
    const to = ((o.wind_dir_deg || 0) + 180) * Math.PI / 180, len = 6 + 5 * (o.wind_m_s || 0);
    const cx = 64, cy = H - 44, dx = Math.sin(to) * len, dy = -Math.cos(to) * len * 0.6;
    const tx = cx + dx / 2, ty = cy + dy / 2, back = Math.atan2(dy, dx) + Math.PI, head = (da) => `M${tx.toFixed(1)} ${ty.toFixed(1)}l${(7 * Math.cos(back + da)).toFixed(1)} ${(7 * Math.sin(back + da)).toFixed(1)}`;
    windArrow.setAttribute("d", `M${(cx - dx / 2).toFixed(1)} ${(cy - dy / 2).toFixed(1)}L${tx.toFixed(1)} ${ty.toFixed(1)}${head(0.45)}${head(-0.45)}`);
    windArrow.setAttribute("stroke-width", "2"); windArrow.setAttribute("opacity", (o.wind_m_s > 0.2 ? 1 : 0.25).toFixed(2));

    // plants: growth, health, loss
    const laiFrac = clamp(c.lai / (c.lai_max || 4));
    const grow = Math.pow(laiFrac, 0.6);
    const lossFraction = clamp((c.cumulative_stress - 0.8) / 0.2);
    const style = plantStyle(c, false), lostStyle = plantStyle(c, true);
    plants.forEach((pl) => {
      const lost = pl.rank < lossFraction, st = lost ? lostStyle : style;
      const h = lost ? Math.max(0.06, kind.hmax * 0.05) : Math.max(0.05, kind.hmax * grow);
      const r = lost ? 0.05 : kind.rmax * (0.25 + 0.75 * grow) * st.narrow;
      const shape = plantShape(P, pl.pos.x, pl.pos.y, h, r, cfg.cropKind, h * st.droop);
      pl.stem.setAttribute("d", shape.stem); pl.stem.setAttribute("stroke", st.fill);
      pl.leaves.setAttribute("d", lost ? "" : shape.leaves); pl.leaves.setAttribute("fill", st.fill);
      pl.leaves.setAttribute("stroke", st.stroke); pl.leaves.setAttribute("stroke-width", (st.strokeWidth * 1.5).toFixed(2)); pl.leaves.setAttribute("stroke-dasharray", st.dash);
      const nFruit = kind.fruit && !lost && c.fruit_fraction != null ? Math.round(3 * clamp(c.fruit_fraction)) : 0;
      pl.fruit.forEach((f, k) => {
        if (k < nFruit) {
          const p = K.iso([pl.pos.x + (k - 1) * r * 0.5, pl.pos.y + 0.1, h * (0.45 + 0.1 * k)], P);
          f.setAttribute("cx", p[0].toFixed(1)); f.setAttribute("cy", p[1].toFixed(1));
          f.setAttribute("fill", `hsl(${lerp(95, 6, clamp(c.fruit_ripeness || 0)).toFixed(0)} 70% 48%)`); f.setAttribute("opacity", "1");
        } else f.setAttribute("opacity", "0");
      });
    });

    if (!open) {
      const tint = tempColour(ind.temp_c);
      cover.setAttribute("fill", tint); cover.style.fill = tint;
      // roof vents: flap rotates about the hinge by opening x 40 degrees, outward
      const opening = clamp(a.vent_opening || 0), ang = opening * 40 * Math.PI / 180;
      ventFacets.forEach((v) => {
        const f = v.facet, vy = v.lower[0] - v.hinge[0], vz = v.lower[1] - v.hinge[1], mag = Math.hypot(vy, vz);
        let ny = -vz / mag, nz = vy / mag; if (nz < 0) { ny = -ny; nz = -nz; }
        const ly = v.hinge[0] + vy * Math.cos(ang) + ny * mag * Math.sin(ang), lz = v.hinge[1] + vz * Math.cos(ang) + nz * mag * Math.sin(ang);
        const pts = [[0, ly, lz], [L, ly, lz], [L, v.hinge[0], v.hinge[1]], [0, v.hinge[0], v.hinge[1]]];
        const d = K.pathOf(pts.map((p) => K.iso(p, P)), true);
        f.node.style.display = opening > 0.02 ? "none" : "";
        v.hole.style.display = opening > 0.02 ? "" : "none";
        v.flap.setAttribute("d", d); v.flapEdge.setAttribute("d", d);
        v.flap.style.display = v.flapEdge.style.display = opening > 0.02 ? "" : "none";
      });
      // thermal/shade screen: sheet deploying from x = 0 along the length
      const dep = clamp(a.screen_deployed || 0), xs = L * dep;
      screen.style.display = dep > 0.01 ? "" : "none";
      if (dep > 0.01) {
        const pts = [[0, 0, screenZ], [xs, 0, screenZ], [xs, Wd, screenZ], [0, Wd, screenZ]].map((p) => K.iso(p, P));
        screenPoly.setAttribute("d", K.pathOf(pts, true));
        screenEdge.setAttribute("d", K.pathOf([K.iso([xs, 0, screenZ], P), K.iso([xs, Wd, screenZ], P)]));
      }
    }

    // HUD: every number with units; unavailable stays "n/a" (never zero)
    const f1 = (v, u, d = 1) => (v == null ? "n/a" : `${v.toFixed(d)} ${u}`);
    outLines[0].textContent = `OUTDOOR  ${s.forcing_label || ""}`;
    outLines[1].textContent = `T ${f1(o.temp_c, "C")}   RH ${f1(o.rh_pct, "%", 0)}`;
    outLines[2].textContent = `Rad ${f1(o.solar_w_m2, "W/m2", 0)}   t ${String(Math.floor(s.hour)).padStart(2, "0")}:${String(Math.round((s.hour % 1) * 60)).padStart(2, "0")}`;
    outLines[3].textContent = `Wind ${f1(o.wind_m_s, "m/s")} from ${o.wind_dir_deg == null ? "n/a" : o.wind_dir_deg + " deg"}`;
    outLines[4].textContent = `Rain ${f1(o.rain_mm_h, "mm/h")}`;
    if (open) {
      inLines[0].textContent = "OPEN FIELD"; inLines[1].textContent = "crop sees outdoor weather";
      inLines[2].textContent = "no thermal backend"; inLines[3].textContent = ""; inLines[4].textContent = "";
    } else {
      inLines[0].textContent = `INDOOR  ${s.backend_label || ""}`;
      inLines[1].textContent = `T ${f1(ind.temp_c, "C")}   RH ${f1(ind.rh_pct, "%", 0)}`;
      inLines[2].textContent = `CO2 ${f1(ind.co2_ppm, "ppm", 0)}`;
      inLines[3].textContent = `Vents ${(100 * (a.vent_opening || 0)).toFixed(0)}%  Screen ${(100 * (a.screen_deployed || 0)).toFixed(0)}%`;
      inLines[4].textContent = `Heater ${a.heater_kw == null ? "n/a" : a.heater_kw.toFixed(1) + " kW"}`;
    }
  }
  const view = { k: 1, x: 0, y: 0 };
  function applyView() {
    view.k = clamp(view.k, 1, 6);
    const maxX = (view.k - 1) * W / 2 + 40, maxY = (view.k - 1) * H / 2 + 40;
    view.x = clamp(view.x, -maxX, maxX); view.y = clamp(view.y, -maxY, maxY);
    body.setAttribute("transform", `translate(${(W / 2 + view.x).toFixed(1)} ${(H / 2 + view.y).toFixed(1)}) scale(${view.k.toFixed(3)}) translate(${-W / 2} ${-H / 2})`);
  }
  function zoomAt(factor, px, py) {  // px, py in viewBox units; that point stays still
    const next = clamp(view.k * factor, 1, 6), r = next / view.k;
    view.x = (px - W / 2) - ((px - W / 2) - view.x) * r; view.y = (py - H / 2) - ((py - H / 2) - view.y) * r; view.k = next; applyView();
  }
  const toBox = (e) => { const b = svg.getBoundingClientRect(); return [(e.clientX - b.left) * W / b.width, (e.clientY - b.top) * H / b.height]; };
  const reset = () => { view.k = 1; view.x = view.y = 0; applyView(); };
  let drag = null;
  svg.style.touchAction = "none"; svg.style.cursor = "grab"; svg.tabIndex = 0;
  svg.onwheel = (e) => { e.preventDefault(); const [px, py] = toBox(e); zoomAt(e.deltaY < 0 ? 1.15 : 1 / 1.15, px, py); };
  svg.onpointerdown = (e) => { drag = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y }; svg.setPointerCapture(e.pointerId); svg.style.cursor = "grabbing"; };
  svg.onpointermove = (e) => { if (!drag) return; const b = svg.getBoundingClientRect(); view.x = drag.vx + (e.clientX - drag.x) * W / b.width; view.y = drag.vy + (e.clientY - drag.y) * H / b.height; applyView(); };
  svg.onpointerup = svg.onpointercancel = () => { drag = null; svg.style.cursor = "grab"; };
  svg.ondblclick = reset;
  svg.onkeydown = (e) => {
    const step = 30; let used = true;
    if (e.key === "+" || e.key === "=") zoomAt(1.25, W / 2, H / 2); else if (e.key === "-") zoomAt(0.8, W / 2, H / 2);
    else if (e.key === "0") reset();
    else if (e.key === "ArrowLeft") { view.x += step; applyView(); } else if (e.key === "ArrowRight") { view.x -= step; applyView(); }
    else if (e.key === "ArrowUp") { view.y += step; applyView(); } else if (e.key === "ArrowDown") { view.y -= step; applyView(); } else used = false;
    if (used) e.preventDefault();
  };
  applyView();
  return { update, plantCount: plants.length, geometry: { length: L, width: Wd, top: zTop }, zoom: (f) => zoomAt(f, W / 2, H / 2), resetView: reset };
}

// Plant inspector: one large plant in the current state next to a healthy reference with the same LAI.
function inspector(svg, cropKind) {
  const kind = CROP_KINDS[cropKind] || CROP_KINDS.vine, W = 330, H = 312;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.innerHTML = "";
  const slots = [{ label: "HEALTHY REFERENCE", x0: 85 }, { label: "CURRENT STATE", x0: 245 }].map((slot) => {
    const g = el("g", {}, svg);
    el("path", { d: `M${slot.x0 - 62} 218l62 -31l62 31l-62 31z`, class: "inspect-ground" }, g);
    const stem = el("path", { class: "stem" }, g), leaves = el("path", { class: "leaves" }, g), fruit = [0, 1, 2].map(() => el("circle", { class: "fruit", r: 5 }, g));
    el("text", { x: slot.x0, y: 262, "text-anchor": "middle", class: "hud-text small" }, g).textContent = slot.label;
    return { ...slot, stem, leaves, fruit };
  });
  const bars = ["water", "temperature", "vpd", "cumulative"].map((name, i) => {
    const y = 272 + i * 10;
    el("text", { x: 8, y: y + 6, class: "hud-text tiny" }, svg).textContent = name.toUpperCase();
    el("rect", { x: 92, y: y, width: 190, height: 6, class: "bar-track" }, svg);
    return { fill: el("rect", { x: 92, y: y, width: 0, height: 6, class: "bar-fill" }, svg), val: el("text", { x: 290, y: y + 6, class: "hud-text tiny" }, svg) };
  });
  function draw(slot, c, lost) {
    const P = { origin: [slot.x0, 218], scale: 66, azimuth: 45, elevation: 30 };
    const st = plantStyle(c, lost), grow = Math.pow(clamp(c.lai / (c.lai_max || 4)), 0.6);
    const h = lost ? 0.12 : Math.max(0.05, kind.hmax * grow), r = lost ? 0.1 : kind.rmax * (0.25 + 0.75 * grow) * st.narrow;
    const shape = plantShape(P, 0, 0, h, r * 1.3, cropKind, h * st.droop);
    slot.stem.setAttribute("d", shape.stem); slot.stem.setAttribute("stroke", st.fill); slot.stem.setAttribute("stroke-width", 2);
    slot.leaves.setAttribute("d", lost ? "" : shape.leaves); slot.leaves.setAttribute("fill", st.fill); slot.leaves.setAttribute("stroke", st.stroke);
    slot.leaves.setAttribute("stroke-width", (st.strokeWidth * 1.6).toFixed(2)); slot.leaves.setAttribute("stroke-dasharray", st.dash);
    const n = kind.fruit && !lost && c.fruit_fraction != null ? Math.round(3 * clamp(c.fruit_fraction)) : 0;
    slot.fruit.forEach((f, k) => {
      if (k < n) { const p = K.iso([(k - 1) * r * 0.9, 0.12, h * (0.45 + 0.1 * k)], P); f.setAttribute("cx", p[0].toFixed(1)); f.setAttribute("cy", p[1].toFixed(1)); f.setAttribute("fill", `hsl(${lerp(95, 6, clamp(c.fruit_ripeness || 0)).toFixed(0)} 70% 48%)`); f.setAttribute("opacity", 1); }
      else f.setAttribute("opacity", 0);
    });
  }
  return {
    update(c) {
      draw(slots[0], { lai: c.lai, lai_max: c.lai_max, fruit_fraction: c.fruit_fraction, fruit_ripeness: c.fruit_ripeness, cumulative_stress: 0, water_stress: 0 }, false);
      draw(slots[1], c, clamp((c.cumulative_stress - 0.8) / 0.2) >= 0.999);
      [c.water_stress, c.temperature_stress || 0, c.vpd_stress || 0, c.cumulative_stress].forEach((v, i) => { bars[i].fill.setAttribute("width", (190 * clamp(v)).toFixed(0)); bars[i].val.textContent = v.toFixed(2); });
    },
  };
}
window.GreenhouseScene = { mount, inspector };
