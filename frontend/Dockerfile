# Build context is the repository root, so the nginx configuration can come from
# infra/ — where deployment topology belongs — rather than being duplicated here.

FROM node:24.18.0-alpine AS build
WORKDIR /src

# npm ci installs exactly what package-lock.json pins and fails if the lock file
# disagrees with package.json — the same guarantee uv --frozen gives on the
# Python side.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------

FROM nginx:1.31-alpine AS runtime

COPY --from=build /src/dist/photoassistant-web/browser /usr/share/nginx/html
COPY infra/nginx/default.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

# BusyBox wget ships with the alpine image, so nothing extra is installed.
#
# 127.0.0.1 rather than localhost: BusyBox wget tries only the first address
# getaddrinfo returns, which is ::1 here, and does not fall back the way curl and
# Python's urllib do. The nginx config now listens on IPv6 as well, so either
# would work — this stays explicit so the check cannot depend on that.
HEALTHCHECK --interval=10s --timeout=5s --retries=10 --start-period=5s \
    CMD wget --quiet --spider http://127.0.0.1/ || exit 1
