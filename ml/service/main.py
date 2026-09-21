"""FastAPI application entry point."""

from fastapi import FastAPI

from photoassistant import __version__
from service import worker
from service.routes import derivatives, health, recommend

app = FastAPI(
    title="PhotoAssistant ML service",
    version=__version__,
    # The export worker starts with the application and is cancelled with it
    # (decision F). It is a loop over the `jobs` table rather than a container of
    # its own: the work it does needs this image's renderer and schema anyway.
    lifespan=worker.lifespan,
    description=(
        "Internal service: embedding, recommendation, render and export. "
        "Reachable by the .NET API only, not by a browser."
    ),
)

app.include_router(derivatives.router)
app.include_router(health.router)
app.include_router(recommend.router)
