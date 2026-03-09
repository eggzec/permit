from __future__ import annotations

import pytest

from _legacy_test_migrations import (
    test_47_privilege_grant_simple,
    test_49_app_writer_can_update,
    test_50_app_deleter_can_delete,
    test_51_privilege_denial,
    test_52_public_role_has_no_create_on_public_schema,
)

pytestmark = [pytest.mark.privileges, pytest.mark.reference, pytest.mark.app, pytest.mark.audit]
