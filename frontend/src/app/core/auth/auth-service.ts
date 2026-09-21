import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, tap, throwError } from 'rxjs';

import { environment } from '../../../environments/environment';
import { TokenStorage } from './token-storage';

/** What the API asks for on both endpoints. */
export interface Credentials {
  readonly email: string;
  readonly password: string;
}

/** A successfully issued token, as `AuthenticationResponse` on the server. */
export interface Session {
  readonly accessToken: string;
  readonly expiresAt: string;
  readonly userId: string;
  readonly email: string;
}

/**
 * Why an attempt failed, in the shape a form can render.
 *
 * `fields` is keyed by form control name. The server groups Identity's errors
 * the same way — a weak password lands on the password field rather than on the
 * form — so the mapping here is a rename, not a guess.
 *
 * `summaryKey` is a translation key for messages we own. Anything the server
 * worded stays in `fields`; we never invent a key for text we did not write.
 */
export interface AuthFailure {
  readonly fields: Readonly<Record<string, readonly string[]>>;
  readonly summaryKey: string | null;
}

/**
 * The part of RFC 9457 we read. `detail` is deliberately absent: the only place
 * it carries anything is the 401, and that one must not be echoed (see below).
 * Field wording inside `errors` is the server's, in English, and is shown as it
 * arrives — localising it is a server-side job and is out of scope here.
 */
interface ProblemDetails {
  readonly errors?: Record<string, string[]>;
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly tokens = inject(TokenStorage);

  /** Tracks the stored token, so a guard or a menu reacts without being told. */
  readonly isAuthenticated = this.tokens.isAuthenticated;

  register(credentials: Credentials): Observable<Session> {
    return this.send('register', credentials);
  }

  login(credentials: Credentials): Observable<Session> {
    return this.send('login', credentials);
  }

  /**
   * Drops the token. There is nothing to tell the server: the token is a signed
   * claim it does not keep a copy of, so signing out is a local act until
   * revocation exists (out of scope, `ClockSkew` is zero and lifetimes short).
   */
  signOut(): void {
    this.tokens.clear();
  }

  private send(endpoint: 'register' | 'login', credentials: Credentials): Observable<Session> {
    return this.http.post<Session>(`${environment.apiBaseUrl}/auth/${endpoint}`, credentials).pipe(
      // Stored before the caller sees the session, so a component that
      // navigates on success cannot race the guard that reads the token.
      tap((session) => this.tokens.set(session.accessToken)),
      catchError((error: unknown) => throwError(() => toFailure(error))),
    );
  }
}

/**
 * Turns whatever went wrong into something a form can display.
 *
 * The three cases are deliberately distinct. A 400 carries per-field wording
 * worth showing. A 401 must not: login answers identically for an unknown
 * address and a wrong password, on purpose, so the client says one thing too.
 * Everything else — no network, a 500, a proxy in the way — is our message, and
 * goes through a translation key.
 */
function toFailure(error: unknown): AuthFailure {
  if (!(error instanceof HttpErrorResponse)) {
    return { fields: {}, summaryKey: 'auth.errors.unexpected' };
  }

  if (error.status === 400) {
    const problem = error.error as ProblemDetails | null;
    const fields = problem?.errors ?? {};

    return {
      // The server keys by request-field name (Email, Password); the forms use
      // the same names in lower case.
      fields: Object.fromEntries(
        Object.entries(fields).map(([field, messages]) => [lowerFirst(field), messages]),
      ),
      summaryKey: Object.keys(fields).length > 0 ? null : 'auth.errors.unexpected',
    };
  }

  if (error.status === 401) {
    return { fields: {}, summaryKey: 'auth.errors.invalidCredentials' };
  }

  // status 0 is the browser refusing or failing to reach the host at all.
  return {
    fields: {},
    summaryKey: error.status === 0 ? 'auth.errors.unreachable' : 'auth.errors.unexpected',
  };
}

function lowerFirst(value: string): string {
  return value.charAt(0).toLowerCase() + value.slice(1);
}

/**
 * The first message for a field, if the server sent one.
 *
 * Only the first: Identity can return several complaints about one password at
 * once, and a list of five under a single input is worse to act on than the one
 * that has to be fixed first.
 */
export function firstMessage(failure: AuthFailure | null, field: string): string | null {
  return failure?.fields[field]?.[0] ?? null;
}
