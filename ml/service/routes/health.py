"""Health check.

At this stage the service has no external dependencies — it opens neither the
database nor object storage. The response says so **explicitly** through an empty
``checks`` list, so that "Healthy" is not read as a claim about something that was
never verified.

When ``storage`` and database access arrive in phase 2, real checks go here and
the answer stops being unconditional.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from photoassistant import __version__
from service.settings import Settings, get_settings

router = APIRouter(tags=["health"])

# The dependency is expressed through Annotated rather than a default argument
# value: the signature stays readable and is not executable code evaluated at
# import time.
SettingsDependency = Annotated[Settings, Depends(get_settings)]


class HealthResponse(BaseModel):
    """Shape of the health response. Same keys as the .NET side, so monitoring is uniform."""

    status: Literal["Healthy", "Unhealthy"]
    version: str
    environment: str
    checks: list[str] = Field(
        default_factory=list,
        description="External dependency checks. Empty while the service has none.",
    )


@router.get("/health", response_model=HealthResponse, summary="Liveness and service version")
def health(settings: SettingsDependency) -> HealthResponse:
    return HealthResponse(
        status="Healthy",
        version=__version__,
        environment=settings.environment,
        checks=[],
    )
