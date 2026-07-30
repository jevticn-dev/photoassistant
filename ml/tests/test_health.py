"""Health endpoint checks."""

from fastapi.testclient import TestClient

from photoassistant import __version__
from service.main import app

client = TestClient(app)


def test_health_returns_status_and_version() -> None:
    response = client.get("/health")

    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "Healthy"
    assert body["version"] == __version__


def test_health_reports_no_dependency_checks_yet() -> None:
    """The empty ``checks`` list is a claim, not an oversight.

    At this stage the service opens neither the database nor storage, so
    "Healthy" must not be read as though either had been verified. When real
    checks arrive in phase 2 this test fails and is changed then — deliberately,
    so the change cannot slip through unnoticed.
    """
    response = client.get("/health")

    assert response.json()["checks"] == []


def test_openapi_document_is_served() -> None:
    """Plan §9 requires OpenAPI on both boundaries, not just the .NET one."""
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/health" in response.json()["paths"]
