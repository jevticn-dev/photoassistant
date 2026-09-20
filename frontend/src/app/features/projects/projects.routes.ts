import { Routes } from '@angular/router';

import { chosenGuard } from '../suggestions/chosen-guard';

export const projectsRoutes: Routes = [
  {
    path: '',
    loadComponent: () => import('./project-list/project-list').then((m) => m.ProjectList),
  },
  {
    // Where an upload lands: three edits of the photograph, to choose between.
    // The display zone, because the screen is photographs being judged and
    // judging them against a light surround is what that zone prevents.
    path: ':id',
    // Choosing is one way: once it is done, this screen sends you on to the
    // editor rather than offering the choice a second time.
    canActivate: [chosenGuard],
    data: { zone: 'display' },
    loadComponent: () => import('../suggestions/suggestions').then((m) => m.Suggestions),
  },
  {
    // The editor arrives in task 4; until then this is where a choice lands.
    path: ':id/edit',
    data: { zone: 'display' },
    loadComponent: () => import('./project-detail/project-detail').then((m) => m.ProjectDetail),
  },
];
