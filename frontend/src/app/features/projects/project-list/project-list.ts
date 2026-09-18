import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslatePipe } from '@ngx-translate/core';

/**
 * List of the signed-in user's projects.
 *
 * Still a placeholder for the list itself — loading from GET /api/projects is
 * task 5. What it has now is the way in: without a link to the upload screen
 * there is no route through the application at all.
 */
@Component({
  selector: 'app-project-list',
  imports: [RouterLink, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="projects">
      <header class="projects__header">
        <h1 class="projects__title">{{ 'projects.title' | translate }}</h1>
        <a class="projects__new" routerLink="/upload">{{ 'projects.new' | translate }}</a>
      </header>

      <p class="projects__empty">{{ 'projects.empty' | translate }}</p>
    </section>
  `,
  styles: `
    .projects__header {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: var(--space-4);
      margin-bottom: var(--space-5);
    }

    .projects__title {
      margin: 0;
      font-size: var(--text-xl);
      font-weight: var(--weight-medium);
    }

    .projects__new {
      padding: var(--space-2) var(--space-4);
      background: var(--accent);
      color: var(--accent-contrast);
      border-radius: var(--radius-md);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      font-weight: var(--weight-medium);
      letter-spacing: var(--tracking-label);
      text-decoration: none;
    }

    .projects__empty {
      color: var(--text-secondary);
    }
  `,
})
export class ProjectList {}
