import type { EditRecipe } from '../../renderer';

/** The three groups of edit schema v1 that hold scalars, in the prototype's order. */
export type ParamGroup = 'whiteBalance' | 'tone' | 'color';

export interface ParamDef {
  /** The schema's own name for it, which is also its translation key. */
  readonly key: string;
  readonly group: ParamGroup;
  readonly min: number;
  readonly max: number;
  readonly step: number;

  /** Decimal places in the readout. Only exposure has any. */
  readonly decimals: number;
}

/**
 * Every scalar parameter of edit schema v1, grouped as the prototype groups
 * them — which is also how the schema itself is laid out, since both follow
 * what the operations do rather than what they are called.
 *
 * <p>The ranges are the schema's, not a second opinion about them: everything
 * but exposure shares the symmetric [-100, 100] interval, and exposure is in
 * stops, where ±5 is the declared limit and +1 means twice the light. Exposure
 * therefore steps by hundredths — a whole stop per arrow key would make the
 * keyboard useless on the one parameter with physical meaning.</p>
 *
 * <p>The tone curve is missing on purpose. It is part of the recipe, arrives
 * with a suggestion and is applied by the renderer; dragging its control points
 * is the phase's first "if time remains" item.</p>
 */
export const PARAMS: readonly ParamDef[] = [
  { key: 'temperature', group: 'whiteBalance', min: -100, max: 100, step: 1, decimals: 0 },
  { key: 'tint', group: 'whiteBalance', min: -100, max: 100, step: 1, decimals: 0 },
  { key: 'exposure', group: 'tone', min: -5, max: 5, step: 0.01, decimals: 2 },
  { key: 'contrast', group: 'tone', min: -100, max: 100, step: 1, decimals: 0 },
  { key: 'highlights', group: 'tone', min: -100, max: 100, step: 1, decimals: 0 },
  { key: 'shadows', group: 'tone', min: -100, max: 100, step: 1, decimals: 0 },
  { key: 'whites', group: 'tone', min: -100, max: 100, step: 1, decimals: 0 },
  { key: 'blacks', group: 'tone', min: -100, max: 100, step: 1, decimals: 0 },
  { key: 'saturation', group: 'color', min: -100, max: 100, step: 1, decimals: 0 },
  { key: 'vibrance', group: 'color', min: -100, max: 100, step: 1, decimals: 0 },
];

export interface ParamSection {
  readonly group: ParamGroup;
  readonly params: readonly ParamDef[];
}

export const SECTIONS: readonly ParamSection[] = (['whiteBalance', 'tone', 'color'] as const).map(
  (group) => ({ group, params: PARAMS.filter((param) => param.group === group) }),
);

// The schema's models are deliberately not indexable: every field is named and
// readonly, which is what makes a mistyped parameter a compile error rather
// than a silent undefined. A table-driven panel needs the opposite, so the two
// functions below are the one place where the shape is treated as a record —
// narrow, adjacent, and impossible to spread through the screen.

export function readParam(recipe: EditRecipe, param: ParamDef): number {
  return (recipe[param.group] as unknown as Record<string, number>)[param.key];
}

export function writeParam(recipe: EditRecipe, param: ParamDef, value: number): EditRecipe {
  return {
    ...recipe,
    [param.group]: { ...recipe[param.group], [param.key]: value },
  } as EditRecipe;
}

/** The value as the panel prints it: always signed, so the direction is read once. */
export function formatParam(value: number, decimals: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(decimals)}`;
}
