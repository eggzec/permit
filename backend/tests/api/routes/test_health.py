"""
Integration tests for the /health endpoint.
"""

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.main import app


@pytest.mark.integration
@pytest.mark.api
def test_health_check_returns_ok():
    """
    WHEN the /health endpoint is called
    THEN it should return a 200 OK response with the status and timestamp
    """
    client = TestClient(app)
    response = client.get("/api/v1/health")
    assert response.status_code == status.HTTP_200_OK, (
        f"Expected status 200 OK, got {response.status_code}: {response.text}"
    )
    data = response.json()
    assert data["data"]["status"] == "ok", (
        f"Expected status to be 'ok', got '{data['data']['status']}'"
    )
    assert "timestamp" in data["data"], (
        f"Expected 'timestamp' field in health response data, got keys: {data['data'].keys()}"
    )


@pytest.mark.integration
@pytest.mark.api
def test_health_check_has_request_id():
    """
    WHEN the /health endpoint is called
    THEN the response should contain an X-Request-ID header
    """
    client = TestClient(app)
    response = client.get("/api/v1/health")
    assert "x-request-id" in response.headers, (
        "Expected 'x-request-id' header in health endpoint response, "
        f"got headers: {list(response.headers.keys())}"
    )
