import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TranslatePipe } from '@ngx-translate/core';

/**
 * Sign-in screen. Placeholder in phase 0; the form and the call to
 * POST /api/auth/login arrive in phase 4.
 */
@Component({
  selector: 'app-login',
  imports: [TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section>
      <h1>{{ 'auth.login.title' | translate }}</h1>
    </section>
  `,
})
export class Login {}
