import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { TranslatePipe } from '@ngx-translate/core';

/**
 * Where an upload lands.
 *
 * Deliberately a stub. The screen that belongs here is the three suggestions
 * (task 3), and after it the editor (task 4); this exists so the upload has
 * somewhere to navigate to instead of failing with "cannot match any routes",
 * which would look like the upload itself breaking.
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
