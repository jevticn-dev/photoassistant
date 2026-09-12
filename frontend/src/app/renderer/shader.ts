/**
 * The GLSL ES 3.00 program: the whole renderer, in the order the spec fixes.
 *
 * Implements `RENDERER_SPEC.md` §2 to §7 as one fragment shader. The Python side
 * is `ml/photoassistant/renderer/pipeline.py`; neither implementation is the
 * reference for the other.
 *
 * Three decisions in here are worth stating, because getting them wrong costs ΔE
 * without producing an error message:
 *
 * - **`precision highp float;` is written out**, and so is
 *   `precision highp sampler2D;`. The default precision in a fragment shader is
 *   `mediump` for floats and `lowp` for samplers, and neither default is enough
 *   to reproduce a NumPy result (§8.1).
 * - **No `smoothstep`, `mix`, `step` or `clamp` built-ins.** §8.2 restricts the
 *   renderer to `+ - * /`, `pow`, `exp2`, `min`, `max`, `floor` and `sqrt`. The
 *   built-ins would compute the same thing here, but writing the formulas out
 *   keeps the shader a line-by-line translation of the specification, which is
 *   what makes a disagreement traceable to a line rather than to a built-in.
 * - **The LUT is read with two `texelFetch` calls and a hand-written lerp**
 *   (§6.5). `GL_LINEAR` on the table is forbidden: the ES specification allows
 *   the interpolation weight to be computed at a reduced precision, so the same
 *   recipe would render differently on different hardware and never match NumPy.
 *
 * Values that are constant over an image — the white-balance multipliers and the
 * exposure scale — are computed on the CPU in `pipeline.ts` and arrive as
 * uniforms. That is not only cheaper; it also puts them somewhere a plain unit
 * test can reach without a GPU.
 */

/** Table size, spec §8.3. Shared with `curve.ts` and injected into the shader. */
import { LUT_SIZE } from './curve';

/** Guards the division in the saturation measure, spec §8.3. */
export const EPS = 1e-6;

/** Rec.709 luma weights over gamma-encoded values, spec §2.2. */
export const LUMA_WEIGHTS: readonly [number, number, number] = [0.2126, 0.7152, 0.0722];

/**
 * A number as a GLSL float literal.
 *
 * GLSL has no implicit int-to-float conversion in expressions, so `3` where a
 * float is meant is a compile error, and `0.25` must not lose its decimal point
 * on the way into the source. Interpolating the constants rather than retyping
 * them keeps one definition per value.
 */
function glslFloat(value: number): string {
  return Number.isInteger(value) ? `${value}.0` : String(value);
}

export const VERTEX_SHADER = `#version 300 es
precision highp float;

out vec2 v_uv;

void main() {
  // Two triangles covering the viewport, addressed by vertex index so the draw
  // needs no buffers at all. As a triangle strip the four corners come out in
  // the order (0,0) (1,0) (0,1) (1,1).
  float x = float(gl_VertexID & 1);
  float y = float((gl_VertexID >> 1) & 1);

  // v = 0 is row 0 of the uploaded image and is placed at the top of the
  // viewport, so a canvas shows the image the right way up. readPixels reads
  // bottom-up, which is why the CPU side reverses the rows on read-back.
  v_uv = vec2(x, y);
  gl_Position = vec4(x * 2.0 - 1.0, 1.0 - y * 2.0, 0.0, 1.0);
}
`;

export const FRAGMENT_SHADER = `#version 300 es
precision highp float;
precision highp sampler2D;

uniform sampler2D u_image;
uniform sampler2D u_lut;
uniform sampler2D u_regionTable;

uniform vec3 u_whiteBalance;    // per-channel multipliers, already normalised
uniform float u_exposureScale;  // 2^exposure
uniform float u_contrast;       // contrast / 100
uniform vec2 u_colour;          // saturation / 100, vibrance / 100

// The skip rule, spec §4.1. Not an optimisation: without it a neutral recipe
// would run through the arithmetic and come back a few last bits away from its
// input. Steps 1 and 4 — decode and encode — live and die together, which is
// what u_linearStage carries.
uniform bool u_linearStage;
uniform bool u_whiteBalanceOn;
uniform bool u_exposureOn;
uniform bool u_regionsOn;
uniform bool u_contrastOn;
uniform bool u_curveOn;
uniform bool u_colourOn;

in vec2 v_uv;
out vec4 fragColour;

const int LUT_SIZE = ${LUT_SIZE};
const float EPS = ${glslFloat(EPS)};
const vec3 LUMA = vec3(${LUMA_WEIGHTS.map(glslFloat).join(', ')});

// ------------------------------------------------------------ colour spaces

// sRGB, IEC 61966-2-1, piecewise by definition (§2.1). A plain 2.2 power is not
// a substitute: the error is systematic and largest in the darks, and on its own
// enough to fail the ΔE threshold.
float srgbDecodeChannel(float s) {
  return s <= 0.04045 ? s / 12.92 : pow((s + 0.055) / 1.055, 2.4);
}

vec3 srgbDecode(vec3 c) {
  return vec3(srgbDecodeChannel(c.r), srgbDecodeChannel(c.g), srgbDecodeChannel(c.b));
}

float srgbEncodeChannel(float l) {
  // The formula continues analytically above 1 and is not clipped here: clipping
  // at this point would throw away the highlight headroom a negative whites is
  // meant to recover (§5). max() only guards the fractional power against a
  // negative base, which the pipeline cannot produce.
  return l <= 0.0031308 ? 12.92 * l : 1.055 * pow(max(l, 0.0), 1.0 / 2.4) - 0.055;
}

vec3 srgbEncode(vec3 c) {
  return vec3(srgbEncodeChannel(c.r), srgbEncodeChannel(c.g), srgbEncodeChannel(c.b));
}

// Luma, not luminance: the same weights over linear values would be luminance,
// and the operations that consume this run in gamma space (§2.2).
float luma(vec3 c) {
  return LUMA.r * c.r + LUMA.g * c.g + LUMA.b * c.b;
}

float unitClamp(float x) {
  return min(max(x, 0.0), 1.0);
}

// The four tone-region masks are **not** here any more (ADR-22). The shift they
// produce is built into a table on the CPU, in pipeline.ts, so that the
// monotonicity condition §3.3 requires can be applied to it before use — and so
// that the arithmetic happens once per recipe in a place NumPy can be compared
// against directly, rather than once per pixel on the GPU.

// ------------------------------------------------------------------- LUT

// §6.4 and §6.5: NEAREST sampling, two texel reads, the interpolation done here.
// The tone-region table is read the same way and for the same reasons.
float regionLookup(float x) {
  float t = unitClamp(x) * float(LUT_SIZE - 1);
  float base = min(max(floor(t), 0.0), float(LUT_SIZE - 2));
  float frac = t - base;

  int i = int(base);
  float a = texelFetch(u_regionTable, ivec2(i, 0), 0).r;
  float b = texelFetch(u_regionTable, ivec2(i + 1, 0), 0).r;
  return a * (1.0 - frac) + b * frac;
}

float lutLookup(float x) {
  float t = unitClamp(x) * float(LUT_SIZE - 1);
  float base = min(max(floor(t), 0.0), float(LUT_SIZE - 2));
  float frac = t - base;

  int index = int(base);
  float low = texelFetch(u_lut, ivec2(index, 0), 0).r;
  float high = texelFetch(u_lut, ivec2(index + 1, 0), 0).r;

  return low * (1.0 - frac) + high * frac;
}

// ------------------------------------------------------------------ main

void main() {
  vec3 c = texture(u_image, v_uv).rgb;

  if (u_linearStage) {
    c = srgbDecode(c);                                  // 1

    if (u_whiteBalanceOn) {                             // 2
      c = c * u_whiteBalance;
    }

    if (u_exposureOn) {                                 // 3
      c = c * u_exposureScale;
    }

    c = srgbEncode(c);                                  // 4
  }

  if (u_regionsOn) {                                    // 5
    // One luma, one lookup, one addition. All four parameters were summed into
    // the table on the CPU, so there is no question of which goes first, and the
    // table was made monotone there (§3.3) so this cannot reverse a gradient.
    //
    // The table holds the **shift**, not the resulting luma: the lookup clips its
    // input, and a table of results would give every luma above 1 the result at 1
    // and flatten the highlight headroom §5 exists to keep.
    c = c + vec3(regionLookup(luma(c)));
  }

  if (u_contrastOn) {                                   // 6
    // The shaping applies to the part of the value inside [0,1]; the excess is
    // carried through untouched (ADR-20). Inside the range this is the original
    // expression. Outside it contrast becomes the identity, which is the only
    // honest answer for a value above white — and without it the cubic dives,
    // turning a blown highlight into pure black at contrast +100.
    vec3 inside = vec3(unitClamp(c.r), unitClamp(c.g), unitClamp(c.b));
    vec3 shaped = inside * inside * (vec3(3.0) - 2.0 * inside) + (c - inside);
    c = c + u_contrast * (shaped - c);
  }

  if (u_curveOn) {                                      // 7
    c = vec3(lutLookup(c.r), lutLookup(c.g), lutLookup(c.b));
  }

  // 8 — slot: HSL, schema 2. Empty, and skipped unconditionally.

  if (u_colourOn) {                                     // 9
    // Both gains come from the same pre-change pixel and are summed, so no
    // ordering between saturation and vibrance exists.
    float y = luma(c);
    float highest = max(max(c.r, c.g), c.b);
    float lowest = min(min(c.r, c.g), c.b);

    // Both limits are required (ADR-20), and both enforce a range the spec
    // already declares. p is stated to be in [0,1], but the guard against
    // dividing by zero only holds while highest is non-negative -- a negative
    // blacks sends all three channels under, and p reached 32,903. And the gain
    // stops at -1, which is "all colour removed": below that the multiplier goes
    // negative and the pixel is mirrored through its own luma instead of
    // collapsing onto it, so a warm colour comes out cool.
    float p = unitClamp((highest - lowest) / max(highest, EPS));

    float gain = max(u_colour.x + u_colour.y * (1.0 - p), -1.0);
    c = vec3(y) + (c - vec3(y)) * (1.0 + gain);
  }

  // 10 — slot: split toning, schema 2. Empty, and skipped unconditionally.

  fragColour = vec4(unitClamp(c.r), unitClamp(c.g), unitClamp(c.b), 1.0);  // 11
}
`;
