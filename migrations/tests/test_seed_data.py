from __future__ import annotations

import pytest

from _legacy_test_migrations import (
    test_11_seed_data_codes,
    test_12_error_codes_seed_count,
    test_13_actions_seed_count,
    test_14_action_code_present,
)

pytestmark = [pytest.mark.seed_data, pytest.mark.reference]
