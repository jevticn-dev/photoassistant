import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TranslatePipe } from '@ngx-translate/core';

/**
 * Account creation screen. Placeholder in phase 0; the form and the call to
 * POST /api/auth/register arrive in phase 4.
 */
@Component({
  selector: 'app-register',
  imports: [TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section>
      <h1>{{ 'auth.register.title' | translate }}</h1>
    </section>
  `,
})
export class Register {}
