import uuid

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api.middlewares import add_request_id


@pytest.fixture
def middleware_app():
    app = FastAPI()
    app.middleware("http")(add_request_id)

    @app.get("/echo")
    async def echo(request: Request):
        return {"request_id": request.state.request_id}

    return app


@pytest.mark.unit
def test_add_request_id_preserves_valid_incoming_header(middleware_app):
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
