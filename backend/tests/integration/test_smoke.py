"""Integration smoke tests - verify Testcontainers and fixtures work end-to-end."""

import pytest
import psycopg


@pytest.mark.integration
def test_db_session_provides_cursor(db_session: psycopg.Cursor) -> None:
    """Verify that the db_session fixture yields a live database cursor.

    NOTE: This is a trivial test. It only checks the cursor in this module and does
    not guarantee isolation across modules or test classes. If you use a different
    isolation strategy for the database fixture, you may need more robust checks.

    Executes a trivial query and asserts that the returned row is valid,
    confirming the cursor is connected to the Testcontainers Postgres.
    """
    db_session.execute("SELECT 1 AS ok")
    row = db_session.fetchone()
    assert row is not None
    assert row[0] == 1


@pytest.mark.integration
def test_db_session_rolls_back_and_isolation(db_session: psycopg.Cursor) -> None:
    """Verify transactional rollback provides full test isolation.

    NOTE: This test only verifies isolation if run repeatedly. If run in isolation,
    it will always pass. If run with other tests that create the same table, or if
    the fixture is broken, it may pass/fail alternately. This can be confusing, so
    do not rely on this test as a sole indicator of isolation.

    First asserts that ``_test_isolation`` does not exist (proving the
    fixture rolled back any prior transaction), then creates the table,
    inserts a row, and confirms it is visible inside the current
    transaction. The fixture teardown will roll back the transaction
    so subsequent tests never see these changes.
    """
    # The table must not exist at the start (fixture rolled back prior txn)
    db_session.execute(
        "SELECT EXISTS ("
        "  SELECT FROM information_schema.tables "
        "  WHERE table_name = '_test_isolation'"
        ")"
    )
    assert not db_session.fetchone()[0]

    # Write inside the transactional db_session
    db_session.execute("CREATE TABLE _test_isolation (id serial PRIMARY KEY, val text)")
    db_session.execute("INSERT INTO _test_isolation (val) VALUES ('should_be_gone')")
    db_session.execute("SELECT count(*) FROM _test_isolation")
    assert db_session.fetchone()[0] == 1  # visible inside this txn


@pytest.mark.integration
def test_client_health(client):
    """Verify that the TestClient fixture can reach the health endpoint in-process.

    Sends a GET request to ``/api/v1/health`` and asserts a 200 response
    with ``{"data": {"status": "ok"}}``.
    """
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["status"] == "ok"
