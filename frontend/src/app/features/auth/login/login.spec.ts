import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';

import { environment } from '../../../../environments/environment';
import { provideTranslations } from '../../../core/i18n/translation.config';
import { Login } from './login';

const SESSION = {
  accessToken: 'a.b.c',
  expiresAt: '2026-09-19T00:00:00+00:00',
  userId: '00000000-0000-0000-0000-000000000001',
  email: 'nikola@test.rs',
};

describe('Login', () => {
  let fixture: ComponentFixture<Login>;
  let http: HttpTestingController;
  let router: Router;

  beforeEach(async () => {
    localStorage.clear();
    await TestBed.configureTestingModule({
      imports: [Login],
      providers: [
        // Real routes, so a successful sign-in navigates instead of rejecting.
        // Empty children are enough: nothing here renders the destination.
        provideRouter([
          { path: 'projects', children: [] },
          { path: 'projects/:id', children: [] },
        ]),
        provideHttpClient(),
        provideHttpClientTesting(),
        provideTranslations(),
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(Login);
    http = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    fixture.detectChanges();
  });

  afterEach(() => {
    // ngx-translate fetches its catalogue through the same testing backend.
    // Draining it keeps `verify()` about the requests this screen makes; the
    // empty body is what the tests then assert against, since a missing key
    // makes the pipe echo the key itself.
    http.match((request) => request.url.includes('/i18n/')).forEach((request) => request.flush({}));
    http.verify();
  });

  function element(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function fill(email: string, password: string): void {
    for (const [id, value] of [
      ['#login-email', email],
      ['#login-password', password],
    ]) {
      const input = element().querySelector<HTMLInputElement>(id)!;
      input.value = value;
      input.dispatchEvent(new Event('input'));
    }
    fixture.detectChanges();
  }

  function submitButton(): HTMLButtonElement {
    return element().querySelector<HTMLButtonElement>('.auth-submit')!;
  }

  it('keeps submit unavailable until both fields are usable', () => {
    expect(submitButton().disabled).toBe(true);

    fill('not-an-email', 'whatever');
    expect(submitButton().disabled).toBe(true);

    fill('nikola@test.rs', 'whatever');
    expect(submitButton().disabled).toBe(false);
  });

  it('sends the credentials and goes where the guard intended', async () => {
    // The guard puts the attempted address in returnUrl; landing anywhere else
    // makes a deep link silently lose the user's place.
    await router.navigate([], { queryParams: { returnUrl: '/projects/42' } });
    const navigate = vi.spyOn(router, 'navigateByUrl');

    fill('nikola@test.rs', 'Test1234!');
    submitButton().click();

    http.expectOne(`${environment.apiBaseUrl}/auth/login`).flush(SESSION);
    fixture.detectChanges();

    expect(navigate).toHaveBeenCalledWith('/projects/42');
  });

  it('falls back to the project list when nothing was intended', async () => {
    const navigate = vi.spyOn(router, 'navigateByUrl');

    fill('nikola@test.rs', 'Test1234!');
    submitButton().click();
    http.expectOne(`${environment.apiBaseUrl}/auth/login`).flush(SESSION);

    expect(navigate).toHaveBeenCalledWith('/projects');
  });

  it('shows one message for rejected credentials and lets the user try again', () => {
    fill('nikola@test.rs', 'wrong-password');
    submitButton().click();

    http
      .expectOne(`${environment.apiBaseUrl}/auth/login`)
      .flush({}, { status: 401, statusText: 'Unauthorized' });
    fixture.detectChanges();

    const summary = element().querySelector('.auth-summary');

    // No translation file is loaded in tests, so ngx-translate echoes the key.
    expect(summary?.textContent?.trim()).toBe('auth.errors.invalidCredentials');
    // Re-enabled, or a mistyped password would strand the user on a dead form.
    expect(submitButton().disabled).toBe(false);
  });

  it('does not send a second request while one is in flight', () => {
    fill('nikola@test.rs', 'Test1234!');
    submitButton().click();
    submitButton().click();

    // expectOne fails if the click sent another; that is the assertion.
    http.expectOne(`${environment.apiBaseUrl}/auth/login`).flush(SESSION);
  });
});
