from __future__ import annotations

import pytest

from .helpers import (
    DOWN_MIGRATIONS,
    MIGRATIONS_DIR,
    UP_MIGRATIONS,
    apply_sql_file,
    snapshot_db_state_parts,
)

MISSING = object()


@pytest.mark.idempotency
@pytest.mark.reference
@pytest.mark.app
@pytest.mark.audit
def test_up_migrations_are_idempotent(superconn):
    before = snapshot_db_state_parts(superconn)
    with superconn.cursor() as cur:
        for filename in UP_MIGRATIONS:
            apply_sql_file(cur, MIGRATIONS_DIR / filename)
    after = snapshot_db_state_parts(superconn)

    diffs = {}
    for k in before:
        after_val = after.get(k, MISSING)
        if before[k] != after_val:
            after_display = "<removed>" if after_val is MISSING else after_val
            diffs[k] = (before[k], after_display)

    for key in after:
        if key not in before:
            diffs[key] = ("<added>", after[key])

    assert not diffs, (
        "DB state changed after re-running up migrations.\n"
        "Fields that differ:\n"
        + "\n".join(
            f"\n  [{field}]\n    BEFORE: {v_before}\n    AFTER:  {v_after}"
            for field, (v_before, v_after) in diffs.items()
        )
    )


@pytest.mark.idempotency
@pytest.mark.reference
@pytest.mark.app
@pytest.mark.audit
def test_down_migrations_are_idempotent(superconn):
    # Apply all down migrations and take snapshot
    with superconn.cursor() as cur:
        for filename in DOWN_MIGRATIONS:
            apply_sql_file(cur, MIGRATIONS_DIR / filename)
    before = snapshot_db_state_parts(superconn)

    # Apply all down migrations again
    with superconn.cursor() as cur:
        for filename in DOWN_MIGRATIONS:
            apply_sql_file(cur, MIGRATIONS_DIR / filename)
    after = snapshot_db_state_parts(superconn)

    diffs = {}
    for k in before:
        second_val = after.get(k, MISSING)
        if before[k] != second_val:
            second_display = "<removed>" if second_val is MISSING else second_val
            diffs[k] = (before[k], second_display)

    for key in after:
        if key not in before:
            diffs[key] = ("<added>", after[key])

    assert not diffs, (
        "DB state changed after re-running down migrations.\n"
        "Fields that differ:\n"
        + "\n".join(
            f"\n  [{field}]\n    BEFORE: {v_before}\n    AFTER:  {v_after}"
            for field, (v_before, v_after) in diffs.items()
        )
    )
