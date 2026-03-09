from __future__ import annotations

import psycopg
import pytest

from .helpers import insert_license, insert_session, insert_vendor, make_audit_log

pytestmark = [pytest.mark.audit_immutability, pytest.mark.audit]


def test_audit_log_update_blocked(superconn):
    with superconn.transaction(force_rollback=True):
        log_id = make_audit_log(superconn)
        with pytest.raises(psycopg.errors.RaiseException):
            superconn.execute(
                "UPDATE audit.\"audit_logs\" SET user_agent='hacked' WHERE id=%s",
                (log_id,),
            )


def test_audit_log_delete_blocked(superconn):
    with superconn.transaction(force_rollback=True):
        log_id = make_audit_log(superconn)
        with pytest.raises(psycopg.errors.RaiseException):
            superconn.execute('DELETE FROM audit."audit_logs" WHERE id=%s', (log_id,))


def test_audit_junction_update_blocked(superconn):
    with superconn.transaction(force_rollback=True):
        vid = insert_vendor(superconn, "imm-junction@example.com")
        log_id = make_audit_log(superconn)
        superconn.execute("SET LOCAL ROLE audit_owner")
        superconn.execute(
            'INSERT INTO audit."audit_log_vendor_actors" (audit_log_id, vendor_id) VALUES (%s,%s)',
            (log_id, vid),
        )
        superconn.execute("RESET ROLE")
        new_vendor_id = insert_vendor(superconn, "imm-junction-2@example.com")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            superconn.execute(
                'UPDATE audit."audit_log_vendor_actors" SET vendor_id=%s WHERE audit_log_id=%s',
                (new_vendor_id, log_id),
            )


def test_log_heartbeat_error_invocation_blocked_for_audit_reader(superconn):
    with superconn.transaction(force_rollback=True):
        vendor_id = insert_vendor(superconn, "hb-audit@example.com")
        license_id = insert_license(superconn, vendor_id)
        session_id = insert_session(superconn, license_id)
        superconn.execute("SET LOCAL ROLE audit_reader")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            superconn.execute(
                "SELECT audit.log_heartbeat_error(%s, %s, %s)",
                (session_id, license_id, "INTERNAL_ERROR"),
            )


def test_log_login_failed_invocation_blocked_for_audit_reader(superconn):
    with superconn.transaction(force_rollback=True):
        superconn.execute("SET LOCAL ROLE audit_reader")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            superconn.execute("SELECT audit.log_login_failed(NULL)")
