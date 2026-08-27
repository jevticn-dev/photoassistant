/**
 * The edit schema v1 as a TypeScript model.
 *
 * Follows `docs/edit_schema_v1.md`. One of three models of the same format; the
 * other two are the pydantic model in `ml/photoassistant/schema/model.py` and the
 * C# record in the backend. Agreement between them is proven over the shared
 * fixtures in `fixtures/edits/` rather than assumed — see `schema.spec.ts`.
 *
 * Two things this module deliberately does, matching the Python model:
 *
 * - **Rejects rather than repairs.** A recipe outside the declared ranges, or with
 *   a tone curve that breaks the rules in `RENDERER_SPEC.md` §6.1, throws. The
 *   renderer may then assume its input is valid and skip defensive checks.
 * - **Always emits every key.** Parsing accepts an omitted group and fills in the
 *   neutral value, but serialising writes the full document. That keeps the
 *   canonical form single-valued, which is what makes the three-language
 *   agreement test meaningful.
 *
 * Written by hand rather than with a validation library. The schema is small and
 * fixed, and the third model would otherwise be the only one whose rules live in
 * a dependency's DSL instead of in readable code — which is the opposite of what
 * a document meant to be compared across three languages needs.
 *
 * Naming: the model is camelCase, the wire format is snake_case, and the two are
 * mapped at the boundary. The C# model will do the same in the other direction.
 */

export const SCHEMA_VERSION = 1;

/** Every parameter but exposure shares this symmetric interval (edit_schema §3). */
const NORMALISED_LIMIT = 100;

/** Exposure is in stops and keeps physical meaning: +1 is twice the light. */
const EXPOSURE_LIMIT = 5;

/**
 * Smallest gap allowed between two curve control points on the x axis
 * (`RENDERER_SPEC.md` §6.1, added by ADR-20).
 *
 * One step of the 1024-entry table. "Strictly increasing" is not enough: two
 * points a denormal apart still increase, and the secant slope between them
 * overflows to infinity, which turns **every pixel of the image** into NaN. Two
 * points closer than one table step also describe detail the table cannot
 * represent, so the threshold is the table's own resolution rather than an
 * arbitrary epsilon.
 */
export const MIN_POINT_SPACING = 1 / 1023;

export interface WhiteBalance {
  readonly temperature: number;
  readonly tint: number;
}

export interface Tone {
  readonly exposure: number;
  readonly contrast: number;
  readonly highlights: number;
  readonly shadows: number;
  readonly whites: number;
  readonly blacks: number;
}

export interface Color {
  readonly saturation: number;
  readonly vibrance: number;
}

/** One control point of the master tone curve: (input, output), both in [0, 1]. */
export type CurvePoint = readonly [number, number];

export interface ToneCurve {
  /**
   * Control points, not the curve itself. The interpolated curve and its
   * 1024-entry LUT are built by the renderer (`RENDERER_SPEC.md` §6).
   */
  readonly points: readonly CurvePoint[];
}

export interface EditRecipe {
  readonly schema: number;
  readonly whiteBalance: WhiteBalance;
  readonly tone: Tone;
  readonly color: Color;
  readonly toneCurve: ToneCurve;
}

/** Thrown for anything the schema refuses. Never used to signal a repaired value. */
export class EditSchemaError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'EditSchemaError';
  }
}

export const NEUTRAL_CURVE: readonly CurvePoint[] = [
  [0, 0],
  [1, 1],
];

export const NEUTRAL_RECIPE: EditRecipe = {
  schema: SCHEMA_VERSION,
  whiteBalance: { temperature: 0, tint: 0 },
  tone: { exposure: 0, contrast: 0, highlights: 0, shadows: 0, whites: 0, blacks: 0 },
  color: { saturation: 0, vibrance: 0 },
  toneCurve: { points: NEUTRAL_CURVE },
};

// --------------------------------------------------------------- validation

function asObject(value: unknown, where: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new EditSchemaError(`${where} must be an object, got ${describe(value)}`);
  }
  return value as Record<string, unknown>;
}

function describe(value: unknown): string {
  if (value === null) {
    return 'null';
  }
  return Array.isArray(value) ? 'an array' : typeof value;
}

function rejectUnknownKeys(
  source: Record<string, unknown>,
  known: readonly string[],
  where: string,
) {
  // A misspelled parameter silently dropped would render as neutral, and the
  // difference would surface only as an unexplained fitting residual.
  const unknown = Object.keys(source).filter((key) => !known.includes(key));
  if (unknown.length > 0) {
    throw new EditSchemaError(`${where} has unknown key(s): ${unknown.join(', ')}`);
  }
}

function number(
  source: Record<string, unknown>,
  key: string,
  where: string,
  limit: number,
): number {
  const raw = source[key];
  if (raw === undefined) {
    return 0;
  }
  if (typeof raw !== 'number' || !Number.isFinite(raw)) {
    throw new EditSchemaError(`${where}.${key} must be a finite number, got ${describe(raw)}`);
  }
  if (raw < -limit || raw > limit) {
    throw new EditSchemaError(`${where}.${key} must be within [${-limit}, ${limit}], got ${raw}`);
  }
  return raw;
}

function unitInterval(raw: unknown, where: string): number {
  if (typeof raw !== 'number' || !Number.isFinite(raw)) {
    throw new EditSchemaError(`${where} must be a finite number, got ${describe(raw)}`);
  }
  if (raw < 0 || raw > 1) {
    throw new EditSchemaError(`${where} must be within [0, 1], got ${raw}`);
  }
  return raw;
}

function parseWhiteBalance(value: unknown): WhiteBalance {
  const source = asObject(value ?? {}, 'white_balance');
  rejectUnknownKeys(source, ['temperature', 'tint'], 'white_balance');
  return {
    temperature: number(source, 'temperature', 'white_balance', NORMALISED_LIMIT),
    tint: number(source, 'tint', 'white_balance', NORMALISED_LIMIT),
  };
}

function parseTone(value: unknown): Tone {
  const source = asObject(value ?? {}, 'tone');
  rejectUnknownKeys(
    source,
    ['exposure', 'contrast', 'highlights', 'shadows', 'whites', 'blacks'],
    'tone',
  );
  return {
    exposure: number(source, 'exposure', 'tone', EXPOSURE_LIMIT),
    contrast: number(source, 'contrast', 'tone', NORMALISED_LIMIT),
    highlights: number(source, 'highlights', 'tone', NORMALISED_LIMIT),
    shadows: number(source, 'shadows', 'tone', NORMALISED_LIMIT),
    whites: number(source, 'whites', 'tone', NORMALISED_LIMIT),
    blacks: number(source, 'blacks', 'tone', NORMALISED_LIMIT),
  };
}

function parseColor(value: unknown): Color {
  const source = asObject(value ?? {}, 'color');
  rejectUnknownKeys(source, ['saturation', 'vibrance'], 'color');
  return {
    saturation: number(source, 'saturation', 'color', NORMALISED_LIMIT),
    vibrance: number(source, 'vibrance', 'color', NORMALISED_LIMIT),
  };
}

function parseToneCurve(value: unknown): ToneCurve {
  const source = asObject(value ?? {}, 'tone_curve');
  rejectUnknownKeys(source, ['points'], 'tone_curve');

  if (source['points'] === undefined) {
    return { points: NEUTRAL_CURVE };
  }

  const raw = source['points'];
  if (!Array.isArray(raw)) {
    throw new EditSchemaError(`tone_curve.points must be an array, got ${describe(raw)}`);
  }
  if (raw.length < 2) {
    throw new EditSchemaError('a tone curve needs at least two points');
  }

  const points: CurvePoint[] = raw.map((entry, index) => {
    if (!Array.isArray(entry) || entry.length !== 2) {
      throw new EditSchemaError(`tone_curve.points[${index}] must be a pair [x, y]`);
    }
    return [
      unitInterval(entry[0], `tone_curve.points[${index}][0]`),
      unitInterval(entry[1], `tone_curve.points[${index}][1]`),
    ];
  });

  const first = points[0][0];
  const last = points[points.length - 1][0];
  if (first !== 0 || last !== 1) {
    // Without both endpoints the curve is undefined over part of the input
    // range, and the two implementations would have to invent the same
    // extrapolation rule.
    throw new EditSchemaError(`the first x must be 0 and the last 1, got ${first} and ${last}`);
  }

  for (let i = 1; i < points.length; i++) {
    if (points[i][0] <= points[i - 1][0]) {
      throw new EditSchemaError(
        `x values must increase strictly, got ${points.map(([x]) => x).join(', ')}`,
      );
    }
    if (points[i][0] - points[i - 1][0] < MIN_POINT_SPACING) {
      throw new EditSchemaError(
        `x values must be at least ${MIN_POINT_SPACING} apart, got ${points
          .map(([x]) => x)
          .join(', ')}`,
      );
    }
  }

  return { points };
}

/** Validate an already-parsed JSON value into a recipe, or throw. */
export function parseRecipe(value: unknown): EditRecipe {
  const source = asObject(value, 'the recipe');
  rejectUnknownKeys(
    source,
    ['schema', 'white_balance', 'tone', 'color', 'tone_curve'],
    'the recipe',
  );

  const version = source['schema'];
  if (version === undefined) {
    throw new EditSchemaError('the recipe must declare a schema version');
  }
  // edit_schema §7: a reader refuses a schema newer than it understands. Older
  // versions stay readable forever, which is why extensions are additive only.
  if (version !== SCHEMA_VERSION) {
    throw new EditSchemaError(
      `unsupported schema version ${String(version)}; this reader understands ${SCHEMA_VERSION}`,
    );
  }

  return {
    schema: SCHEMA_VERSION,
    whiteBalance: parseWhiteBalance(source['white_balance']),
    tone: parseTone(source['tone']),
    color: parseColor(source['color']),
    toneCurve: parseToneCurve(source['tone_curve']),
  };
}

export function fromJson(text: string): EditRecipe {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    throw new EditSchemaError(`the recipe is not valid JSON: ${(error as Error).message}`);
  }
  return parseRecipe(parsed);
}

/** The canonical mapping: every key present, in schema order, snake_case. */
export function toDocument(recipe: EditRecipe): Record<string, unknown> {
  return {
    schema: recipe.schema,
    white_balance: {
      temperature: recipe.whiteBalance.temperature,
      tint: recipe.whiteBalance.tint,
    },
    tone: {
      exposure: recipe.tone.exposure,
      contrast: recipe.tone.contrast,
      highlights: recipe.tone.highlights,
      shadows: recipe.tone.shadows,
      whites: recipe.tone.whites,
      blacks: recipe.tone.blacks,
    },
    color: {
      saturation: recipe.color.saturation,
      vibrance: recipe.color.vibrance,
    },
    tone_curve: {
      points: recipe.toneCurve.points.map(([x, y]) => [x, y]),
    },
  };
}

/**
 * Serialise to the canonical form, newline-terminated.
 *
 * Note what "canonical" can and cannot mean across three languages: key order
 * and content are fixed here, but the *text* is not comparable between
 * languages, because `JSON.stringify` cannot distinguish 0 from 0.0. The
 * agreement test therefore compares parsed values, not bytes.
 */
export function toJson(recipe: EditRecipe, indent = 2): string {
  return `${JSON.stringify(toDocument(recipe), null, indent)}\n`;
}

export function isNeutralCurve(points: readonly CurvePoint[]): boolean {
  return (
    points.length === 2 &&
    points[0][0] === 0 &&
    points[0][1] === 0 &&
    points[1][0] === 1 &&
    points[1][1] === 1
  );
}

/**
 * True when the recipe is the identity.
 *
 * The renderer uses the per-operation skip rule rather than this; this answers
 * the whole-recipe question, which the tests and the editor want.
 */
export function isNeutralRecipe(recipe: EditRecipe): boolean {
  const { whiteBalance, tone, color } = recipe;
  return (
    whiteBalance.temperature === 0 &&
    whiteBalance.tint === 0 &&
    tone.exposure === 0 &&
    tone.contrast === 0 &&
    tone.highlights === 0 &&
    tone.shadows === 0 &&
    tone.whites === 0 &&
    tone.blacks === 0 &&
    color.saturation === 0 &&
    color.vibrance === 0 &&
    isNeutralCurve(recipe.toneCurve.points)
  );
}
