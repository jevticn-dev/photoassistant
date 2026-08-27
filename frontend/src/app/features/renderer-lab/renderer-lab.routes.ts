import { Routes } from '@angular/router';

/**
 * The renderer test page (phase 1, task 5).
 *
 * Lazily loaded like every other feature, so nothing of it reaches the initial
 * bundle of a user who never opens it.
 */
export const rendererLabRoutes: Routes = [
  {
    path: '',
    loadComponent: () => import('./renderer-lab').then((m) => m.RendererLab),
  },
];
