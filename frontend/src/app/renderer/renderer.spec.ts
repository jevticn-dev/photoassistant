import { describe, expect, it } from 'vitest';

/**
 * The renderer folder must not depend on Angular.
 *
 * If it ever does, the golden agreement test — same image and recipe through
 * NumPy and through WebGL2, compared by ΔE — can no longer run this code in
 * isolation, and the comparison that justifies the whole two-implementation
 * design quietly stops being possible.
 *
 * The equivalents elsewhere: LayerDependencyTests (backend) and
 * test_library_boundary.py (ML package).
 */
describe('renderer boundary', () => {
  // Vite resolves this at build time into a map of path -> file contents.
  const sources = import.meta.glob('./**/*.ts', {
    query: '?raw',
    import: 'default',
    eager: true,
  }) as Record<string, string>;

  const sourceFiles = Object.entries(sources).filter(
    ([path]) => !path.endsWith('.spec.ts'),
  );

  it('contains source files to check', () => {
    // Guards the test below: an empty folder would make it pass vacuously.
    expect(sourceFiles.length).toBeGreaterThan(0);
  });

  it('imports nothing from @angular', () => {
    const offenders = sourceFiles
      .filter(([, contents]) => /from\s+['"]@angular\//.test(contents))
      .map(([path]) => path);

    expect(offenders).toEqual([]);
  });
});
