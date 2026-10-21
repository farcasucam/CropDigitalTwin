import { readFileSync, writeFileSync } from "node:fs";
import {
  fitProjection, iso, depthOf, pathOf, slabOf, cylinder, solidSvg, lineSvg, figureSvg, plateHtml, pageHtml,
} from "./iso-kit.mjs";

const geom = JSON.parse(readFileSync(new URL("./geom.json", import.meta.url), "utf8"));
const theme = process.argv[2] || "light";
const lai = 0.6; // demo value only: a real scene would take it from the crop engine state
const W = 640, H = 400;

const NAMES = {
  MULTITUNEL_CAPILLA: "Multitunel Capilla", MULTITUNEL_GOTICO: "Multitunel Gotico",
  MULTITUNEL_TROPICAL_ASIMETRICO: "Tropical asimetrico", MULTITUNEL_GRANDE_LUX: "Grande LUX",
  RASPA_Y_AMAGADO: "Raspa y Amagado", TUNEL: "Tunel",
};

function scene(g, index, key) {
  const L = g.length, width = g.span * g.spans;
  const top = Math.max(...g.profile.map((p) => p[1]));
  const P = fitProjection(
    [[-3, -3, -0.3], [L + 3, -3, -0.3], [L + 3, width + 3, -0.3], [-3, width + 3, -0.3], [0, 0, top], [L, width, top], [0, width, top], [L, 0, top]],
    W, H, { pad: 18 },
  );
  const out = [];
  const ground = slabOf({ x: -3, y: -3, w: L + 6, d: width + 6, r: 2 }, -0.3, 0.3, P, 8, 0.4);
  out.push(solidSvg(ground, { tone: "lo", crease: "faint", halo: true }));
  out.push(solidSvg(slabOf({ x: 0, y: 0, w: L, d: width, r: 0 }, 0, 0.02, P, 2), { tone: "faint", flat: true, crease: "none" }));

  // interior solids, painted back to front
  const interior = [];
  const rowH = 0.35 + 1.1 * lai;
  for (let s = 0; s < g.spans; s++) {
    for (let k = 0; k < 4; k++) {
      const y = s * g.span + g.span * (0.14 + 0.72 * (k / 3));
      const paths = slabOf({ x: 2, y: y - 0.3, w: L - 4, d: 0.6, r: 0.25 }, 0, rowH, P, 8, 0.15);
      interior.push({ depth: depthOf([L / 2, y, rowH / 2], P), svg: solidSvg(paths, { tone: "mid", crease: "faint", className: "crop" }) });
    }
  }
  if (g.gutter > 0) {
    const stations = Math.round(L / g.pillar_spacing);
    for (let i = 0; i <= stations; i++) {
      const x = (L * i) / stations;
      for (let s = 0; s <= g.spans; s++) {
        const y = s * g.span;
        interior.push({ depth: depthOf([x, y, g.gutter / 2], P), svg: solidSvg(cylinder(x, y, 0.12, 0, g.gutter, P, 12), { tone: "mid", crease: "none" }) });
      }
    }
  }
  interior.sort((a, b) => a.depth - b.depth);
  out.push(...interior.map((item) => item.svg));

  // structure lines: arch ribs, ridge/gutter lines
  const ribLines = [];
  const stations = Math.max(2, Math.round(L / g.pillar_spacing));
  for (let i = 0; i <= stations; i++) {
    const x = (L * i) / stations;
    for (let s = 0; s < g.spans; s++) {
      ribLines.push(pathOf(g.profile.map(([y, z]) => iso([x, s * g.span + y, z], P))));
    }
  }
  out.push(lineSvg(ribLines.join(""), { tone: "mid" }));
  const seams = g.profile.map(([y, z], i) => {
    const d = [];
    for (let s = 0; s < g.spans; s++) d.push(pathOf([iso([0, s * g.span + y, z], P), iso([L, s * g.span + y, z], P)]));
    return d.join("");
  });
  out.push(lineSvg(seams.join(""), { tone: "lo" }));

  // translucent cover: roof facets, end walls, side walls
  const facets = [];
  const poly = (pts) => pts.map((p) => iso(p, P));
  for (let s = 0; s < g.spans; s++) {
    const y0 = s * g.span;
    for (let i = 0; i < g.profile.length - 1; i++) {
      const [ya, za] = g.profile[i], [yb, zb] = g.profile[i + 1];
      const pts = [[0, y0 + ya, za], [L, y0 + ya, za], [L, y0 + yb, zb], [0, y0 + yb, zb]];
      facets.push({ pts, kind: "roof" });
    }
    for (const x of [0, L]) {
      const ring = [[x, y0, 0], [x, y0 + g.span, 0], ...g.profile.slice().reverse().map(([y, z]) => [x, y0 + y, z])];
      facets.push({ pts: ring, kind: "end" });
    }
  }
  if (g.gutter > 0) {
    for (const y of [0, width]) facets.push({ pts: [[0, y, 0], [L, y, 0], [L, y, g.gutter], [0, y, g.gutter]], kind: "side" });
  }
  facets.sort((a, b) => depthOf(a.pts.reduce((c, p) => [c[0] + p[0] / a.pts.length, c[1] + p[1] / a.pts.length, c[2] + p[2] / a.pts.length], [0, 0, 0]), P)
    - depthOf(b.pts.reduce((c, p) => [c[0] + p[0] / b.pts.length, c[1] + p[1] / b.pts.length, c[2] + p[2] / b.pts.length], [0, 0, 0]), P));
  out.push(`<g class="cover">${facets.map((f) => `<path d="${pathOf(poly(f.pts), true)}"/>`).join("")}</g>`);
  out.push(lineSvg(facets.filter((f) => f.kind !== "roof").map((f) => pathOf(poly(f.pts), true)).join(""), { tone: "lo" }));
  const gutterLine = [];
  for (let s = 0; s <= g.spans; s++) {
    const [ya, za] = s === 0 ? g.profile[0] : [0, g.profile[0][1]];
    gutterLine.push(pathOf([iso([0, s * g.span, g.profile[0][1]], P), iso([L, s * g.span, g.profile[0][1]], P)]));
  }
  out.push(lineSvg(gutterLine.join(""), { tone: "hi" }));

  const ev = g.evidence;
  const flags = Object.entries(ev).filter(([, v]) => v !== "DOCUMENTED_COMMERCIAL").map(([k]) => k.replace("_m", "")).join(", ");
  return plateHtml({
    fig: `Fig ${index + 1}`, title: NAMES[key], hint: "PARAMETRIC SCHEMATIC", readout: `${g.spans} x ${g.span} m, LAI ${lai} (demo)`,
    caption: flags ? `Provisional: ${flags}.` : "All listed dimensions documented (commercial page).",
    body: figureSvg({ width: W, height: H, label: `Isometric schematic of ${NAMES[key]}`, body: out }),
  });
}

const extra = `
<style>
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:28px}
@media (max-width:900px){.grid{grid-template-columns:1fr}}
.iso-figure{margin:0}
.iso-plate{position:relative;background:var(--anatomy-card);border-radius:14px;box-shadow:var(--anatomy-lift);padding:34px 8px 30px}
.iso-plate-corners span{position:absolute;font:10px/1 var(--anatomy-mono);letter-spacing:.08em;text-transform:uppercase;color:var(--anatomy-muted)}
[data-corner=fig]{left:16px;top:14px}[data-corner=title]{right:16px;top:14px;color:var(--anatomy-strong)!important}
[data-corner=hint]{left:16px;bottom:12px}[data-corner=readout]{right:16px;bottom:12px}
.iso-legend{display:block;color:var(--anatomy-muted);font-size:12px;margin:8px 4px 0}
.cover path{fill:var(--anatomy-blue);fill-opacity:.07;stroke:none}
.crop .iso-top{fill:var(--anatomy-green);fill-opacity:.6}
.crop .iso-fill{fill:var(--anatomy-paper)}
.crop .iso-shade{fill:var(--anatomy-green);fill-opacity:.28}
</style>`;
const body = extra + `<div class="grid">${Object.keys(NAMES).map((key, i) => scene(geom[key], i, key)).join("")}</div>`;
writeFileSync(new URL(`./greenhouses-${theme}.html`, import.meta.url), pageHtml({ title: "Greenhouse typologies (kit prototype)", theme, body, width: 1280 }));
console.log("written", theme);
