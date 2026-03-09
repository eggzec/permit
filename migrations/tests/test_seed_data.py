from __future__ import annotations

import psycopg
import pytest
from psycopg import sql

pytestmark = [pytest.mark.seed_data, pytest.mark.reference]


@pytest.mark.parametrize(
    "table_name,expected_codes",
    [
        pytest.param(
            "license_statuses",
            ["ACTIVE", "REVOKED"],
            id="license_statuses",
        ),
        pytest.param(
            "session_statuses",
            ["ACTIVE", "CLEANUP", "REVOKED", "ZOMBIE"],
            id="session_statuses",
        ),
        pytest.param(
            "heartbeat_resp_statuses",
            ["CONTINUE", "ERROR", "EXPIRED", "REFRESH", "REVOKED"],
            id="heartbeat_resp_statuses",
        ),
    ],
)
def test_seed_data_codes(conn_url, table_name, expected_codes):
    with psycopg.connect(conn_url) as conn:
        codes = [
            r[0]
            for r in conn.execute(
                sql.SQL("SELECT code FROM reference.{} ORDER BY code").format(
                    sql.Identifier(table_name)
                )
            ).fetchall()
        ]
    expected = sorted(expected_codes)
    assert codes == expected, (
        f"Expected seed codes for reference.{table_name} to be {expected}, got {codes}"
    )


def test_error_codes_seed_count(conn_url):
    with psycopg.connect(conn_url) as conn:
        count = conn.execute('SELECT COUNT(*) FROM reference."error_codes"').fetchone()[
            0
        ]
    assert count == 12, f"Expected 12 seeded error_codes rows, got {count}"


@pytest.mark.parametrize(
    "table_name,expected_count",
    [
        pytest.param("error_codes", 12, id="error_codes"),
        pytest.param("actions", 15, id="actions"),
    ],
)
def test_seed_count(conn_url, table_name, expected_count):
    with psycopg.connect(conn_url) as conn:
        count = conn.execute(
            sql.SQL("SELECT COUNT(*) FROM reference.{}").format(
                sql.Identifier(table_name)
            )
        ).fetchone()[0]
    assert count == expected_count, (
        f"Expected {expected_count} seeded rows in reference.{table_name}, got {count}"
    )


@pytest.mark.parametrize(
    "code",
    [
        pytest.param("SIGNUP", id="signup"),
        pytest.param("LOGIN_SUCCESS", id="login_success"),
        pytest.param("LOGIN_FAILED", id="login_failed"),
        pytest.param("TOKEN_REFRESHED", id="token_refreshed"),
        pytest.param("CREATED", id="created"),
        pytest.param("MODIFIED", id="modified"),
        pytest.param("CONFIG_UPDATED", id="config_updated"),
        pytest.param("REVOKED", id="revoked"),
        pytest.param("EXPIRED", id="expired"),
        pytest.param("ACTIVATED", id="activated"),
        pytest.param("TOKEN_ROTATED", id="token_rotated"),
        pytest.param("HEARTBEAT_ERROR", id="heartbeat_error"),
        pytest.param("DELETED", id="deleted"),
        pytest.param("PASSWORD_CHANGED", id="password_changed"),
        pytest.param("CLEANED", id="cleaned"),
    ],
)
def test_action_code_present(conn_url, code):
    with psycopg.connect(conn_url) as conn:
        row = conn.execute(
            'SELECT 1 FROM reference."actions" WHERE code = %s',
            (code,),
        ).fetchone()
    assert row is not None, f"Action code '{code}' not found in reference.actions"
