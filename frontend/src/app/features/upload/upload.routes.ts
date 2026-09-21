import { Routes } from '@angular/router';

/**
 * Lazily loaded, and behind the guard: an upload has to belong to someone.
 *
 * The screen stays in the casing zone. Its waiting state draws a photograph and
 * turns dark, but that is one element inside the page rather than the page, so
 * it carries the class itself instead of the route declaring it.
 */
export const uploadRoutes: Routes = [
  {
    path: '',
    loadComponent: () => import('./upload').then((m) => m.Upload),
  },
];
