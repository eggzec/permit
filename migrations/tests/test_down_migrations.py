from __future__ import annotations

import pytest

from _legacy_test_migrations import (
    test_53_down_migrations_remove_schemas,
    test_54_down_migrations_remove_all_roles,
    test_55_down_migrations_remove_trigger_function,
    test_56_down_migrations_restore_public_schema_privileges,
    test_57_down_migrations_are_idempotent,
    test_58_up_after_down_restores_full_state,
)

pytestmark = [pytest.mark.down_migrations, pytest.mark.reference, pytest.mark.app, pytest.mark.audit]
