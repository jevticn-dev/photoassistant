import { HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { environment } from '../../../environments/environment';
import { AuthFailure, AuthService, Session, firstMessage } from './auth-service';
import { TokenStorage } from './token-storage';

const SESSION: Session = {
  accessToken: 'a.b.c',
  expiresAt: '2026-09-19T00:00:00+00:00',
  userId: '00000000-0000-0000-0000-000000000001',
  email: 'nikola@test.rs',
};

const CREDENTIALS = { email: 'nikola@test.rs', password: 'Test1234!' };

describe('AuthService', () => {
  let service: AuthService;
  let http: HttpTestingController;
  let tokens: TokenStorage;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });

    service = TestBed.inject(AuthService);
    http = TestBed.inject(HttpTestingController);
    tokens = TestBed.inject(TokenStorage);
  });

  afterEach(() => http.verify());

  function expectPost(endpoint: 'register' | 'login') {
    return http.expectOne(`${environment.apiBaseUrl}/auth/${endpoint}`);
  }

  it('stores the token before the caller is told the sign-in succeeded', () => {
    // Order matters: a component that navigates on success must not beat the
    // guard that reads the token.
    let tokenWhenNotified: string | null = null;
    service.login(CREDENTIALS).subscribe(() => (tokenWhenNotified = tokens.accessToken()));

    expectPost('login').flush(SESSION);

    expect(tokenWhenNotified).toBe(SESSION.accessToken);
  });

  it('registers against the register endpoint, not login', () => {
    service.register(CREDENTIALS).subscribe();

    const request = expectPost('register');

    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual(CREDENTIALS);
  });

  it('reports a 400 as per-field messages, keyed as the form names them', () => {
    let failure: AuthFailure | undefined;
    service.register(CREDENTIALS).subscribe({ error: (error: AuthFailure) => (failure = error) });

    // The server keys by request-field name; the forms use lower case.
    expectPost('register').flush(
      { errors: { Email: ["Email 'nikola@test.rs' is already taken."] } },
      { status: 400, statusText: 'Bad Request' },
    );

    expect(firstMessage(failure ?? null, 'email')).toBe("Email 'nikola@test.rs' is already taken.");
    expect(failure?.summaryKey).toBeNull();
  });

  it('turns a 401 into one message of our own, never the server wording', () => {
    // Login answers identically for an unknown address and a wrong password on
    // purpose; echoing the server's detail would risk leaking that difference
    // if the server ever stopped being careful.
    let failure: AuthFailure | undefined;
    service.login(CREDENTIALS).subscribe({ error: (error: AuthFailure) => (failure = error) });

    expectPost('login').flush(
      { title: 'Authentication failed', detail: 'Invalid email or password.' },
      { status: 401, statusText: 'Unauthorized' },
    );

    expect(failure?.summaryKey).toBe('auth.errors.invalidCredentials');
    expect(failure?.fields).toEqual({});
  });

  it('distinguishes an unreachable server from a failing one', () => {
    let failure: AuthFailure | undefined;
    service.login(CREDENTIALS).subscribe({ error: (error: AuthFailure) => (failure = error) });

    expectPost('login').error(new ProgressEvent('error'), { status: 0, statusText: '' });

    expect(failure?.summaryKey).toBe('auth.errors.unreachable');
  });

  it('does not store a token when the attempt failed', () => {
    service.login(CREDENTIALS).subscribe({ error: () => undefined });

    expectPost('login').flush({}, { status: 401, statusText: 'Unauthorized' });

    expect(tokens.accessToken()).toBeNull();
  });

  it('signing out clears the token', () => {
    tokens.set(SESSION.accessToken);

    service.signOut();

    expect(tokens.accessToken()).toBeNull();
    expect(service.isAuthenticated()).toBe(false);
  });

  it('treats something that is not an HTTP failure as unexpected', () => {
    // Guards the type narrowing: a thrown TypeError must not fall through the
    // HttpErrorResponse branches and read `.status` off nothing.
    let failure: AuthFailure | undefined;
    service.login(CREDENTIALS).subscribe({ error: (error: AuthFailure) => (failure = error) });

    const request = expectPost('login');
    request.error(new ProgressEvent('boom'), { status: 500, statusText: 'Server Error' });

    expect(failure?.summaryKey).toBe('auth.errors.unexpected');
    expect(failure instanceof HttpErrorResponse).toBe(false);
  });
});
