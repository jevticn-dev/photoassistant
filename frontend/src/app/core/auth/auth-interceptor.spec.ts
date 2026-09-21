import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';

import { environment } from '../../../environments/environment';
import { authInterceptor } from './auth-interceptor';
import { TokenStorage } from './token-storage';

const OURS = `${environment.apiBaseUrl}/projects`;

describe('authInterceptor', () => {
  let http: HttpClient;
  let backend: HttpTestingController;
  let tokens: TokenStorage;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideRouter([{ path: 'auth/login', children: [] }]),
        provideHttpClient(withInterceptors([authInterceptor])),
        provideHttpClientTesting(),
      ],
    });

    http = TestBed.inject(HttpClient);
    backend = TestBed.inject(HttpTestingController);
    tokens = TestBed.inject(TokenStorage);
  });

  afterEach(() => backend.verify());

  it('attaches the token to our own API', () => {
    tokens.set('a.b.c');
    http.get(OURS).subscribe({ error: () => undefined });

    const request = backend.expectOne(OURS);

    expect(request.request.headers.get('Authorization')).toBe('Bearer a.b.c');
    request.flush({});
  });

  it('never attaches it to anywhere else', () => {
    tokens.set('a.b.c');
    http.get('https://example.com/whatever').subscribe({ error: () => undefined });

    const request = backend.expectOne('https://example.com/whatever');

    expect(request.request.headers.has('Authorization')).toBe(false);
    request.flush({});
  });

  it('forgets a token the server has rejected, and asks for a new sign-in', () => {
    // Otherwise it stays in storage: the guard still sees someone signed in,
    // every screen fails with "your session has expired", and the only way out
    // is clearing localStorage by hand.
    //
    // The navigation is asserted by intent rather than by the resulting url —
    // it is started inside the failing request's handler, and waiting for it
    // to settle would be racing the router for no added confidence.
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigate');
    tokens.set('expired.token.here');
    http.get(OURS).subscribe({ error: () => undefined });

    backend.expectOne(OURS).flush({}, { status: 401, statusText: 'Unauthorized' });

    expect(tokens.accessToken()).toBeNull();
    expect(navigate).toHaveBeenCalledWith(['/auth/login'], expect.anything());
  });

  it('leaves the token alone when the failure is not about authentication', () => {
    // A 503 from the ML service must not sign anyone out.
    tokens.set('a.b.c');
    http.get(OURS).subscribe({ error: () => undefined });

    backend.expectOne(OURS).flush({}, { status: 503, statusText: 'Service Unavailable' });

    expect(tokens.accessToken()).toBe('a.b.c');
  });
});
