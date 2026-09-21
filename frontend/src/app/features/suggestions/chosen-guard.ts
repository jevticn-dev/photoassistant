import { inject } from '@angular/core';
import { CanActivateFn, RedirectCommand, Router } from '@angular/router';
import { catchError, map, of } from 'rxjs';

import { SuggestionsService } from './suggestions-service';

/**
 * Keeps the suggestion screen out of reach once a choice has been made.
 *
 * <p>Choosing is a one-way step: it writes a row to `choices` and opens the
 * editor. Pressing Back returned to three cards that could be chosen from
 * again, which logs a second choice for the same photograph and reopens the
 * editor on a different recipe than the one already being worked on.</p>
 *
 * <p>Decided from the server rather than from client state, because Back is
 * exactly the case where client state is gone. The project reports whether a
 * choice exists; a saved version would be the wrong signal, since it would
 * miss someone who chose and then left the editor without saving.</p>
 *
 * <p>Like the other guards this is convenience, not security: nothing is
 * protected by it, and asking for suggestions again would harm nothing. It
 * removes a step that no longer makes sense.</p>
 */
export const chosenGuard: CanActivateFn = (route) => {
  const router = inject(Router);
  const projectId = route.paramMap.get('id');

  if (projectId === null) {
    return of(true);
  }

  return inject(SuggestionsService)
    .project(projectId)
    .pipe(
      map((project) =>
        project.hasChoice
          ? // replaceUrl, so Back from the editor leaves the application
            // rather than bouncing between these two screens.
            new RedirectCommand(router.createUrlTree(['/projects', projectId, 'edit']), {
              replaceUrl: true,
            })
          : true,
      ),

      // A project that cannot be read is not a reason to block: the screen
      // reports that far better than a redirect to nowhere would.
      catchError(() => of(true)),
    );
};
