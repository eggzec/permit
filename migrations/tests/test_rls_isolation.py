from __future__ import annotations

import pytest

from _legacy_test_migrations import (
    test_62_vendor_isolation_select,
    test_63_vendor_isolation_insert,
    test_64_vendor_isolation_update,
    test_65_vendor_isolation_delete,
    test_66_queries_without_context_return_zero_rows,
    test_67_sessions_isolation,
    test_68_node_locked_isolation,
    test_69_heartbeats_isolation,
    test_70_connection_context_isolation,
    test_71_rls_bypass_for_app_reader_bypass,
    test_72_rls_blocks_vendor_id_hijack_via_update,
    test_73_rls_no_leakage_via_app_owner_role_switch,
)

pytestmark = [pytest.mark.rls, pytest.mark.app]
