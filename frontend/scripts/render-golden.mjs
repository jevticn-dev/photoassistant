/**
 * Render every (test image x recipe) combination through the WebGL2 renderer and
 * write the results as PNGs, for the Python half of the golden test to compare.
 *
 *     npm --prefix frontend run golden
 *
 * Why the work is split across two languages at all: CIEDE2000 exists exactly
 * once in this project, in Python (`notes` §B11). Two implementations of the
 * ruler could disagree with each other, and then a failing golden test would
 * have three possible causes instead of two. So this side only produces pixels.
 *
 * Why a standalone Playwright script rather than a test in browser mode. The
 * browser has to hand a few hundred images back to disk, and writing files is
 * precisely what a browser cannot do; vitest's custom-command mechanism can, but
 * it lives under `test.browser`, which the Angular builder overwrites when it
 * configures browsers itself. A script also runs on its own when the golden test
 * fails and the next question is what the difference looks like.
 *
 * The renderer is bundled straight from source with esbuild. No Angular, no
 * framework, nothing but `src/app/renderer/` — which is the boundary
 * `boundary.spec.ts` exists to protect, seen from the other side: if the renderer
 * ever imported Angular, this bundle would be the thing that broke.
 */

import { mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import * as esbuild from 'esbuild';
import { chromium } from 'playwright';

import { encodePng } from './png.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = join(HERE, '..', '..');
const IMAGES = join(REPO, 'fixtures', 'images');
const CORPUS = join(REPO, 'fixtures', 'golden', 'recipes.json');
const OUT = join(REPO, 'ml', 'tests', 'golden', 'rendered');

async function bundleRenderer() {
  const result = await esbuild.build({
    entryPoints: [join(HERE, '..', 'src', 'app', 'renderer', 'index.ts')],
    bundle: true,
    format: 'iife',
    globalName: 'PhotoRenderer',
    platform: 'browser',
    target: 'es2022',
    write: false,
  });

  return result.outputFiles[0].text;
}

/**
 * Everything that happens inside the page, for one image and every recipe.
 *
 * `createImageBitmap` is given both options explicitly. Left at their defaults a
 * bitmap may arrive premultiplied or converted to the display's colour space, and
 * the shader would then be reading pixels the file never contained — a difference
 * no formula explains, which is the worst kind for a golden test to report.
 */
async function renderAll(page, pngBase64, recipes) {
  return page.evaluate(
    async ([pngBase64, recipes]) => {
      const binary = Uint8Array.from(atob(pngBase64), (c) => c.charCodeAt(0));
      const bitmap = await createImageBitmap(new Blob([binary], { type: 'image/png' }), {
        premultiplyAlpha: 'none',
        colorSpaceConversion: 'none',
      });

      const canvas = document.createElement('canvas');
      const renderer = window.PhotoRenderer.WebGlRenderer.create(canvas);
      renderer.setImageSource(bitmap, bitmap.width, bitmap.height);

      const out = [];
      for (const entry of recipes) {
        const recipe = window.PhotoRenderer.parseRecipe(entry.recipe);
        const { data, width, height } = renderer.readPixels(recipe);

        let text = '';
        for (let i = 0; i < data.length; i += 0x8000) {
          text += String.fromCharCode(...data.subarray(i, i + 0x8000));
        }
        out.push({ name: entry.name, width, height, data: btoa(text) });
      }

      renderer.dispose();
      return out;
    },
    [pngBase64, recipes],
  );
}

/** The 1024-entry table for every distinct curve in the corpus (spec §6.6). */
async function renderLuts(page, recipes) {
  const curves = new Map();
  for (const entry of recipes) {
    const points = entry.recipe.tone_curve?.points ?? [
      [0, 0],
      [1, 1],
    ];
    curves.set(JSON.stringify(points), points);
  }

  return page.evaluate(
    (curves) => {
      const out = {};
      for (const [key, points] of curves) {
        out[key] = Array.from(window.PhotoRenderer.buildLut(points));
      }
      return out;
    },
    [...curves.entries()],
  );
}

/**
 * The tone-region tables, one per distinct set of the four regional values.
 *
 * Compared array against array, exactly as the curve tables are (§6.6): the part
 * that could quietly diverge runs 1024 times per recipe rather than per pixel, so
 * the hardest question — do two hand-written implementations agree — becomes a
 * comparison of two arrays of numbers, with no picture to interpret.
 */
async function renderRegionTables(page, recipes) {
  const tables = new Map();
  for (const entry of recipes) {
    const tone = entry.recipe.tone ?? {};
    const values = {
      highlights: tone.highlights ?? 0,
      shadows: tone.shadows ?? 0,
      whites: tone.whites ?? 0,
      blacks: tone.blacks ?? 0,
    };
    tables.set(JSON.stringify(values), values);
  }

  return page.evaluate(
    (tables) => {
      const out = {};
      for (const [key, values] of tables) {
        out[key] = Array.from(
          window.PhotoRenderer.buildRegionTable({
            tone: { exposure: 0, contrast: 0, ...values },
          }),
        );
      }
      return out;
    },
    [...tables.entries()],
  );
}

async function main() {
  const bundle = await bundleRenderer();
  const { recipes } = JSON.parse(await readFile(CORPUS, 'utf-8'));
  const names = (await readdir(IMAGES)).filter((file) => file.endsWith('.png')).sort();

  await rm(OUT, { recursive: true, force: true });
  await mkdir(OUT, { recursive: true });

  const browser = await chromium.launch();
  const page = await browser.newPage();

  const problems = [];
  page.on('pageerror', (error) => problems.push(error.message));

  await page.goto('about:blank');
  await page.addScriptTag({ content: bundle });

  let written = 0;
  for (const file of names) {
    const png = await readFile(join(IMAGES, file));
    const rendered = await renderAll(page, png.toString('base64'), recipes);

    for (const { name, width, height, data } of rendered) {
      const rgba = Buffer.from(data, 'base64');
      await writeFile(
        join(OUT, `${file.replace(/\.png$/, '')}__${name}.png`),
        encodePng(rgba, width, height),
      );
      written++;
    }
    process.stdout.write(`  ${file.padEnd(24)} ${rendered.length} recipes\n`);
  }

  const luts = await renderLuts(page, recipes);
  const regionTables = await renderRegionTables(page, recipes);

  const version = await page.evaluate(() => {
    const gl = document.createElement('canvas').getContext('webgl2');
    return { version: gl.getParameter(gl.VERSION), renderer: gl.getParameter(gl.RENDERER) };
  });

  await browser.close();

  if (problems.length > 0) {
    throw new Error(`the page reported errors:\n${problems.join('\n')}`);
  }

  await writeFile(join(OUT, 'luts.json'), `${JSON.stringify(luts)}\n`);
  await writeFile(join(OUT, 'region-tables.json'), `${JSON.stringify(regionTables)}\n`);
  await writeFile(
    join(OUT, 'manifest.json'),
    `${JSON.stringify(
      {
        images: names.map((file) => file.replace(/\.png$/, '')),
        recipes: recipes.map((entry) => entry.name),
        combinations: written,
        webgl: version,
      },
      null,
      2,
    )}\n`,
  );

  console.log(`\n${written} combinations and ${Object.keys(luts).length} tables written to`);
  console.log(`  ${OUT}`);
  console.log(`  ${version.renderer}`);
}

await main();
