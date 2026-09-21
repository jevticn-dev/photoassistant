import { ComponentFixture, TestBed } from '@angular/core/testing';

import { provideTranslations } from '../../core/i18n/translation.config';
import { MIN_POINT_SPACING, type CurvePoint, parseRecipe } from '../../renderer';
import { CurveEditor } from './curve-editor';

/**
 * The tone curve editor.
 *
 * <p>What is checked is mostly one thing said several ways: a curve made here
 * has to be one the schema accepts. The rules are not this component's to
 * invent — they are edit_schema §6.1 — so each test ends by putting the result
 * through `parseRecipe`, which is the same validator the server and the
 * pipeline apply. A rule this component got wrong would otherwise surface as a
 * 400 on save, long after the drag that caused it.</p>
 */
describe('CurveEditor', () => {
  let fixture: ComponentFixture<CurveEditor>;
  let emitted: readonly CurvePoint[] | null;
  let steps: number;

  const NEUTRAL: readonly CurvePoint[] = [
    [0, 0],
    [1, 1],
  ];

  beforeEach(() => {
    // jsdom implements no pointer capture. The component needs it so a drag
    // that leaves the little square keeps going, which is what makes the
    // control usable at all; stubbing is the same accommodation the editor
    // spec makes for a canvas context jsdom also lacks.
    Element.prototype.setPointerCapture ??= (): void => undefined;
    Element.prototype.releasePointerCapture ??= (): void => undefined;
    Element.prototype.hasPointerCapture ??= (): boolean => false;
  });

  async function open(points: readonly CurvePoint[] = NEUTRAL): Promise<void> {
    emitted = null;
    steps = 0;

    await TestBed.configureTestingModule({
      imports: [CurveEditor],
      providers: [provideTranslations()],
    }).compileComponents();

    fixture = TestBed.createComponent(CurveEditor);
    fixture.componentRef.setInput('points', points);
    fixture.componentInstance.changed.subscribe((next) => {
      emitted = next;

      // The editor would hand the new points straight back, and several tests
      // depend on the second gesture seeing the result of the first.
      fixture.componentRef.setInput('points', next);
      fixture.detectChanges();
    });
    fixture.componentInstance.stepStart.subscribe(() => (steps += 1));

    fixture.detectChanges();
  }

  afterEach(() => TestBed.resetTestingModule());

  /** The frame, which is what takes every press — the drawing takes none. */
  function surface(): HTMLElement {
    return (fixture.nativeElement as HTMLElement).querySelector('.curve__frame')!;
  }

  function handles(): HTMLButtonElement[] {
    return [
      ...(fixture.nativeElement as HTMLElement).querySelectorAll<HTMLButtonElement>(
        '.curve__handle',
      ),
    ];
  }

  /**
   * A press at a point on the curve's square.
   *
   * <p>jsdom gives every element a zero-sized rectangle, so the box the
   * component measures against is supplied here. 200x200 keeps the arithmetic
   * plain: a value of 0.25 is 50 pixels.</p>
   */
  function press(x: number, y: number): void {
    vi.spyOn(surface(), 'getBoundingClientRect').mockReturnValue({
      left: 0,
      top: 0,
      width: 200,
      height: 200,
    } as DOMRect);

    surface().dispatchEvent(
      new PointerEvent('pointerdown', { clientX: x * 200, clientY: (1 - y) * 200 }),
    );
    fixture.detectChanges();
  }

  function moveTo(x: number, y: number): void {
    surface().dispatchEvent(
      new PointerEvent('pointermove', { clientX: x * 200, clientY: (1 - y) * 200 }),
    );
    fixture.detectChanges();
  }

  function release(): void {
    surface().dispatchEvent(new PointerEvent('pointerup', {}));
    fixture.detectChanges();
  }

  /** The rule this component exists to stay inside. */
  function accepted(points: readonly CurvePoint[]): boolean {
    try {
      parseRecipe({ schema: 1, tone_curve: { points: points.map(([x, y]) => [x, y]) } });

      return true;
    } catch {
      return false;
    }
  }

  it('opens on the two points a neutral curve has', async () => {
    await open();

    expect(handles()).toHaveLength(2);
  });

  it('the handles live outside the drawing, so they stay round', async () => {
    // The square is stretched to the panel's width, and anything inside that
    // viewBox is stretched with it — a circle drawn there comes out an ellipse.
    // Keeping the handles in HTML over the drawing is what makes them circles.
    await open();

    const svg = (fixture.nativeElement as HTMLElement).querySelector('svg')!;

    expect(handles()).toHaveLength(2);
    expect(handles().some((handle) => svg.contains(handle))).toBe(false);
  });

  it('pressing where there is no point adds one there', async () => {
    await open();

    press(0.5, 0.7);
    release();

    expect(emitted).toHaveLength(3);
    expect(emitted![1][0]).toBeCloseTo(0.5, 5);
    expect(emitted![1][1]).toBeCloseTo(0.7, 5);
    expect(accepted(emitted!)).toBe(true);
  });

  it('a new point goes in where its x belongs, not on the end', async () => {
    // The list is ordered by x and the schema insists on it; an append would
    // produce a curve that is refused the moment it is saved.
    await open([
      [0, 0],
      [0.8, 0.8],
      [1, 1],
    ]);

    press(0.4, 0.2);
    release();

    expect(emitted!.map(([x]) => x)).toEqual([0, 0.4, 0.8, 1]);
    expect(accepted(emitted!)).toBe(true);
  });

  it('dragging a point moves it, and the whole drag is one step', async () => {
    await open();

    press(0.5, 0.5);
    moveTo(0.6, 0.9);
    moveTo(0.7, 0.95);
    release();

    expect(emitted![1][0]).toBeCloseTo(0.7, 5);
    expect(emitted![1][1]).toBeCloseTo(0.95, 5);

    // One press, one step — whatever happened in between.
    expect(steps).toBe(1);
  });

  it('a point cannot be dragged past its neighbours', async () => {
    // Monotone x is the schema's rule, not a preference: two points out of
    // order make the interpolation undefined.
    await open([
      [0, 0],
      [0.3, 0.3],
      [0.6, 0.6],
      [1, 1],
    ]);

    press(0.6, 0.6);
    moveTo(0.1, 0.5);
    release();

    const xs = emitted!.map(([x]) => x);

    expect(xs[2]).toBeGreaterThan(xs[1]);
    expect(xs[2] - xs[1]).toBeGreaterThanOrEqual(MIN_POINT_SPACING);
    expect(accepted(emitted!)).toBe(true);
  });

  it('a point cannot be dragged out of the square', async () => {
    await open();

    press(0.5, 0.5);
    moveTo(1.5, 2);
    release();

    expect(emitted![1][1]).toBe(1);
    expect(accepted(emitted!)).toBe(true);
  });

  it('the ends keep their x, so the curve stays defined everywhere', async () => {
    // Without x = 0 and x = 1 the curve says nothing about part of the input
    // range, and the two implementations would have to invent the same
    // extrapolation.
    await open();

    press(0, 0);
    moveTo(0.4, 0.5);
    release();

    expect(emitted![0]).toEqual([0, 0.5]);
    expect(accepted(emitted!)).toBe(true);
  });

  it('holding a point removes it', async () => {
    vi.useFakeTimers();

    try {
      await open([
        [0, 0],
        [0.5, 0.5],
        [1, 1],
      ]);

      press(0.5, 0.5);
      vi.advanceTimersByTime(600);
      fixture.detectChanges();
      release();

      expect(emitted).toHaveLength(2);
      expect(accepted(emitted!)).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it('holding an end does not remove it', async () => {
    vi.useFakeTimers();

    try {
      await open([
        [0, 0],
        [0.5, 0.5],
        [1, 1],
      ]);

      press(1, 1);
      vi.advanceTimersByTime(600);
      fixture.detectChanges();
      release();

      expect(emitted).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('a drag is not a hold, however long it takes', async () => {
    vi.useFakeTimers();

    try {
      await open([
        [0, 0],
        [0.5, 0.5],
        [1, 1],
      ]);

      press(0.5, 0.5);
      moveTo(0.55, 0.6);
      vi.advanceTimersByTime(600);
      fixture.detectChanges();
      release();

      expect(emitted).toHaveLength(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it('the keyboard moves a point and removes one', async () => {
    await open([
      [0, 0],
      [0.5, 0.5],
      [1, 1],
    ]);

    handles()[1].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }));
    fixture.detectChanges();
    expect(emitted![1][1]).toBeCloseTo(0.51, 5);

    handles()[1].dispatchEvent(new KeyboardEvent('keydown', { key: 'Delete', bubbles: true }));
    fixture.detectChanges();
    expect(emitted).toHaveLength(2);
  });

  it('the drawn curve is the one the renderer would apply', async () => {
    // Sampled through the renderer's own interpolation rather than drawn as a
    // bezier through the points: a picture that is close to what happens but
    // not it defeats the only thing this control is for.
    await open([
      [0, 0],
      [0.5, 0.8],
      [1, 1],
    ]);

    const path = (fixture.nativeElement as HTMLElement)
      .querySelector('.curve__line')!
      .getAttribute('d')!;

    // At x = 0.5 the curve passes through y = 0.8, which in the box is 20 from
    // the top. The path is sampled, so that sample is in it verbatim.
    expect(path).toContain('L50.00,20.00');
  });
});
