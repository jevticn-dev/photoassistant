import { Injectable, signal } from '@angular/core';

const STORAGE_KEY = 'photoassistant.accessToken';

/**
 * Holds the access token and mirrors it into localStorage so a page reload does
 * not sign the user out.
 *
 * The token is exposed as a signal, so anything that depends on "is someone
 * signed in" updates on its own rather than by being told.
 */
@Injectable({ providedIn: 'root' })
export class TokenStorage {
  private readonly token = signal<string | null>(readStoredToken());

  readonly accessToken = this.token.asReadonly();

  /** Cheap enough to compute on demand; no attempt to validate the signature. */
  readonly isAuthenticated = () => this.token() !== null;

  set(token: string): void {
    this.token.set(token);
    localStorage.setItem(STORAGE_KEY, token);
  }

  clear(): void {
    this.token.set(null);
    localStorage.removeItem(STORAGE_KEY);
  }
}

function readStoredToken(): string | null {
  // Guards against storage being unavailable (private mode, disabled cookies).
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}
