import { Routes } from '@angular/router';

/**
 * Lazily loaded: the sign-in screens are not part of the bundle a returning,
 * already authenticated user downloads.
 */
export const authRoutes: Routes = [
  {
    path: 'login',
    loadComponent: () => import('./login/login').then((m) => m.Login),
  },
  {
    path: 'register',
    loadComponent: () => import('./register/register').then((m) => m.Register),
  },
  { path: '', pathMatch: 'full', redirectTo: 'login' },
];
