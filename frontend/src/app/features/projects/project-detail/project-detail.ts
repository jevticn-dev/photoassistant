import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { TranslatePipe } from '@ngx-translate/core';

/**
 * Where a chosen suggestion lands.
 *
 * Deliberately a stub: the editor is task 4. It exists so that choosing has
 * somewhere to go instead of failing with "cannot match any routes", which
 * would look like the choice itself breaking.
 */
@Component({
  selector: 'app-project-detail',
  imports: [TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section>
      <h1>{{ 'projects.detail.title' | translate }}</h1>
      <p class="readout">{{ projectId }}</p>
      <p>{{ 'projects.detail.pending' | translate }}</p>
    </section>
  `,
})
export class ProjectDetail {
  protected readonly projectId = inject(ActivatedRoute).snapshot.paramMap.get('id') ?? '';
}
