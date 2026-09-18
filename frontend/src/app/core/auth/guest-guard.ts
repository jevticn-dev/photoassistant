import { inject } from '@angular/core';
import { CanActivateFn, RedirectCommand, Router } from '@angular/router';

import { TokenStorage } from './token-storage';

/**
 * Keeps someone who is already signed in off the sign-in screens.
 *
 * The mirror image of {@link authGuard}, and it was missing: the guard stopped
 * strangers reaching the application but let a signed-in person walk back to a
 * form asking them to sign in, which is a dead end — submitting it would only
 * hand them the session they already have.
 *
 * Like the other guard, this is convenience and not security. Nothing is
 * protected by it; it prevents a screen that would make no sense.
 */
export const guestGuard: CanActivateFn = () => {
  const router = inject(Router);

  if (!inject(TokenStorage).isAuthenticated()) {
    return true;
  }

  // `replaceUrl`, because the way back here is usually the Back button. A plain
  // redirect would push /projects on top of the /auth/login the person just
  // tried to reach, so pressing Back again would land on it and bounce forward
  // once more — a trap two presses deep.
  return new RedirectCommand(router.createUrlTree(['/projects']), { replaceUrl: true });
};
