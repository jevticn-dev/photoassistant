import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { TranslatePipe } from '@ngx-translate/core';

import { EditSchemaError, parseRecipe, toJson } from '../../../renderer';
import {
  PhotoApi,
  type ApiFailure,
  type JobState,
  type Project,
  saveBlob,
} from '../../../shared/photos/photo-api';

/** One export as the list shows it: what it is, and which edit it was. */
interface ExportRow {
  readonly job: JobState;

  /**
   * The saved version this export matches, or null when it matches none.
   *
   * <p>Worked out here rather than stored, because an export is not tied to a
   * version: it carries the recipe that was on screen when it was asked for
   * (§B118, §B126). So the honest answer is "this file is version V02" when the
   * recipes are the same document, and "an edit that was never saved" when they
   * are not — which is a real and ordinary case, not a gap.</p>
   */
  readonly version: string | null;
}

/**
 * Every export of one project.
 *
 * <p>Reached from the project's card rather than from the editor, because a
 * finished file outlives the sitting that made it: until this screen existed,
 * an export was reachable only from the editor of its own project, and only the
 * newest one.</p>
 *
 * <p>The housing zone, not the display zone: this is a list of files, not a
 * photograph being judged (§B91).</p>
 */
@Component({
  selector: 'app-project-exports',
  imports: [DatePipe, RouterLink, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './project-exports.html',
  styleUrl: './project-exports.scss',
})
export class ProjectExports {
  private readonly api = inject(PhotoApi);
  private readonly route = inject(ActivatedRoute);

  private readonly projectId = this.route.snapshot.paramMap.get('id') ?? '';

  protected readonly project = signal<Project | null>(null);
  protected readonly rows = signal<readonly ExportRow[] | null>(null);
  protected readonly failure = signal<ApiFailure | null>(null);

  /** Set when a file could not be fetched; cleared by the next attempt. */
  protected readonly downloadProblem = signal<string | null>(null);

  protected readonly empty = computed(() => this.rows()?.length === 0);

  constructor() {
    this.load();
  }

  protected retry(): void {
    this.failure.set(null);
    this.rows.set(null);
    this.load();
  }

  protected download(job: JobState): void {
    this.downloadProblem.set(null);

    this.api.download(job.id).subscribe({
      next: (blob) =>
        saveBlob(blob, `${this.project()?.name ?? 'photograph'}-${job.id.slice(0, 8)}.png`),
      error: (failure: ApiFailure) => this.downloadProblem.set(failure.summaryKey),
    });
  }

  /**
   * The project, its versions and its exports.
   *
   * <p>All three, because the list says which version each export was, and that
   * is a comparison rather than a stored fact. Reading them together is also
   * what keeps the answer honest when nothing matches.</p>
   */
  private load(): void {
    this.api.project(this.projectId).subscribe({
      next: (project) => this.project.set(project),
      error: (failure: ApiFailure) => this.failure.set(failure),
    });

    this.api.versions(this.projectId).subscribe({
      next: (versions) => {
        // Canonical documents on both sides, the same equality the editor uses
        // to decide whether a file still matches the picture (§B125).
        const labels = new Map<string, string>();

        for (const version of versions) {
          const document = canonical(version.edit);

          if (document !== null) {
            labels.set(document, version.label);
          }
        }

        this.api.exports(this.projectId).subscribe({
          next: (exports) =>
            this.rows.set(
              exports.map((job) => {
                const document = canonical(job.edit);

                return {
                  job,
                  version: document === null ? null : (labels.get(document) ?? null),
                };
              }),
            ),
          error: (failure: ApiFailure) => this.failure.set(failure),
        });
      },
      error: (failure: ApiFailure) => this.failure.set(failure),
    });
  }
}

/**
 * A stored document in the one form two recipes can be compared in, or null
 * when it is not a recipe at all.
 */
function canonical(document: unknown): string | null {
  try {
    return toJson(parseRecipe(document));
  } catch (error) {
    if (error instanceof EditSchemaError) {
      return null;
    }

    throw error;
  }
}
