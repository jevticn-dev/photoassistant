import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  computed,
  input,
  output,
} from '@angular/core';
import { TranslatePipe } from '@ngx-translate/core';

import { MIN_POINT_SPACING, type CurvePoint, evaluate, tangents } from '../../renderer';

/** How many samples the drawn curve is made of. */
const SAMPLES = 64;

/**
 * How close a press has to land to count as "this point" rather than "a new one",
 * in the curve's own units.
 *
 * <p>Nearest-point-within-a-radius rather than a hit area per handle, because
 * handles sit as little as a thousandth apart and overlapping hit areas would
 * make the one on top unreachable. One rule — the nearest point if something is
 * near enough, a new point otherwise — is also what makes a finger work on a
 * box this small, which per-handle targets of 44px could not in 150 pixels of
 * height.</p>
 */
const GRAB_RADIUS = 0.06;

/**
 * The closest two points are allowed to get here.
 *
 * <p>Twice the schema's floor, and the margin is the point. `MIN_POINT_SPACING`
 * is where the arithmetic breaks — two points nearer than that give a secant
 * slope that overflows and turns every pixel into NaN (ADR-20) — so it is a
 * cliff edge, not a target. Clamping exactly onto it produces values that fail
 * the schema's own check by one unit in the last place: `0.3 + 1/1023` minus
 * `0.3` is not `1/1023`. Found by a test that ran the result back through
 * `parseRecipe`, which is why that check is in every test in the file.</p>
 *
 * <p>The cost of the margin is nothing anybody can see: a thousandth of the
 * width of the box.</p>
 */
const SAFE_SPACING = MIN_POINT_SPACING * 2;

/** How far an arrow key moves the focused point. */
const NUDGE = 0.01;

/** How long a press has to rest before it means "remove this point". */
const LONG_PRESS_MS = 550;

/**
 * The tone curve: control points on a square, and the curve they describe.
 *
 * <p><b>The curve drawn is the curve applied.</b> The path is sampled through
 * the renderer's own `evaluate`, the same monotone interpolation the shader
 * runs and the Python side is held to by the golden test. Drawing it any other
 * way — a bezier through the points, say, as the prototype sketches — would put
 * a picture on screen that is close to what happens but not it, and the whole
 * point of this control is that you are looking at what you are doing.</p>
 *
 * <p><b>What it may not do</b> comes from the schema rather than from taste
 * (edit_schema §6.1): the first x is 0 and the last is 1, x increases strictly,
 * and consecutive points stay at least `MIN_POINT_SPACING` apart. The component
 * enforces all three while dragging rather than refusing afterwards, so a
 * recipe that cannot be saved cannot be made in the first place.</p>
 *
 * <p>Like `param-slider`, it owns how a change is <em>asked for</em> and
 * nothing about what it means: history belongs to the editor.</p>
 */
@Component({
  selector: 'app-curve-editor',
  imports: [TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './curve-editor.html',
  styleUrl: './curve-editor.scss',
})
export class CurveEditor implements OnDestroy {
  readonly points = input.required<readonly CurvePoint[]>();

  readonly changed = output<readonly CurvePoint[]>();

  /** A gesture beginning and ending, so the editor can make it one undo step. */
  readonly stepStart = output<void>();
  readonly stepEnd = output<void>();

  /** The curve itself, as an SVG path over a 100x100 box. */
  protected readonly path = computed(() => {
    const points = this.points();
    const slopes = tangents(points);
    const steps: string[] = [];

    for (let i = 0; i <= SAMPLES; i++) {
      const x = i / SAMPLES;
      const y = evaluate(points, slopes, x);

      steps.push(`${i === 0 ? 'M' : 'L'}${(x * 100).toFixed(2)},${((1 - y) * 100).toFixed(2)}`);
    }

    return steps.join(' ');
  });

  /** Where each handle sits in the box, with the ends marked as fixed in x. */
  protected readonly handles = computed(() =>
    this.points().map(([x, y], index, all) => ({
      index,
      x: x * 100,
      y: (1 - y) * 100,
      fixed: index === 0 || index === all.length - 1,
      value: `${x.toFixed(2)}, ${y.toFixed(2)}`,
    })),
  );

  protected readonly removable = computed(() => this.points().length > 2);

  private dragging: number | null = null;
  private pressTimer: ReturnType<typeof setTimeout> | null = null;

  ngOnDestroy(): void {
    this.clearPress();
  }

  // -- pointer --------------------------------------------------------------

  protected onPointerDown(event: PointerEvent, surface: Element): void {
    event.preventDefault();
    surface.setPointerCapture(event.pointerId);

    const [x, y] = this.at(event, surface);
    const nearest = this.nearestTo(x, y);

    this.stepStart.emit();

    if (nearest === null) {
      this.dragging = this.insert(x, y);
    } else {
      this.dragging = nearest;

      // A press that rests on a point means "take it away". Only for the ones
      // that may go: the ends hold the curve's domain (§6.1).
      this.pressTimer = setTimeout(() => this.remove(nearest), LONG_PRESS_MS);
    }
  }

  protected onPointerMove(event: PointerEvent, surface: Element): void {
    if (this.dragging === null) {
      return;
    }

    // Any movement means this was a drag rather than a rest, so it is no
    // longer a removal.
    this.clearPress();

    const [x, y] = this.at(event, surface);
    this.move(this.dragging, x, y);
  }

  protected onPointerUp(event: PointerEvent, surface: Element): void {
    if (surface.hasPointerCapture(event.pointerId)) {
      surface.releasePointerCapture(event.pointerId);
    }

    this.clearPress();

    if (this.dragging !== null) {
      this.dragging = null;
      this.stepEnd.emit();
    }
  }

  // -- keyboard -------------------------------------------------------------

  /**
   * The same moves as the pointer, for anyone not using one. Each press is its
   * own step, which is what makes a nudge undoable on its own.
   */
  protected onKey(event: KeyboardEvent, index: number): void {
    const moves: Record<string, readonly [number, number]> = {
      ArrowLeft: [-NUDGE, 0],
      ArrowRight: [NUDGE, 0],
      ArrowUp: [0, NUDGE],
      ArrowDown: [0, -NUDGE],
    };

    const move = moves[event.key];

    if (move !== undefined) {
      const [x, y] = this.points()[index];

      event.preventDefault();
      this.stepStart.emit();
      this.move(index, x + move[0], y + move[1]);
      this.stepEnd.emit();

      return;
    }

    if (event.key === 'Delete' || event.key === 'Backspace') {
      event.preventDefault();
      this.stepStart.emit();
      this.remove(index);
      this.stepEnd.emit();
    }
  }

  // -- the rules ------------------------------------------------------------

  /**
   * Moves one point, as far as the schema allows it to go.
   *
   * <p>Clamped rather than refused: a drag that hits its neighbour stops there
   * instead of snapping back or producing a recipe that will not save. The ends
   * keep their x — 0 and 1 are what make the curve defined over the whole input
   * range.</p>
   */
  private move(index: number, x: number, y: number): void {
    const points = this.points();
    const last = points.length - 1;

    const lower = index === 0 ? 0 : points[index - 1][0] + SAFE_SPACING;
    const upper = index === last ? 1 : points[index + 1][0] - SAFE_SPACING;

    const nextX = index === 0 || index === last ? points[index][0] : clamp(x, lower, upper);

    const moved = points.map((point, at): CurvePoint =>
      at === index ? [nextX, clamp(y, 0, 1)] : point,
    );

    this.changed.emit(moved);
  }

  /** Adds a point where the press landed, and returns where it went in the list. */
  private insert(x: number, y: number): number {
    const points = this.points();
    const at = points.findIndex(([px]) => px > x);
    const index = at === -1 ? points.length - 1 : at;

    // Not between two points that are already as close as the schema allows:
    // there is nowhere for it to be, and inserting anyway is what produces the
    // tangent that turns the whole image into NaN (ADR-20).
    const before = points[index - 1][0];
    const after = points[index][0];

    if (after - before < 2 * SAFE_SPACING) {
      return index - 1;
    }

    const placed = clamp(x, before + SAFE_SPACING, after - SAFE_SPACING);
    const next = [...points];

    next.splice(index, 0, [placed, clamp(y, 0, 1)]);
    this.changed.emit(next);

    return index;
  }

  /** Removes a point, unless it is one of the two that define the domain. */
  private remove(index: number): void {
    const points = this.points();

    if (index === 0 || index === points.length - 1) {
      return;
    }

    this.clearPress();
    this.dragging = null;
    this.changed.emit(points.filter((_, at) => at !== index));
  }

  private nearestTo(x: number, y: number): number | null {
    let best: number | null = null;
    let distance = GRAB_RADIUS;

    this.points().forEach(([px, py], index) => {
      const away = Math.hypot(px - x, py - y);

      if (away <= distance) {
        best = index;
        distance = away;
      }
    });

    return best;
  }

  /** Pointer position as a point on the curve's own square. */
  private at(event: PointerEvent, surface: Element): readonly [number, number] {
    const box = surface.getBoundingClientRect();

    return [
      clamp((event.clientX - box.left) / box.width, 0, 1),
      clamp(1 - (event.clientY - box.top) / box.height, 0, 1),
    ];
  }

  private clearPress(): void {
    if (this.pressTimer !== null) {
      clearTimeout(this.pressTimer);
      this.pressTimer = null;
    }
  }
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value));
}
