import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';

import { environment } from '../../../environments/environment';
import { TokenStorage } from './token-storage';

/**
 * Attaches the access token to outgoing requests.
 *
 * Only requests aimed at our own API are touched: a token must never be sent to
 * a third-party host that a URL happens to point at.
 */
export const authInterceptor: HttpInterceptorFn = (request, next) => {
  const token = inject(TokenStorage).accessToken();

  if (!token || !request.url.startsWith(environment.apiBaseUrl)) {
    return next(request);
  }

  return next(
    request.clone({
      setHeaders: { Authorization: `Bearer ${token}` },
    }),
  );
};
