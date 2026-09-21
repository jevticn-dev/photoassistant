/**
 * Development configuration, and the file the application imports. The
 * production build swaps it for environment.production.ts through
 * `fileReplacements` in angular.json.
 *
 * The API address is relative, the same as in production, and deliberately so.
 * The dev server forwards /api to the .NET API (`proxy.config.json`) exactly as
 * nginx does in the delivered stack, so the browser talks to one origin either
 * way.
 *
 * Two consequences. The API needs no CORS policy — there is no cross-origin
 * request to permit, and therefore no permissive development rule that could
 * survive into production. And a mistake made with an absolute address cannot
 * hide until the full stack is assembled, because development is no longer the
 * lenient case.
 *
 * Changing where the API listens means editing the proxy, not this file.
 */
export const environment = {
  production: false,

  /** The .NET API is the only address the frontend ever calls (ADR-8). */
  apiBaseUrl: '/api',

  defaultLanguage: 'en',
};
