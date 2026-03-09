from __future__ import annotations

import pytest

from _legacy_test_migrations import (
    test_01_schema_exists,
    test_02_reference_table_exists,
    test_03_app_table_exists,
    test_04_audit_table_exists,
    test_05_heartbeat_partition_exists,
    test_39_vendors_id_defaults_to_uuidv7,
)

pytestmark = [pytest.mark.schema, pytest.mark.reference, pytest.mark.app, pytest.mark.audit]
