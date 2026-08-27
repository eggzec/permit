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
    Verifies that `app.api.routes.health.health_check` returns the public health
    payload with an OK status and timestamp. This matters because infrastructure
    and uptime checks depend on a stable liveness contract.

    Covers:
        - `app.api.routes.health.health_check`

    Rationale:
        This is a straightforward route integration test with no fixtures or patches because the endpoint contract is fully observable from the response.

    Fixtures:
        None.
    """
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == status.HTTP_200_OK, (
        f"Expected status 200 OK, got {response.status_code}: {response.text}"
    )
    data = response.json()
    assert data["data"]["status"] == "ok", (
        f"Expected status to be 'ok', got '{data['data']['status']}'"
    )
    assert "timestamp" in data["data"], (
        "Expected 'timestamp' field in health response data,"
        f" got keys: {data['data'].keys()}"
    )


@pytest.mark.integration
@pytest.mark.api
def test_health_check_has_request_id():
    """
    Verifies that `app.api.routes.health.health_check` responses include the
    request-id header added by the middleware stack. This matters because error
    and success responses should be traceable with the same correlation
    identifier mechanism.

    Covers:
        - `app.api.routes.health.health_check`
        - request-id middleware behavior on a healthy route response

    Rationale:
        The test asserts only the externally visible header because the middleware contract is exposed through the response.

    Fixtures:
        None.
    """
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
    assert "x-request-id" in response.headers, (
        "Expected 'x-request-id' header in health endpoint response, "
        f"got headers: {list(response.headers.keys())}"
    )
