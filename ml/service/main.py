"""FastAPI application entry point."""

from fastapi import FastAPI

from photoassistant import __version__
from service.routes import health

app = FastAPI(
    title="PhotoAssistant ML service",
    version=__version__,
    description=(
        "Internal service: embedding, recommendation, render and export. "
        "Reachable by the .NET API only, not by a browser."
    ),
)

app.include_router(health.router)
