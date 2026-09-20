import { TestBed } from '@angular/core/testing';
import { ActivatedRouteSnapshot, RedirectCommand, Router, provideRouter } from '@angular/router';
import { Observable, of, throwError } from 'rxjs';

import { chosenGuard } from './chosen-guard';
import { type Project, SuggestionsService } from './suggestions-service';

const PROJECT = '0199a1f0-0000-7000-8000-000000000001';

function project(hasChoice: boolean): Project {
  return {
    id: PROJECT,
    name: 'Alpine Ridge',
    photoId: '0199a1f0-0000-7000-8000-000000000002',
    createdAt: '2026-09-20T10:00:00+00:00',
    versionCount: 0,
    hasChoice,
    startingEdit: null,
  };
}

function run(answer: Observable<Project>, id: string | null = PROJECT) {
  TestBed.configureTestingModule({
    providers: [
      provideRouter([]),
      { provide: SuggestionsService, useValue: { project: () => answer } },
    ],
  });

  const snapshot = {
    paramMap: { get: () => id },
  } as unknown as ActivatedRouteSnapshot;

  return TestBed.runInInjectionContext(() =>
    chosenGuard(snapshot, { url: '' } as never),
  ) as Observable<boolean | RedirectCommand>;
}

describe('chosenGuard', () => {
  it('lets a project that has not been decided through', async () => {
    const result = await firstValue(run(of(project(false))));

    expect(result).toBe(true);
  });

  it('sends a project that has been decided on to the editor', async () => {
    // Choosing is one way: Back must not offer the three cards again, which
    // would log a second choice and reopen the editor on a different recipe
    // than the one already being worked on.
    const result = await firstValue(run(of(project(true))));

    expect(result).toBeInstanceOf(RedirectCommand);
  });

  it('replaces the history entry rather than stacking one', async () => {
    // Otherwise Back from the editor lands here, is redirected forward, and
    // the person is trapped two presses deep.
    const result = (await firstValue(run(of(project(true))))) as RedirectCommand;

    expect(result.navigationBehaviorOptions?.replaceUrl).toBe(true);
    expect(TestBed.inject(Router).serializeUrl(result.redirectTo)).toBe(
      `/projects/${PROJECT}/edit`,
    );
  });

  it('does not block when the project cannot be read', async () => {
    // The screen reports a missing or unreachable project far better than a
    // redirect to somewhere equally unavailable.
    const result = await firstValue(run(throwError(() => new Error('offline'))));

    expect(result).toBe(true);
  });

  it('does not block a route without a project id', async () => {
    const result = run(of(project(true)), null);

    expect(await firstValue(result)).toBe(true);
  });
});

function firstValue<T>(source: Observable<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    source.subscribe({ next: resolve, error: reject });
  });
}
