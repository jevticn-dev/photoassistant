import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { routes } from './app.routes';
import { SuggestionsService } from './features/suggestions/suggestions-service';
import { TokenStorage } from './core/auth/token-storage';
import { provideTranslations } from './core/i18n/translation.config';

/**
 * That every address the application navigates to actually resolves.
 *
 * <p>This exists because of how the failure looks. `app.routes.ts` ends with
 * `{ path: '**', redirectTo: 'projects' }`, so an address that matches nothing
 * does not error — it quietly lands on the project list. A route that was never
 * added therefore presents as "the upload finished but did not open the
 * project", which sends you looking at the upload.</p>
 *
 * <p>Every task that adds a screen should add a line here.</p>
 */
describe('routes', () => {
  let router: Router;
  let tokens: TokenStorage;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideRouter(routes),
        provideHttpClient(),
        provideHttpClientTesting(),
        provideTranslations(),

        // The suggestion route is guarded by a question to the server. This
        // file is about whether addresses resolve, so the answer is stubbed;
        // what the guard does with it is tested where the guard lives.
        {
          provide: SuggestionsService,
          useValue: {
            project: () => of({ hasChoice: false }),
          },
        },
      ],
    });

    router = TestBed.inject(Router);
    tokens = TestBed.inject(TokenStorage);
  });

  afterEach(() => localStorage.clear());

  it.each([
    ['/projects'],
    ['/projects/0199a1f0-0000-7000-8000-000000000001'],
    ['/projects/0199a1f0-0000-7000-8000-000000000001/edit'],
    ['/upload'],
    ['/renderer-lab'],
  ])('%s resolves to a screen of its own when signed in', async (address) => {
    tokens.set('a.b.c');

    await router.navigateByUrl(address);

    // Landing somewhere else means the wildcard caught it, which is the silent
    // failure this file exists to make loud.
    expect(router.url).toBe(address);
  });

  it.each([['/auth/login'], ['/auth/register']])(
    '%s resolves to a screen of its own when signed out',
    async (address) => {
      await router.navigateByUrl(address);

      expect(router.url).toBe(address);
    },
  );

  it('an unknown address still falls back to the project list', async () => {
    tokens.set('a.b.c');

    await router.navigateByUrl('/nowhere');

    expect(router.url).toBe('/projects');
  });

  it('an unauthenticated visitor is sent to sign in, keeping where they were going', async () => {
    await router.navigateByUrl('/upload');

    expect(router.url).toBe('/auth/login?returnUrl=%2Fupload');
  });

  it.each([['/auth/login'], ['/auth/register']])(
    '%s sends a signed-in person back to the application',
    async (address) => {
      // A form asking someone to sign in when they already are is a dead end:
      // submitting it would hand them the session they are holding.
      tokens.set('a.b.c');

      await router.navigateByUrl(address);

      expect(router.url).toBe('/projects');
    },
  );
});
