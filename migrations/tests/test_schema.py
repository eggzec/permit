from __future__ import annotations

import uuid

import psycopg
import pytest

pytestmark = [
    pytest.mark.schema,
    pytest.mark.reference,
    pytest.mark.app,
    pytest.mark.audit,
]


@pytest.mark.parametrize(
    "schema",
    [
        pytest.param("app", id="app"),
        pytest.param("audit", id="audit"),
        pytest.param("reference", id="reference"),
    ],
)
def test_schema_exists(conn_url, schema):
    with psycopg.connect(conn_url) as conn:
        row = conn.execute(
            "SELECT 1 FROM pg_namespace WHERE nspname = %s",
            (schema,),
        ).fetchone()
    assert row is not None, f"Schema '{schema}' does not exist"


@pytest.mark.parametrize(
    "table",
    [
        pytest.param("actions", id="actions"),
        pytest.param("error_codes", id="error_codes"),
        pytest.param("heartbeat_resp_statuses", id="heartbeat_resp_statuses"),
        pytest.param("license_statuses", id="license_statuses"),
        pytest.param("session_statuses", id="session_statuses"),
    ],
)
def test_reference_table_exists(conn_url, table):
    schema_name = "reference"
    with psycopg.connect(conn_url) as conn:
        row = conn.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema=%s AND table_name=%s",
            (schema_name, table),
        ).fetchone()
    assert row is not None, f"Table reference.{table} does not exist"


@pytest.mark.parametrize(
    "table",
    [
        pytest.param("heartbeats", id="heartbeats"),
        pytest.param("licenses", id="licenses"),
        pytest.param("node_locked_license_data", id="node_locked_license_data"),
        pytest.param("sessions", id="sessions"),
        pytest.param("vendors", id="vendors"),
        pytest.param("v_license_node_locked", id="v_license_node_locked_view"),
    ],
)
def test_app_relation_exists(conn_url, table):
    schema_name = "app"
    with psycopg.connect(conn_url) as conn:
        row = conn.execute(
            "SELECT 1 FROM pg_class c "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname=%s AND c.relname=%s AND c.relkind IN ('r','p','v')",
            (schema_name, table),
        ).fetchone()
    assert row is not None, f"Relation app.{table} does not exist"


@pytest.mark.parametrize(
    "table",
    [
        pytest.param("audit_log_licenses", id="audit_log_licenses"),
        pytest.param("audit_log_sessions", id="audit_log_sessions"),
        pytest.param("audit_log_vendor_actors", id="audit_log_vendor_actors"),
        pytest.param("audit_logs", id="audit_logs"),
    ],
)
def test_audit_table_exists(conn_url, table):
    schema_name = "audit"
    with psycopg.connect(conn_url) as conn:
        row = conn.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema=%s AND table_name=%s",
            (schema_name, table),
        ).fetchone()
    assert row is not None, f"Table audit.{table} does not exist"


@pytest.mark.parametrize(
    "partition",
    [
        pytest.param("heartbeats_2026_q1", id="2026_q1"),
        pytest.param("heartbeats_2026_q2", id="2026_q2"),
        pytest.param("heartbeats_2026_q3", id="2026_q3"),
        pytest.param("heartbeats_2026_q4", id="2026_q4"),
        pytest.param("heartbeats_2027_q1", id="2027_q1"),
        pytest.param("heartbeats_default", id="default"),
    ],
)
def test_heartbeat_partition_exists(conn_url, partition):
    schema_name = "app"
    with psycopg.connect(conn_url) as conn:
        row = conn.execute(
            "SELECT 1 FROM pg_class c "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname=%s AND c.relkind='r' "
            "AND c.relispartition=true AND c.relname=%s",
            (schema_name, partition),
        ).fetchone()
    assert row is not None, f"Heartbeat partition '{partition}' does not exist"


def test_vendors_id_defaults_to_uuidv7(superconn):
    with superconn.transaction(force_rollback=True):
        superconn.execute("SET LOCAL ROLE app_owner")
        superconn.execute('ALTER TABLE app."vendors" DISABLE TRIGGER vendors_audit_tr')
        email = "uuid7-check@example.com"
        password_hash = "hash"
        generated_id = superconn.execute(
            'INSERT INTO app."vendors" (email, password_hash) '
            "VALUES (%s,%s) RETURNING id",
            (email, password_hash),
        ).fetchone()[0]
        superconn.execute('ALTER TABLE app."vendors" ENABLE TRIGGER vendors_audit_tr')
    assert isinstance(generated_id, uuid.UUID), (
        f"Expected generated vendor id to be uuid.UUID, got {type(generated_id).__name__}"
    )
    assert (generated_id.int >> 76) & 0xF == 7, "Expected UUIDv7 (version nibble = 7)"
