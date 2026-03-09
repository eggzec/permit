from __future__ import annotations

import pytest

from _legacy_test_migrations import (
    test_43_audit_log_update_blocked,
    test_44_audit_log_delete_blocked,
    test_45_audit_junction_update_blocked,
    test_46_audit_immutability_fires_for_superuser,
)

pytestmark = [pytest.mark.audit_immutability, pytest.mark.audit]
