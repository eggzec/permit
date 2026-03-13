from __future__ import annotations

import hashlib
import shlex
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg import sql
from testcontainers.core.waiting_utils import WaitStrategy, WaitStrategyTarget

POSTGRES_IMAGE = "postgres:18.3-alpine3.23"
MIGRATIONS_DIR = Path(__file__).parents[1].resolve()

UP_MIGRATIONS = [
    "01_roles.sql",
    "02_reference.sql",
    "03_app.sql",
    "04_audit.sql",
    "05_functions.sql",
    "06_rls.sql",
    "07_audit_triggers.sql",
]

DOWN_MIGRATIONS = [
    "down/07_audit_triggers_down.sql",
    "down/06_rls_down.sql",
    "down/05_functions_down.sql",
    "down/04_audit_down.sql",
    "down/03_app_down.sql",
    "down/02_reference_down.sql",
    "down/01_roles_down.sql",
]

ALL_GROUP_ROLES = [
    "reference_owner",
    "reference_reader",
    "reference_writer",
    "audit_owner",
    "audit_writer",
    "audit_reader",
    "app_owner",
    "app_reader_rls",
    "app_reader_bypass",
    "app_writer",
    "app_deleter",
]


class PgReadyWaitStrategy(WaitStrategy):
    """Wait until postgres accepts connections; fail fast with container logs."""

    def wait_until_ready(self, container: WaitStrategyTarget) -> None:
        wrapped = container.get_wrapped_container()
        user = container.username
        start = time.time()

        while True:
            if time.time() - start > self._startup_timeout:
                raise TimeoutError(
                    f"Postgres did not become ready within {self._startup_timeout}s"
                )

            wrapped.reload()
            state = wrapped.attrs["State"]

            if state["Status"] == "exited" and state["ExitCode"] != 0:
                stdout, stderr = container.get_logs()
                logs = (stdout + stderr).decode(errors="replace").strip()
                raise RuntimeError(
                    f"Postgres container exited with code {state['ExitCode']}\n"
                    f"--- container logs ---\n{logs}"
                )

            result = container.exec(f"pg_isready -U {shlex.quote(user)}")
            if result.exit_code == 0:
                return

            time.sleep(self._poll_interval)


def apply_sql_file(cur: psycopg.Cursor, filepath: Path) -> None:
    """Execute SQL file content on a cursor inside the caller's transaction.

    Migration files are authored with top-level BEGIN/COMMIT wrappers for psql
    execution. Remove only standalone wrapper lines so the outer transaction
    (e.g. conn.transaction(force_rollback=True)) remains authoritative.
    """
    sql_text = filepath.read_text()
    sql_text = re.sub(r"(?m)^\s*BEGIN\s*;\s*$", "", sql_text)
    sql_text = re.sub(r"(?m)^\s*COMMIT\s*;\s*$", "", sql_text)
    cur.execute(sql_text)
    # Migration files rely on COMMIT to clear SET LOCAL ROLE effects.
    # Since wrappers are stripped, reset explicitly to avoid role leakage.
    cur.execute("RESET ROLE")


def insert_vendor(conn: psycopg.Connection, email: str) -> uuid.UUID:
    with psycopg.ClientCursor(conn) as cur:
        cur.execute(
            "SET LOCAL ROLE app_owner; "
            'ALTER TABLE app."vendors" DISABLE TRIGGER vendors_audit_tr; '
            'INSERT INTO app."vendors" ("email", "password_hash") VALUES (%s, %s) RETURNING id',
            (email, "hash"),
        )
        return cur.set_result(-1).fetchone()[0]


def insert_license(
    conn: psycopg.Connection,
    vendor_id: uuid.UUID,
    *,
    grace_secs: int = 60,
    status: str = "ACTIVE",
) -> uuid.UUID:
    row = conn.execute(
        'INSERT INTO app."licenses" '
        '("vendor_id", "license_status_code", "max_grace_secs") '
        "VALUES (%s, %s, %s) RETURNING id",
        (vendor_id, status, grace_secs),
    ).fetchone()
    return row[0]


def insert_node_locked(
    conn: psycopg.Connection,
    license_id: uuid.UUID,
    license_key: str,
    max_sessions: int = 1,
) -> None:
    conn.execute(
        'INSERT INTO app."node_locked_license_data" '
        '("license_id", "license_key", "max_sessions") '
        "VALUES (%s, %s, %s)",
        (license_id, license_key, max_sessions),
    )


def insert_session(
    conn: psycopg.Connection,
    license_id: uuid.UUID,
    *,
    token_hash: bytes | None = None,
    fingerprint: str = "fp_abc",
    status: str = "ACTIVE",
) -> uuid.UUID:
    if token_hash is None:
        token_hash = uuid.uuid4().bytes * 4
    with psycopg.ClientCursor(conn) as cur:
        cur.execute(
            "SET LOCAL ROLE app_owner; "
            'ALTER TABLE app."sessions" DISABLE TRIGGER sessions_audit_tr; '
            'INSERT INTO app."sessions" '
            '  ("license_id", "session_status_code", "session_token_hash", "device_fingerprint_hash") '
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (license_id, status, token_hash, fingerprint),
        )
        return cur.set_result(-1).fetchone()[0]


def insert_heartbeat(
    conn: psycopg.Connection,
    session_id: uuid.UUID,
    *,
    resp_code: str = "CONTINUE",
    error_code: str | None = None,
    heartbeat_at: datetime | None = None,
) -> None:
    if heartbeat_at is None:
        heartbeat_at = datetime.now(timezone.utc)
    conn.execute(
        'INSERT INTO app."heartbeats" '
        '  ("session_id", "heartbeat_resp_status_code", "error_code", "heartbeat_at") '
        "VALUES (%s, %s, %s, %s)",
        (session_id, resp_code, error_code, heartbeat_at),
    )


def make_audit_log(conn: psycopg.Connection) -> uuid.UUID:
    with psycopg.ClientCursor(conn) as cur:
        cur.execute(
            "SET LOCAL ROLE audit_owner; "
            'INSERT INTO audit."audit_logs" (action_code) VALUES (%s) RETURNING id',
            ("CREATED",),
        )
        return cur.set_result(-1).fetchone()[0]


def snapshot_db_state(conn: psycopg.Connection) -> str:
    parts = snapshot_db_state_parts(conn)
    return hashlib.sha256("\n".join(parts.values()).encode()).hexdigest()


def snapshot_db_state_parts(conn: psycopg.Connection) -> dict[str, str]:
    """Snapshot DB state using the provided connection.

    Running on the same connection makes in-transaction DDL visible to the
    snapshot logic during mutation/idempotency tests.
    """
    parts: dict[str, str] = {}

    parts["schemas"] = str(
        conn.execute(
            "SELECT nspname FROM pg_namespace "
            "WHERE nspname IN ('reference','app','audit') ORDER BY 1"
        ).fetchall()
    )

    parts["tables"] = str(
        conn.execute(
            "SELECT n.nspname, c.relname, c.relkind, COALESCE(c.relispartition,false) "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname IN ('reference','app','audit') AND c.relkind IN ('r','p','v') "
            "ORDER BY 1,2"
        ).fetchall()
    )

    parts["sequences"] = str(
        conn.execute(
            "SELECT n.nspname, c.relname FROM pg_class c "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname IN ('reference','app','audit') AND c.relkind='S' ORDER BY 1,2"
        ).fetchall()
    )

    parts["functions"] = str(
        conn.execute(
            "SELECT n.nspname, p.proname, pg_get_function_identity_arguments(p.oid) "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname IN ('reference','app','audit') ORDER BY 1,2,3"
        ).fetchall()
    )

    parts["triggers"] = str(
        conn.execute(
            "SELECT n.nspname, c.relname, t.tgname, t.tgenabled "
            "FROM pg_trigger t "
            "JOIN pg_class c ON c.oid=t.tgrelid "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname IN ('reference','app','audit') AND NOT t.tgisinternal "
            "ORDER BY 1,2,3"
        ).fetchall()
    )

    parts["roles"] = str(
        conn.execute(
            "SELECT rolname, rolinherit, rolcanlogin, rolbypassrls FROM pg_roles "
            "WHERE rolname = ANY(%s) ORDER BY rolname",
            (ALL_GROUP_ROLES,),
        ).fetchall()
    )

    parts["rls_flags"] = str(
        conn.execute(
            "SELECT n.nspname, c.relname, c.relrowsecurity, c.relforcerowsecurity "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname IN ('reference','app','audit') AND c.relkind IN ('r','p') "
            "ORDER BY 1, 2"
        ).fetchall()
    )

    parts["rls_policies"] = str(
        conn.execute(
            "SELECT schemaname, tablename, policyname, permissive, roles, cmd "
            "FROM pg_policies "
            "WHERE schemaname IN ('reference','app','audit') "
            "ORDER BY 1, 2, 3"
        ).fetchall()
    )

    parts["acls"] = str(
        conn.execute(
            "SELECT n.nspname, c.relname, c.relacl "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname IN ('reference','app','audit') "
            "AND c.relkind IN ('r','p','v','S') "
            "ORDER BY 1, 2"
        ).fetchall()
    )

    for tbl in [
        "license_statuses",
        "session_statuses",
        "heartbeat_resp_statuses",
        "error_codes",
        "actions",
    ]:
        schema_name = "reference"
        exists = conn.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema=%s AND table_name=%s)",
            (schema_name, tbl),
        ).fetchone()[0]
        if exists:
            parts[f"reference.{tbl}"] = str(
                conn.execute(
                    sql.SQL("SELECT * FROM reference.{} ORDER BY 1").format(
                        sql.Identifier(tbl)
                    )
                ).fetchall()
            )

    return parts
