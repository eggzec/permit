from __future__ import annotations

import pytest

from _legacy_test_migrations import (
    test_40_heartbeat_routes_to_2026_q1,
    test_41_heartbeat_routes_to_2026_q3,
    test_42_heartbeat_routes_to_default_partition,
)

pytestmark = [pytest.mark.partitioning, pytest.mark.app]
