import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { TranslatePipe } from '@ngx-translate/core';

/** What the strip needs of a version: enough to label a chip and name it back. */
export interface StripEntry {
  readonly id: string;
  readonly label: string;
}

/**
 * The history strip: every saved version of this project, oldest at the top.
 *
 * <p><b>It shows and it asks; it does not decide.</b> Which version is open,
 * what happens to the unsaved work when another one is picked, and what the
 * save button says while an old one is showing all belong to the editor — the
 * one place that can see a change as one step among others. The same division
 * `param-slider` follows, and for the same reason.</p>
 *
 * <p>Oldest at the top rather than newest, because the labels are positions:
 * `V01` is the first thing saved and stays `V01`. Reading downwards is then
 * reading forwards in time, which is the order the work happened in.</p>
 */
@Component({
  selector: 'app-version-strip',
  imports: [TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './version-strip.html',
  styleUrl: './version-strip.scss',
})
export class VersionStrip {
  readonly entries = input.required<readonly StripEntry[]>();

  /**
   * The version currently on screen, or null when what is shown is the working
   * edit rather than any saved one.
   */
  readonly openId = input.required<string | null>();

  readonly opened = output<StripEntry>();
}
