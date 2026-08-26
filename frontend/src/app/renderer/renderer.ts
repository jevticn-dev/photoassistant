/**
 * The WebGL2 renderer: context, textures, uniforms, and one draw call.
 *
 * The arithmetic is all in `shader.ts`; this file is the implementation layer the
 * specification deliberately does not cover (§9). What it does have to get right
 * is everything around the shader, and most of that is about the image arriving
 * unchanged:
 *
 * - **Upload settings are written out, never left at their defaults.**
 *   `UNPACK_PREMULTIPLY_ALPHA_WEBGL` and `UNPACK_COLORSPACE_CONVERSION_WEBGL`
 *   default to values that let the browser rewrite pixels before the shader ever
 *   sees them. A renderer that disagrees with NumPy because the browser applied a
 *   colour profile during upload fails the golden test with no hint of why.
 * - **`MAX_TEXTURE_SIZE` is checked, not assumed** (plan §11). It is a device
 *   property; the smallest value WebGL2 guarantees is 2048, which is exactly the
 *   proxy size the editor intends to use.
 * - **Read-back reverses the rows.** The texture is uploaded with row 0 first and
 *   the quad puts row 0 at the top, so the canvas shows the image upright;
 *   `readPixels` starts at the bottom of the framebuffer. One flip on the way
 *   out, in one place, rather than two conventions that have to stay in step.
 *
 * No Angular here, and none anywhere under `renderer/`: the golden test has to be
 * able to run this code outside a component test environment.
 */

import { buildLut, LUT_SIZE } from './curve';
import { exposureScale, planFor, whiteBalanceMultipliers } from './pipeline';
import type { EditRecipe } from './schema';
import { FRAGMENT_SHADER, VERTEX_SHADER } from './shader';

/** Raw pixels, RGBA8, row 0 first — the form both ends of the golden test use. */
export interface PixelSource {
  readonly data: Uint8Array;
  readonly width: number;
  readonly height: number;
}

export interface RenderedPixels {
  readonly data: Uint8Array;
  readonly width: number;
  readonly height: number;
}

export class RendererError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'RendererError';
  }
}

const CONTEXT_ATTRIBUTES: WebGLContextAttributes = {
  alpha: false,
  antialias: false,
  depth: false,
  stencil: false,
  premultipliedAlpha: false,
  // Read-back happens in the same task as the draw, but a canvas whose contents
  // survive until then is one less thing to reason about.
  preserveDrawingBuffer: true,
};

function compile(gl: WebGL2RenderingContext, type: number, source: string): WebGLShader {
  const shader = gl.createShader(type);
  if (!shader) {
    throw new RendererError('the context refused to create a shader');
  }

  gl.shaderSource(shader, source);
  gl.compileShader(shader);

  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const log = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    const kind = type === gl.VERTEX_SHADER ? 'vertex' : 'fragment';
    throw new RendererError(`the ${kind} shader did not compile:\n${log ?? '(no log)'}`);
  }

  return shader;
}

function link(gl: WebGL2RenderingContext): WebGLProgram {
  const program = gl.createProgram();
  if (!program) {
    throw new RendererError('the context refused to create a program');
  }

  const vertex = compile(gl, gl.VERTEX_SHADER, VERTEX_SHADER);
  const fragment = compile(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER);

  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.linkProgram(program);

  // The shaders are attached to the program, which keeps them alive; deleting the
  // handles here is the usual pairing and avoids leaking one per renderer.
  gl.deleteShader(vertex);
  gl.deleteShader(fragment);

  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    const log = gl.getProgramInfoLog(program);
    gl.deleteProgram(program);
    throw new RendererError(`the program did not link:\n${log ?? '(no log)'}`);
  }

  return program;
}

const UNIFORM_NAMES = [
  'u_image',
  'u_lut',
  'u_whiteBalance',
  'u_exposureScale',
  'u_regions',
  'u_contrast',
  'u_colour',
  'u_linearStage',
  'u_whiteBalanceOn',
  'u_exposureOn',
  'u_regionsOn',
  'u_contrastOn',
  'u_curveOn',
  'u_colourOn',
] as const;

type UniformName = (typeof UNIFORM_NAMES)[number];

export class WebGlRenderer {
  private readonly program: WebGLProgram;
  private readonly uniforms: Record<UniformName, WebGLUniformLocation | null>;
  private readonly imageTexture: WebGLTexture;
  private readonly lutTexture: WebGLTexture;
  private readonly vertexArray: WebGLVertexArrayObject | null;

  private imageWidth = 0;
  private imageHeight = 0;

  /** The points the uploaded table was built from, so it is rebuilt only on change. */
  private lutKey: string | null = null;

  private target: {
    framebuffer: WebGLFramebuffer;
    texture: WebGLTexture;
    width: number;
    height: number;
  } | null = null;

  constructor(private readonly gl: WebGL2RenderingContext) {
    this.program = link(gl);

    this.uniforms = Object.fromEntries(
      UNIFORM_NAMES.map((name) => [name, gl.getUniformLocation(this.program, name)]),
    ) as Record<UniformName, WebGLUniformLocation | null>;

    this.imageTexture = this.createTexture();
    this.lutTexture = this.createTexture();

    // The draw needs no attributes — the quad comes from gl_VertexID — but a
    // vertex array object still has to be bound for the draw to be valid.
    this.vertexArray = gl.createVertexArray();

    gl.useProgram(this.program);
    gl.uniform1i(this.uniforms.u_image, 0);
    gl.uniform1i(this.uniforms.u_lut, 1);
  }

  static create(canvas: HTMLCanvasElement | OffscreenCanvas): WebGlRenderer {
    const gl = canvas.getContext('webgl2', CONTEXT_ATTRIBUTES) as WebGL2RenderingContext | null;
    if (!gl) {
      throw new RendererError('this browser does not provide a WebGL2 context');
    }
    return new WebGlRenderer(gl);
  }

  /** The largest image this device can hold in a texture (plan §11). */
  get maxImageSize(): number {
    return this.gl.getParameter(this.gl.MAX_TEXTURE_SIZE) as number;
  }

  get width(): number {
    return this.imageWidth;
  }

  get height(): number {
    return this.imageHeight;
  }

  /** Upload raw RGBA8 pixels, row 0 first. */
  setImage(source: PixelSource): void {
    this.checkSize(source.width, source.height);
    const gl = this.gl;

    this.bindUploadSettings();
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.imageTexture);
    gl.texImage2D(
      gl.TEXTURE_2D,
      0,
      gl.RGBA8,
      source.width,
      source.height,
      0,
      gl.RGBA,
      gl.UNSIGNED_BYTE,
      source.data,
    );

    this.imageWidth = source.width;
    this.imageHeight = source.height;
  }

  /**
   * Upload from a browser image source — an `ImageBitmap`, a canvas, an `<img>`.
   *
   * The bitmap must have been created with `premultiplyAlpha: 'none'` and
   * `colorSpaceConversion: 'none'`; the settings applied here cover the upload,
   * not the decode that happened before it.
   */
  setImageSource(source: TexImageSource, width: number, height: number): void {
    this.checkSize(width, height);
    const gl = this.gl;

    this.bindUploadSettings();
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.imageTexture);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, gl.RGBA, gl.UNSIGNED_BYTE, source);

    this.imageWidth = width;
    this.imageHeight = height;
  }

  /** Draw into the bound canvas, for a live preview. */
  render(recipe: EditRecipe): void {
    const gl = this.gl;
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    this.draw(recipe, gl.drawingBufferWidth, gl.drawingBufferHeight);
  }

  /**
   * Render off-screen and return the 8-bit result, row 0 first.
   *
   * The framebuffer is `RGBA8`, so the GPU applies the quantisation rule of §8.4
   * — `floor(x * 255 + 0.5)` — on the way out, and the NumPy side must apply the
   * same rule rather than compare a quantised result against a continuous one.
   */
  readPixels(recipe: EditRecipe): RenderedPixels {
    const gl = this.gl;
    const width = this.imageWidth;
    const height = this.imageHeight;

    if (width === 0 || height === 0) {
      throw new RendererError('no image has been set');
    }

    this.bindTarget(width, height);
    this.draw(recipe, width, height);

    const bottomUp = new Uint8Array(width * height * 4);
    gl.pixelStorei(gl.PACK_ALIGNMENT, 1);
    gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, bottomUp);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);

    // readPixels starts at the bottom of the framebuffer; the caller wants the
    // same row order it uploaded.
    const stride = width * 4;
    const data = new Uint8Array(bottomUp.length);
    for (let row = 0; row < height; row++) {
      data.set(
        bottomUp.subarray((height - 1 - row) * stride, (height - row) * stride),
        row * stride,
      );
    }

    return { data, width, height };
  }

  dispose(): void {
    const gl = this.gl;
    gl.deleteTexture(this.imageTexture);
    gl.deleteTexture(this.lutTexture);
    gl.deleteProgram(this.program);
    if (this.vertexArray) {
      gl.deleteVertexArray(this.vertexArray);
    }
    if (this.target) {
      gl.deleteFramebuffer(this.target.framebuffer);
      gl.deleteTexture(this.target.texture);
      this.target = null;
    }
  }

  // ------------------------------------------------------------- internals

  private createTexture(): WebGLTexture {
    const gl = this.gl;
    const texture = gl.createTexture();
    if (!texture) {
      throw new RendererError('the context refused to create a texture');
    }

    gl.bindTexture(gl.TEXTURE_2D, texture);
    // NEAREST on both textures. On the LUT it is mandatory (§6.5); on the image
    // it keeps a 1:1 render free of any filtering the two implementations would
    // have to agree about.
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

    return texture;
  }

  private bindUploadSettings(): void {
    const gl = this.gl;
    // All four are stated rather than left to their defaults — see the note at
    // the top of the file.
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
  }

  private checkSize(width: number, height: number): void {
    const limit = this.maxImageSize;
    if (width > limit || height > limit) {
      throw new RendererError(
        `image is ${width}x${height} but this device caps textures at ${limit}`,
      );
    }
  }

  private uploadLut(points: EditRecipe['toneCurve']['points']): void {
    const key = JSON.stringify(points);
    if (key === this.lutKey) {
      return;
    }

    const gl = this.gl;
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, this.lutTexture);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.R32F, LUT_SIZE, 1, 0, gl.RED, gl.FLOAT, buildLut(points));

    this.lutKey = key;
  }

  private bindTarget(width: number, height: number): void {
    const gl = this.gl;

    if (this.target) {
      if (this.target.width === width && this.target.height === height) {
        gl.bindFramebuffer(gl.FRAMEBUFFER, this.target.framebuffer);
        return;
      }
      gl.deleteFramebuffer(this.target.framebuffer);
      gl.deleteTexture(this.target.texture);
      this.target = null;
    }

    const texture = gl.createTexture();
    const framebuffer = gl.createFramebuffer();
    if (!texture || !framebuffer) {
      throw new RendererError('the context refused to create a render target');
    }

    gl.activeTexture(gl.TEXTURE2);
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, width, height, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);

    gl.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texture, 0);

    const status = gl.checkFramebufferStatus(gl.FRAMEBUFFER);
    if (status !== gl.FRAMEBUFFER_COMPLETE) {
      throw new RendererError(`the render target is incomplete (status 0x${status.toString(16)})`);
    }

    this.target = { framebuffer, texture, width, height };
  }

  private draw(recipe: EditRecipe, width: number, height: number): void {
    const gl = this.gl;
    const plan = planFor(recipe);

    if (plan.curve) {
      this.uploadLut(recipe.toneCurve.points);
    }

    gl.useProgram(this.program);
    gl.bindVertexArray(this.vertexArray);

    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.imageTexture);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, this.lutTexture);

    const { tone, color, whiteBalance } = recipe;
    const multipliers = whiteBalanceMultipliers(whiteBalance.temperature, whiteBalance.tint);

    gl.uniform3f(this.uniforms.u_whiteBalance, multipliers[0], multipliers[1], multipliers[2]);
    gl.uniform1f(this.uniforms.u_exposureScale, exposureScale(tone.exposure));
    gl.uniform4f(
      this.uniforms.u_regions,
      tone.highlights / 100,
      tone.shadows / 100,
      tone.whites / 100,
      tone.blacks / 100,
    );
    gl.uniform1f(this.uniforms.u_contrast, tone.contrast / 100);
    gl.uniform2f(this.uniforms.u_colour, color.saturation / 100, color.vibrance / 100);

    gl.uniform1i(this.uniforms.u_linearStage, plan.linearStage ? 1 : 0);
    gl.uniform1i(this.uniforms.u_whiteBalanceOn, plan.whiteBalance ? 1 : 0);
    gl.uniform1i(this.uniforms.u_exposureOn, plan.exposure ? 1 : 0);
    gl.uniform1i(this.uniforms.u_regionsOn, plan.regions ? 1 : 0);
    gl.uniform1i(this.uniforms.u_contrastOn, plan.contrast ? 1 : 0);
    gl.uniform1i(this.uniforms.u_curveOn, plan.curve ? 1 : 0);
    gl.uniform1i(this.uniforms.u_colourOn, plan.colour ? 1 : 0);

    gl.viewport(0, 0, width, height);
    gl.disable(gl.BLEND);
    gl.disable(gl.DEPTH_TEST);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);

    gl.bindVertexArray(null);
  }
}
