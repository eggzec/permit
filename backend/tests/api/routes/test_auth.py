from __future__ import annotations

from datetime import timedelta

import pytest
from faker import Faker
from fastapi.testclient import TestClient
from uuid6 import uuid7

from app.core.config import Settings
from app.core.security import create_access_token
from app.main import app


fake = Faker()
API_V1 = "/api/v1"


# ---------------------------------------------------------------------------
# Helpers (not fixtures — avoids fixture-composition overhead)
# ---------------------------------------------------------------------------


def signup(
    client: TestClient,
    email: str,
    password: str,
    client_id: str,
):
    return client.post(
        f"{API_V1}/auth/signup",
        json={
            "email": email,
            "password": password,
            "client_id": client_id,
        },
    )


def login(
    client: TestClient,
    email: str,
    password: str,
    client_id: str,
):
    return client.post(
        f"{API_V1}/auth/login",
        json={
            "email": email,
            "password": password,
            "client_id": client_id,
        },
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.api
def test_signup_creates_vendor_201():
    with TestClient(app) as client:
        email = fake.email()
        password = fake.password(length=12)
        client_id = str(uuid7())
        resp = signup(client, email, password, client_id)
        assert resp.status_code == 201, resp.json()
        body = resp.json()
        assert "data" in body, "Response must contain 'data' key"
        assert (
            body["data"]["vendor"]["email"] == email
        ), "Returned email must match submitted email"
        assert "id" in body["data"]["vendor"], "Created vendor must have an id"


@pytest.mark.integration
@pytest.mark.api
def test_signup_duplicate_email_409():
    with TestClient(app) as client:
        email = fake.email()
        password = fake.password()
        client_id = str(uuid7())
        resp1 = signup(client, email, password, client_id)
        assert resp1.status_code == 201, "First signup must succeed"

        resp2 = signup(client, email, password, client_id)
        assert resp2.status_code == 409, (
            "Duplicate email signup must return 409"
        )


@pytest.mark.integration
@pytest.mark.api
def test_signup_weak_password_422():
    with TestClient(app) as client:
        resp = signup(client, fake.email(), "short", str(uuid7()))
        assert resp.status_code == 422, "Weak password must return 422"


@pytest.mark.integration
@pytest.mark.api
def test_signup_missing_client_id_422():
    with TestClient(app) as client:
        resp = client.post(
            f"{API_V1}/auth/signup",
            json={
                "email": fake.email(),
                "password": fake.password(),
            },
        )
        assert resp.status_code == 422, "Missing client_id must return 422"


@pytest.mark.integration
@pytest.mark.api
def test_login_returns_token_pair():
    with TestClient(app) as client:
        email = fake.email()
        password = fake.password()
        client_id = str(uuid7())
        signup(client, email, password, client_id)

        resp = login(client, email, password, client_id)
        assert resp.status_code == 200, resp.json()
        data = resp.json()["data"]
        assert "access_token" in data, "Response must contain access_token"
        assert "refresh_token" in data, "Response must contain refresh_token"
        assert data["token_type"] == "bearer", "token_type must be 'bearer'"


@pytest.mark.integration
@pytest.mark.api
def test_login_wrong_password_401():
    with TestClient(app) as client:
        email = fake.email()
        client_id = str(uuid7())
        signup(client, email, "CorrectPassword1!", client_id)

        resp = login(client, email, "WrongPassword!", client_id)
        assert resp.status_code == 401, "Wrong password must return 401"


@pytest.mark.integration
@pytest.mark.api
def test_login_nonexistent_email_401():
    with TestClient(app) as client:
        resp = login(client, fake.email(), fake.password(), str(uuid7()))
        assert resp.status_code == 401, "Unknown email must return 401"


@pytest.mark.integration
@pytest.mark.api
def test_refresh_issues_new_tokens():
    with TestClient(app) as client:
        email = fake.email()
        password = fake.password()
        client_id = str(uuid7())
        signup(client, email, password, client_id)

        login_resp = login(client, email, password, client_id)
        login_data = login_resp.json()["data"]

        resp = client.post(
            f"{API_V1}/auth/refresh",
            json={
                "refresh_token": login_data["refresh_token"],
                "client_id": client_id,
            },
        )
        assert resp.status_code == 200, resp.json()
        data = resp.json()["data"]
        assert "access_token" in data, "Refresh must return new access_token"
        assert "refresh_token" in data, "Refresh must return new refresh_token"


@pytest.mark.integration
@pytest.mark.api
def test_refresh_with_access_token_fails_401():
    with TestClient(app) as client:
        email = fake.email()
        password = fake.password()
        client_id = str(uuid7())
        signup(client, email, password, client_id)

        login_resp = login(client, email, password, client_id)
        login_data = login_resp.json()["data"]

        resp = client.post(
            f"{API_V1}/auth/refresh",
            json={
                "refresh_token": login_data["access_token"],  # wrong token type
                "client_id": client_id,
            },
        )
        assert resp.status_code == 401, (
            "Using an access token for refresh must return 401"
        )


@pytest.mark.integration
@pytest.mark.api
def test_refresh_with_garbage_token_fails_401():
    with TestClient(app) as client:
        resp = client.post(
            f"{API_V1}/auth/refresh",
            json={
                "refresh_token": "not.a.real.token",
                "client_id": str(uuid7()),
            },
        )
        assert resp.status_code == 401, "Garbage token must return 401"


@pytest.mark.integration
@pytest.mark.api
def test_missing_token_401():
    with TestClient(app) as client:
        resp = client.get("/tests/protected-test")
        assert resp.status_code == 401, "Missing token must return 401"


@pytest.mark.integration
@pytest.mark.api
def test_expired_token_401(app_settings: Settings):
    with TestClient(app) as client:
        token = create_access_token(
            str(uuid7()), app_settings, expires_delta=timedelta(seconds=-1)
        )
        resp = client.get(
            "/tests/protected-test",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401, "Expired token must return 401"


@pytest.mark.integration
@pytest.mark.api
def test_valid_token_returns_vendor_id():
    with TestClient(app) as client:
        email = fake.email()
        password = fake.password()
        client_id = str(uuid7())

        signup_resp = signup(client, email, password, client_id)
        signup_data = signup_resp.json()
        created_vendor_id = signup_data["data"]["vendor"]["id"]

        login_resp = login(client, email, password, client_id)
        assert login_resp.status_code == 200, login_resp.json()
        token = login_resp.json()["data"]["access_token"]

        resp = client.get(
            "/tests/protected-test",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.json()
        body = resp.json()
        assert body["vendor_id"] == created_vendor_id, (
            "vendor_id in response must match the signed-up vendor"
        )
        assert body["db_vendor_id"] == created_vendor_id, (
            "RLS context vendor_id in DB must match the signed-up vendor"
        )
