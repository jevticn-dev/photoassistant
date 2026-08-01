# Build context is the repository root, because global.json lives there and it
# is what pins the SDK version.

FROM mcr.microsoft.com/dotnet/sdk:10.0.302 AS build
WORKDIR /src

# Project files first, on their own layer: restoring packages is slow, and a
# change to source code must not invalidate it.
COPY global.json ./
COPY backend/Directory.Build.props backend/Directory.Packages.props backend/PhotoAssistant.slnx backend/
COPY backend/src/PhotoAssistant.Domain/PhotoAssistant.Domain.csproj backend/src/PhotoAssistant.Domain/
COPY backend/src/PhotoAssistant.Application/PhotoAssistant.Application.csproj backend/src/PhotoAssistant.Application/
COPY backend/src/PhotoAssistant.Infrastructure/PhotoAssistant.Infrastructure.csproj backend/src/PhotoAssistant.Infrastructure/
COPY backend/src/PhotoAssistant.Api/PhotoAssistant.Api.csproj backend/src/PhotoAssistant.Api/
COPY backend/tests/PhotoAssistant.Api.Tests/PhotoAssistant.Api.Tests.csproj backend/tests/PhotoAssistant.Api.Tests/

RUN dotnet restore backend/PhotoAssistant.slnx

COPY backend/ backend/
RUN dotnet publish backend/src/PhotoAssistant.Api \
    -c Release \
    -o /app \
    --no-restore

# ---------------------------------------------------------------------------

FROM mcr.microsoft.com/dotnet/aspnet:10.0.10 AS runtime
WORKDIR /app

# curl is not in the runtime image and is needed by the health check below.
# Roughly a megabyte, and it makes the container able to report its own state.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Runs as a non-root user, which the base image already provides.
USER $APP_UID

COPY --from=build /app ./

ENV ASPNETCORE_HTTP_PORTS=8080
EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=5s --retries=10 --start-period=20s \
    CMD curl --fail --silent http://localhost:8080/health || exit 1

ENTRYPOINT ["dotnet", "PhotoAssistant.Api.dll"]
