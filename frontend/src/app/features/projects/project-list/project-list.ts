import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TranslatePipe } from '@ngx-translate/core';

/**
 * List of the signed-in user's projects. Placeholder in phase 0; loading from
 * GET /api/projects and the upload flow arrive in phase 4.
 */
@Component({
  selector: 'app-project-list',
  imports: [TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section>
      <h1>{{ 'projects.title' | translate }}</h1>
      <p>{{ 'projects.empty' | translate }}</p>
    </section>
  `,
})
export class ProjectList {}
