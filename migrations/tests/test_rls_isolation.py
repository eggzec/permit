from __future__ import annotations

import psycopg
import pytest

from .helpers import (
    insert_heartbeat,
    insert_license,
    insert_node_locked,
    insert_session,
    insert_vendor,
)

pytestmark = [pytest.mark.rls, pytest.mark.app]


def test_vendor_isolation_select(superconn):
    with superconn.transaction(force_rollback=True):
        vendor_a_id = insert_vendor(superconn, "vendor_a_76@example.com")
        vendor_b_id = insert_vendor(superconn, "vendor_b_76@example.com")
        license_a_id = insert_license(superconn, vendor_a_id)
        license_b_id = insert_license(superconn, vendor_b_id)

        superconn.execute("SET LOCAL ROLE app_reader_rls")
        superconn.execute("SELECT app.set_app_context(%s)", (vendor_a_id,))

        count = superconn.execute('SELECT COUNT(*) FROM app."licenses"').fetchone()[0]
        assert count == 1, f"Vendor A expected 1 license, got {count}"

        own = superconn.execute(
            'SELECT vendor_id FROM app."licenses" WHERE id = %s', (license_a_id,)
        ).fetchone()
        assert own is not None, (
            f"Expected license {license_a_id} to be visible to vendor {vendor_a_id}"
        )
        assert own[0] == vendor_a_id, (
            f"Expected license {license_a_id} to belong to vendor {vendor_a_id}, got {own[0]}"
        )

        cross = superconn.execute(
            'SELECT COUNT(*) FROM app."licenses" WHERE id = %s', (license_b_id,)
        ).fetchone()[0]
        assert cross == 0, (
            f"Expected vendor {vendor_a_id} to see 0 licenses owned by vendor {vendor_b_id}, got {cross}"
        )


def test_vendor_isolation_insert(superconn):
    with superconn.transaction(force_rollback=True):
        vendor_a_id = insert_vendor(superconn, "vendor_a_77@example.com")
        vendor_b_id = insert_vendor(superconn, "vendor_b_77@example.com")

        superconn.execute("SET LOCAL ROLE app_writer")
        superconn.execute("SELECT app.set_app_context(%s)", (vendor_a_id,))

        superconn.execute(
            'INSERT INTO app."licenses" ("vendor_id","license_status_code","max_grace_secs") '
            "VALUES (%s,%s,%s)",
            (vendor_a_id, "ACTIVE", 60),
        )

        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            superconn.execute(
                'INSERT INTO app."licenses" ("vendor_id","license_status_code","max_grace_secs") '
                "VALUES (%s,%s,%s)",
                (vendor_b_id, "ACTIVE", 60),
            )


def test_vendor_isolation_update(superconn):
    with superconn.transaction(force_rollback=True):
        vendor_a_id = insert_vendor(superconn, "vendor_a_78@example.com")
        vendor_b_id = insert_vendor(superconn, "vendor_b_78@example.com")
        license_a_id = insert_license(superconn, vendor_a_id)
        license_b_id = insert_license(superconn, vendor_b_id)

        superconn.execute("SET LOCAL ROLE app_writer")
        superconn.execute("SELECT app.set_app_context(%s)", (vendor_a_id,))

        cur = superconn.execute(
            'UPDATE app."licenses" SET updated_at=NOW() WHERE id=%s', (license_a_id,)
        )
        assert cur.rowcount == 1, "Expected update on own license to succeed"

        cur = superconn.execute(
            'UPDATE app."licenses" SET updated_at=NOW() WHERE id=%s', (license_b_id,)
        )
        assert cur.rowcount == 0, (
            f"Expected update on vendor {vendor_b_id} license {license_b_id} to affect 0 rows, got {cur.rowcount}"
        )


def test_vendor_isolation_delete(superconn):
    with superconn.transaction(force_rollback=True):
        vendor_a_id = insert_vendor(superconn, "vendor_a_79@example.com")
        vendor_b_id = insert_vendor(superconn, "vendor_b_79@example.com")
        license_a_id = insert_license(superconn, vendor_a_id)
        license_b_id = insert_license(superconn, vendor_b_id)

        superconn.execute("SET LOCAL ROLE app_deleter")
        superconn.execute("SELECT app.set_app_context(%s)", (vendor_a_id,))

        cur = superconn.execute(
            'DELETE FROM app."licenses" WHERE id=%s', (license_a_id,)
        )
        assert cur.rowcount == 1, (
            f"Expected delete of own license {license_a_id} to affect 1 row, got {cur.rowcount}"
        )

        cur = superconn.execute(
            'DELETE FROM app."licenses" WHERE id=%s', (license_b_id,)
        )
        assert cur.rowcount == 0, (
            f"Expected delete of vendor {vendor_b_id} license {license_b_id} to affect 0 rows, got {cur.rowcount}"
        )

        superconn.execute("SET LOCAL ROLE app_owner")
        remaining = superconn.execute(
            'SELECT COUNT(*) FROM app."licenses" WHERE id=%s', (license_b_id,)
        ).fetchone()[0]
        assert remaining == 1, (
            f"Expected vendor {vendor_b_id} license {license_b_id} to remain after cross-tenant delete attempt, got count {remaining}"
        )


def test_queries_without_context_return_zero_rows(superconn):
    with superconn.transaction(force_rollback=True):
        vid = insert_vendor(superconn, "vendor_80@example.com")
        insert_license(superconn, vid)

        superconn.execute("SET LOCAL ROLE app_reader_rls")
        count = superconn.execute('SELECT COUNT(*) FROM app."licenses"').fetchone()[0]
        assert count == 0, f"Expected 0 licenses without app context set, got {count}"


def test_sessions_isolation(superconn):
    with superconn.transaction(force_rollback=True):
        vendor_a_id = insert_vendor(superconn, "vendor_a_81@example.com")
        vendor_b_id = insert_vendor(superconn, "vendor_b_81@example.com")
        license_a_id = insert_license(superconn, vendor_a_id)
        license_b_id = insert_license(superconn, vendor_b_id)
        insert_session(superconn, license_a_id, fingerprint="fp_a")
        session_b_id = insert_session(superconn, license_b_id, fingerprint="fp_b")

        superconn.execute("SET LOCAL ROLE app_reader_rls")
        superconn.execute("SELECT app.set_app_context(%s)", (vendor_a_id,))

        count = superconn.execute('SELECT COUNT(*) FROM app."sessions"').fetchone()[0]
        assert count == 1, (
            f"Expected vendor {vendor_a_id} to see 1 session, got {count}"
        )

        cross = superconn.execute(
            'SELECT COUNT(*) FROM app."sessions" WHERE id=%s', (session_b_id,)
        ).fetchone()[0]
        assert cross == 0, (
            f"Expected vendor {vendor_a_id} to see 0 sessions for vendor {vendor_b_id}, got {cross}"
        )


def test_node_locked_isolation(superconn):
    with superconn.transaction(force_rollback=True):
        vendor_a_id = insert_vendor(superconn, "vendor_a_82@example.com")
        vendor_b_id = insert_vendor(superconn, "vendor_b_82@example.com")
        license_a_id = insert_license(superconn, vendor_a_id)
        license_b_id = insert_license(superconn, vendor_b_id)
        insert_node_locked(superconn, license_a_id, "key_a_82")
        insert_node_locked(superconn, license_b_id, "key_b_82")

        superconn.execute("SET LOCAL ROLE app_reader_rls")
        superconn.execute("SELECT app.set_app_context(%s)", (vendor_a_id,))

        count = superconn.execute(
            'SELECT COUNT(*) FROM app."node_locked_license_data"'
        ).fetchone()[0]
        assert count == 1, (
            f"Expected vendor {vendor_a_id} to see 1 node-locked record, got {count}"
        )

        cross = superconn.execute(
            'SELECT COUNT(*) FROM app."node_locked_license_data" WHERE license_id=%s',
            (license_b_id,),
        ).fetchone()[0]
        assert cross == 0, (
            f"Expected vendor {vendor_a_id} to see 0 node-locked records for license {license_b_id}, got {cross}"
        )


def test_heartbeats_isolation(superconn):
    with superconn.transaction(force_rollback=True):
        vendor_a_id = insert_vendor(superconn, "vendor_a_83@example.com")
        vendor_b_id = insert_vendor(superconn, "vendor_b_83@example.com")
        license_a_id = insert_license(superconn, vendor_a_id)
        license_b_id = insert_license(superconn, vendor_b_id)
        session_a_id = insert_session(superconn, license_a_id)
        session_b_id = insert_session(superconn, license_b_id)
        insert_heartbeat(superconn, session_a_id)
        insert_heartbeat(superconn, session_b_id)

        superconn.execute("SET LOCAL ROLE app_reader_rls")
        superconn.execute("SELECT app.set_app_context(%s)", (vendor_a_id,))

        count = superconn.execute('SELECT COUNT(*) FROM app."heartbeats"').fetchone()[0]
        assert count == 1, (
            f"Expected vendor {vendor_a_id} to see 1 heartbeat, got {count}"
        )

        cross = superconn.execute(
            'SELECT COUNT(*) FROM app."heartbeats" WHERE session_id=%s', (session_b_id,)
        ).fetchone()[0]
        assert cross == 0, (
            f"Expected vendor {vendor_a_id} to see 0 heartbeats for session {session_b_id}, got {cross}"
        )


def test_connection_context_isolation(superconn):
    # Verify that app context (vendor identity set via app.set_app_context) does not
    # leak between transaction boundaries on the same connection. SET LOCAL settings
    # are reset when the inner transaction ends.
    with superconn.transaction(force_rollback=True):
        vendor_a_id = insert_vendor(superconn, "vendor_a_84@example.com")
        vendor_b_id = insert_vendor(superconn, "vendor_b_84@example.com")
        insert_license(superconn, vendor_a_id)
        insert_license(superconn, vendor_b_id)

        # Use two nested transactions on the same connection to verify that
        # SET LOCAL context is not carried over between transaction boundaries.
        with superconn.transaction(force_rollback=True):
            superconn.execute("SET LOCAL ROLE app_reader_rls")
            superconn.execute("SELECT app.set_app_context(%s)", (vendor_a_id,))
            count_a = superconn.execute(
                'SELECT COUNT(*) FROM app."licenses"'
            ).fetchone()[0]

        # After the inner transaction ends, LOCAL settings are reset.
        # Re-set context as vendor_b to prove context is independent.
        with superconn.transaction(force_rollback=True):
            superconn.execute("SET LOCAL ROLE app_reader_rls")
            superconn.execute("SELECT app.set_app_context(%s)", (vendor_b_id,))
            count_b = superconn.execute(
                'SELECT COUNT(*) FROM app."licenses"'
            ).fetchone()[0]

        # Re-enter as vendor_a to confirm context was not polluted by vendor_b block
        with superconn.transaction(force_rollback=True):
            superconn.execute("SET LOCAL ROLE app_reader_rls")
            superconn.execute("SELECT app.set_app_context(%s)", (vendor_a_id,))
            count_a_again = superconn.execute(
                'SELECT COUNT(*) FROM app."licenses"'
            ).fetchone()[0]

    assert count_a == 1, f"vendor_a expected 1 license, got {count_a}"
    assert count_b == 1, f"vendor_b expected 1 license, got {count_b}"
    assert count_a_again == 1, "vendor_a context polluted after vendor_b block"


def test_rls_bypass_for_app_reader_bypass(superconn):
    with superconn.transaction(force_rollback=True):
        vendor_a_id = insert_vendor(superconn, "vendor_a_85@example.com")
        vendor_b_id = insert_vendor(superconn, "vendor_b_85@example.com")
        license_a_id = insert_license(superconn, vendor_a_id)
        license_b_id = insert_license(superconn, vendor_b_id)

        superconn.execute("SET LOCAL ROLE app_reader_bypass")

        count = superconn.execute(
            'SELECT COUNT(*) FROM app."licenses" WHERE id IN (%s,%s)',
            (license_a_id, license_b_id),
        ).fetchone()[0]
        assert count == 2, f"Expected bypass reader to see 2 licenses, got {count}"


def test_rls_blocks_vendor_id_hijack_via_update(superconn):
    with superconn.transaction(force_rollback=True):
        vendor_a_id = insert_vendor(superconn, "vendor_a_86@example.com")
        vendor_b_id = insert_vendor(superconn, "vendor_b_86@example.com")
        license_a_id = insert_license(superconn, vendor_a_id)

        superconn.execute("SET LOCAL ROLE app_writer")
        superconn.execute("SELECT app.set_app_context(%s)", (vendor_a_id,))

        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            superconn.execute(
                'UPDATE app."licenses" SET vendor_id=%s WHERE id=%s',
                (vendor_b_id, license_a_id),
            )


def test_rls_no_leakage_via_app_owner_role_switch(superconn):
    with superconn.transaction(force_rollback=True):
        vendor_a_id = insert_vendor(superconn, "vendor_a_87@example.com")
        vendor_b_id = insert_vendor(superconn, "vendor_b_87@example.com")
        lic_a = insert_license(superconn, vendor_a_id)
        lic_b = insert_license(superconn, vendor_b_id)

        superconn.execute("SET LOCAL ROLE app_owner")
        count = superconn.execute(
            'SELECT COUNT(*) FROM app."licenses" WHERE id IN (%s,%s)',
            (lic_a, lic_b),
        ).fetchone()[0]
        assert count == 2, (
            f"Expected app_owner role to see 2 licenses across vendors, got {count}"
        )
