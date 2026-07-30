/**
 * Development configuration.
 *
 * The API base address lives here and nowhere else: no service may hard-code a
 * host. Under docker compose the SPA is served by nginx, which proxies /api to
 * the api container, so the production file below uses a relative path.
 */
export const environment = {
  production: false,

  /** The .NET API is the only address the frontend ever calls (ADR-8). */
  apiBaseUrl: 'http://localhost:8080/api',

  defaultLanguage: 'en',
};
