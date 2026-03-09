from __future__ import annotations

from datetime import datetime, timezone

import pytest
from psycopg import sql

from .helpers import insert_heartbeat, insert_license, insert_session, insert_vendor

pytestmark = [pytest.mark.partitioning, pytest.mark.app]


@pytest.mark.parametrize(
    "email,heartbeat_at,partition",
    [
        pytest.param(
            "part-q1@example.com",
            datetime(2026, 2, 15, 12, 0, 0, tzinfo=timezone.utc),
            "heartbeats_2026_q1",
            id="routes_q1",
        ),
        pytest.param(
            "part-q1-boundary@example.com",
            datetime(2026, 3, 31, 23, 59, 59, tzinfo=timezone.utc),
            "heartbeats_2026_q1",
            id="routes_q1_boundary_end",
        ),
        pytest.param(
            "part-q2-boundary@example.com",
            datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc),
            "heartbeats_2026_q2",
            id="routes_q2_boundary_start",
        ),
        pytest.param(
            "part-q2@example.com",
            datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc),
            "heartbeats_2026_q2",
            id="routes_q2",
        ),
        pytest.param(
            "part-q3@example.com",
            datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc),
            "heartbeats_2026_q3",
            id="routes_q3",
        ),
        pytest.param(
            "part-q3-boundary@example.com",
            datetime(2026, 9, 30, 23, 59, 59, tzinfo=timezone.utc),
            "heartbeats_2026_q3",
            id="routes_q3_boundary_end",
        ),
        pytest.param(
            "part-q4-boundary@example.com",
            datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc),
            "heartbeats_2026_q4",
            id="routes_q4_boundary_start",
        ),
        pytest.param(
            "part-q4@example.com",
            datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc),
            "heartbeats_2026_q4",
            id="routes_q4",
        ),
        pytest.param(
            "part-default@example.com",
            datetime(2030, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            "heartbeats_default",
            id="routes_default",
        ),
    ],
)
def test_heartbeat_partition_routing(superconn, email, heartbeat_at, partition):
    all_partitions = [
        "heartbeats_2026_q1",
        "heartbeats_2026_q2",
        "heartbeats_2026_q3",
        "heartbeats_2026_q4",
        "heartbeats_default",
    ]
    with superconn.transaction(force_rollback=True):
        vid = insert_vendor(superconn, email)
        lid = insert_license(superconn, vid)
        sid = insert_session(superconn, lid)
        insert_heartbeat(superconn, sid, heartbeat_at=heartbeat_at)

        # Verify heartbeat is in the expected partition
        count = superconn.execute(
            sql.SQL("SELECT COUNT(*) FROM app.{} WHERE session_id=%s").format(
                sql.Identifier(partition)
            ),
            (sid,),
        ).fetchone()[0]
        assert count == 1, f"Heartbeat not found in expected partition {partition}"

        # Verify heartbeat is absent from all other partitions
        for other_partition in all_partitions:
            if other_partition != partition:
                other_count = superconn.execute(
                    sql.SQL("SELECT COUNT(*) FROM app.{} WHERE session_id=%s").format(
                        sql.Identifier(other_partition)
                    ),
                    (sid,),
                ).fetchone()[0]
                assert other_count == 0, (
                    f"Heartbeat unexpectedly found in {other_partition}"
                )
