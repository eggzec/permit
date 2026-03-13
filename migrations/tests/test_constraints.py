from __future__ import annotations

import uuid

import psycopg
import pytest

from .helpers import (
    insert_heartbeat,
    insert_license,
    insert_node_locked,
    insert_session,
    insert_vendor,
)

pytestmark = [
    pytest.mark.app,
    pytest.mark.audit,
    pytest.mark.constraints,
    pytest.mark.foreign_keys,
]


def test_licenses_max_grace_secs_blocks_zero(superconn):
    with superconn.transaction(force_rollback=True):
        vid = insert_vendor(superconn, "grace-zero@example.com")
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_license(superconn, vid, grace_secs=0)


def test_licenses_max_grace_secs_blocks_negative(superconn):
    with superconn.transaction(force_rollback=True):
        vid = insert_vendor(superconn, "grace-neg@example.com")
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_license(superconn, vid, grace_secs=-10)


def test_node_locked_max_sessions_blocks_zero(superconn):
    with superconn.transaction(force_rollback=True):
        vid = insert_vendor(superconn, "maxsess-zero@example.com")
        lid = insert_license(superconn, vid)
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_node_locked(superconn, lid, "key-zero", max_sessions=0)


def test_node_locked_max_sessions_blocks_negative(superconn):
    with superconn.transaction(force_rollback=True):
        vid = insert_vendor(superconn, "maxsess-neg@example.com")
        lid = insert_license(superconn, vid)
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_node_locked(superconn, lid, "key-neg", max_sessions=-5)


def test_heartbeat_error_code_required_when_resp_is_error(superconn):
    with superconn.transaction(force_rollback=True):
        vid = insert_vendor(superconn, "hb-errcode-req@example.com")
        lid = insert_license(superconn, vid)
        sid = insert_session(superconn, lid)
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_heartbeat(superconn, sid, resp_code="ERROR", error_code=None)


def test_heartbeat_error_code_must_be_null_for_non_error(superconn):
    with superconn.transaction(force_rollback=True):
        vid = insert_vendor(superconn, "hb-errcode-null@example.com")
        lid = insert_license(superconn, vid)
        sid = insert_session(superconn, lid)
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_heartbeat(
                superconn, sid, resp_code="CONTINUE", error_code="INTERNAL_ERROR"
            )


def test_heartbeat_error_resp_with_valid_error_code_succeeds(superconn):
    with superconn.transaction(force_rollback=True):
        vid = insert_vendor(superconn, "hb-errcode-ok@example.com")
        lid = insert_license(superconn, vid)
        sid = insert_session(superconn, lid)
        insert_heartbeat(superconn, sid, resp_code="ERROR", error_code="INTERNAL_ERROR")

        # Verify the heartbeat was inserted with correct values
        row = superconn.execute(
            'SELECT "session_id", "heartbeat_resp_status_code", "error_code" '
            'FROM app."heartbeats" WHERE "session_id" = %s',
            (sid,),
        ).fetchone()
        assert row is not None, "Heartbeat not found"
        assert row[0] == sid, f"Expected session_id {sid}, got {row[0]}"
        assert row[1] == "ERROR", f"Expected resp_code ERROR, got {row[1]}"
        assert row[2] == "INTERNAL_ERROR", (
            f"Expected error_code INTERNAL_ERROR, got {row[2]}"
        )


def test_vendors_email_lower_unique_enforced(superconn):
    with superconn.transaction(force_rollback=True):
        insert_vendor(superconn, "UniqueEmail@Example.com")
        with pytest.raises(psycopg.errors.UniqueViolation):
            insert_vendor(superconn, "uniqueemail@example.com")


def test_vendors_email_upper_case_duplicate_rejected(superconn):
    with superconn.transaction(force_rollback=True):
        insert_vendor(superconn, "CaseTest@Domain.com")
        with pytest.raises(psycopg.errors.UniqueViolation):
            insert_vendor(superconn, "CASETEST@DOMAIN.COM")


def test_license_key_unique_enforced(superconn):
    with superconn.transaction(force_rollback=True):
        vid = insert_vendor(superconn, "dup-key@example.com")
        lid1 = insert_license(superconn, vid)
        lid2 = insert_license(superconn, vid)
        insert_node_locked(superconn, lid1, "SAME-KEY")
        with pytest.raises(psycopg.errors.UniqueViolation):
            insert_node_locked(superconn, lid2, "SAME-KEY")


@pytest.mark.parametrize(
    "table_name,expected_cols",
    [
        pytest.param(
            "audit_log_vendor_actors",
            ["audit_log_id", "vendor_id"],
            id="vendor_actors_composite_pk",
        ),
        pytest.param(
            "audit_log_licenses",
            ["audit_log_id", "license_id"],
            id="licenses_composite_pk",
        ),
        pytest.param(
            "audit_log_sessions",
            ["audit_log_id", "session_id"],
            id="sessions_composite_pk",
        ),
    ],
)
def test_audit_junction_composite_pk(superconn, table_name, expected_cols):
    row = superconn.execute(
        "SELECT array_agg(a.attname ORDER BY u.ord) "
        "FROM pg_constraint c "
        "JOIN pg_class t ON t.oid = c.conrelid "
        "JOIN pg_namespace n ON n.oid = t.relnamespace "
        "JOIN unnest(c.conkey) WITH ORDINALITY AS u(attnum, ord) ON TRUE "
        "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = u.attnum "
        "WHERE c.contype = 'p' AND n.nspname = 'audit' AND t.relname = %s",
        (table_name,),
    ).fetchone()
    assert row is not None and row[0] is not None, f"PK not found on audit.{table_name}"
    assert row[0] == expected_cols, (
        f"audit.{table_name} PK columns are {row[0]}, expected {expected_cols}"
    )


def test_session_token_hash_unique_enforced(superconn):
    token = b"x" * 64
    with superconn.transaction(force_rollback=True):
        vid = insert_vendor(superconn, "dup-token@example.com")
        lid = insert_license(superconn, vid)
        insert_session(superconn, lid, token_hash=token, fingerprint="fp1")
        with pytest.raises(psycopg.errors.UniqueViolation):
            insert_session(superconn, lid, token_hash=token, fingerprint="fp2")


def test_license_fk_rejects_nonexistent_vendor(superconn):
    with superconn.transaction(force_rollback=True):
        superconn.execute("SET LOCAL ROLE app_owner")
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            superconn.execute(
                'INSERT INTO app."licenses" '
                '("vendor_id","license_status_code","max_grace_secs") '
                "VALUES (%s,'ACTIVE',60)",
                (uuid.uuid4(),),
            )


def test_license_fk_rejects_bad_status_code(superconn):
    with superconn.transaction(force_rollback=True):
        vid = insert_vendor(superconn, "bad-status@example.com")
        superconn.execute("SET LOCAL ROLE app_owner")
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            superconn.execute(
                'INSERT INTO app."licenses" '
                '("vendor_id","license_status_code","max_grace_secs") '
                "VALUES (%s,'NONEXISTENT',60)",
                (vid,),
            )


def test_session_fk_rejects_bad_status_code(superconn):
    with superconn.transaction(force_rollback=True):
        vid = insert_vendor(superconn, "sess-badstatus@example.com")
        lid = insert_license(superconn, vid)
        superconn.execute("SET LOCAL ROLE app_owner")
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            superconn.execute(
                'INSERT INTO app."sessions" '
                '("license_id","session_status_code","session_token_hash","device_fingerprint_hash") '
                "VALUES (%s,'BOGUS',%s,'fp')",
                (lid, b"z" * 64),
            )


def test_vendor_on_delete_restrict_blocks_deletion(superconn):
    with superconn.transaction(force_rollback=True):
        vid = insert_vendor(superconn, "restrict-vendor@example.com")
        insert_license(superconn, vid)
        with pytest.raises(psycopg.errors.RestrictViolation):
            superconn.execute('DELETE FROM app."vendors" WHERE id=%s', (vid,))


def test_license_on_delete_restrict_blocks_deletion(superconn):
    with superconn.transaction(force_rollback=True):
        vid = insert_vendor(superconn, "restrict-license@example.com")
        lid = insert_license(superconn, vid)
        insert_session(superconn, lid)
        with pytest.raises(psycopg.errors.RestrictViolation):
            superconn.execute('DELETE FROM app."licenses" WHERE id=%s', (lid,))


def test_heartbeat_on_delete_cascade_removes_heartbeats(superconn):
    with superconn.transaction(force_rollback=True):
        vid = insert_vendor(superconn, "cascade-hb@example.com")
        lid = insert_license(superconn, vid)
        sid = insert_session(superconn, lid)
        insert_heartbeat(superconn, sid)
        insert_heartbeat(superconn, sid)
        superconn.execute('DELETE FROM app."sessions" WHERE id=%s', (sid,))
        count = superconn.execute(
            'SELECT COUNT(*) FROM app."heartbeats" WHERE session_id=%s', (sid,)
        ).fetchone()[0]
        assert count == 0, (
            f"Expected cascading delete from session {sid} to remove all heartbeats, got {count} remaining"
        )


def test_audit_fk_rejects_nonexistent_audit_log(superconn):
    with superconn.transaction(force_rollback=True):
        # Create a valid vendor to use for vendor_id
        vendor_id = insert_vendor(superconn, "audit-fk-test@example.com")

        # Switch to audit_owner role and attempt insert with nonexistent audit_log_id
        superconn.execute("SET LOCAL ROLE audit_owner")
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            superconn.execute(
                'INSERT INTO audit."audit_log_vendor_actors" ("audit_log_id","vendor_id") '
                "VALUES (%s,%s)",
                (uuid.uuid4(), vendor_id),
            )
