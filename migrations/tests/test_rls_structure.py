from __future__ import annotations

import pytest

from _legacy_test_migrations import (
    test_59_rls_enabled_on_tenant_table,
    test_60_rls_policy_exists,
    test_61_set_app_context_function_exists,
    test_61b_set_app_context_not_executable_by_public,
    test_61c_rls_function_owned_by_app_owner,
    test_61d_rls_tenant_tables_owned_by_app_owner,
    test_61e_audit_trigger_function_owned_by_audit_owner,
)

pytestmark = [pytest.mark.rls, pytest.mark.app, pytest.mark.audit]
