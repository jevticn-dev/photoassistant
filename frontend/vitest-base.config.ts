import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

/**
 * Extra Vitest configuration the Angular unit-test builder cannot express.
 *
 * Picked up because `runnerConfig: true` is set on the test targets in
 * `angular.json`; the builder searches for this exact filename.
 *
 * The only thing here is file-system reach. Vitest serves files through Vite,
 * which refuses to read anything above its root — and its root is `frontend/`.
 * The edit-schema agreement test has to read `fixtures/edits/*.json`, the very
 * same files the Python and C# tests read, so it needs one level up. Copying the
 * fixtures into the frontend instead would defeat the point of the test: three
 * languages agreeing on three copies proves nothing.
 *
 * Why a plugin rather than a plain `server.fs.allow` entry. The builder does not
 * hand the whole configuration file to the test project — it takes `test` and
 * the user plugins and builds the project configuration itself, so a top-level
 * `server` block is dropped on the way. A plugin's `config` hook runs as part of
 * that project, which is the one place the setting survives.
 */
const repositoryRoot = fileURLToPath(new URL('..', import.meta.url));

export default defineConfig({
  plugins: [
    {
      name: 'photoassistant:fixture-access',
      config: () => ({ server: { fs: { allow: [repositoryRoot] } } }),
    },
  ],
});
