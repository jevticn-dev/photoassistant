import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  computed,
  input,
  output,
} from '@angular/core';
import { TranslatePipe } from '@ngx-translate/core';

import { type ParamDef, formatParam } from './editor-params';

/** How long a finger must rest before a press counts as "reset this one". */
const LONG_PRESS_MS = 550;

/**
 * The keys a range input answers to by changing its value.
 *
 * <p>Checked rather than assumed, because the editor opens a history entry when
 * a key goes down: Tab and Shift arrive at the same handler, and tabbing
 * through the panel would otherwise fill the undo stack with steps that changed
 * nothing.</p>
 */
const VALUE_KEYS = new Set([
  'ArrowLeft',
  'ArrowRight',
  'ArrowUp',
  'ArrowDown',
  'Home',
  'End',
  'PageUp',
  'PageDown',
]);

/**
 * One parameter: its name, its value, and the track that changes it.
 *
 * <p><b>A native range input under hand-drawn paint.</b> The panel is drawn by
 * hand from the tokens, as ADR-26 requires, but the element underneath is the
 * browser's own: keyboard stepping, the screen reader's announcement and touch
 * dragging then come for free and cannot be got subtly wrong. A div with
 * pointer handlers would have to earn all three back.</p>
 *
 * <p>The component owns how a reset is <em>asked for</em> and nothing about
 * what it means: history belongs to the editor, which is the only place that
 * can see a change as one step among others.</p>
 */
@Component({
  selector: 'app-param-slider',
  imports: [TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './param-slider.html',
  styleUrl: './param-slider.scss',
})
export class ParamSlider implements OnDestroy {
  readonly param = input.required<ParamDef>();
  readonly value = input.required<number>();

  readonly changed = output<number>();
  readonly resetRequested = output<void>();

  /** A gesture beginning and ending, so the editor can make it one undo step. */
  readonly stepStart = output<void>();
  readonly stepEnd = output<void>();

  protected readonly id = computed(() => `param-${this.param().key}`);
  protected readonly name = computed(() => `editor.params.${this.param().key}`);
  protected readonly display = computed(() => formatParam(this.value(), this.param().decimals));

  /** Where the thumb sits, as a percentage, for the filled part of the track. */
  protected readonly fill = computed(() => {
    const param = this.param();

    return `${((this.value() - param.min) / (param.max - param.min)) * 100}%`;
  });

  private pressTimer: ReturnType<typeof setTimeout> | null = null;

  ngOnDestroy(): void {
    this.clearPress();
  }

  protected onInput(event: Event): void {
    this.changed.emit(Number((event.target as HTMLInputElement).value));
  }

  protected onKey(event: KeyboardEvent): void {
    if (VALUE_KEYS.has(event.key)) {
      this.stepStart.emit();
    }
  }

  protected requestReset(): void {
    if (this.value() !== 0) {
      this.resetRequested.emit();
    }
  }

  /**
   * A double click has no equivalent on a touch screen — the second tap arrives
   * as a separate tap — so a finger resting on the row does the same job. Mouse
   * presses are left alone: there the double click is the gesture, and a mouse
   * that pauses is usually a person thinking.
   */
  protected pressStart(event: PointerEvent): void {
    if (event.pointerType !== 'touch') {
      return;
    }

    this.clearPress();
    this.pressTimer = setTimeout(() => this.requestReset(), LONG_PRESS_MS);
  }

  protected clearPress(): void {
    if (this.pressTimer !== null) {
      clearTimeout(this.pressTimer);
      this.pressTimer = null;
    }
  }
}
