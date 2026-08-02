import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { TokenStorage } from './token-storage';

/**
 * Keeps unauthenticated visitors out of the application shell.
 *
 * This is convenience, not security: the token is checked properly by the API on
 * every request. A guard only avoids showing a screen that would fail anyway.
 */
export const authGuard: CanActivateFn = (_route, state) => {
  const router = inject(Router);

  if (inject(TokenStorage).isAuthenticated()) {
    return true;
  }

  return router.createUrlTree(['/auth/login'], {
    // Remembered so the user lands where they were headed after signing in.
    queryParams: { returnUrl: state.url },
  });
};
