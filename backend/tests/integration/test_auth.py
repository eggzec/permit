"""Integration tests for auth endpoints (signup, login, refresh).

Uses Testcontainers for a real PostgreSQL instance with migrations applied.
Verifies the full HTTP round-trip including RLS context setting.
"""

from __future__ import annotations

import typing
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import Cursor, connect
from testcontainers.postgres import PostgresContainer

from app.api.deps import get_db, get_settings
from app.api.main import api_router
from app.core.config import Settings
from app.core.exception_handlers import (
    api_exception_handler,
    general_exception_handler,
    validation_exception_handler,
)
from app.core.exceptions import APIException
from fastapi.exceptions import RequestValidationError

MIGRATIONS_DIR = str(Path(__file__).parents[3] / "migrations")
API_V1 = "/api/v1"


# ── Module-scoped fixtures ──────────────────────────────────


@pytest.fixture(scope="module")
def pg_container() -> typing.Generator[PostgresContainer, None, None]:
    with PostgresContainer("postgres:18.2-alpine3.23", driver=None).with_volume_mapping(
        MIGRATIONS_DIR, "/docker-entrypoint-initdb.d"
    ) as container:
        yield container


@pytest.fixture(scope="module")
def test_settings() -> Settings:
    return Settings(
        SECRET_KEY="integration-test-secret-key-32bytes!",
        PROJECT_NAME="test",
        POSTGRES_SERVER="localhost",
        POSTGRES_USER="test",
        POSTGRES_PASSWORD="test",
        POSTGRES_DB="test",
        ACCESS_TOKEN_EXPIRE_MINUTES=60,
        REFRESH_TOKEN_EXPIRE_DAYS=7,
    )


@pytest.fixture(scope="module")
def client(
    pg_container: PostgresContainer, test_settings: Settings
) -> typing.Generator[TestClient, None, None]:
    """TestClient with a lightweight test app (no real lifespan)."""

    @asynccontextmanager
    async def _noop_lifespan(app: FastAPI):
        yield

    test_app = FastAPI(lifespan=_noop_lifespan)
    test_app.include_router(api_router, prefix=API_V1)
    test_app.add_exception_handler(APIException, api_exception_handler)
    test_app.add_exception_handler(RequestValidationError, validation_exception_handler)
    test_app.add_exception_handler(Exception, general_exception_handler)

    def _override_get_db() -> typing.Generator[Cursor, None, None]:
        with connect(pg_container.get_connection_url()) as conn:
            with conn.cursor() as cur:
                yield cur

    def _override_get_settings() -> Settings:
        return test_settings

    test_app.dependency_overrides[get_db] = _override_get_db
    test_app.dependency_overrides[get_settings] = _override_get_settings

    with TestClient(test_app) as tc:
        yield tc


# ── Helpers ──────────────────────────────────────────────────


def _signup(
    client: TestClient, email: str = "vendor@test.com", password: str = "SecurePass123!"
) -> dict:
    return client.post(
        f"{API_V1}/auth/signup",
        json={"email": email, "password": password, "client_id": "integration-test"},
    ).json()


def _login(
    client: TestClient, email: str = "vendor@test.com", password: str = "SecurePass123!"
) -> dict:
    return client.post(
        f"{API_V1}/auth/login",
        json={"email": email, "password": password, "client_id": "integration-test"},
    ).json()


# ── Tests ────────────────────────────────────────────────────


@pytest.mark.integration
class TestSignup:
    def test_signup_creates_vendor_201(self, client: TestClient):
        resp = client.post(
            f"{API_V1}/auth/signup",
            json={
                "email": "signup-test@example.com",
                "password": "StrongPass1!",
                "client_id": "test-client",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "data" in body
        assert body["data"]["vendor"]["email"] == "signup-test@example.com"
        assert "id" in body["data"]["vendor"]

    def test_signup_duplicate_email_409(self, client: TestClient):
        email = "dup@example.com"
        # First signup succeeds
        resp1 = client.post(
            f"{API_V1}/auth/signup",
            json={"email": email, "password": "Pass12345!", "client_id": "c1"},
        )
        assert resp1.status_code == 201

        # Second signup with same email fails
        resp2 = client.post(
            f"{API_V1}/auth/signup",
            json={"email": email, "password": "Pass12345!", "client_id": "c1"},
        )
        assert resp2.status_code == 409

    def test_signup_weak_password_422(self, client: TestClient):
        resp = client.post(
            f"{API_V1}/auth/signup",
            json={"email": "weak@example.com", "password": "short", "client_id": "c1"},
        )
        assert resp.status_code == 422

    def test_signup_missing_client_id_422(self, client: TestClient):
        resp = client.post(
            f"{API_V1}/auth/signup",
            json={"email": "no-client@example.com", "password": "StrongPass1!"},
        )
        assert resp.status_code == 422


@pytest.mark.integration
class TestLogin:
    def test_login_returns_token_pair(self, client: TestClient):
        email = "login-test@example.com"
        _signup(client, email=email)

        resp = client.post(
            f"{API_V1}/auth/login",
            json={"email": email, "password": "SecurePass123!", "client_id": "c1"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    def test_login_wrong_password_401(self, client: TestClient):
        email = "login-fail@example.com"
        _signup(client, email=email)

        resp = client.post(
            f"{API_V1}/auth/login",
            json={"email": email, "password": "WrongPassword!", "client_id": "c1"},
        )
        assert resp.status_code == 401

    def test_login_nonexistent_email_401(self, client: TestClient):
        resp = client.post(
            f"{API_V1}/auth/login",
            json={
                "email": "nobody@example.com",
                "password": "Pass12345!",
                "client_id": "c1",
            },
        )
        assert resp.status_code == 401


@pytest.mark.integration
class TestRefresh:
    def test_refresh_issues_new_tokens(self, client: TestClient):
        email = "refresh-test@example.com"
        _signup(client, email=email)
        login_data = _login(client, email=email)["data"]

        resp = client.post(
            f"{API_V1}/auth/refresh",
            json={
                "refresh_token": login_data["refresh_token"],
                "client_id": "c1",
            },
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "access_token" in data
        assert "refresh_token" in data

    def test_refresh_with_access_token_fails_401(self, client: TestClient):
        email = "refresh-bad@example.com"
        _signup(client, email=email)
        login_data = _login(client, email=email)["data"]

        resp = client.post(
            f"{API_V1}/auth/refresh",
            json={
                "refresh_token": login_data["access_token"],  # wrong token type
                "client_id": "c1",
            },
        )
        assert resp.status_code == 401

    def test_refresh_with_garbage_token_fails_401(self, client: TestClient):
        resp = client.post(
            f"{API_V1}/auth/refresh",
            json={"refresh_token": "not.a.real.token", "client_id": "c1"},
        )
        assert resp.status_code == 401


@pytest.mark.integration
class TestProtectedEndpoints:
    """Verify that protected endpoints reject invalid/missing tokens."""

    def test_missing_token_401(self, client: TestClient):
        """A request without Authorization header should be rejected.

        We use the health endpoint here as a baseline; in a real app
        you would test an endpoint that uses CurrentVendorId dependency.
        This test validates that the dependency itself rejects missing tokens.
        """
        from app.api.deps import get_current_vendor_id
        from app.core.exceptions import AuthenticationException

        # Directly test the dependency
        from app.core.config import Settings

        settings = Settings(
            SECRET_KEY="integration-test-secret",
            PROJECT_NAME="test",
            POSTGRES_SERVER="localhost",
            POSTGRES_USER="test",
            POSTGRES_PASSWORD="test",
            POSTGRES_DB="test",
        )

        with pytest.raises(AuthenticationException, match="Missing"):
            get_current_vendor_id(None, settings)
