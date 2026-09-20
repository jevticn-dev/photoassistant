import { ChangeDetectionStrategy, Component, OnDestroy, inject, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { TranslatePipe } from '@ngx-translate/core';
import { forkJoin } from 'rxjs';

import { NEUTRAL_RECIPE, type EditRecipe } from '../../renderer';
import { SuggestionPreview } from './suggestion-preview';
import {
  type ParsedSuggestion,
  type Project,
  SuggestionsFailure,
  SuggestionsService,
} from './suggestions-service';

/** One readout line under a preview: the strongest parameters, as numbers. */
interface Readout {
  readonly label: string;
  readonly value: string;
}

/**
 * Choosing between three edits of your own photograph.
 *
 * <p>The previews are drawn here rather than fetched (decision C), from the
 * 2048px working copy the editor will use — so what is chosen from and what is
 * edited are the same image.</p>
 *
 * <p>Nothing is shown until both the recipes and the image have arrived. Half a
 * screen of cards with empty frames says less than the photograph itself does
 * while it waits (§B94).</p>
 */
@Component({
  selector: 'app-suggestions',
  imports: [SuggestionPreview, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './suggestions.html',
  styleUrl: './suggestions.scss',
})
export class Suggestions implements OnDestroy {
  private readonly service = inject(SuggestionsService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  private readonly projectId = this.route.snapshot.paramMap.get('id') ?? '';

  protected readonly project = signal<Project | null>(null);
  protected readonly suggestions = signal<readonly ParsedSuggestion[]>([]);
  protected readonly image = signal<ImageBitmap | null>(null);
  protected readonly failure = signal<SuggestionsFailure | null>(null);
  protected readonly choosing = signal(false);

  /** The photograph as it was uploaded — the reference the three are read against. */
  protected readonly neutral = NEUTRAL_RECIPE;

  constructor() {
    this.load();
  }

  ngOnDestroy(): void {
    // An ImageBitmap holds decoded pixels — 2048×1365×4 is eleven megabytes —
    // until it is closed or collected. Closing it is cheap and certain.
    this.image()?.close();
  }

  protected readonly ready = () => this.image() !== null && this.suggestions().length > 0;

  /**
   * The values that moved, strongest first.
   *
   * <p>Printed, not interpreted. Turning them into adjectives would need a rule
   * for which of thirteen parameters matter and what to say when they disagree,
   * and a wrong rule produces a label that lies rather than an error (§B94).</p>
   */
  protected readout(recipe: EditRecipe): readonly Readout[] {
    const candidates: readonly Readout[] = [
      { label: 'TEMP', value: signed(recipe.whiteBalance.temperature, 0) },
      { label: 'TINT', value: signed(recipe.whiteBalance.tint, 0) },
      { label: 'EXP', value: signed(recipe.tone.exposure, 2) },
      { label: 'CONTR', value: signed(recipe.tone.contrast, 0) },
      { label: 'HIGH', value: signed(recipe.tone.highlights, 0) },
      { label: 'SHAD', value: signed(recipe.tone.shadows, 0) },
      { label: 'WHITE', value: signed(recipe.tone.whites, 0) },
      { label: 'BLACK', value: signed(recipe.tone.blacks, 0) },
      { label: 'SAT', value: signed(recipe.color.saturation, 0) },
      { label: 'VIB', value: signed(recipe.color.vibrance, 0) },
    ];

    return candidates
      .filter((entry) => Number.parseFloat(entry.value) !== 0)
      .sort((a, b) => Math.abs(Number.parseFloat(b.value)) - Math.abs(Number.parseFloat(a.value)))
      .slice(0, 3);
  }

  protected choose(suggestion: ParsedSuggestion): void {
    this.record(suggestion.index);
  }

  /** Into the editor with none of them — the prototype's `skipRecommendations`. */
  protected skip(): void {
    this.record(null);
  }

  protected retry(): void {
    this.failure.set(null);
    this.load();
  }

  private record(chosenIndex: number | null): void {
    const photo = this.project()?.photoId;
    if (photo === undefined || this.choosing()) {
      return;
    }

    this.choosing.set(true);

    this.service
      .recordChoice(
        photo,
        this.suggestions().map((suggestion) => suggestion.raw),
        chosenIndex,
      )
      .subscribe({
        // The log is not the point of the click; the editor is. A failure to
        // record must not strand someone who has chosen, so the navigation
        // happens either way and the log is best effort.
        next: () => this.openEditor(),
        error: () => this.openEditor(),
      });
  }

  private openEditor(): void {
    void this.router.navigate(['/projects', this.projectId, 'edit']);
  }

  private load(): void {
    this.service.project(this.projectId).subscribe({
      next: (project) => {
        this.project.set(project);

        // Both at once: the recipes take about a second in the ML service and
        // the image is a network fetch, and neither needs the other.
        forkJoin({
          suggestions: this.service.suggestions(project.photoId),
          image: this.service.proxy(project.photoId),
        }).subscribe({
          next: ({ suggestions, image }) => {
            this.suggestions.set(suggestions);
            this.image.set(image);
          },
          error: (failure: SuggestionsFailure) => this.failure.set(failure),
        });
      },
      error: (failure: SuggestionsFailure) => this.failure.set(failure),
    });
  }
}

function signed(value: number, decimals: number): string {
  // Explicit sign: "+14" and "−14" are different edits, and a bare "14" makes
  // the reader look for the direction elsewhere.
  return `${value >= 0 ? '+' : ''}${value.toFixed(decimals)}`;
}
