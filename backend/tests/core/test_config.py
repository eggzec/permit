from __future__ import annotations

import pytest

from app.core.config import Settings


@pytest.mark.unit
def test_settings_builds_database_dsn_from_fields(faker) -> None:
    """
    Purpose:
        Verifies that `app.core.config.Settings` assembles `DATABASE_DSN` from the individual Postgres fields.
        This matters because database connectivity depends on the computed DSN matching the configured environment.

    Covers:
        - `app.core.config.Settings`

    Rationale:
        The test instantiates `Settings` directly because DSN assembly is a pure configuration concern with no external dependencies.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate realistic settings values.
    """
    settings = Settings(
        SECRET_KEY=faker.password(length=32, special_chars=False),
        PROJECT_NAME=faker.slug(),
        POSTGRES_SERVER=faker.ipv4_private(),
        POSTGRES_PORT=faker.random_int(min=1025, max=65535),
        POSTGRES_USER=faker.user_name(),
        POSTGRES_PASSWORD=faker.password(length=16, special_chars=False),
        POSTGRES_DB=faker.slug(),
    )
    expected_dsn = (
        f"postgresql://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
        f"@{settings.POSTGRES_SERVER}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
    )

    assert str(settings.DATABASE_DSN) == expected_dsn, (
        f"Expected DATABASE_DSN '{expected_dsn}', got '{settings.DATABASE_DSN}'"
    )


@pytest.mark.unit
def test_settings_expose_default_token_expiries(faker) -> None:
    """
    Purpose:
        Verifies that `app.core.config.Settings` exposes the default access-token and refresh-token expiry values.
        This matters because auth token lifetime is part of the application’s default security contract.

    Covers:
        - `app.core.config.Settings`

    Rationale:
        The test constructs a minimal valid settings object and asserts the defaults that should apply when the expiry fields are not overridden.

    Fixtures:
        faker: Session-scoped `Faker` instance used to generate the required non-expiry settings values.
    """
    settings = Settings(
        SECRET_KEY=faker.password(length=32, special_chars=False),
        PROJECT_NAME=faker.slug(),
        POSTGRES_SERVER=faker.ipv4_private(),
        POSTGRES_USER=faker.user_name(),
        POSTGRES_PASSWORD=faker.password(length=16, special_chars=False),
        POSTGRES_DB=faker.slug(),
    )

    assert settings.ACCESS_TOKEN_EXPIRE_MINUTES == 60, (
        f"Expected default access token expiry 60, got {settings.ACCESS_TOKEN_EXPIRE_MINUTES}"
    )
    assert settings.REFRESH_TOKEN_EXPIRE_DAYS == 7, (
        f"Expected default refresh token expiry 7, got {settings.REFRESH_TOKEN_EXPIRE_DAYS}"
    )
