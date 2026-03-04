#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#     "psycopg[binary]>=3.1.13",
#     "pytest>=7.4.3",
#     "pytest-xdist>=3.2.0",
#     "testcontainers[postgres]>=4.0.0",
# ]
# ///

from __future__ import annotations

import hashlib
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from testcontainers.core.waiting_utils import WaitStrategy, WaitStrategyTarget
from testcontainers.postgres import PostgresContainer

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

POSTGRES_IMAGE = "postgres:18.2-alpine3.23"
MIGRATIONS_DIR = Path(__file__).parent.absolute()

UP_MIGRATIONS = [
    "01_roles.sql",
    "02_reference.sql",
    "03_app.sql",
    "04_audit.sql",
    "05_rls.sql",
]

DOWN_MIGRATIONS = [
    "down/05_rls_down.sql",
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
    """
    Polls `pg_isready -U <user>` inside the container on each tick.

    On every iteration:
      - Reloads container state. If it has exited with a non-zero code,
        fetches the container logs immediately (before __exit__ removes the
        container) and embeds them in the RuntimeError — no need to chase a
        dead container with `docker logs`.
      - If pg_isready exits 0, postgres is accepting connections — done.
    """

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
                # __enter__ raised → __exit__ never runs → container still exists.
                # Grab logs now before the caller cleans up.
                stdout, stderr = container.get_logs()
                logs = (stdout + stderr).decode(errors="replace").strip()
                raise RuntimeError(
                    f"Postgres container exited with code {state['ExitCode']} — "
                    f"likely a syntax error in a migration script.\n"
                    f"--- container logs ---\n{logs}"
                )

            result = container.exec(f"pg_isready -U {user}")
            if result.exit_code == 0:
                return

            time.sleep(self._poll_interval)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def migrated_db():
    # Session-scoped container. Migrations are auto-applied via
    # /docker-entrypoint-initdb.d. All read-only and additive tests share this.
    with (
        PostgresContainer(POSTGRES_IMAGE, driver=None)
        .with_volume_mapping(
            str(MIGRATIONS_DIR), "/docker-entrypoint-initdb.d", mode="ro"
        )
        .waiting_for(PgReadyWaitStrategy()) as container
    ):
        yield container


@pytest.fixture(scope="session")
def conn_url(migrated_db):
    return migrated_db.get_connection_url(driver=None)


@pytest.fixture
def superconn(conn_url):
    # Fresh superuser connection, auto-rolled-back after each test.
    with psycopg.connect(conn_url, autocommit=False) as conn:
        yield conn
        conn.rollback()


@pytest.fixture
def fresh_db():
    # Function-scoped container for destructive / down-migration tests.
    # Each test that tears down the schema gets its own clean container.
    with (
        PostgresContainer(POSTGRES_IMAGE, driver=None)
        .with_volume_mapping(
            str(MIGRATIONS_DIR), "/docker-entrypoint-initdb.d", mode="ro"
        )
        .waiting_for(PgReadyWaitStrategy()) as container
    ):
        yield container


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def apply_sql_file(container: PostgresContainer, filepath: Path) -> None:
    # Execute an entire SQL file by invoking psql inside the container.
    #
    # psycopg's pipeline parser pre-scans SQL bytes for '$' before handing
    # them to libpq. Dollar-quoted DO blocks (DO $$ ... $$) trigger a
    # client-side parse error that never reaches the server. Splitting on
    # ';' is equally fragile because semicolons inside DO block bodies would
    # terminate the statement prematurely.
    #
    # Running psql inside the container sidesteps all of this: psql reads the
    # file directly from disk, handles dollar-quoting natively, and
    # -v ON_ERROR_STOP=1 turns the first SQL error into a non-zero exit code.
    #
    # username/dbname are read from the container object so that the call
    # works regardless of POSTGRES_USER / POSTGRES_DB env-var overrides.
    relative = filepath.relative_to(MIGRATIONS_DIR)
    container_path = f"/docker-entrypoint-initdb.d/{relative}"
    user = container.username
    db = container.dbname
    exit_code, output = container.exec(
        f'psql -U {user} -d {db} -v ON_ERROR_STOP=1 -f "{container_path}"'
    )
    if exit_code != 0:
        raise RuntimeError(
            f"SQL error in {filepath.name}:\n{output.decode(errors='replace').strip()}"
        )


def insert_vendor(conn: psycopg.Connection, email: str) -> uuid.UUID:
    conn.execute("SET LOCAL ROLE app_owner")
    row = conn.execute(
        'INSERT INTO app."vendors" ("email", "password_hash") '
        "VALUES (%s, 'hash') RETURNING id",
        (email,),
    ).fetchone()
    return row[0]


def insert_license(
    conn: psycopg.Connection,
    vendor_id: uuid.UUID,
    *,
    grace_secs: int = 60,
    status: str = "ACTIVE",
) -> uuid.UUID:
    conn.execute("SET LOCAL ROLE app_owner")
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
    conn.execute("SET LOCAL ROLE app_owner")
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
    row = conn.execute(
        'INSERT INTO app."sessions" '
        '("license_id", "session_status_code", "session_token_hash", "device_fingerprint_hash") '
        "VALUES (%s, %s, %s, %s) RETURNING id",
        (license_id, status, token_hash, fingerprint),
    ).fetchone()
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
    conn.execute("SET LOCAL ROLE app_owner")
    conn.execute(
        'INSERT INTO app."heartbeats" '
        '("session_id", "heartbeat_resp_status_code", "error_code", "heartbeat_at") '
        "VALUES (%s, %s, %s, %s)",
        (session_id, resp_code, error_code, heartbeat_at),
    )


def _make_audit_log(conn: psycopg.Connection) -> uuid.UUID:
    conn.execute("SET LOCAL ROLE audit_owner")
    row = conn.execute(
        "INSERT INTO audit.\"audit_logs\" (action_code) VALUES ('CREATED') RETURNING id"
    ).fetchone()
    return row[0]


def snapshot_db_state(container: PostgresContainer) -> str:
    url = container.get_connection_url(driver=None)
    with psycopg.connect(url) as conn:
        parts: list[str] = []

        parts.append(
            f"schemas={
                conn.execute(
                    'SELECT nspname FROM pg_namespace '
                    "WHERE nspname IN ('reference','app','audit') ORDER BY 1"
                ).fetchall()
            }"
        )

        parts.append(
            f"tables={
                conn.execute(
                    'SELECT n.nspname, c.relname, c.relkind, COALESCE(c.relispartition,false) '
                    'FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace '
                    "WHERE n.nspname IN ('reference','app','audit') AND c.relkind IN ('r','p') "
                    'ORDER BY 1,2'
                ).fetchall()
            }"
        )

        parts.append(
            f"sequences={
                conn.execute(
                    'SELECT n.nspname, c.relname FROM pg_class c '
                    'JOIN pg_namespace n ON n.oid=c.relnamespace '
                    "WHERE n.nspname IN ('reference','app','audit') AND c.relkind='S' ORDER BY 1,2"
                ).fetchall()
            }"
        )

        parts.append(
            f"functions={
                conn.execute(
                    'SELECT n.nspname, p.proname, pg_get_function_identity_arguments(p.oid) '
                    'FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace '
                    "WHERE n.nspname IN ('reference','app','audit') ORDER BY 1,2,3"
                ).fetchall()
            }"
        )

        parts.append(
            f"triggers={
                conn.execute(
                    'SELECT n.nspname, c.relname, t.tgname, t.tgenabled '
                    'FROM pg_trigger t '
                    'JOIN pg_class c ON c.oid=t.tgrelid '
                    'JOIN pg_namespace n ON n.oid=c.relnamespace '
                    "WHERE n.nspname IN ('reference','app','audit') AND NOT t.tgisinternal "
                    'ORDER BY 1,2,3'
                ).fetchall()
            }"
        )

        parts.append(
            f"indexes={
                conn.execute(
                    'SELECT n.nspname, c.relname, i.relname, ix.indisunique, ix.indisprimary '
                    'FROM pg_index ix '
                    'JOIN pg_class c ON c.oid=ix.indrelid '
                    'JOIN pg_class i ON i.oid=ix.indexrelid '
                    'JOIN pg_namespace n ON n.oid=c.relnamespace '
                    "WHERE n.nspname IN ('reference','app','audit') "
                    'ORDER BY 1,2,3'
                ).fetchall()
            }"
        )

        parts.append(
            f"constraints={
                conn.execute(
                    'SELECT n.nspname, c.relname, con.conname, con.contype '
                    'FROM pg_constraint con '
                    'JOIN pg_class c ON c.oid=con.conrelid '
                    'JOIN pg_namespace n ON n.oid=c.relnamespace '
                    "WHERE n.nspname IN ('reference','app','audit') "
                    'ORDER BY 1,2,3'
                ).fetchall()
            }"
        )

        parts.append(
            f"roles={
                conn.execute(
                    'SELECT rolname, rolinherit, rolcanlogin, rolbypassrls FROM pg_roles '
                    'WHERE rolname = ANY(%s) ORDER BY rolname',
                    (ALL_GROUP_ROLES,),
                ).fetchall()
            }"
        )

        parts.append(
            f"table_privs={
                conn.execute(
                    'SELECT grantee, table_schema, table_name, privilege_type '
                    'FROM information_schema.role_table_grants '
                    "WHERE table_schema IN ('reference','app','audit') "
                    'ORDER BY grantee, table_schema, table_name, privilege_type'
                ).fetchall()
            }"
        )

        parts.append(
            f"seq_privs={
                conn.execute(
                    'SELECT grantee, object_schema, object_name, privilege_type '
                    'FROM information_schema.usage_privileges '
                    "WHERE object_type='SEQUENCE' AND object_schema IN ('reference','app','audit') "
                    'ORDER BY grantee, object_schema, object_name, privilege_type'
                ).fetchall()
            }"
        )

        parts.append(
            f"default_acls={
                conn.execute(
                    'SELECT r.rolname, n.nspname, da.defaclobjtype, da.defaclacl '
                    'FROM pg_default_acl da '
                    'JOIN pg_roles r ON r.oid=da.defaclrole '
                    'LEFT JOIN pg_namespace n ON n.oid=da.defaclnamespace '
                    "WHERE r.rolname IN ('reference_owner','audit_owner','app_owner') "
                    'ORDER BY 1,2,3'
                ).fetchall()
            }"
        )

        # RLS: per-table enablement flag
        parts.append(
            f"rls_enabled={
                conn.execute(
                    'SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity '
                    'FROM pg_class c '
                    'JOIN pg_namespace n ON n.oid = c.relnamespace '
                    "WHERE n.nspname = 'app' AND c.relkind IN ('r','p') "
                    'ORDER BY c.relname'
                ).fetchall()
            }"
        )

        # RLS: policy definitions (name, command, qual, with_check)
        parts.append(
            f"rls_policies={
                conn.execute(
                    'SELECT schemaname, tablename, policyname, permissive, '
                    '       roles, cmd, qual, with_check '
                    'FROM pg_policies '
                    "WHERE schemaname = 'app' "
                    'ORDER BY tablename, policyname'
                ).fetchall()
            }"
        )

        # RLS: EXECUTE grant on set_app_context
        parts.append(
            f"rls_func_grants={
                conn.execute(
                    'SELECT grantee, privilege_type '
                    'FROM information_schema.routine_privileges '
                    "WHERE routine_schema = 'app' AND routine_name = 'set_app_context' "
                    'ORDER BY grantee'
                ).fetchall()
            }"
        )

        for tbl in [
            "license_statuses",
            "session_statuses",
            "heartbeat_resp_statuses",
            "error_codes",
            "actions",
        ]:
            exists = conn.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='reference' AND table_name=%s)",
                (tbl,),
            ).fetchone()[0]
            if exists:
                rows = conn.execute(
                    sql.SQL("SELECT * FROM reference.{} ORDER BY 1").format(
                        sql.Identifier(tbl)
                    )
                ).fetchall()
                parts.append(f"reference.{tbl}={rows}")

        return hashlib.sha256("\n".join(str(p) for p in parts).encode()).hexdigest()


def snapshot_db_state_parts(container: PostgresContainer) -> dict[str, str]:
    """Field-by-field version of snapshot_db_state for diff diagnostics."""
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
                "WHERE n.nspname IN ('reference','app','audit') AND c.relkind IN ('r','p') "
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

        parts["indexes"] = str(
            conn.execute(
                "SELECT n.nspname, c.relname, i.relname, ix.indisunique, ix.indisprimary "
                "FROM pg_index ix "
                "JOIN pg_class c ON c.oid=ix.indrelid "
                "JOIN pg_class i ON i.oid=ix.indexrelid "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname IN ('reference','app','audit') "
                "ORDER BY 1,2,3"
            ).fetchall()
        )

        parts["constraints"] = str(
            conn.execute(
                "SELECT n.nspname, c.relname, con.conname, con.contype "
                "FROM pg_constraint con "
                "JOIN pg_class c ON c.oid=con.conrelid "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname IN ('reference','app','audit') "
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

        parts["table_privs"] = str(
            conn.execute(
                "SELECT grantee, table_schema, table_name, privilege_type "
                "FROM information_schema.role_table_grants "
                "WHERE table_schema IN ('reference','app','audit') "
                "ORDER BY grantee, table_schema, table_name, privilege_type"
            ).fetchall()
        )

        parts["seq_privs"] = str(
            conn.execute(
                "SELECT grantee, object_schema, object_name, privilege_type "
                "FROM information_schema.usage_privileges "
                "WHERE object_type='SEQUENCE' AND object_schema IN ('reference','app','audit') "
                "ORDER BY grantee, object_schema, object_name, privilege_type"
            ).fetchall()
        )

        parts["default_acls"] = str(
            conn.execute(
                "SELECT r.rolname, n.nspname, da.defaclobjtype, da.defaclacl "
                "FROM pg_default_acl da "
                "JOIN pg_roles r ON r.oid=da.defaclrole "
                "LEFT JOIN pg_namespace n ON n.oid=da.defaclnamespace "
                "WHERE r.rolname IN ('reference_owner','audit_owner','app_owner') "
                "ORDER BY 1,2,3"
            ).fetchall()
        )

        parts["rls_enabled"] = str(
            conn.execute(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'app' AND c.relkind IN ('r','p') "
                "ORDER BY c.relname"
            ).fetchall()
        )

        parts["rls_policies"] = str(
            conn.execute(
                "SELECT schemaname, tablename, policyname, permissive, "
                "       roles, cmd, qual, with_check "
                "FROM pg_policies "
                "WHERE schemaname = 'app' "
                "ORDER BY tablename, policyname"
            ).fetchall()
        )

        parts["rls_func_grants"] = str(
            conn.execute(
                "SELECT grantee, privilege_type "
                "FROM information_schema.routine_privileges "
                "WHERE routine_schema = 'app' AND routine_name = 'set_app_context' "
                "ORDER BY grantee"
            ).fetchall()
        )

        for tbl in [
            "license_statuses",
            "session_statuses",
            "heartbeat_resp_statuses",
            "error_codes",
            "actions",
        ]:
            exists = conn.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='reference' AND table_name=%s)",
                (tbl,),
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


# ===========================================================================
# 1. SCHEMA AND TABLE PRESENCE
# ===========================================================================


@pytest.mark.parametrize("schema", ["app", "audit", "reference"])
def test_01_schema_exists(conn_url, schema):
    with psycopg.connect(conn_url) as conn:
        row = conn.execute(
            "SELECT 1 FROM pg_namespace WHERE nspname = %s",
            (schema,),
        ).fetchone()
    assert row is not None, f"Schema '{schema}' does not exist"


@pytest.mark.parametrize(
    "table",
    [
        "actions",
        "error_codes",
        "heartbeat_resp_statuses",
        "license_statuses",
        "session_statuses",
    ],
)
def test_02_reference_table_exists(conn_url, table):
    with psycopg.connect(conn_url) as conn:
        row = conn.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='reference' AND table_name=%s",
            (table,),
        ).fetchone()
    assert row is not None, f"Table reference.{table} does not exist"


@pytest.mark.parametrize(
    "table",
    [
        "heartbeats",
        "licenses",
        "node_locked_license_data",
        "sessions",
        "vendors",
    ],
)
def test_03_app_table_exists(conn_url, table):
    with psycopg.connect(conn_url) as conn:
        row = conn.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='app' AND table_name=%s",
            (table,),
        ).fetchone()
    assert row is not None, f"Table app.{table} does not exist"


@pytest.mark.parametrize(
    "table",
    [
        "audit_log_licenses",
        "audit_log_sessions",
        "audit_log_vendor_actors",
        "audit_logs",
    ],
)
def test_04_audit_table_exists(conn_url, table):
    with psycopg.connect(conn_url) as conn:
        row = conn.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='audit' AND table_name=%s",
            (table,),
        ).fetchone()
    assert row is not None, f"Table audit.{table} does not exist"


@pytest.mark.parametrize(
    "partition",
    [
        "heartbeats_2026_q1",
        "heartbeats_2026_q2",
        "heartbeats_2026_q3",
        "heartbeats_2026_q4",
        "heartbeats_2027_q1",
        "heartbeats_default",
    ],
)
def test_05_heartbeat_partition_exists(conn_url, partition):
    with psycopg.connect(conn_url) as conn:
        row = conn.execute(
            "SELECT 1 FROM pg_class c "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='app' AND c.relkind='r' "
            "AND c.relispartition=true AND c.relname=%s",
            (partition,),
        ).fetchone()
    assert row is not None, f"Heartbeat partition '{partition}' does not exist"


# ===========================================================================
# 2. IDEMPOTENCY
# ===========================================================================


def test_06_up_migrations_are_idempotent(migrated_db):
    before = snapshot_db_state_parts(migrated_db)
    for f in UP_MIGRATIONS:
        apply_sql_file(migrated_db, MIGRATIONS_DIR / f)
    after = snapshot_db_state_parts(migrated_db)

    diffs = {k: (before[k], after[k]) for k in before if before[k] != after.get(k)}
    for k in after:
        if k not in before:
            diffs[k] = ("<missing>", after[k])

    assert not diffs, (
        "DB state changed after re-running up migrations.\n"
        "Fields that differ:\n"
        + "\n".join(
            f"\n  [{field}]\n    BEFORE: {v_before}\n    AFTER:  {v_after}"
            for field, (v_before, v_after) in diffs.items()
        )
    )


# ===========================================================================
# 3. ROLES
# ===========================================================================


@pytest.mark.parametrize("role", ALL_GROUP_ROLES)
def test_07_role_exists(conn_url, role):
    with psycopg.connect(conn_url) as conn:
        row = conn.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s",
            (role,),
        ).fetchone()
    assert row is not None, f"Role '{role}' does not exist"


@pytest.mark.parametrize("role", ALL_GROUP_ROLES)
def test_08_role_is_nologin_noinherit(conn_url, role):
    with psycopg.connect(conn_url) as conn:
        row = conn.execute(
            "SELECT rolinherit, rolcanlogin FROM pg_roles WHERE rolname = %s",
            (role,),
        ).fetchone()
    assert row is not None, f"Role '{role}' not found"
    assert row[0] is False, f"{role}: expected NOINHERIT"
    assert row[1] is False, f"{role}: expected NOLOGIN"


def test_09_app_reader_bypass_has_bypassrls(conn_url):
    with psycopg.connect(conn_url) as conn:
        row = conn.execute(
            "SELECT rolbypassrls FROM pg_roles WHERE rolname='app_reader_bypass'"
        ).fetchone()
    assert row is not None and row[0] is True


@pytest.mark.parametrize(
    "role", [r for r in ALL_GROUP_ROLES if r != "app_reader_bypass"]
)
def test_10_role_has_no_bypassrls(conn_url, role):
    with psycopg.connect(conn_url) as conn:
        row = conn.execute(
            "SELECT rolbypassrls FROM pg_roles WHERE rolname = %s",
            (role,),
        ).fetchone()
    assert row is not None, f"Role '{role}' not found"
    assert row[0] is False, f"{role} should not have BYPASSRLS"


# ===========================================================================
# 4. SEED DATA
# ===========================================================================


@pytest.mark.parametrize(
    "table_name,expected_codes",
    [
        ("license_statuses", ["ACTIVE", "REVOKED"]),
        ("session_statuses", ["ACTIVE", "CLEANUP", "REVOKED", "ZOMBIE"]),
        (
            "heartbeat_resp_statuses",
            ["CONTINUE", "ERROR", "EXPIRED", "REFRESH", "REVOKED"],
        ),
    ],
)
def test_11_seed_data_codes(conn_url, table_name, expected_codes):
    """Verify reference table seed data contains expected codes."""
    with psycopg.connect(conn_url) as conn:
        codes = [
            r[0]
            for r in conn.execute(
                sql.SQL("SELECT code FROM reference.{} ORDER BY code").format(
                    sql.Identifier(table_name)
                )
            ).fetchall()
        ]
    assert sorted(codes) == sorted(expected_codes)


def test_12_error_codes_seed_count(conn_url):
    with psycopg.connect(conn_url) as conn:
        count = conn.execute('SELECT COUNT(*) FROM reference."error_codes"').fetchone()[
            0
        ]
    assert count == 12


def test_13_actions_seed_count(conn_url):
    with psycopg.connect(conn_url) as conn:
        count = conn.execute('SELECT COUNT(*) FROM reference."actions"').fetchone()[0]
    assert count == 11


@pytest.mark.parametrize(
    "code",
    [
        "SIGNUP",
        "LOGIN_SUCCESS",
        "LOGIN_FAILED",
        "TOKEN_REFRESHED",
        "CREATED",
        "MODIFIED",
        "REVOKED",
        "EXPIRED",
        "ACTIVATED",
        "HEARTBEAT_ERROR",
        "DELETED",
    ],
)
def test_14_action_code_present(conn_url, code):
    with psycopg.connect(conn_url) as conn:
        row = conn.execute(
            'SELECT 1 FROM reference."actions" WHERE code = %s',
            (code,),
        ).fetchone()
    assert row is not None, f"Action code '{code}' not found in reference.actions"


# ===========================================================================
# 5. INDEXES
# ===========================================================================


@pytest.mark.parametrize(
    "schema,table,index_name",
    [
        ("app", "vendors", "vendors_email_lower_idx"),
        ("app", "heartbeats", "heartbeats_session_id_idx"),
        ("audit", "audit_log_vendor_actors", "audit_log_vendor_actors_vendor_id_idx"),
    ],
)
def test_15_index_exists(conn_url, schema, table, index_name):
    """Verify expected indexes are created on application tables."""
    with psycopg.connect(conn_url) as conn:
        row = conn.execute(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname=%s AND tablename=%s AND indexname=%s",
            (schema, table, index_name),
        ).fetchone()
    assert row is not None, f"Index {index_name} missing on {schema}.{table}"


def test_16_heartbeats_brin_index_type(conn_url):
    """Verify heartbeats.heartbeat_at uses BRIN index for time-series data."""
    with psycopg.connect(conn_url) as conn:
        row = conn.execute(
            "SELECT i.relname, am.amname "
            "FROM pg_index ix "
            "JOIN pg_class i ON i.oid=ix.indexrelid "
            "JOIN pg_class c ON c.oid=ix.indrelid "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "JOIN pg_am am ON am.oid=i.relam "
            "WHERE n.nspname='app' AND c.relname='heartbeats' "
            "AND i.relname='heartbeats_heartbeat_at_idx'"
        ).fetchone()
    assert row is not None, "BRIN index on heartbeats.heartbeat_at missing"
    assert row[1] == "brin", f"Expected BRIN, got {row[1]}"


# ===========================================================================
# 6. CONSTRAINTS
# ===========================================================================


def test_17_licenses_max_grace_secs_blocks_zero(superconn):
    # CHECK: max_grace_secs > 0 rejects zero
    with superconn.transaction():
        vid = insert_vendor(superconn, "grace-zero@example.com")
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_license(superconn, vid, grace_secs=0)


def test_19_licenses_max_grace_secs_blocks_negative(superconn):
    # CHECK: max_grace_secs > 0 rejects negative
    with superconn.transaction():
        vid = insert_vendor(superconn, "grace-neg@example.com")
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_license(superconn, vid, grace_secs=-10)


def test_20_node_locked_max_sessions_blocks_zero(superconn):
    # CHECK: max_sessions > 0 rejects zero
    with superconn.transaction():
        vid = insert_vendor(superconn, "maxsess-zero@example.com")
        lid = insert_license(superconn, vid)
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_node_locked(superconn, lid, "key-zero", max_sessions=0)


def test_21_node_locked_max_sessions_blocks_negative(superconn):
    # CHECK: max_sessions > 0 rejects negative
    with superconn.transaction():
        vid = insert_vendor(superconn, "maxsess-neg@example.com")
        lid = insert_license(superconn, vid)
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_node_locked(superconn, lid, "key-neg", max_sessions=-5)


def test_22_heartbeat_error_code_required_when_resp_is_error(superconn):
    # CHECK: resp=ERROR with NULL error_code must be rejected
    with superconn.transaction():
        vid = insert_vendor(superconn, "hb-errcode-req@example.com")
        lid = insert_license(superconn, vid)
        sid = insert_session(superconn, lid)
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_heartbeat(superconn, sid, resp_code="ERROR", error_code=None)


def test_23_heartbeat_error_code_must_be_null_for_non_error(superconn):
    # CHECK: resp=CONTINUE with a non-NULL error_code must be rejected
    with superconn.transaction():
        vid = insert_vendor(superconn, "hb-errcode-null@example.com")
        lid = insert_license(superconn, vid)
        sid = insert_session(superconn, lid)
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_heartbeat(
                superconn, sid, resp_code="CONTINUE", error_code="INTERNAL_ERROR"
            )


def test_24_heartbeat_error_resp_with_valid_error_code_succeeds(superconn):
    # CHECK: resp=ERROR + valid error_code is accepted
    with superconn.transaction():
        vid = insert_vendor(superconn, "hb-errcode-ok@example.com")
        lid = insert_license(superconn, vid)
        sid = insert_session(superconn, lid)
        insert_heartbeat(superconn, sid, resp_code="ERROR", error_code="INTERNAL_ERROR")


def test_25_vendors_email_lower_unique_enforced(superconn):
    # UNIQUE: case-insensitive duplicate email must be rejected
    with superconn.transaction():
        insert_vendor(superconn, "UniqueEmail@Example.com")
        with pytest.raises(psycopg.errors.UniqueViolation):
            insert_vendor(superconn, "uniqueemail@example.com")


def test_26_vendors_email_upper_case_duplicate_rejected(superconn):
    # UNIQUE: all-caps variant also rejected by lower() index
    with superconn.transaction():
        insert_vendor(superconn, "CaseTest@Domain.com")
        with pytest.raises(psycopg.errors.UniqueViolation):
            insert_vendor(superconn, "CASETEST@DOMAIN.COM")


def test_27_license_key_unique_enforced(superconn):
    # UNIQUE: duplicate license_key values are rejected
    with superconn.transaction():
        vid = insert_vendor(superconn, "dup-key@example.com")
        lid1 = insert_license(superconn, vid)
        lid2 = insert_license(superconn, vid)
        insert_node_locked(superconn, lid1, "SAME-KEY")
        with pytest.raises(psycopg.errors.UniqueViolation):
            insert_node_locked(superconn, lid2, "SAME-KEY")


def test_31_session_token_hash_unique_enforced(superconn):
    # UNIQUE: duplicate session_token_hash values are rejected
    token = b"x" * 64
    with superconn.transaction():
        vid = insert_vendor(superconn, "dup-token@example.com")
        lid = insert_license(superconn, vid)
        insert_session(superconn, lid, token_hash=token, fingerprint="fp1")
        with pytest.raises(psycopg.errors.UniqueViolation):
            insert_session(superconn, lid, token_hash=token, fingerprint="fp2")


# ===========================================================================
# 7. FOREIGN KEY ENFORCEMENT
# ===========================================================================


def test_32_license_fk_rejects_nonexistent_vendor(superconn):
    # FK: license.vendor_id referencing a non-existent vendor must fail
    with superconn.transaction():
        superconn.execute("SET LOCAL ROLE app_owner")
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            superconn.execute(
                'INSERT INTO app."licenses" '
                '("vendor_id","license_status_code","max_grace_secs") '
                "VALUES (%s,'ACTIVE',60)",
                (uuid.uuid4(),),
            )


def test_33_license_fk_rejects_bad_status_code(superconn):
    # FK: unknown license_status_code must fail
    with superconn.transaction():
        vid = insert_vendor(superconn, "bad-status@example.com")
        superconn.execute("SET LOCAL ROLE app_owner")
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            superconn.execute(
                'INSERT INTO app."licenses" '
                '("vendor_id","license_status_code","max_grace_secs") '
                "VALUES (%s,'NONEXISTENT',60)",
                (vid,),
            )


def test_34_session_fk_rejects_bad_status_code(superconn):
    # FK: unknown session_status_code must fail
    with superconn.transaction():
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


def test_35_vendor_on_delete_restrict_blocks_deletion(superconn):
    # ON DELETE RESTRICT: deleting a vendor with referencing licenses must fail.
    # PostgreSQL raises RestrictViolation (23001), not ForeignKeyViolation (23503).
    vid = insert_vendor(superconn, "restrict-vendor@example.com")
    insert_license(superconn, vid)
    superconn.commit()
    with pytest.raises(psycopg.errors.RestrictViolation):
        superconn.execute('DELETE FROM app."vendors" WHERE id=%s', (vid,))
    superconn.rollback()


def test_36_license_on_delete_restrict_blocks_deletion(superconn):
    # ON DELETE RESTRICT: deleting a license with referencing sessions must fail.
    # Same RestrictViolation / ForeignKeyViolation distinction as test_35.
    vid = insert_vendor(superconn, "restrict-license@example.com")
    lid = insert_license(superconn, vid)
    insert_session(superconn, lid)
    superconn.commit()
    with pytest.raises(psycopg.errors.RestrictViolation):
        superconn.execute('DELETE FROM app."licenses" WHERE id=%s', (lid,))
    superconn.rollback()


def test_37_heartbeat_on_delete_cascade_removes_heartbeats(superconn):
    # ON DELETE CASCADE: deleting a session hard-deletes all its heartbeat rows
    vid = insert_vendor(superconn, "cascade-hb@example.com")
    lid = insert_license(superconn, vid)
    sid = insert_session(superconn, lid)
    insert_heartbeat(superconn, sid)
    insert_heartbeat(superconn, sid)
    superconn.commit()
    superconn.execute('DELETE FROM app."sessions" WHERE id=%s', (sid,))
    superconn.commit()
    count = superconn.execute(
        'SELECT COUNT(*) FROM app."heartbeats" WHERE session_id=%s', (sid,)
    ).fetchone()[0]
    assert count == 0


def test_38_audit_fk_rejects_nonexistent_audit_log(superconn):
    # FK: audit junction row referencing a non-existent audit_log_id must fail
    with superconn.transaction():
        superconn.execute("SET LOCAL ROLE audit_owner")
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            superconn.execute(
                'INSERT INTO audit."audit_log_vendor_actors" ("audit_log_id","vendor_id") '
                "VALUES (%s,%s)",
                (uuid.uuid4(), uuid.uuid4()),
            )


# ===========================================================================
# 8. uuidv7 DEFAULT GENERATION
# ===========================================================================


def test_39_vendors_id_defaults_to_uuidv7(superconn):
    # Omitting id on INSERT must produce a valid UUID version 7
    with superconn.transaction():
        superconn.execute("SET LOCAL ROLE app_owner")
        generated_id = superconn.execute(
            'INSERT INTO app."vendors" (email, password_hash) '
            "VALUES ('uuid7-check@example.com','hash') RETURNING id"
        ).fetchone()[0]
    assert isinstance(generated_id, uuid.UUID)
    assert (generated_id.int >> 76) & 0xF == 7, "Expected UUIDv7 (version nibble = 7)"


# ===========================================================================
# 9. PARTITIONING
# ===========================================================================


def test_40_heartbeat_routes_to_2026_q1(superconn):
    with superconn.transaction():
        vid = insert_vendor(superconn, "part-q1@example.com")
        lid = insert_license(superconn, vid)
        sid = insert_session(superconn, lid)
        ts = datetime(2026, 2, 15, 12, 0, 0, tzinfo=timezone.utc)
        insert_heartbeat(superconn, sid, heartbeat_at=ts)
        count = superconn.execute(
            'SELECT COUNT(*) FROM app."heartbeats_2026_q1" WHERE session_id=%s', (sid,)
        ).fetchone()[0]
    assert count == 1


def test_41_heartbeat_routes_to_2026_q3(superconn):
    with superconn.transaction():
        vid = insert_vendor(superconn, "part-q3@example.com")
        lid = insert_license(superconn, vid)
        sid = insert_session(superconn, lid)
        ts = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        insert_heartbeat(superconn, sid, heartbeat_at=ts)
        count = superconn.execute(
            'SELECT COUNT(*) FROM app."heartbeats_2026_q3" WHERE session_id=%s', (sid,)
        ).fetchone()[0]
    assert count == 1


def test_42_heartbeat_routes_to_default_partition(superconn):
    with superconn.transaction():
        vid = insert_vendor(superconn, "part-default@example.com")
        lid = insert_license(superconn, vid)
        sid = insert_session(superconn, lid)
        ts = datetime(2030, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        insert_heartbeat(superconn, sid, heartbeat_at=ts)
        count = superconn.execute(
            'SELECT COUNT(*) FROM app."heartbeats_default" WHERE session_id=%s', (sid,)
        ).fetchone()[0]
    assert count == 1


# ===========================================================================
# 10. AUDIT IMMUTABILITY
# ===========================================================================


def test_43_audit_log_update_blocked(superconn):
    # Audit logs must never be modified; trigger RAISE to prevent UPDATE
    log_id = _make_audit_log(superconn)
    superconn.commit()
    with pytest.raises(psycopg.errors.RaiseException):
        superconn.execute(
            "UPDATE audit.\"audit_logs\" SET user_agent='hacked' WHERE id=%s", (log_id,)
        )
    superconn.rollback()


def test_44_audit_log_delete_blocked(superconn):
    # Audit logs must never be deleted; trigger RAISE to prevent deletion
    log_id = _make_audit_log(superconn)
    superconn.commit()
    with pytest.raises(psycopg.errors.RaiseException):
        superconn.execute('DELETE FROM audit."audit_logs" WHERE id=%s', (log_id,))
    superconn.rollback()


def test_45_audit_junction_update_blocked(superconn):
    # Junction tables must also be protected from updates
    vid = insert_vendor(superconn, "imm-junction@example.com")
    superconn.commit()
    log_id = _make_audit_log(superconn)
    superconn.execute("SET LOCAL ROLE audit_owner")
    superconn.execute(
        'INSERT INTO audit."audit_log_vendor_actors" (audit_log_id, vendor_id) VALUES (%s,%s)',
        (log_id, vid),
    )
    superconn.commit()
    with pytest.raises(psycopg.errors.RaiseException):
        superconn.execute(
            'UPDATE audit."audit_log_vendor_actors" SET vendor_id=%s WHERE audit_log_id=%s',
            (uuid.uuid4(), log_id),
        )
    superconn.rollback()


def test_46_audit_immutability_fires_for_superuser(superconn):
    # Audit immutability must be enforced even for the superuser (no bypasses)
    log_id = _make_audit_log(superconn)
    superconn.commit()
    with pytest.raises(psycopg.errors.RaiseException):
        superconn.execute('DELETE FROM audit."audit_logs" WHERE id=%s', (log_id,))
    superconn.rollback()


# ===========================================================================
# 11. PRIVILEGE SUCCESS PATHS
# ===========================================================================


@pytest.mark.parametrize(
    "role,sql_stmt",
    [
        ("app_reader_rls", 'SELECT COUNT(*) FROM app."vendors"'),
        (
            "app_writer",
            "INSERT INTO app.\"vendors\" (email, password_hash) VALUES ('writer-ok@example.com','hash')",
        ),
        ("reference_reader", 'SELECT COUNT(*) FROM reference."license_statuses"'),
        (
            "audit_writer",
            "INSERT INTO audit.\"audit_logs\" (action_code) VALUES ('CREATED')",
        ),
        ("audit_reader", 'SELECT COUNT(*) FROM audit."audit_logs"'),
    ],
)
def test_47_privilege_grant_simple(conn_url, role, sql_stmt):
    """Verify roles have expected permissions for basic operations."""
    # Validate role against whitelist to prevent SQL injection via role name
    if role not in ALL_GROUP_ROLES:
        raise ValueError(f"Invalid role: {role}")

    with psycopg.connect(conn_url, autocommit=False) as conn:
        conn.execute(f"SET LOCAL ROLE {role}")
        conn.execute(sql_stmt)
        conn.commit()  # Verify operation succeeds without exception


def test_49_app_writer_can_update(conn_url):
    with psycopg.connect(conn_url, autocommit=False) as conn:
        conn.execute("SET LOCAL ROLE app_owner")
        vid = conn.execute(
            'INSERT INTO app."vendors" (email, password_hash) '
            "VALUES ('writer-upd@example.com','hash') RETURNING id"
        ).fetchone()[0]
        conn.commit()
    with psycopg.connect(conn_url, autocommit=False) as conn:
        conn.execute("SET LOCAL ROLE app_writer")
        conn.execute('UPDATE app."vendors" SET updated_at=NOW() WHERE id=%s', (vid,))
        conn.commit()


def test_50_app_deleter_can_delete(conn_url):
    with psycopg.connect(conn_url, autocommit=False) as conn:
        conn.execute("SET LOCAL ROLE app_owner")
        vid = conn.execute(
            'INSERT INTO app."vendors" (email, password_hash) '
            "VALUES ('deleter-ok@example.com','hash') RETURNING id"
        ).fetchone()[0]
        conn.commit()
    with psycopg.connect(conn_url, autocommit=False) as conn:
        conn.execute("SET LOCAL ROLE app_deleter")
        conn.execute('DELETE FROM app."vendors" WHERE id=%s', (vid,))
        conn.commit()


# ===========================================================================
# 12. PRIVILEGE FAILURE PATHS
# ===========================================================================


@pytest.mark.parametrize(
    "role,sql_stmt",
    [
        (
            "app_reader_rls",
            "INSERT INTO app.\"vendors\" (email, password_hash) VALUES ('reader-fail@example.com','hash')",
        ),
        ("app_reader_rls", 'UPDATE app."vendors" SET updated_at=NOW()'),
        ("app_reader_rls", 'DELETE FROM app."vendors"'),
        ("app_writer", 'DELETE FROM app."vendors"'),
        (
            "app_deleter",
            "INSERT INTO app.\"vendors\" (email, password_hash) VALUES ('deleter-insert-fail@example.com','hash')",
        ),
        ("app_deleter", 'UPDATE app."vendors" SET updated_at=NOW()'),
        (
            "reference_reader",
            "INSERT INTO reference.\"license_statuses\" (code, description) VALUES ('FAKE','should fail')",
        ),
        (
            "reference_writer",
            "UPDATE reference.\"license_statuses\" SET description='hacked' WHERE code='ACTIVE'",
        ),
        ("reference_writer", 'DELETE FROM reference."license_statuses"'),
        ("audit_writer", 'SELECT COUNT(*) FROM audit."audit_logs"'),
        (
            "audit_reader",
            "INSERT INTO audit.\"audit_logs\" (action_code) VALUES ('CREATED')",
        ),
        ("app_reader_rls", 'SELECT * FROM reference."license_statuses"'),
    ],
)
def test_51_privilege_denial(conn_url, role, sql_stmt):
    """Verify roles cannot perform unauthorized operations."""
    # Validate role against whitelist to prevent SQL injection via role name
    if role not in ALL_GROUP_ROLES:
        raise ValueError(f"Invalid role: {role}")

    with psycopg.connect(conn_url, autocommit=False) as conn:
        conn.execute(f"SET LOCAL ROLE {role}")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(sql_stmt)
        conn.rollback()


# ===========================================================================
# 13. PUBLIC SCHEMA HARDENING
# ===========================================================================


def test_52_public_role_has_no_create_on_public_schema(conn_url):
    with psycopg.connect(conn_url) as conn:
        acl = conn.execute(
            "SELECT nspacl FROM pg_namespace WHERE nspname='public'"
        ).fetchone()[0]
    acl_str = str(acl) if acl else ""
    assert "=C" not in acl_str, "PUBLIC should not have CREATE on public schema"


# ===========================================================================
# 14. DOWN MIGRATIONS
# ===========================================================================


def test_53_down_migrations_remove_schemas(fresh_db):
    for f in DOWN_MIGRATIONS:
        apply_sql_file(fresh_db, MIGRATIONS_DIR / f)
    url = fresh_db.get_connection_url(driver=None)
    with psycopg.connect(url) as conn:
        schemas = conn.execute(
            "SELECT nspname FROM pg_namespace "
            "WHERE nspname IN ('reference','app','audit')"
        ).fetchall()
    assert len(schemas) == 0


def test_54_down_migrations_remove_all_roles(fresh_db):
    for f in DOWN_MIGRATIONS:
        apply_sql_file(fresh_db, MIGRATIONS_DIR / f)
    url = fresh_db.get_connection_url(driver=None)
    with psycopg.connect(url) as conn:
        roles = conn.execute(
            "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)",
            (ALL_GROUP_ROLES,),
        ).fetchall()
    assert len(roles) == 0


def test_55_down_migrations_remove_trigger_function(fresh_db):
    for f in DOWN_MIGRATIONS:
        apply_sql_file(fresh_db, MIGRATIONS_DIR / f)
    url = fresh_db.get_connection_url(driver=None)
    with psycopg.connect(url) as conn:
        row = conn.execute(
            "SELECT proname FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='audit' AND p.proname='prevent_audit_update_delete'"
        ).fetchone()
    assert row is None


def test_56_down_migrations_restore_public_schema_privileges(fresh_db):
    for f in DOWN_MIGRATIONS:
        apply_sql_file(fresh_db, MIGRATIONS_DIR / f)
    url = fresh_db.get_connection_url(driver=None)
    with psycopg.connect(url) as conn:
        conn.execute("CREATE ROLE pub_test LOGIN PASSWORD 'x'")
        conn.commit()
        create_ok = conn.execute(
            "SELECT has_schema_privilege('pub_test','public','CREATE')"
        ).fetchone()[0]
        usage_ok = conn.execute(
            "SELECT has_schema_privilege('pub_test','public','USAGE')"
        ).fetchone()[0]
        conn.execute("DROP ROLE pub_test")
        conn.commit()
    assert create_ok is True, "PUBLIC CREATE on public schema not restored"
    assert usage_ok is True, "PUBLIC USAGE on public schema not restored"


def test_57_down_migrations_are_idempotent(fresh_db):
    for f in DOWN_MIGRATIONS:
        apply_sql_file(fresh_db, MIGRATIONS_DIR / f)
    for f in DOWN_MIGRATIONS:
        apply_sql_file(fresh_db, MIGRATIONS_DIR / f)


def test_58_up_after_down_restores_full_state(fresh_db):
    with PostgresContainer(POSTGRES_IMAGE, driver=None).with_volume_mapping(
        str(MIGRATIONS_DIR), "/docker-entrypoint-initdb.d", mode="ro"
    ) as reference_container:
        reference_snapshot = snapshot_db_state(reference_container)

    for f in DOWN_MIGRATIONS:
        apply_sql_file(fresh_db, MIGRATIONS_DIR / f)
    for f in UP_MIGRATIONS:
        apply_sql_file(fresh_db, MIGRATIONS_DIR / f)

    restored_snapshot = snapshot_db_state(fresh_db)
    assert restored_snapshot == reference_snapshot, (
        "DB state after down+up does not match a fresh migration"
    )


# ===========================================================================
# 15. RLS — STRUCTURE
# ===========================================================================


@pytest.mark.parametrize(
    "table",
    ["licenses", "node_locked_license_data", "sessions", "heartbeats"],
)
def test_59_rls_enabled_on_tenant_table(conn_url, table):
    with psycopg.connect(conn_url) as conn:
        row = conn.execute(
            "SELECT relrowsecurity FROM pg_class WHERE relname = %s "
            "AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname='app')",
            (table,),
        ).fetchone()
    assert row is not None, f"Table app.{table} not found"
    assert row[0] is True, f"RLS not enabled on app.{table}"


@pytest.mark.parametrize(
    "table,policy",
    [
        ("licenses", "licenses_select_own"),
        ("licenses", "licenses_insert_own"),
        ("licenses", "licenses_update_own"),
        ("licenses", "licenses_delete_own"),
        ("node_locked_license_data", "node_locked_select_own"),
        ("node_locked_license_data", "node_locked_insert_own"),
        ("node_locked_license_data", "node_locked_update_own"),
        ("node_locked_license_data", "node_locked_delete_own"),
        ("sessions", "sessions_select_own"),
        ("sessions", "sessions_insert_own"),
        ("sessions", "sessions_update_own"),
        ("sessions", "sessions_delete_own"),
        ("heartbeats", "heartbeats_select_own"),
        ("heartbeats", "heartbeats_insert_own"),
        ("heartbeats", "heartbeats_update_own"),
        ("heartbeats", "heartbeats_delete_own"),
    ],
)
def test_60_rls_policy_exists(conn_url, table, policy):
    with psycopg.connect(conn_url) as conn:
        row = conn.execute(
            "SELECT 1 FROM pg_policies "
            "WHERE tablename = %s AND policyname = %s AND schemaname = 'app'",
            (table, policy),
        ).fetchone()
    assert row is not None, f"Policy '{policy}' not found on table app.{table}"


def test_61_set_app_context_function_exists(conn_url):
    with psycopg.connect(conn_url) as conn:
        result = conn.execute(
            "SELECT 1 FROM pg_proc p "
            "JOIN pg_namespace n ON p.pronamespace = n.oid "
            "WHERE n.nspname = 'app' AND p.proname = 'set_app_context'"
        ).fetchone()
        assert result is not None, "app.set_app_context function not found"


def test_61b_set_app_context_not_executable_by_public(conn_url):
    """PUBLIC must not be able to call set_app_context."""
    with psycopg.connect(conn_url) as conn:
        grants = [
            r[0]
            for r in conn.execute(
                "SELECT grantee FROM information_schema.routine_privileges "
                "WHERE routine_schema='app' AND routine_name='set_app_context' "
                "ORDER BY grantee"
            ).fetchall()
        ]
    assert "PUBLIC" not in grants, "PUBLIC should not have EXECUTE on set_app_context"


def test_61c_rls_function_owned_by_app_owner(conn_url):
    """set_app_context must be owned by app_owner — not the migration runner (superuser).

    Why this matters: if SET LOCAL ROLE app_owner is omitted before CREATE FUNCTION,
    the function is silently created under the superuser and inherits no app-schema
    defaults.  The function still *works*, so isolation tests keep passing — only an
    ownership test catches the regression.
    """
    with psycopg.connect(conn_url) as conn:
        row = conn.execute(
            "SELECT r.rolname "
            "FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid = p.pronamespace "
            "JOIN pg_roles r ON r.oid = p.proowner "
            "WHERE n.nspname = 'app' AND p.proname = 'set_app_context'"
        ).fetchone()
    assert row is not None, "app.set_app_context function not found"
    assert row[0] == "app_owner", (
        f"set_app_context is owned by '{row[0]}', expected 'app_owner'. "
        "Check that SET LOCAL ROLE app_owner is active when CREATE FUNCTION runs."
    )


@pytest.mark.parametrize(
    "table",
    ["licenses", "node_locked_license_data", "sessions", "heartbeats"],
)
def test_61d_rls_tenant_tables_owned_by_app_owner(conn_url, table):
    """All tenant-scoped tables must be owned by app_owner.

    This ensures the entire RLS surface — including ALTER TABLE ENABLE ROW LEVEL
    SECURITY and CREATE POLICY — is exercised by a single role and that no
    step silently requires superuser privileges.
    """
    with psycopg.connect(conn_url) as conn:
        row = conn.execute(
            "SELECT r.rolname "
            "FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "JOIN pg_roles r ON r.oid = c.relowner "
            "WHERE n.nspname = 'app' AND c.relname = %s",
            (table,),
        ).fetchone()
    assert row is not None, f"app.{table} not found"
    assert row[0] == "app_owner", (
        f"app.{table} is owned by '{row[0]}', expected 'app_owner'."
    )


def test_61e_audit_trigger_function_owned_by_audit_owner(conn_url):
    """prevent_audit_update_delete must be owned by audit_owner.

    PostgreSQL does not track the creator of a policy (pg_policy has no
    polowner column), so policy ownership cannot be verified via system
    catalogs.  The nearest equivalent ownership check for migration DDL is
    the trigger function, which does carry a proowner.  If SET LOCAL ROLE
    audit_owner is absent when 04_audit.sql runs the function is silently
    created under the superuser.
    """
    with psycopg.connect(conn_url) as conn:
        row = conn.execute(
            "SELECT r.rolname "
            "FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid = p.pronamespace "
            "JOIN pg_roles r ON r.oid = p.proowner "
            "WHERE n.nspname = 'audit' AND p.proname = 'prevent_audit_update_delete'",
        ).fetchone()
    assert row is not None, "audit.prevent_audit_update_delete function not found"
    assert row[0] == "audit_owner", (
        f"prevent_audit_update_delete is owned by '{row[0]}', expected 'audit_owner'. "
        "Check that SET LOCAL ROLE audit_owner is active when the function is created in 04_audit.sql."
    )


# ===========================================================================
# 16. RLS — VENDOR ISOLATION
# ===========================================================================


def test_62_vendor_isolation_select(superconn):
    vendor_a_id = insert_vendor(superconn, "vendor_a_76@example.com")
    vendor_b_id = insert_vendor(superconn, "vendor_b_76@example.com")
    license_a_id = insert_license(superconn, vendor_a_id)
    license_b_id = insert_license(superconn, vendor_b_id)

    with superconn.transaction():
        superconn.execute("SET LOCAL ROLE app_reader_rls")
        superconn.execute("SELECT app.set_app_context(%s)", (vendor_a_id,))

        count = superconn.execute('SELECT COUNT(*) FROM app."licenses"').fetchone()[0]
        assert count == 1, f"Vendor A expected 1 license, got {count}"

        own = superconn.execute(
            'SELECT vendor_id FROM app."licenses" WHERE id = %s', (license_a_id,)
        ).fetchone()
        assert own is not None and own[0] == vendor_a_id

        cross = superconn.execute(
            'SELECT COUNT(*) FROM app."licenses" WHERE id = %s', (license_b_id,)
        ).fetchone()[0]
        assert cross == 0, "Vendor A must not see Vendor B's license"

        # Flip context to vendor_b
        superconn.execute("SELECT app.set_app_context(%s)", (vendor_b_id,))
        count = superconn.execute('SELECT COUNT(*) FROM app."licenses"').fetchone()[0]
        assert count == 1, f"Vendor B expected 1 license, got {count}"


def test_63_vendor_isolation_insert(superconn):
    vendor_a_id = insert_vendor(superconn, "vendor_a_77@example.com")
    vendor_b_id = insert_vendor(superconn, "vendor_b_77@example.com")

    superconn.execute("SET LOCAL ROLE app_writer")
    superconn.execute("SELECT app.set_app_context(%s)", (vendor_a_id,))

    # Own insert succeeds
    superconn.execute(
        'INSERT INTO app."licenses" ("vendor_id","license_status_code","max_grace_secs") '
        "VALUES (%s,'ACTIVE',60)",
        (vendor_a_id,),
    )

    # Cross-vendor insert rejected by WITH CHECK
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        superconn.execute(
            'INSERT INTO app."licenses" ("vendor_id","license_status_code","max_grace_secs") '
            "VALUES (%s,'ACTIVE',60)",
            (vendor_b_id,),
        )

    superconn.rollback()


def test_64_vendor_isolation_update(superconn):
    vendor_a_id = insert_vendor(superconn, "vendor_a_78@example.com")
    vendor_b_id = insert_vendor(superconn, "vendor_b_78@example.com")
    license_a_id = insert_license(superconn, vendor_a_id)
    license_b_id = insert_license(superconn, vendor_b_id)

    with superconn.transaction():
        superconn.execute("SET LOCAL ROLE app_writer")
        superconn.execute("SELECT app.set_app_context(%s)", (vendor_a_id,))

        # Own update succeeds
        superconn.execute(
            'UPDATE app."licenses" SET updated_at=NOW() WHERE id=%s', (license_a_id,)
        )

        # Cross-vendor update silently affects 0 rows (USING hides it)
        cur = superconn.execute(
            'UPDATE app."licenses" SET updated_at=NOW() WHERE id=%s', (license_b_id,)
        )
        assert cur.rowcount == 0, "Vendor A must not update Vendor B's license"


def test_65_vendor_isolation_delete(superconn):
    vendor_a_id = insert_vendor(superconn, "vendor_a_79@example.com")
    vendor_b_id = insert_vendor(superconn, "vendor_b_79@example.com")
    license_a_id = insert_license(superconn, vendor_a_id)
    license_b_id = insert_license(superconn, vendor_b_id)

    with superconn.transaction():
        superconn.execute("SET LOCAL ROLE app_deleter")
        superconn.execute("SELECT app.set_app_context(%s)", (vendor_a_id,))

        # Own delete succeeds
        cur = superconn.execute(
            'DELETE FROM app."licenses" WHERE id=%s', (license_a_id,)
        )
        assert cur.rowcount == 1, "Own license should be deleted"

        # Cross-vendor delete silently affects 0 rows
        cur = superconn.execute(
            'DELETE FROM app."licenses" WHERE id=%s', (license_b_id,)
        )
        assert cur.rowcount == 0, "Vendor A must not delete Vendor B's license"

        # Confirm license_b is untouched (verify as app_owner to bypass RLS)
        superconn.execute("SET LOCAL ROLE app_owner")
        remaining = superconn.execute(
            'SELECT COUNT(*) FROM app."licenses" WHERE id=%s', (license_b_id,)
        ).fetchone()[0]
        assert remaining == 1, "Vendor B's license was wrongly deleted"


def test_66_queries_without_context_return_zero_rows(superconn):
    vid = insert_vendor(superconn, "vendor_80@example.com")
    insert_license(superconn, vid)

    # Switch role but intentionally do NOT call set_app_context
    with superconn.transaction():
        superconn.execute("SET LOCAL ROLE app_reader_rls")

        count = superconn.execute('SELECT COUNT(*) FROM app."licenses"').fetchone()[0]
        assert count == 0, f"Expected 0 rows without context, got {count}"


def test_67_sessions_isolation(superconn):
    vendor_a_id = insert_vendor(superconn, "vendor_a_81@example.com")
    vendor_b_id = insert_vendor(superconn, "vendor_b_81@example.com")
    license_a_id = insert_license(superconn, vendor_a_id)
    license_b_id = insert_license(superconn, vendor_b_id)
    insert_session(superconn, license_a_id, fingerprint="fp_a")
    session_b_id = insert_session(superconn, license_b_id, fingerprint="fp_b")

    with superconn.transaction():
        superconn.execute("SET LOCAL ROLE app_reader_rls")
        superconn.execute("SELECT app.set_app_context(%s)", (vendor_a_id,))

        count = superconn.execute('SELECT COUNT(*) FROM app."sessions"').fetchone()[0]
        assert count == 1, f"Vendor A expected 1 session, got {count}"

        cross = superconn.execute(
            'SELECT COUNT(*) FROM app."sessions" WHERE id=%s', (session_b_id,)
        ).fetchone()[0]
        assert cross == 0, "Vendor A must not see Vendor B's session"


def test_68_node_locked_isolation(superconn):
    vendor_a_id = insert_vendor(superconn, "vendor_a_82@example.com")
    vendor_b_id = insert_vendor(superconn, "vendor_b_82@example.com")
    license_a_id = insert_license(superconn, vendor_a_id)
    license_b_id = insert_license(superconn, vendor_b_id)
    insert_node_locked(superconn, license_a_id, "key_a_82")
    insert_node_locked(superconn, license_b_id, "key_b_82")

    with superconn.transaction():
        superconn.execute("SET LOCAL ROLE app_reader_rls")
        superconn.execute("SELECT app.set_app_context(%s)", (vendor_a_id,))

        count = superconn.execute(
            'SELECT COUNT(*) FROM app."node_locked_license_data"'
        ).fetchone()[0]
        assert count == 1, f"Vendor A expected 1 node-locked record, got {count}"

        cross = superconn.execute(
            'SELECT COUNT(*) FROM app."node_locked_license_data" WHERE license_id=%s',
            (license_b_id,),
        ).fetchone()[0]
        assert cross == 0, "Vendor A must not see Vendor B's node-locked data"


def test_69_heartbeats_isolation(superconn):
    vendor_a_id = insert_vendor(superconn, "vendor_a_83@example.com")
    vendor_b_id = insert_vendor(superconn, "vendor_b_83@example.com")
    license_a_id = insert_license(superconn, vendor_a_id)
    license_b_id = insert_license(superconn, vendor_b_id)
    session_a_id = insert_session(superconn, license_a_id)
    session_b_id = insert_session(superconn, license_b_id)
    insert_heartbeat(superconn, session_a_id)
    insert_heartbeat(superconn, session_b_id)

    with superconn.transaction():
        superconn.execute("SET LOCAL ROLE app_reader_rls")
        superconn.execute("SELECT app.set_app_context(%s)", (vendor_a_id,))

        count = superconn.execute('SELECT COUNT(*) FROM app."heartbeats"').fetchone()[0]
        assert count == 1, f"Vendor A expected 1 heartbeat, got {count}"

        cross = superconn.execute(
            'SELECT COUNT(*) FROM app."heartbeats" WHERE session_id=%s', (session_b_id,)
        ).fetchone()[0]
        assert cross == 0, "Vendor A must not see Vendor B's heartbeats"


def test_70_connection_context_isolation(conn_url):
    with psycopg.connect(conn_url) as conn1, psycopg.connect(conn_url) as conn2:
        vendor_a_id = insert_vendor(conn1, "vendor_a_84@example.com")
        vendor_b_id = insert_vendor(conn1, "vendor_b_84@example.com")
        insert_license(conn1, vendor_a_id)
        insert_license(conn1, vendor_b_id)
        conn1.commit()

        with conn1.transaction():
            conn1.execute("SET LOCAL ROLE app_reader_rls")
            conn1.execute("SELECT app.set_app_context(%s)", (vendor_a_id,))
            assert (
                conn1.execute('SELECT COUNT(*) FROM app."licenses"').fetchone()[0] == 1
            )

        with conn2.transaction():
            conn2.execute("SET LOCAL ROLE app_reader_rls")
            conn2.execute("SELECT app.set_app_context(%s)", (vendor_b_id,))
            assert (
                conn2.execute('SELECT COUNT(*) FROM app."licenses"').fetchone()[0] == 1
            )

        # Re-check conn1 to confirm context didn't bleed from conn2
        with conn1.transaction():
            conn1.execute("SET LOCAL ROLE app_reader_rls")
            conn1.execute("SELECT app.set_app_context(%s)", (vendor_a_id,))
            assert (
                conn1.execute('SELECT COUNT(*) FROM app."licenses"').fetchone()[0] == 1
            )


def test_71_rls_bypass_for_app_reader_bypass(superconn):
    vendor_a_id = insert_vendor(superconn, "vendor_a_85@example.com")
    vendor_b_id = insert_vendor(superconn, "vendor_b_85@example.com")
    license_a_id = insert_license(superconn, vendor_a_id)
    license_b_id = insert_license(superconn, vendor_b_id)

    with superconn.transaction():
        superconn.execute("SET LOCAL ROLE app_reader_bypass")

        count = superconn.execute(
            'SELECT COUNT(*) FROM app."licenses" WHERE id IN (%s,%s)',
            (license_a_id, license_b_id),
        ).fetchone()[0]
        assert count == 2, f"app_reader_bypass should see both licenses, got {count}"


def test_72_rls_blocks_vendor_id_hijack_via_update(superconn):
    """Vendor A cannot UPDATE vendor_id to re-assign their license to Vendor B's namespace."""
    vendor_a_id = insert_vendor(superconn, "vendor_a_86@example.com")
    vendor_b_id = insert_vendor(superconn, "vendor_b_86@example.com")
    license_a_id = insert_license(superconn, vendor_a_id)

    superconn.execute("SET LOCAL ROLE app_writer")
    superconn.execute("SELECT app.set_app_context(%s)", (vendor_a_id,))

    # Attempting to change vendor_id to vendor_b on an own row must fail the
    # WITH CHECK clause (new vendor_id != context vendor_id).
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        superconn.execute(
            'UPDATE app."licenses" SET vendor_id=%s WHERE id=%s',
            (vendor_b_id, license_a_id),
        )

    superconn.rollback()


def test_73_rls_no_leakage_via_app_owner_role_switch(superconn):
    """app_owner bypasses RLS by design and must see all vendors' rows."""
    vendor_a_id = insert_vendor(superconn, "vendor_a_87@example.com")
    vendor_b_id = insert_vendor(superconn, "vendor_b_87@example.com")
    lic_a = insert_license(superconn, vendor_a_id)
    lic_b = insert_license(superconn, vendor_b_id)

    with superconn.transaction():
        superconn.execute("SET LOCAL ROLE app_owner")
        count = superconn.execute(
            'SELECT COUNT(*) FROM app."licenses" WHERE id IN (%s,%s)',
            (lic_a, lic_b),
        ).fetchone()[0]
        assert count == 2, "app_owner should see both licenses (RLS bypass)"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"] + sys.argv[1:])
