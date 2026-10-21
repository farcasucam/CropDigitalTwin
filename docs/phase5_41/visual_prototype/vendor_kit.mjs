// Wraps the unmodified Anatomy kit (MIT) as a plain script: window.IsoKit. Run from the repo root:
//   node docs/phase5_41/visual_prototype/vendor_kit.mjs
import { readFileSync, writeFileSync, copyFileSync } from "node:fs";

const source = readFileSync(new URL("./iso-kit.mjs", import.meta.url), "utf8");
const names = [...source.matchAll(/^export (?:const|function|let) ([A-Za-z0-9_]+)/gm)].map((m) => m[1]);
const body = source.replace(/^export /gm, "");
const banner = `/* Vendored: iso-kit.mjs from https://github.com/wheresryan22/anatomy (MIT, see isokit.LICENSE).
 * Unmodified source, wrapped as a plain script exposing window.IsoKit. Presentation only (projection and SVG strings). */\n`;
const wrapped = `${banner}window.IsoKit = (function () {\n${body}\nreturn { ${names.join(", ")} };\n})();\n`;
writeFileSync(new URL("../../../frontend/vendor/isokit.iife.js", import.meta.url), wrapped);
const css = source.match(/const ISO_CSS = `([\s\S]*?)`;/)[1];
writeFileSync(new URL("../../../frontend/vendor/isokit.css", import.meta.url), `/* Vendored from the Anatomy kit (MIT, see isokit.LICENSE): ISO_CSS, unmodified. */
${css}
`);
copyFileSync(new URL("./ANATOMY_LICENSE_MIT.txt", import.meta.url), new URL("../../../frontend/vendor/isokit.LICENSE", import.meta.url));
console.log(`wrapped ${names.length} exports`);
