import { Routes } from '@angular/router';

import { authGuard } from './core/auth/auth-guard';

export const routes: Routes = [
  {
    path: 'auth',
    loadChildren: () => import('./features/auth/auth.routes').then((m) => m.authRoutes),
  },
  {
    path: 'projects',
    canActivate: [authGuard],
    loadChildren: () => import('./features/projects/projects.routes').then((m) => m.projectsRoutes),
  },
  { path: '', pathMatch: 'full', redirectTo: 'projects' },

  // Unknown addresses land in the same place as the root rather than on a blank
  // screen. A dedicated not-found page can replace this later.
  { path: '**', redirectTo: 'projects' },
];
