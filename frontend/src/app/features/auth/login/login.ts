import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { TranslatePipe } from '@ngx-translate/core';

import { AuthFailure, AuthService, firstMessage } from '../../../core/auth/auth-service';

/** Sign-in screen. */
@Component({
  selector: 'app-login',
  imports: [ReactiveFormsModule, RouterLink, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './login.html',
  styleUrl: '../auth-form.scss',
})
export class Login {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly builder = inject(NonNullableFormBuilder);

  protected readonly form = this.builder.group({
    email: ['', [Validators.required, Validators.email]],
    // No minimum length here. This form checks that something was typed; how
    // long a valid password is belongs to registration, and enforcing it on
    // sign-in would tell an attacker the shape of accepted passwords.
    password: ['', [Validators.required]],
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

    this.auth.login(this.form.getRawValue()).subscribe({
      next: () => {
        // Where the guard sent them from, or the default screen. Read from the
        // snapshot rather than kept in a field: nothing can change it while one
        // request is in flight.
        const returnUrl = this.route.snapshot.queryParamMap.get('returnUrl') ?? '/projects';
        void this.router.navigateByUrl(returnUrl);
      },
      error: (failure: AuthFailure) => {
        this.failure.set(failure);
        this.submitting.set(false);
      },
    });
  }
}
