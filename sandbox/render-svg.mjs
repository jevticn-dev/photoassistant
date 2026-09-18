// Renders the hand-written SVG diagrams to PNG, next to the source.
//
//   node sandbox/render-svg.mjs docs/thesis/figures/*.svg
//
// Two reasons, and the second is the one that matters. First, a diagram should
// never be called finished without having been looked at. Second, the thesis
// markdown references PNG for **every** figure, diagrams included: SVG is the
// better master, but converters differ in how they treat it, and a document that
// has to survive being handed to an unknown tool is better off uniform. The SVG
// stays as the editable source; this produces what the document points at.
//
// Playwright lives in `frontend/node_modules`, and this script does not, so the
// import is resolved from there explicitly rather than by walking up from here.

import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(resolve(here, "../frontend/package.json"));
const { chromium } = require("playwright");

const files = process.argv.slice(2);
if (files.length === 0) {
  console.error("usage: node sandbox/render-svg.mjs <file.svg> ...");
  process.exit(1);
}

const browser = await chromium.launch();
for (const file of files) {
  const source = readFileSync(file, "utf8");
  const width = Number(/width="(\d+)"/.exec(source)?.[1] ?? 1000);
  const height = Number(/height="(\d+)"/.exec(source)?.[1] ?? 700);

  const page = await browser.newPage({
    viewport: { width, height },
    deviceScaleFactor: 2,
  });
  await page.setContent(
    `<body style="margin:0;background:#fff">${source}</body>`,
    { waitUntil: "load" },
  );
  const out = join(dirname(file), `${basename(file, ".svg")}.png`);
  await page.screenshot({ path: out });
  await page.close();
  console.log(out);
}
await browser.close();
