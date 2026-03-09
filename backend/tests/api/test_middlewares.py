import uuid

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api.middlewares import add_request_id


@pytest.fixture
def middleware_app():
    """
    Provides a minimal FastAPI app with the request-id middleware installed and an echo endpoint for assertions.

    Scope: function — the fixture builds a fresh app object per test and the app state is mutable during request handling.

    Provides:
        A `FastAPI` instance whose `/echo` route returns `request.state.request_id`.

    Dependencies:
        None.

    Teardown:
        None.

    Note:
        This fixture exists only to exercise `app.api.middlewares.add_request_id` in isolation from the main application.
    """
    app = FastAPI()
    app.middleware("http")(add_request_id)

    @app.get("/echo")
    async def echo(request: Request):
        return {"request_id": request.state.request_id}

    return app


@pytest.mark.unit
def test_add_request_id_preserves_valid_incoming_header(middleware_app):
    """
    Verifies that `app.api.middlewares.add_request_id` preserves a valid
    incoming request id instead of replacing it. This matters because upstream
    systems may supply trace identifiers that should survive through the
    application.

    Covers:
        - `app.api.middlewares.add_request_id`

    Rationale:
        The middleware is exercised through a tiny in-process app because the contract under test is the header and request-state outcome.

    Fixtures:
        middleware_app: Minimal FastAPI app with the request-id middleware and an echo endpoint.
    """
    incoming = "123e4567-e89b-12d3-a456-426614174000"

    with TestClient(middleware_app) as client:
        response = client.get("/echo", headers={"X-Request-ID": incoming})

    assert response.status_code == 200, (
        f"Expected 200 response, got {response.status_code}: {response.text}"
    )
    assert response.headers.get("X-Request-ID") == incoming, (
        "Middleware must preserve a valid incoming request id in response header"
    )
    assert response.json()["request_id"] == incoming, (
        "Middleware must store the same valid request id on request.state"
    )


@pytest.mark.unit
def test_add_request_id_replaces_invalid_header_with_uuid(middleware_app):
    """
    Verifies that `app.api.middlewares.add_request_id` replaces an invalid
    incoming request id with a fresh canonical UUID. This matters because
    downstream tracing should not trust malformed client-supplied identifiers.

    Covers:
        - `app.api.middlewares.add_request_id`

    Rationale:
        The assertions stay at the observable boundary by checking the response header and `request.state` value rather than middleware internals.

    Fixtures:
        middleware_app: Minimal FastAPI app with the request-id middleware and an echo endpoint.
    """
    incoming = "not-a-uuid"

    with TestClient(middleware_app) as client:
        response = client.get("/echo", headers={"X-Request-ID": incoming})

    assert response.status_code == 200, (
        f"Expected 200 response, got {response.status_code}: {response.text}"
    )
    generated = response.headers.get("X-Request-ID")
    assert generated, "Middleware must always emit an X-Request-ID header"
    assert generated != incoming, (
        "Middleware must replace invalid incoming request ids with a new UUID"
    )
    parsed = uuid.UUID(generated)
    assert str(parsed) == generated, (
        "Generated request id header must be a canonical UUID string"
    )
    assert response.json()["request_id"] == generated, (
        "request.state.request_id must match the response X-Request-ID header"
    )
