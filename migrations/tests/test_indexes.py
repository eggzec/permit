from __future__ import annotations

import psycopg.rows
import pytest

pytestmark = [pytest.mark.indexes, pytest.mark.app, pytest.mark.audit]


@pytest.mark.parametrize(
    "schema,table,index_name",
    [
        pytest.param(
            "app", "vendors", "vendors_email_lower_idx", id="vendors_email_lower"
        ),
        pytest.param(
            "app",
            "heartbeats",
            "heartbeats_session_id_idx",
            id="heartbeats_session_id",
        ),
        pytest.param(
            "audit",
            "audit_log_vendor_actors",
            "audit_log_vendor_actors_vendor_id_idx",
            id="audit_vendor_actor_vendor_id",
        ),
    ],
)
def test_index_exists(superconn, schema, table, index_name):
    row = superconn.execute(
        "SELECT indexname FROM pg_indexes "
        "WHERE schemaname=%s AND tablename=%s AND indexname=%s",
        (schema, table, index_name),
    ).fetchone()
    assert row is not None, f"Index {index_name} missing on {schema}.{table}"


def test_heartbeats_brin_index_type(superconn):
    with superconn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        row = cur.execute(
            "SELECT i.relname AS index_name, am.amname AS am_name "
            "FROM pg_index ix "
            "JOIN pg_class i ON i.oid=ix.indexrelid "
            "JOIN pg_class c ON c.oid=ix.indrelid "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "JOIN pg_am am ON am.oid=i.relam "
            "WHERE n.nspname=%s AND c.relname=%s AND i.relname=%s",
            ("app", "heartbeats", "heartbeats_heartbeat_at_idx"),
        ).fetchone()
    assert row is not None, "BRIN index on heartbeats.heartbeat_at missing"
    assert row["am_name"] == "brin", f"Expected BRIN, got {row['am_name']}"
