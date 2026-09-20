import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnDestroy,
  effect,
  input,
  output,
  viewChild,
} from '@angular/core';

import { RendererError, WebGlRenderer, type EditRecipe } from '../../renderer';

/** Why the canvas cannot draw. Both are reported; only one is recoverable. */
export type CanvasFailure = 'no-webgl2' | 'gpu';

/**
 * The photograph with a recipe applied, drawn on the GPU and kept live.
 *
 * <p>Separate from the suggestion screen's preview even though both draw the
 * same two things, because what they have to survive differs. A preview that
 * fails leaves an empty card among three; this one <b>is</b> the screen, so it
 * watches for a lost context, asks to be given a smaller image when the GPU
 * runs out, and says so rather than going quietly black (decision I).</p>
 *
 * <p>Two things about the canvas are not free choices, and each produces a
 * blank frame when got wrong (§B104). The context must come from
 * `WebGlRenderer.create`, which sets `preserveDrawingBuffer: true`, because
 * this draws once per change rather than every frame. And the buffer size is
 * assigned here beside the draw, never bound in the template: assigning
 * `canvas.width` clears the buffer, so a binding applied during the next view
 * refresh wipes the image that was just drawn.</p>
 */
@Component({
  selector: 'app-editor-canvas',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './editor-canvas.html',
  styleUrl: './editor-canvas.scss',
})
export class EditorCanvas implements OnDestroy {
  readonly image = input.required<ImageBitmap>();
  readonly recipe = input.required<EditRecipe>();
  readonly label = input('');

  /**
   * Raised when the GPU could not be used.
   *
   * <p>`gpu` is a request for a smaller image rather than a report of a broken
   * screen: the caller answers it by halving the working copy, which is the one
   * thing that helps and the one thing this component cannot do for itself,
   * since the image belongs to the screen and is shared with the other layer.</p>
   */
  readonly failed = output<CanvasFailure>();

  private readonly canvas = viewChild.required<ElementRef<HTMLCanvasElement>>('canvas');

  private renderer: WebGlRenderer | null = null;
  private uploaded: ImageBitmap | null = null;
  private listening = false;

  constructor() {
    effect(() => {
      this.draw(this.canvas().nativeElement, this.image(), this.recipe());
    });
  }

  ngOnDestroy(): void {
    // A WebGL context is not garbage: browsers cap how many exist at once, and
    // an editor opened and left repeatedly would exhaust them.
    this.renderer?.dispose();
    this.renderer = null;
  }

  private draw(canvas: HTMLCanvasElement, image: ImageBitmap, recipe: EditRecipe): void {
    this.listen(canvas);

    try {
      this.renderer ??= WebGlRenderer.create(canvas);

      // The belt over the braces (decision I): practically every device of the
      // last eight years reports at least 4096, so this almost never fires —
      // but the failure it prevents is a black screen with nothing in the
      // console, and reading one parameter is three lines.
      if (Math.max(image.width, image.height) > this.renderer.maxImageSize) {
        this.failed.emit('gpu');

        return;
      }

      if (canvas.width !== image.width || canvas.height !== image.height) {
        canvas.width = image.width;
        canvas.height = image.height;
      }

      // Uploaded once per image rather than once per draw: moving a slider
      // changes the recipe, not the pixels, and re-uploading 2048px of
      // photograph on every frame of a drag would dominate everything else.
      if (this.uploaded !== image) {
        this.renderer.setImageSource(image, image.width, image.height);
        this.uploaded = image;
      }

      this.renderer.render(recipe);
    } catch (error) {
      if (error instanceof RendererError) {
        this.renderer = null;
        this.uploaded = null;
        this.failed.emit(canvas.getContext('webgl2') === null ? 'no-webgl2' : 'gpu');

        return;
      }

      throw error;
    }
  }

  /**
   * A lost context is the shape running out of graphics memory actually takes:
   * no exception, no console message, just a canvas that stops updating
   * (decision I, and among the phase's known traps).
   *
   * <p>`preventDefault` on the loss is what makes the browser promise a
   * restore; without it the editor would stay black for good. Everything the
   * GPU held is gone by then, so both references are dropped and the next draw
   * builds a new renderer — after the screen has been given the chance to halve
   * the image, which is why the loss is reported rather than only repaired.</p>
   */
  private listen(canvas: HTMLCanvasElement): void {
    if (this.listening) {
      return;
    }
    this.listening = true;

    canvas.addEventListener('webglcontextlost', (event) => {
      event.preventDefault();

      this.renderer = null;
      this.uploaded = null;
      this.failed.emit('gpu');
    });

    canvas.addEventListener('webglcontextrestored', () => {
      this.renderer = null;
      this.uploaded = null;
      this.draw(canvas, this.image(), this.recipe());
    });
  }
}
