/**
 * Production configuration.
 *
 * A relative path on purpose: nginx serves the SPA and proxies /api to the api
 * container, so the browser never needs to know a host name. That also keeps the
 * ML service unreachable — nginx has no route to it (see .claude/rules/ml_service.md).
 */
export const environment = {
  production: true,

  apiBaseUrl: '/api',

  defaultLanguage: 'en',
};
