/**
 * Public surface of the WebGL2 renderer.
 *
 * Everything under this folder is plain TypeScript with no Angular imports — see
 * README.md for why, and boundary.spec.ts for the test that enforces it.
 *
 * The specification both this and the NumPy implementation translate is
 * `docs/RENDERER_SPEC.md`. Neither is the reference for the other; the golden
 * test proves they agree.
 */

export {
  EditSchemaError,
  NEUTRAL_CURVE,
  NEUTRAL_RECIPE,
  SCHEMA_VERSION,
  fromJson,
  isNeutralCurve,
  isNeutralRecipe,
  parseRecipe,
  toDocument,
  toJson,
  type Color,
  type CurvePoint,
  type EditRecipe,
  type Tone,
  type ToneCurve,
  type WhiteBalance,
} from './schema';

export { LUT_SIZE, applyLut, buildLut, evaluate, tangents, type CurvePoints } from './curve';

export {
  K_WB,
  exposureScale,
  isPlanEmpty,
  planFor,
  whiteBalanceMultipliers,
  type RenderPlan,
} from './pipeline';

export { EPS, FRAGMENT_SHADER, K_REG, LUMA_WEIGHTS, VERTEX_SHADER } from './shader';

export { RendererError, WebGlRenderer, type PixelSource, type RenderedPixels } from './renderer';
