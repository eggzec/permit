"""
Root conftest - shared fixtures for unit and integration tests.

Key fixtures:
    override_get_db: Module-scoped override of the get_db dependency.
        Starts a dedicated Testcontainers Postgres per module with
        migrations auto-applied via volume mapping.
"""

from __future__ import annotations

import typing
from pathlib import Path

import pytest

from app.api.deps import get_db
from app.main import app
from psycopg import Cursor, connect
from testcontainers.postgres import PostgresContainer

from app.api.deps import get_db
from app.main import app


MIGRATIONS_DIR = str(Path(__file__).parents[2] / "migrations")


@pytest.fixture(scope="module")
def test_container() -> typing.Generator[PostgresContainer, None, None]:
    """Fixture that yields a Testcontainers Postgres (PostgresContainer) with migrations applied."""
    with PostgresContainer("postgres:18.2-alpine3.23", driver=None).with_volume_mapping(
        MIGRATIONS_DIR, "/docker-entrypoint-initdb.d"
    ) as container:
        yield container


@pytest.fixture(scope="module")
def override_get_db(test_container: PostgresContainer):
    """Override the get_db dependency to use test container database.

    Ensures each test module gets its own isolated container, avoiding
    cross-module side effects when tests run in parallel.
    """

    def _get_db() -> typing.Generator[Cursor, None, None]:
        with connect(test_container.get_connection_url()) as conn:
            with conn.cursor() as cursor:
                yield cursor

    app.dependency_overrides[get_db] = _get_db
    yield
    app.dependency_overrides.pop(get_db, None)
