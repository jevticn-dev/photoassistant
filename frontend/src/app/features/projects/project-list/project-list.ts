import { Dialog } from '@angular/cdk/dialog';
import { DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  afterRenderEffect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslatePipe } from '@ngx-translate/core';

import { ConfirmDelete, type ConfirmDeleteData } from '../confirm-delete/confirm-delete';
import { ProjectThumbnail } from '../project-thumbnail/project-thumbnail';
import { type ProjectListItem, type ProjectsFailure, ProjectsService } from '../projects-service';

/** What the column holds, so the field stops where the server would refuse. */
const NAME_LIMIT = 200;

/**
 * Everything the signed-in person is working on.
 *
 * <p>A project is made by an upload rather than by finishing anything
 * (decision G), so a row with nothing saved is an ordinary row and not a fault
 * to hide. What the list says about it is "not saved yet", which is the truth
 * and also the invitation to open it.</p>
 */
@Component({
  selector: 'app-project-list',
  imports: [DatePipe, ProjectThumbnail, RouterLink, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './project-list.html',
  styleUrl: './project-list.scss',
})
export class ProjectList {
  private readonly service = inject(ProjectsService);
  private readonly dialog = inject(Dialog);

  protected readonly nameLimit = NAME_LIMIT;

  protected readonly projects = signal<readonly ProjectListItem[]>([]);
  protected readonly failure = signal<ProjectsFailure | null>(null);

  /** False until the first answer, so an empty list is not shown before there is one. */
  protected readonly loaded = signal(false);

  protected readonly renaming = signal<string | null>(null);

  /** The project a request is in flight for, so its buttons cannot be pressed twice. */
  protected readonly busy = signal<string | null>(null);

  private readonly field = viewChild<ElementRef<HTMLInputElement>>('field');

  constructor() {
    this.load();

    afterRenderEffect(() => {
      // The field only exists while a row is being renamed, and it is useless
      // until it has focus — nobody opens a rename in order to then click it.
      // Selected rather than merely focused: renaming is usually replacing.
      if (this.renaming() !== null) {
        this.field()?.nativeElement.select();
      }
    });
  }

  protected retry(): void {
    this.failure.set(null);
    this.loaded.set(false);
    this.load();
  }

  /** Which of the three count messages this project gets. */
  protected versionLabel(project: ProjectListItem): string {
    if (project.versionCount === 0) {
      return 'projects.versions.none';
    }

    return project.versionCount === 1 ? 'projects.versions.one' : 'projects.versions.many';
  }

  // -- renaming -------------------------------------------------------------

  protected startRename(project: ProjectListItem): void {
    this.renaming.set(project.id);
  }

  protected cancelRename(): void {
    this.renaming.set(null);
  }

  protected submitRename(project: ProjectListItem, event: Event): void {
    event.preventDefault();

    const name = this.field()?.nativeElement.value.trim() ?? '';

    // Nothing typed, or nothing changed: closing the field is the whole of the
    // right answer, and a request that renames a project to what it is called
    // is a round trip for no result.
    if (name === '' || name === project.name) {
      this.cancelRename();

      return;
    }

    this.busy.set(project.id);

    this.service.rename(project.id, name).subscribe({
      next: (renamed) => {
        // Patched in place rather than reloading the list: the server answers
        // with the name it stored, which is the one thing that changed, and
        // reloading would reorder nothing and cost a request.
        this.projects.update((list) =>
          list.map((row) => (row.id === project.id ? { ...row, name: renamed.name } : row)),
        );

        this.cancelRename();
        this.busy.set(null);
      },
      error: (failure: ProjectsFailure) => {
        this.failure.set(failure);
        this.cancelRename();
        this.busy.set(null);
      },
    });
  }

  // -- deleting -------------------------------------------------------------

  protected askToDelete(project: ProjectListItem): void {
    const confirmation = this.dialog.open<boolean, ConfirmDeleteData>(ConfirmDelete, {
      data: { name: project.name },
    });

    // Escape and a click outside close with undefined; both mean no, and the
    // check treats them the same as the cancel button.
    confirmation.closed.subscribe((confirmed) => {
      if (confirmed === true) {
        this.remove(project);
      }
    });
  }

  private remove(project: ProjectListItem): void {
    this.busy.set(project.id);

    this.service.delete(project.id).subscribe({
      next: () => {
        this.projects.update((list) => list.filter((row) => row.id !== project.id));
        this.busy.set(null);
      },
      error: (failure: ProjectsFailure) => {
        this.failure.set(failure);
        this.busy.set(null);
      },
    });
  }

  private load(): void {
    this.service.list().subscribe({
      next: (projects) => {
        this.projects.set(projects);
        this.loaded.set(true);
      },
      error: (failure: ProjectsFailure) => {
        this.failure.set(failure);
        this.loaded.set(true);
      },
    });
  }
}
