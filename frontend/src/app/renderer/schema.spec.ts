/**
 * Agreement over the shared fixtures, and the validation rules behind it.
 *
 * The edit schema exists as three models — Python, C# and TypeScript. Agreement
 * is proven rather than assumed: each parses the same files from
 * `fixtures/edits/` and re-serialising must produce the same document
 * (`docs/edit_schema_v1.md` §8). This is the TypeScript half of that claim; the
 * Python half is `ml/tests/test_schema_roundtrip.py`, and the assertions are
 * deliberately the same ones.
 *
 * The fixtures are read from outside the frontend project, which is the point —
 * a copy inside `frontend/` would let three languages agree on three different
 * files. `vitest-base.config.ts` opens that one path.
 *
 * What "the same document" means, precisely. The comparison is over parsed
 * values, not bytes: `JSON.stringify` writes `0` where Python writes `0.0`, and
 * neither is wrong. Comparing bytes would turn a language detail into a spurious
 * failure.
 */

import { describe, expect, it } from 'vitest';

import {
  EditSchemaError,
  SCHEMA_VERSION,
  fromJson,
  isNeutralRecipe,
  toJson,
  type EditRecipe,
} from './schema';

const EXPECTED_FIXTURES = ['curve_only', 'extreme', 'neutral', 'warm_bright'];

const sources = import.meta.glob('../../../../fixtures/edits/*.json', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>;

const fixtures = new Map(
  Object.entries(sources).map(([path, text]) => [
    path.replace(/^.*\/(.*)\.json$/, '$1'),
    text as string,
  ]),
);

function fixture(name: string): string {
  const text = fixtures.get(name);
  if (text === undefined) {
    throw new Error(`fixture ${name} not found; found ${[...fixtures.keys()].join(', ')}`);
  }
  return text;
}

describe('edit schema fixtures', () => {
  it('finds the expected fixtures', () => {
    // Guards the tests below: iterating an empty directory passes vacuously.
    expect([...fixtures.keys()].sort()).toEqual(EXPECTED_FIXTURES);
  });

  it.each(EXPECTED_FIXTURES)('round-trips %s unchanged', (name) => {
    const text = fixture(name);

    const reserialised = toJson(fromJson(text));

    expect(JSON.parse(reserialised)).toEqual(JSON.parse(text));
  });

  it.each(EXPECTED_FIXTURES)('is stable at the model level for %s', (name) => {
    const recipe = fromJson(fixture(name));

    expect(fromJson(toJson(recipe))).toEqual(recipe);
  });

  it.each(EXPECTED_FIXTURES)('declares the supported version in %s', (name) => {
    expect(fromJson(fixture(name)).schema).toBe(SCHEMA_VERSION);
  });

  it('reads neutral.json as the identity recipe', () => {
    expect(isNeutralRecipe(fromJson(fixture('neutral')))).toBe(true);
  });

  it.each(['warm_bright', 'extreme', 'curve_only'])('reads %s as not neutral', (name) => {
    expect(isNeutralRecipe(fromJson(fixture(name)))).toBe(false);
  });

  it('reads curve_only as touching nothing but the curve', () => {
    const recipe = fromJson(fixture('curve_only'));
    const neutral = fromJson(fixture('neutral'));

    expect(recipe.whiteBalance).toEqual(neutral.whiteBalance);
    expect(recipe.tone).toEqual(neutral.tone);
    expect(recipe.color).toEqual(neutral.color);
    expect(recipe.toneCurve).not.toEqual(neutral.toneCurve);
  });
});

describe('edit schema validation', () => {
  it('reads an omitted group as neutral and writes it back', () => {
    const recipe = fromJson('{"schema": 1, "color": {"vibrance": 30.0}}');

    expect(recipe.tone.exposure).toBe(0);
    expect(recipe.color.saturation).toBe(0);
    expect(recipe.color.vibrance).toBe(30);

    const written = JSON.parse(toJson(recipe)) as Record<string, unknown>;
    expect(Object.keys(written).sort()).toEqual(
      ['color', 'schema', 'tone', 'tone_curve', 'white_balance'].sort(),
    );
    expect((written['tone_curve'] as { points: number[][] }).points).toEqual([
      [0, 0],
      [1, 1],
    ]);
  });

  it('refuses a newer schema', () => {
    // edit_schema §7: a reader refuses what it does not understand rather than
    // guessing at it.
    expect(() => fromJson('{"schema": 2}')).toThrow(/unsupported schema version/);
  });

  it('refuses a recipe with no schema version', () => {
    expect(() => fromJson('{"tone": {"exposure": 1.0}}')).toThrow(EditSchemaError);
  });

  it('refuses an unknown key', () => {
    // A misspelled parameter silently dropped would render as neutral and hide
    // as fitting residual.
    expect(() => fromJson('{"schema": 1, "tone": {"exposure": 0.0, "clarity": 40.0}}')).toThrow(
      /unknown key/,
    );
  });

  it.each([
    ['exposure over +5 stops', '{"schema": 1, "tone": {"exposure": 5.5}}'],
    ['contrast over +100', '{"schema": 1, "tone": {"contrast": 101.0}}'],
    ['temperature under -100', '{"schema": 1, "white_balance": {"temperature": -101.0}}'],
    ['vibrance over +100', '{"schema": 1, "color": {"vibrance": 200.0}}'],
  ])('refuses a value outside the declared range: %s', (_label, document) => {
    expect(() => fromJson(document)).toThrow(EditSchemaError);
  });

  it.each([
    ['a single point is not a curve', '[[0.0, 0.0]]'],
    ['does not start at x = 0', '[[0.2, 0.0], [1.0, 1.0]]'],
    ['does not end at x = 1', '[[0.0, 0.0], [0.8, 1.0]]'],
    ['x repeats', '[[0.0, 0.0], [0.5, 0.4], [0.5, 0.6], [1.0, 1.0]]'],
    ['x decreases', '[[0.0, 0.0], [0.7, 0.4], [0.3, 0.6], [1.0, 1.0]]'],
    ['y outside [0, 1]', '[[0.0, 0.0], [0.5, 1.4], [1.0, 1.0]]'],
  ])('refuses a curve breaking spec §6.1: %s', (_label, points) => {
    expect(() => fromJson(`{"schema": 1, "tone_curve": {"points": ${points}}}`)).toThrow(
      EditSchemaError,
    );
  });

  it('allows a lifted black point', () => {
    // Only x is constrained to the endpoints; y is free, which is what a faded
    // look needs.
    const recipe: EditRecipe = fromJson(
      '{"schema": 1, "tone_curve": {"points": [[0.0, 0.1], [1.0, 0.9]]}}',
    );

    expect(recipe.toneCurve.points).toEqual([
      [0, 0.1],
      [1, 0.9],
    ]);
  });

  it('refuses a value that is not a number', () => {
    expect(() => fromJson('{"schema": 1, "tone": {"exposure": "1.0"}}')).toThrow(EditSchemaError);
  });
});
