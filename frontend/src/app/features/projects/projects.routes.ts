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
    // Every export of one project, reached from its card. The housing zone:
    // this is a list of files, not a photograph being judged.
    path: ':id/exports',
    loadComponent: () => import('./project-exports/project-exports').then((m) => m.ProjectExports),
  },
  {
    // Where a choice lands, and where a project is reopened. The display zone
    // for the same reason as the screen above it: this is a photograph being
    // judged, and a light surround changes that judgement.
    path: ':id/edit',
    data: { zone: 'display' },
    loadComponent: () => import('../editor/editor').then((m) => m.Editor),
  },
];
