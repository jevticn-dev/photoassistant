import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter, withComponentInputBinding } from '@angular/router';

import { routes } from './app.routes';
import { authInterceptor } from './core/auth/auth-interceptor';
import { provideTranslations } from './core/i18n/translation.config';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes, withComponentInputBinding()),

    // Registered once for the whole application, so every request — including
    // the ones ngx-translate makes to fetch translation files — goes through
    // the same client.
    provideHttpClient(withInterceptors([authInterceptor])),

    provideTranslations(),
  ],
};
