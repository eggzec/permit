from __future__ import annotations

import pytest

from _legacy_test_migrations import (
    test_17_licenses_max_grace_secs_blocks_zero,
    test_19_licenses_max_grace_secs_blocks_negative,
    test_20_node_locked_max_sessions_blocks_zero,
    test_21_node_locked_max_sessions_blocks_negative,
    test_22_heartbeat_error_code_required_when_resp_is_error,
    test_23_heartbeat_error_code_must_be_null_for_non_error,
    test_24_heartbeat_error_resp_with_valid_error_code_succeeds,
    test_25_vendors_email_lower_unique_enforced,
    test_26_vendors_email_upper_case_duplicate_rejected,
    test_27_license_key_unique_enforced,
    test_31_session_token_hash_unique_enforced,
    test_32_license_fk_rejects_nonexistent_vendor,
    test_33_license_fk_rejects_bad_status_code,
    test_34_session_fk_rejects_bad_status_code,
    test_35_vendor_on_delete_restrict_blocks_deletion,
    test_36_license_on_delete_restrict_blocks_deletion,
    test_37_heartbeat_on_delete_cascade_removes_heartbeats,
    test_38_audit_fk_rejects_nonexistent_audit_log,
)

pytestmark = [
    pytest.mark.app,
    pytest.mark.audit,
    pytest.mark.constraints,
    pytest.mark.foreign_keys,
]
