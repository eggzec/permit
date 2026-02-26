"""Integration smoke tests - verify Testcontainers and fixtures work end-to-end."""

import pytest
import psycopg
import httpx


@pytest.mark.integration
def test_db_session_provides_cursor(db_session: psycopg.Cursor) -> None:
    """Verify that the db_session fixture yields a live database cursor.

    Executes a trivial query and asserts that the returned row is valid,
    confirming the cursor is connected to the Testcontainers Postgres.
    """
    db_session.execute("SELECT 1 AS ok")
    row = db_session.fetchone()
    assert row is not None
    assert row[0] == 1


@pytest.mark.integration
def test_db_session_rolls_back(db_session: psycopg.Cursor) -> None:
    """Verify that writes within a test are rolled back after it finishes.

    Creates a temporary table, inserts a row, and confirms the row is
    visible inside this transaction. The db_session fixture will roll
    back the transaction so subsequent tests never see these changes.
    """
    db_session.execute(
        "CREATE TABLE IF NOT EXISTS _test_isolation (id serial PRIMARY KEY, val text)"
    )
    db_session.execute("INSERT INTO _test_isolation (val) VALUES ('should_be_gone')")
    db_session.execute("SELECT count(*) FROM _test_isolation")
    assert db_session.fetchone()[0] == 1  # visible inside this txn


@pytest.mark.integration
def test_db_session_is_isolated(db_session: psycopg.Cursor) -> None:
    """Verify that the table created in the previous test was rolled back.

    Queries ``information_schema.tables`` to confirm that the
    ``_test_isolation`` table does not exist, proving that the
    transactional rollback provides full test isolation.
    """
    db_session.execute(
        "SELECT EXISTS ("
        "  SELECT FROM information_schema.tables "
        "  WHERE table_name = '_test_isolation'"
        ")"
    )
    exists = db_session.fetchone()[0]
    # The table should not exist because the prior transaction was rolled back
    assert not exists


@pytest.mark.integration
async def test_client_health(client: httpx.AsyncClient) -> None:
    """Verify that the async client fixture can reach the health endpoint.

    Sends a GET request to ``/api/v1/health`` and asserts a 200 response
    with ``{"data": {"status": "ok"}}``.
    """
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["status"] == "ok"
