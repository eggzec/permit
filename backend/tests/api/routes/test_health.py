"""
Integration tests for the /health endpoint.
"""

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.main import app


@pytest.mark.integration
@pytest.mark.api
def test_health_check_returns_ok(override_get_db):
    """
    WHEN the /health endpoint is called
    THEN it should return a 200 OK response with the status and timestamp
    """
    client = TestClient(app)
    response = client.get("/api/v1/health")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["data"]["status"] == "ok"
    assert "timestamp" in data["data"]


@pytest.mark.integration
@pytest.mark.api
def test_health_check_has_request_id(override_get_db):
    """
    WHEN the /health endpoint is called
    THEN the response should contain an X-Request-ID header
    """
    client = TestClient(app)
    response = client.get("/api/v1/health")
    assert "x-request-id" in response.headers
