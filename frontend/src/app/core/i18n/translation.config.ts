import { Provider } from '@angular/core';
import { provideTranslateService } from '@ngx-translate/core';
import { provideTranslateHttpLoader } from '@ngx-translate/http-loader';

import { environment } from '../../../environments/environment';

/**
 * Runtime translation loading.
 *
 * ngx-translate rather than the built-in @angular/localize (plan §11 allows
 * either): translations are fetched at runtime from a JSON file, so adding
 * Serbian later means dropping in sr.json — no separate build and no
 * per-language bundle. The built-in mechanism works at build time and cannot
 * switch language while the application is running.
 *
 * HttpClient is not provided here; it is registered once in app.config.ts,
 * together with the interceptor that attaches the access token.
 */
export function provideTranslations(): Provider[] {
  return [
    provideTranslateService({
      lang: environment.defaultLanguage,
      fallbackLang: environment.defaultLanguage,
    }),
    provideTranslateHttpLoader({
      prefix: './assets/i18n/',
      suffix: '.json',
    }),
  ];
}
