from __future__ import annotations

import pytest

from _legacy_test_migrations import test_15_index_exists, test_16_heartbeats_brin_index_type

pytestmark = [pytest.mark.indexes, pytest.mark.app, pytest.mark.audit]
