import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';

import { environment } from '../../../environments/environment';
import { TokenStorage } from './token-storage';

/**
 * Attaches the access token to outgoing requests, and drops it when the server
 * says it is no longer good.
 *
 * Only requests aimed at our own API are touched: a token must never be sent to
 * a third-party host that a URL happens to point at.
 */
export const authInterceptor: HttpInterceptorFn = (request, next) => {
  const tokens = inject(TokenStorage);
  const router = inject(Router);
  const token = tokens.accessToken();

  if (!token || !request.url.startsWith(environment.apiBaseUrl)) {
    return next(request);
  }

  return next(request.clone({ setHeaders: { Authorization: `Bearer ${token}` } })).pipe(
    catchError((error: unknown) => {
      // A 401 on a request that carried a token means the token is finished —
      // expired, or issued by a server that has since restarted with another
      // signing key. There is no refresh in v1 (plan §9), so the only honest
      // response is to forget it and ask for a sign-in.
      //
      // Without this the token stays in storage: the guard sees someone signed
      // in, every screen fails with "your session has expired", and the way out
      // is clearing localStorage by hand. Which is what happened.
      if (error instanceof HttpErrorResponse && error.status === 401) {
        tokens.clear();

        void router.navigate(['/auth/login'], {
          queryParams: { returnUrl: router.url },
        });
      }

      return throwError(() => error);
    }),
  );
};
