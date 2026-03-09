from __future__ import annotations

import hashlib
import shlex
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg import sql
from testcontainers.core.waiting_utils import WaitStrategy, WaitStrategyTarget
from testcontainers.postgres import PostgresContainer

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


def apply_sql_file(container: PostgresContainer, filepath: Path) -> None:
    relative = filepath.relative_to(MIGRATIONS_DIR)
    container_path = f"/docker-entrypoint-initdb.d/{relative}"
    user = container.username
    db = container.dbname
    exit_code, output = container.exec(
        f"psql -U {shlex.quote(user)} -d {shlex.quote(db)} -v ON_ERROR_STOP=1 -f {shlex.quote(container_path)}"
    )
    if exit_code != 0:
        raise RuntimeError(
            f"SQL error in {filepath.name}:\n{output.decode(errors='replace').strip()}"
        )


def insert_vendor(conn: psycopg.Connection, email: str) -> uuid.UUID:
    conn.execute("SET LOCAL ROLE app_owner")
    conn.execute("SAVEPOINT sp_insert_vendor")
    password_hash = "hash"
    try:
        conn.execute('ALTER TABLE app."vendors" DISABLE TRIGGER vendors_audit_tr')
        row = conn.execute(
            'INSERT INTO app."vendors" ("email", "password_hash") '
            "VALUES (%s, %s) RETURNING id",
            (email, password_hash),
        ).fetchone()
        conn.execute('ALTER TABLE app."vendors" ENABLE TRIGGER vendors_audit_tr')
        conn.execute("RELEASE SAVEPOINT sp_insert_vendor")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT sp_insert_vendor")
        conn.execute("RELEASE SAVEPOINT sp_insert_vendor")
        raise
    return row[0]


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
    conn.execute("SET LOCAL ROLE app_owner")
    conn.execute("SAVEPOINT sp_insert_session")
    try:
        conn.execute('ALTER TABLE app."sessions" DISABLE TRIGGER sessions_audit_tr')
        row = conn.execute(
            'INSERT INTO app."sessions" '
            '  ("license_id", "session_status_code", "session_token_hash", "device_fingerprint_hash") '
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (license_id, status, token_hash, fingerprint),
        ).fetchone()
        conn.execute('ALTER TABLE app."sessions" ENABLE TRIGGER sessions_audit_tr')
        conn.execute("RELEASE SAVEPOINT sp_insert_session")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT sp_insert_session")
        conn.execute("RELEASE SAVEPOINT sp_insert_session")
        raise
    return row[0]


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
    conn.execute("SET LOCAL ROLE audit_owner")
    action_code = "CREATED"
    row = conn.execute(
        'INSERT INTO audit."audit_logs" (action_code) VALUES (%s) RETURNING id',
        (action_code,),
    ).fetchone()
    return row[0]


def snapshot_db_state(container: PostgresContainer) -> str:
    parts = snapshot_db_state_parts(container)
    return hashlib.sha256("\n".join(parts.values()).encode()).hexdigest()


def snapshot_db_state_parts(container: PostgresContainer) -> dict[str, str]:
    url = container.get_connection_url(driver=None)
    with psycopg.connect(url) as conn:
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
