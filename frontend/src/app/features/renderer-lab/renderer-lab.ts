import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnDestroy,
  computed,
  effect,
  signal,
  viewChild,
} from '@angular/core';
import { TranslatePipe } from '@ngx-translate/core';

import {
  NEUTRAL_RECIPE,
  RendererError,
  WebGlRenderer,
  parseRecipe,
  toJson,
  type CurvePoint,
  type EditRecipe,
  type PixelSource,
} from '../../renderer';

/**
 * A page for looking at the renderer.
 *
 * The unit tests say whether the shader computes the right numbers; this says
 * what those numbers look like, which is a different question and not one a test
 * answers. The phase 1b probe found a wrong constant by looking at a contact
 * sheet after every summary statistic had called the same edit acceptable — so a
 * place to look is worth its keep.
 *
 * Note where the Angular boundary is. This component imports the renderer;
 * nothing under `src/app/renderer/` imports Angular, and `boundary.spec.ts`
 * enforces that. The dependency has to point this way for the golden test to be
 * able to run the renderer outside a component test environment.
 */

type SliderKey =
  | 'temperature'
  | 'tint'
  | 'exposure'
  | 'contrast'
  | 'highlights'
  | 'shadows'
  | 'whites'
  | 'blacks'
  | 'saturation'
  | 'vibrance';

interface Slider {
  readonly key: SliderKey;
  readonly min: number;
  readonly max: number;
  readonly step: number;
}

const SLIDERS: readonly Slider[] = [
  { key: 'temperature', min: -100, max: 100, step: 1 },
  { key: 'tint', min: -100, max: 100, step: 1 },
  // Exposure is the one parameter in stops rather than on the shared -100..100
  // scale, and its range is the schema's, not a display choice.
  { key: 'exposure', min: -5, max: 5, step: 0.05 },
  { key: 'contrast', min: -100, max: 100, step: 1 },
  { key: 'highlights', min: -100, max: 100, step: 1 },
  { key: 'shadows', min: -100, max: 100, step: 1 },
  { key: 'whites', min: -100, max: 100, step: 1 },
  { key: 'blacks', min: -100, max: 100, step: 1 },
  { key: 'saturation', min: -100, max: 100, step: 1 },
  { key: 'vibrance', min: -100, max: 100, step: 1 },
];

const CURVES: Record<string, CurvePoint[]> = {
  neutral: [
    [0, 0],
    [1, 1],
  ],
  // FiveK "Medium Contrast", the most common curve in the catalogue after linear.
  mediumContrast: [
    [0, 0],
    [32 / 255, 22 / 255],
    [64 / 255, 56 / 255],
    [128 / 255, 128 / 255],
    [192 / 255, 196 / 255],
    [1, 1],
  ],
  faded: [
    [0, 0.08],
    [0.25, 0.28],
    [0.75, 0.8],
    [1, 0.95],
  ],
};

const GROUP_OF: Record<SliderKey, 'white_balance' | 'tone' | 'color'> = {
  temperature: 'white_balance',
  tint: 'white_balance',
  exposure: 'tone',
  contrast: 'tone',
  highlights: 'tone',
  shadows: 'tone',
  whites: 'tone',
  blacks: 'tone',
  saturation: 'color',
  vibrance: 'color',
};

type LabImage =
  | {
      readonly kind: 'pixels';
      readonly pixels: PixelSource;
      readonly width: number;
      readonly height: number;
    }
  | {
      readonly kind: 'bitmap';
      readonly bitmap: ImageBitmap;
      readonly width: number;
      readonly height: number;
    };

/**
 * The image the page starts on: a grey wedge over a hue sweep.
 *
 * Built here rather than loaded from `fixtures/images/` because those files sit
 * outside the frontend project and are the golden test's input, not the editor's.
 * The shapes are the same for the same reason they were chosen there — a wedge
 * shows the curve and the region masks, a hue sweep shows white balance and
 * saturation.
 */
function startingImage(): PixelSource {
  const width = 256;
  const height = 128;
  const data = new Uint8Array(width * height * 4);

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const at = (y * width + x) * 4;
      let r: number;
      let g: number;
      let b: number;

      if (y < height / 2) {
        r = g = b = x;
      } else {
        const hue = (x / width) * 6;
        const sector = Math.floor(hue) % 6;
        const rise = Math.round((hue - Math.floor(hue)) * 255);
        const fall = 255 - rise;
        [r, g, b] = [
          [255, rise, 0],
          [fall, 255, 0],
          [0, 255, rise],
          [0, fall, 255],
          [rise, 0, 255],
          [255, 0, fall],
        ][sector];
      }

      data[at] = r;
      data[at + 1] = g;
      data[at + 2] = b;
      data[at + 3] = 255;
    }
  }

  return { data, width, height };
}

@Component({
  selector: 'app-renderer-lab',
  imports: [TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './renderer-lab.html',
  styleUrl: './renderer-lab.scss',
})
export class RendererLab implements OnDestroy {
  private readonly canvasRef = viewChild.required<ElementRef<HTMLCanvasElement>>('canvas');

  private renderer: WebGlRenderer | null = null;
  private uploaded: LabImage | null = null;

  readonly sliders = SLIDERS;
  readonly curveNames = Object.keys(CURVES);

  readonly values = signal<Record<SliderKey, number>>({
    temperature: 0,
    tint: 0,
    exposure: 0,
    contrast: 0,
    highlights: 0,
    shadows: 0,
    whites: 0,
    blacks: 0,
    saturation: 0,
    vibrance: 0,
  });

  readonly curveName = signal<string>('neutral');
  readonly image = signal<LabImage>({
    kind: 'pixels',
    pixels: startingImage(),
    width: 256,
    height: 128,
  });
  readonly failure = signal<string | null>(null);

  readonly recipe = computed<EditRecipe>(() => {
    const values = this.values();
    const groups: Record<string, Record<string, number>> = {
      white_balance: {},
      tone: {},
      color: {},
    };
    for (const { key } of SLIDERS) {
      groups[GROUP_OF[key]][key] = values[key];
    }

    return parseRecipe({
      schema: 1,
      ...groups,
      tone_curve: { points: CURVES[this.curveName()] },
    });
  });

  readonly recipeJson = computed(() => toJson(this.recipe()));

  constructor() {
    effect(() => {
      const canvas = this.canvasRef().nativeElement;
      const image = this.image();
      const recipe = this.recipe();

      try {
        this.renderer ??= WebGlRenderer.create(canvas);

        // The canvas matches the image pixel for pixel; CSS scales it for
        // display. Anything else would put a resample between the shader and
        // what is on screen, and the point of the page is to see the shader.
        if (canvas.width !== image.width || canvas.height !== image.height) {
          canvas.width = image.width;
          canvas.height = image.height;
        }

        if (this.uploaded !== image) {
          if (image.kind === 'pixels') {
            this.renderer.setImage(image.pixels);
          } else {
            this.renderer.setImageSource(image.bitmap, image.width, image.height);
          }
          this.uploaded = image;
        }

        this.renderer.render(recipe);
        this.failure.set(null);
      } catch (error) {
        this.failure.set(
          error instanceof RendererError ? error.message : String((error as Error).message),
        );
      }
    });
  }

  ngOnDestroy(): void {
    this.renderer?.dispose();
  }

  setValue(key: SliderKey, event: Event): void {
    const value = Number((event.target as HTMLInputElement).value);
    this.values.update((current) => ({ ...current, [key]: value }));
  }

  setCurve(event: Event): void {
    this.curveName.set((event.target as HTMLSelectElement).value);
  }

  reset(): void {
    this.values.set({
      temperature: 0,
      tint: 0,
      exposure: 0,
      contrast: 0,
      highlights: 0,
      shadows: 0,
      whites: 0,
      blacks: 0,
      saturation: 0,
      vibrance: 0,
    });
    this.curveName.set('neutral');
  }

  isNeutral(): boolean {
    return this.recipeJson() === toJson(NEUTRAL_RECIPE);
  }

  async openFile(event: Event): Promise<void> {
    const file = (event.target as HTMLInputElement).files?.[0];
    if (!file) {
      return;
    }

    try {
      // Both options are stated. A bitmap decoded with the defaults may arrive
      // premultiplied or converted to the display's colour space, and the shader
      // would then be reading pixels the file never contained.
      const bitmap = await createImageBitmap(file, {
        premultiplyAlpha: 'none',
        colorSpaceConversion: 'none',
      });
      this.image.set({
        kind: 'bitmap',
        bitmap,
        width: bitmap.width,
        height: bitmap.height,
      });
    } catch (error) {
      this.failure.set(String((error as Error).message));
    }
  }
}
