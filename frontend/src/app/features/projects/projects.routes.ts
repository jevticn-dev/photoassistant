import { Routes } from '@angular/router';

export const projectsRoutes: Routes = [
  {
    path: '',
    loadComponent: () => import('./project-list/project-list').then((m) => m.ProjectList),
  },
];
