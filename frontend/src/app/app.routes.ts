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
  {
    // The renderer test page. Not part of the product: it exists so the shader
    // can be looked at while it is being written, which is how phase 1b found a
    // wrong constant that no summary statistic had flagged. No guard, because it
    // reads nothing but the image the visitor chooses.
    path: 'renderer-lab',
    loadChildren: () =>
      import('./features/renderer-lab/renderer-lab.routes').then((m) => m.rendererLabRoutes),
  },
  { path: '', pathMatch: 'full', redirectTo: 'projects' },

  // Unknown addresses land in the same place as the root rather than on a blank
  // screen. A dedicated not-found page can replace this later.
  { path: '**', redirectTo: 'projects' },
];
