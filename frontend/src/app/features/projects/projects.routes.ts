import { Routes } from '@angular/router';

export const projectsRoutes: Routes = [
  {
    path: '',
    loadComponent: () => import('./project-list/project-list').then((m) => m.ProjectList),
  },
  {
    // A stub for now; the suggestions screen takes this place in task 3.
    path: ':id',
    loadComponent: () => import('./project-detail/project-detail').then((m) => m.ProjectDetail),
  },
];
