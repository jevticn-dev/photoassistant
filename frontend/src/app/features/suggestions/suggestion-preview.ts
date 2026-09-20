import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnDestroy,
  effect,
  input,
  viewChild,
} from '@angular/core';

import { RendererError, WebGlRenderer, type EditRecipe } from '../../renderer';

/**
 * One photograph with one recipe applied, drawn on the GPU.
 *
 * <p><b>Why the browser draws this and not the server</b> (phase 4, decision C).
 * The same renderer runs on both sides and the golden test proves they agree,
 * so a rendered image in the response would be 141 KB of duplication — and at
 * 512px rather than the 2048px the person is about to edit at. Drawing it here
 * means the preview and the editor show the same pixels because they are the
 * same pixels.</p>
 *
 * <p>Each preview owns its context. Three contexts is well inside what a
 * browser allows, and sharing one would mean reading pixels back and pushing
 * them through a 2D canvas — a round trip off the GPU for no gain.</p>
 *
 * <p>Two things about the canvas are not free choices, and each produces a
 * blank frame when got wrong. The context must come from
 * `WebGlRenderer.create`, which sets `preserveDrawingBuffer: true`: this draws
 * once rather than every frame, and without it the browser may clear the
 * buffer before compositing. And the buffer size must be set here, beside the
 * draw, never bound in the template — assigning `canvas.width` resets and
 * clears the buffer, so a binding applied during the next view refresh wipes
 * the image that was just drawn. `renderer-lab` has done both correctly since
 * phase 1; this component learned it twice over.</p>
 */
@Component({
  selector: 'app-suggestion-preview',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './suggestion-preview.html',
  styleUrl: './suggestion-preview.scss',
})
export class SuggestionPreview implements OnDestroy {
  readonly image = input.required<ImageBitmap>();
  readonly recipe = input.required<EditRecipe>();

  /**
   * Longest side of the drawing buffer.
   *
   * <p>Smaller than the proxy on purpose: a card is a few hundred pixels wide,
   * and three 2048px buffers would be tens of megabytes of GPU memory for
   * detail nobody can see at that size. The editor renders the same recipe
   * over the same image at full proxy resolution.</p>
   */
  readonly longestSide = input(1024);

  private readonly canvas = viewChild.required<ElementRef<HTMLCanvasElement>>('canvas');

  private renderer: WebGlRenderer | null = null;
  private uploaded: ImageBitmap | null = null;

  constructor() {
    effect(() => {
      this.draw(this.canvas().nativeElement, this.image(), this.recipe(), this.longestSide());
    });
  }

  ngOnDestroy(): void {
    // A WebGL context is not garbage: browsers cap how many exist at once, and
    // a screen entered and left repeatedly would exhaust them.
    this.renderer?.dispose();
    this.renderer = null;
  }

  private draw(
    canvas: HTMLCanvasElement,
    image: ImageBitmap,
    recipe: EditRecipe,
    longest: number,
  ): void {
    try {
      this.renderer ??= WebGlRenderer.create(canvas);

      const scale = Math.min(1, longest / Math.max(image.width, image.height));
      const width = Math.max(1, Math.round(image.width * scale));
      const height = Math.max(1, Math.round(image.height * scale));

      // Only when it differs: every assignment clears the buffer, so doing it
      // unconditionally would throw away the previous frame for nothing.
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }

      // Uploaded once per image, not once per draw: the texture is the same
      // for all three previews of a photograph, and re-uploading 2048px of it
      // on every change would dominate the cost.
      if (this.uploaded !== image) {
        this.renderer.setImageSource(image, image.width, image.height);
        this.uploaded = image;
      }

      this.renderer.render(recipe);
    } catch (error) {
      if (error instanceof RendererError) {
        // Left as an empty frame rather than taking the screen down: two of
        // three previews are still worth choosing between.
        this.renderer = null;
        this.uploaded = null;

        return;
      }

      throw error;
    }
  }
}
