import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { TranslatePipe } from '@ngx-translate/core';

import { AuthFailure, AuthService, firstMessage } from '../../../core/auth/auth-service';

/** Minimum kept in step with `RegisterRequest.Password` on the server. */
const MINIMUM_PASSWORD_LENGTH = 8;

/** Sign-up screen. */
@Component({
  selector: 'app-register',
  imports: [ReactiveFormsModule, RouterLink, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './register.html',
  styleUrl: '../auth-form.scss',
})
export class Register {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly builder = inject(NonNullableFormBuilder);

  protected readonly minimumPasswordLength = MINIMUM_PASSWORD_LENGTH;

  protected readonly form = this.builder.group({
    email: ['', [Validators.required, Validators.email]],
    // Mirrors the server's length rule so the obvious mistake is caught without
    // a round trip. It is a courtesy, not the rule: Identity also demands a
    // digit and an upper-case letter, and those are reported by the server
    // rather than duplicated here, where they would drift out of step.
    password: ['', [Validators.required, Validators.minLength(MINIMUM_PASSWORD_LENGTH)]],
  });

  protected readonly submitting = signal(false);
  protected readonly failure = signal<AuthFailure | null>(null);

  protected errorFor(field: 'email' | 'password'): string | null {
    return firstMessage(this.failure(), field);
  }

  protected submit(): void {
    if (this.form.invalid || this.submitting()) {
      this.form.markAllAsTouched();
      return;
    }

    this.submitting.set(true);
    this.failure.set(null);

    this.auth.register(this.form.getRawValue()).subscribe({
      // Registration signs the new account in: the server returns a token with
      // the account, so asking the same credentials again would be ceremony.
      next: () => void this.router.navigateByUrl('/projects'),
      error: (failure: AuthFailure) => {
        this.failure.set(failure);
        this.submitting.set(false);
      },
    });
  }
}
