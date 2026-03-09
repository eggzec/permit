from __future__ import annotations

import pytest

from _legacy_test_migrations import (
    test_07_role_exists,
    test_08_role_is_nologin_noinherit,
    test_09_app_reader_bypass_has_bypassrls,
    test_10_role_has_no_bypassrls,
)

pytestmark = [pytest.mark.roles, pytest.mark.app]
