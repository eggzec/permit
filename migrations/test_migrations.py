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
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pytest
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
]

DOWN_MIGRATIONS = [
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

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def migrated_db():
    # Session-scoped container. Migrations are auto-applied via
    # /docker-entrypoint-initdb.d. All read-only and additive tests share this.
    with PostgresContainer(POSTGRES_IMAGE, driver=None).with_volume_mapping(
        str(MIGRATIONS_DIR), "/docker-entrypoint-initdb.d", mode="ro"
    ) as container:
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
    with PostgresContainer(POSTGRES_IMAGE, driver=None).with_volume_mapping(
        str(MIGRATIONS_DIR), "/docker-entrypoint-initdb.d", mode="ro"
    ) as container:
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
    # Insert a minimal audit_log row as audit_owner. Does NOT commit.
    conn.execute("SET LOCAL ROLE audit_owner")
    row = conn.execute(
        "INSERT INTO audit.\"audit_logs\" (action_code) VALUES ('CREATED') RETURNING id"
    ).fetchone()
    return row[0]


def snapshot_db_state(container: PostgresContainer) -> str:
    # Deterministic SHA-256 fingerprint of relevant DB state.
    # Covers: schemas, tables/partitions, sequences, functions, triggers,
    # indexes, constraints, roles, table/seq privileges, default ACLs, seed data.
    url = container.get_connection_url(driver=None)
    with psycopg.connect(url) as conn:
        parts: list[str] = []

        schemas = conn.execute(
            "SELECT nspname FROM pg_namespace "
            "WHERE nspname IN ('reference','app','audit') ORDER BY 1"
        ).fetchall()
        parts.append(f"schemas={schemas}")

        tables = conn.execute(
            "SELECT n.nspname, c.relname, c.relkind, COALESCE(c.relispartition,false) "
            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname IN ('reference','app','audit') AND c.relkind IN ('r','p') "
            "ORDER BY 1,2"
        ).fetchall()
        parts.append(f"tables={tables}")

        seqs = conn.execute(
            "SELECT n.nspname, c.relname FROM pg_class c "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname IN ('reference','app','audit') AND c.relkind='S' ORDER BY 1,2"
        ).fetchall()
        parts.append(f"sequences={seqs}")

        funcs = conn.execute(
            "SELECT n.nspname, p.proname, pg_get_function_identity_arguments(p.oid) "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname IN ('reference','app','audit') ORDER BY 1,2,3"
        ).fetchall()
        parts.append(f"functions={funcs}")

        triggers = conn.execute(
            "SELECT n.nspname, c.relname, t.tgname, t.tgenabled "
            "FROM pg_trigger t "
            "JOIN pg_class c ON c.oid=t.tgrelid "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname IN ('reference','app','audit') AND NOT t.tgisinternal "
            "ORDER BY 1,2,3"
        ).fetchall()
        parts.append(f"triggers={triggers}")

        indexes = conn.execute(
            "SELECT n.nspname, c.relname, i.relname, ix.indisunique, ix.indisprimary "
            "FROM pg_index ix "
            "JOIN pg_class c ON c.oid=ix.indrelid "
            "JOIN pg_class i ON i.oid=ix.indexrelid "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname IN ('reference','app','audit') "
            "ORDER BY 1,2,3"
        ).fetchall()
        parts.append(f"indexes={indexes}")

        constraints = conn.execute(
            "SELECT n.nspname, c.relname, con.conname, con.contype "
            "FROM pg_constraint con "
            "JOIN pg_class c ON c.oid=con.conrelid "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname IN ('reference','app','audit') "
            "ORDER BY 1,2,3"
        ).fetchall()
        parts.append(f"constraints={constraints}")

        roles = conn.execute(
            "SELECT rolname, rolinherit, rolcanlogin, rolbypassrls FROM pg_roles "
            f"WHERE rolname IN ({','.join(repr(r) for r in ALL_GROUP_ROLES)}) "
            "ORDER BY rolname"
        ).fetchall()
        parts.append(f"roles={roles}")

        table_privs = conn.execute(
            "SELECT grantee, table_schema, table_name, privilege_type "
            "FROM information_schema.role_table_grants "
            "WHERE table_schema IN ('reference','app','audit') "
            "ORDER BY grantee, table_schema, table_name, privilege_type"
        ).fetchall()
        parts.append(f"table_privs={table_privs}")

        seq_privs = conn.execute(
            "SELECT grantee, object_schema, object_name, privilege_type "
            "FROM information_schema.usage_privileges "
            "WHERE object_type='SEQUENCE' AND object_schema IN ('reference','app','audit') "
            "ORDER BY grantee, object_schema, object_name, privilege_type"
        ).fetchall()
        parts.append(f"seq_privs={seq_privs}")

        default_acls = conn.execute(
            "SELECT r.rolname, n.nspname, da.defaclobjtype, da.defaclacl "
            "FROM pg_default_acl da "
            "JOIN pg_roles r ON r.oid=da.defaclrole "
            "LEFT JOIN pg_namespace n ON n.oid=da.defaclnamespace "
            "WHERE r.rolname IN ('reference_owner','audit_owner','app_owner') "
            "ORDER BY 1,2,3"
        ).fetchall()
        parts.append(f"default_acls={default_acls}")

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
                    f'SELECT * FROM reference."{tbl}" ORDER BY 1'
                ).fetchall()
                parts.append(f"reference.{tbl}={rows}")

        return hashlib.sha256("\n".join(str(p) for p in parts).encode()).hexdigest()


# ===========================================================================
# 1. SCHEMA AND TABLE PRESENCE
# ===========================================================================


def test_01_schemas_exist(conn_url):
    with psycopg.connect(conn_url) as conn:
        schemas = [
            r[0]
            for r in conn.execute(
                "SELECT nspname FROM pg_namespace "
                "WHERE nspname IN ('reference','app','audit') ORDER BY 1"
            ).fetchall()
        ]
    assert schemas == ["app", "audit", "reference"]


def test_02_reference_tables_exist(conn_url):
    with psycopg.connect(conn_url) as conn:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='reference' ORDER BY table_name"
            ).fetchall()
        ]
    expected = [
        "actions",
        "error_codes",
        "heartbeat_resp_statuses",
        "license_statuses",
        "session_statuses",
    ]
    assert all(t in tables for t in expected)


def test_03_app_tables_exist(conn_url):
    with psycopg.connect(conn_url) as conn:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='app' ORDER BY table_name"
            ).fetchall()
        ]
    expected = [
        "heartbeats",
        "licenses",
        "node_locked_license_data",
        "sessions",
        "vendors",
    ]
    assert all(t in tables for t in expected)


def test_04_audit_tables_exist(conn_url):
    with psycopg.connect(conn_url) as conn:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='audit' ORDER BY table_name"
            ).fetchall()
        ]
    expected = [
        "audit_log_licenses",
        "audit_log_sessions",
        "audit_log_vendor_actors",
        "audit_logs",
    ]
    assert all(t in tables for t in expected)


def test_05_heartbeat_partitions_exist(conn_url):
    # Filters relkind='r' to exclude partition indexes (which also have
    # relispartition=true but relkind='i').
    with psycopg.connect(conn_url) as conn:
        partitions = [
            r[0]
            for r in conn.execute(
                "SELECT c.relname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='app' AND c.relkind='r' AND c.relispartition=true "
                "ORDER BY c.relname"
            ).fetchall()
        ]
    expected = [
        "heartbeats_2026_q1",
        "heartbeats_2026_q2",
        "heartbeats_2026_q3",
        "heartbeats_2026_q4",
        "heartbeats_2027_q1",
        "heartbeats_default",
    ]
    assert partitions == expected


# ===========================================================================
# 2. IDEMPOTENCY
# ===========================================================================


def test_06_up_migrations_are_idempotent(migrated_db):
    state_before = snapshot_db_state(migrated_db)
    for f in UP_MIGRATIONS:
        apply_sql_file(migrated_db, MIGRATIONS_DIR / f)
    state_after = snapshot_db_state(migrated_db)
    assert state_after == state_before, (
        "DB state changed after re-running up migrations"
    )


# ===========================================================================
# 3. ROLES
# ===========================================================================


def test_07_all_roles_exist(conn_url):
    with psycopg.connect(conn_url) as conn:
        roles = [
            r[0]
            for r in conn.execute(
                f"SELECT rolname FROM pg_roles "
                f"WHERE rolname IN ({','.join(repr(r) for r in ALL_GROUP_ROLES)}) "
                f"ORDER BY rolname"
            ).fetchall()
        ]
    assert sorted(roles) == sorted(ALL_GROUP_ROLES)


def test_08_roles_are_nologin_noinherit(conn_url):
    with psycopg.connect(conn_url) as conn:
        rows = conn.execute(
            f"SELECT rolname, rolinherit, rolcanlogin FROM pg_roles "
            f"WHERE rolname IN ({','.join(repr(r) for r in ALL_GROUP_ROLES)})"
        ).fetchall()
    for rolname, inherit, login in rows:
        assert inherit is False, f"{rolname}: expected NOINHERIT"
        assert login is False, f"{rolname}: expected NOLOGIN"


def test_09_app_reader_bypass_has_bypassrls(conn_url):
    with psycopg.connect(conn_url) as conn:
        row = conn.execute(
            "SELECT rolbypassrls FROM pg_roles WHERE rolname='app_reader_bypass'"
        ).fetchone()
    assert row is not None and row[0] is True


def test_10_non_bypass_roles_have_no_bypassrls(conn_url):
    non_bypass = [r for r in ALL_GROUP_ROLES if r != "app_reader_bypass"]
    with psycopg.connect(conn_url) as conn:
        rows = conn.execute(
            f"SELECT rolname, rolbypassrls FROM pg_roles "
            f"WHERE rolname IN ({','.join(repr(r) for r in non_bypass)})"
        ).fetchall()
    for rolname, bypassrls in rows:
        assert bypassrls is False, f"{rolname} should not have BYPASSRLS"


# ===========================================================================
# 4. SEED DATA
# ===========================================================================


def test_11_license_statuses_seed(conn_url):
    with psycopg.connect(conn_url) as conn:
        rows = conn.execute(
            'SELECT code FROM reference."license_statuses" ORDER BY code'
        ).fetchall()
    assert [r[0] for r in rows] == ["ACTIVE", "REVOKED"]


def test_12_session_statuses_seed(conn_url):
    with psycopg.connect(conn_url) as conn:
        codes = [
            r[0]
            for r in conn.execute(
                'SELECT code FROM reference."session_statuses" ORDER BY code'
            ).fetchall()
        ]
    assert sorted(codes) == ["ACTIVE", "CLEANUP", "REVOKED", "ZOMBIE"]


def test_13_heartbeat_resp_statuses_seed(conn_url):
    with psycopg.connect(conn_url) as conn:
        codes = [
            r[0]
            for r in conn.execute(
                'SELECT code FROM reference."heartbeat_resp_statuses" ORDER BY code'
            ).fetchall()
        ]
    assert sorted(codes) == ["CONTINUE", "ERROR", "EXPIRED", "REFRESH", "REVOKED"]


def test_14_error_codes_seed_count(conn_url):
    with psycopg.connect(conn_url) as conn:
        count = conn.execute('SELECT COUNT(*) FROM reference."error_codes"').fetchone()[
            0
        ]
    assert count == 12


def test_15_actions_seed_count(conn_url):
    with psycopg.connect(conn_url) as conn:
        count = conn.execute('SELECT COUNT(*) FROM reference."actions"').fetchone()[0]
    assert count == 11


def test_16_required_action_codes_present(conn_url):
    required = {
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
    }
    with psycopg.connect(conn_url) as conn:
        codes = {
            r[0]
            for r in conn.execute('SELECT code FROM reference."actions"').fetchall()
        }
    assert required == codes


# ===========================================================================
# 5. INDEXES
# ===========================================================================


def test_17_vendors_email_lower_unique_index_exists(conn_url):
    with psycopg.connect(conn_url) as conn:
        row = conn.execute(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname='app' AND tablename='vendors' "
            "AND indexname='vendors_email_lower_idx'"
        ).fetchone()
    assert row is not None, "vendors_email_lower_idx missing"


def test_18_heartbeats_session_id_index_exists(conn_url):
    with psycopg.connect(conn_url) as conn:
        row = conn.execute(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname='app' AND tablename='heartbeats' "
            "AND indexname='heartbeats_session_id_idx'"
        ).fetchone()
    assert row is not None


def test_19_heartbeats_brin_index_exists_and_is_brin(conn_url):
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


def test_20_audit_vendor_actors_index_exists(conn_url):
    with psycopg.connect(conn_url) as conn:
        row = conn.execute(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname='audit' AND tablename='audit_log_vendor_actors' "
            "AND indexname='audit_log_vendor_actors_vendor_id_idx'"
        ).fetchone()
    assert row is not None


# ===========================================================================
# 6. CONSTRAINTS
# ===========================================================================


def test_21_licenses_max_grace_secs_blocks_zero(superconn):
    # CHECK: max_grace_secs > 0 rejects zero
    with superconn.transaction():
        vid = insert_vendor(superconn, "grace-zero@example.com")
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_license(superconn, vid, grace_secs=0)


def test_22_licenses_max_grace_secs_blocks_negative(superconn):
    # CHECK: max_grace_secs > 0 rejects negative
    with superconn.transaction():
        vid = insert_vendor(superconn, "grace-neg@example.com")
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_license(superconn, vid, grace_secs=-10)


def test_23_node_locked_max_sessions_blocks_zero(superconn):
    # CHECK: max_sessions > 0 rejects zero
    with superconn.transaction():
        vid = insert_vendor(superconn, "maxsess-zero@example.com")
        lid = insert_license(superconn, vid)
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_node_locked(superconn, lid, "key-zero", max_sessions=0)


def test_24_node_locked_max_sessions_blocks_negative(superconn):
    # CHECK: max_sessions > 0 rejects negative
    with superconn.transaction():
        vid = insert_vendor(superconn, "maxsess-neg@example.com")
        lid = insert_license(superconn, vid)
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_node_locked(superconn, lid, "key-neg", max_sessions=-5)


def test_25_heartbeat_error_code_required_when_resp_is_error(superconn):
    # CHECK: resp=ERROR with NULL error_code must be rejected
    with superconn.transaction():
        vid = insert_vendor(superconn, "hb-errcode-req@example.com")
        lid = insert_license(superconn, vid)
        sid = insert_session(superconn, lid)
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_heartbeat(superconn, sid, resp_code="ERROR", error_code=None)


def test_26_heartbeat_error_code_must_be_null_for_non_error(superconn):
    # CHECK: resp=CONTINUE with a non-NULL error_code must be rejected
    with superconn.transaction():
        vid = insert_vendor(superconn, "hb-errcode-null@example.com")
        lid = insert_license(superconn, vid)
        sid = insert_session(superconn, lid)
        with pytest.raises(psycopg.errors.CheckViolation):
            insert_heartbeat(
                superconn, sid, resp_code="CONTINUE", error_code="INTERNAL_ERROR"
            )


def test_27_heartbeat_error_resp_with_valid_error_code_succeeds(superconn):
    # CHECK: resp=ERROR + valid error_code is accepted
    with superconn.transaction():
        vid = insert_vendor(superconn, "hb-errcode-ok@example.com")
        lid = insert_license(superconn, vid)
        sid = insert_session(superconn, lid)
        insert_heartbeat(superconn, sid, resp_code="ERROR", error_code="INTERNAL_ERROR")


def test_28_vendors_email_lower_unique_enforced(superconn):
    # UNIQUE: case-insensitive duplicate email must be rejected
    with superconn.transaction():
        insert_vendor(superconn, "UniqueEmail@Example.com")
        with pytest.raises(psycopg.errors.UniqueViolation):
            insert_vendor(superconn, "uniqueemail@example.com")


def test_29_vendors_email_upper_case_duplicate_rejected(superconn):
    # UNIQUE: all-caps variant also rejected by lower() index
    with superconn.transaction():
        insert_vendor(superconn, "CaseTest@Domain.com")
        with pytest.raises(psycopg.errors.UniqueViolation):
            insert_vendor(superconn, "CASETEST@DOMAIN.COM")


def test_30_license_key_unique_enforced(superconn):
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
    # A 2026-Q1 timestamp must land in heartbeats_2026_q1
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
    # A 2026-Q3 timestamp must land in heartbeats_2026_q3
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
    # A far-future timestamp must fall into the default partition
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
    # UPDATE on audit_logs must be blocked by the immutability trigger
    log_id = _make_audit_log(superconn)
    superconn.commit()
    with pytest.raises(psycopg.errors.RaiseException):
        superconn.execute(
            "UPDATE audit.\"audit_logs\" SET user_agent='hacked' WHERE id=%s", (log_id,)
        )
    superconn.rollback()


def test_44_audit_log_delete_blocked(superconn):
    # DELETE on audit_logs must be blocked by the immutability trigger
    log_id = _make_audit_log(superconn)
    superconn.commit()
    with pytest.raises(psycopg.errors.RaiseException):
        superconn.execute('DELETE FROM audit."audit_logs" WHERE id=%s', (log_id,))
    superconn.rollback()


def test_45_audit_junction_update_blocked(superconn):
    # UPDATE on audit_log_vendor_actors is also blocked
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
    # SECURITY DEFINER: the trigger must fire even when the caller is the
    # postgres superuser (no SET ROLE in effect).
    log_id = _make_audit_log(superconn)
    superconn.commit()
    with pytest.raises(psycopg.errors.RaiseException):
        superconn.execute('DELETE FROM audit."audit_logs" WHERE id=%s', (log_id,))
    superconn.rollback()


# ===========================================================================
# 11. PRIVILEGE SUCCESS PATHS
# ===========================================================================


def test_47_app_reader_rls_can_select(conn_url):
    with psycopg.connect(conn_url, autocommit=False) as conn:
        conn.execute("SET LOCAL ROLE app_reader_rls")
        conn.execute('SELECT COUNT(*) FROM app."vendors"').fetchone()
        conn.rollback()


def test_48_app_writer_can_insert(conn_url):
    with psycopg.connect(conn_url, autocommit=False) as conn:
        conn.execute("SET LOCAL ROLE app_writer")
        conn.execute(
            'INSERT INTO app."vendors" (email, password_hash) '
            "VALUES ('writer-ok@example.com','hash')"
        )
        conn.commit()


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


def test_51_reference_reader_can_select(conn_url):
    with psycopg.connect(conn_url, autocommit=False) as conn:
        conn.execute("SET LOCAL ROLE reference_reader")
        count = conn.execute(
            'SELECT COUNT(*) FROM reference."license_statuses"'
        ).fetchone()[0]
        conn.rollback()
    assert count == 2


def test_52_audit_writer_can_insert(conn_url):
    with psycopg.connect(conn_url, autocommit=False) as conn:
        conn.execute("SET LOCAL ROLE audit_writer")
        conn.execute(
            "INSERT INTO audit.\"audit_logs\" (action_code) VALUES ('CREATED')"
        )
        conn.commit()


def test_53_audit_reader_can_select(conn_url):
    with psycopg.connect(conn_url, autocommit=False) as conn:
        conn.execute("SET LOCAL ROLE audit_reader")
        conn.execute('SELECT COUNT(*) FROM audit."audit_logs"').fetchone()
        conn.rollback()


# ===========================================================================
# 12. PRIVILEGE FAILURE PATHS
# ===========================================================================


def test_54_app_reader_rls_cannot_insert(conn_url):
    with psycopg.connect(conn_url, autocommit=False) as conn:
        conn.execute("SET LOCAL ROLE app_reader_rls")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                'INSERT INTO app."vendors" (email, password_hash) '
                "VALUES ('reader-fail@example.com','hash')"
            )
        conn.rollback()


def test_55_app_reader_rls_cannot_update(conn_url):
    with psycopg.connect(conn_url, autocommit=False) as conn:
        conn.execute("SET LOCAL ROLE app_reader_rls")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute('UPDATE app."vendors" SET updated_at=NOW()')
        conn.rollback()


def test_56_app_reader_rls_cannot_delete(conn_url):
    with psycopg.connect(conn_url, autocommit=False) as conn:
        conn.execute("SET LOCAL ROLE app_reader_rls")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute('DELETE FROM app."vendors"')
        conn.rollback()


def test_57_app_writer_cannot_delete(conn_url):
    with psycopg.connect(conn_url, autocommit=False) as conn:
        conn.execute("SET LOCAL ROLE app_writer")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute('DELETE FROM app."vendors"')
        conn.rollback()


def test_58_app_deleter_cannot_insert(conn_url):
    with psycopg.connect(conn_url, autocommit=False) as conn:
        conn.execute("SET LOCAL ROLE app_deleter")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                'INSERT INTO app."vendors" (email, password_hash) '
                "VALUES ('deleter-insert-fail@example.com','hash')"
            )
        conn.rollback()


def test_59_app_deleter_cannot_update(conn_url):
    with psycopg.connect(conn_url, autocommit=False) as conn:
        conn.execute("SET LOCAL ROLE app_deleter")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute('UPDATE app."vendors" SET updated_at=NOW()')
        conn.rollback()


def test_60_reference_reader_cannot_insert(conn_url):
    with psycopg.connect(conn_url, autocommit=False) as conn:
        conn.execute("SET LOCAL ROLE reference_reader")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                'INSERT INTO reference."license_statuses" (code, description) '
                "VALUES ('FAKE','should fail')"
            )
        conn.rollback()


def test_61_reference_writer_cannot_update(conn_url):
    # reference_writer has INSERT only, not UPDATE
    with psycopg.connect(conn_url, autocommit=False) as conn:
        conn.execute("SET LOCAL ROLE reference_writer")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                'UPDATE reference."license_statuses" '
                "SET description='hacked' WHERE code='ACTIVE'"
            )
        conn.rollback()


def test_62_reference_writer_cannot_delete(conn_url):
    with psycopg.connect(conn_url, autocommit=False) as conn:
        conn.execute("SET LOCAL ROLE reference_writer")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute('DELETE FROM reference."license_statuses"')
        conn.rollback()


def test_63_audit_writer_cannot_select(conn_url):
    # audit_writer has INSERT only, not SELECT
    with psycopg.connect(conn_url, autocommit=False) as conn:
        conn.execute("SET LOCAL ROLE audit_writer")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute('SELECT COUNT(*) FROM audit."audit_logs"')
        conn.rollback()


def test_64_audit_reader_cannot_insert(conn_url):
    with psycopg.connect(conn_url, autocommit=False) as conn:
        conn.execute("SET LOCAL ROLE audit_reader")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "INSERT INTO audit.\"audit_logs\" (action_code) VALUES ('CREATED')"
            )
        conn.rollback()


def test_65_app_reader_rls_cannot_access_reference_schema(conn_url):
    # app_reader_rls has no USAGE on reference schema, so name resolution fails
    with psycopg.connect(conn_url, autocommit=False) as conn:
        conn.execute("SET LOCAL ROLE app_reader_rls")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute('SELECT * FROM reference."license_statuses"')
        conn.rollback()


# ===========================================================================
# 13. PUBLIC SCHEMA HARDENING
# ===========================================================================


def test_66_public_role_has_no_create_on_public_schema(conn_url):
    # 01_roles.sql revokes CREATE on public from PUBLIC; verify it is absent
    with psycopg.connect(conn_url) as conn:
        acl = conn.execute(
            "SELECT nspacl FROM pg_namespace WHERE nspname='public'"
        ).fetchone()[0]
    acl_str = str(acl) if acl else ""
    assert "=C" not in acl_str, "PUBLIC should not have CREATE on public schema"


# ===========================================================================
# 14. DOWN MIGRATIONS
# ===========================================================================


def test_67_down_migrations_remove_schemas(fresh_db):
    for f in DOWN_MIGRATIONS:
        apply_sql_file(fresh_db, MIGRATIONS_DIR / f)
    url = fresh_db.get_connection_url(driver=None)
    with psycopg.connect(url) as conn:
        schemas = conn.execute(
            "SELECT nspname FROM pg_namespace "
            "WHERE nspname IN ('reference','app','audit')"
        ).fetchall()
    assert len(schemas) == 0


def test_68_down_migrations_remove_all_roles(fresh_db):
    for f in DOWN_MIGRATIONS:
        apply_sql_file(fresh_db, MIGRATIONS_DIR / f)
    url = fresh_db.get_connection_url(driver=None)
    with psycopg.connect(url) as conn:
        roles = conn.execute(
            f"SELECT rolname FROM pg_roles "
            f"WHERE rolname IN ({','.join(repr(r) for r in ALL_GROUP_ROLES)})"
        ).fetchall()
    assert len(roles) == 0


def test_69_down_migrations_remove_trigger_function(fresh_db):
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


def test_70_down_migrations_restore_public_schema_privileges(fresh_db):
    # 01_roles_down.sql must restore CREATE and USAGE on public for PUBLIC
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


def test_71_down_migrations_are_idempotent(fresh_db):
    # Running all down migrations twice must not raise any error
    for f in DOWN_MIGRATIONS:
        apply_sql_file(fresh_db, MIGRATIONS_DIR / f)
    for f in DOWN_MIGRATIONS:
        apply_sql_file(fresh_db, MIGRATIONS_DIR / f)


def test_72_up_after_down_restores_full_state(fresh_db):
    # down then up must produce a snapshot identical to a freshly migrated DB
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


if __name__ == "__main__":
    pytest.main([__file__, "-n", "auto", "-v", "--tb=short"])
