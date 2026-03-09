from __future__ import annotations

import pytest

from _legacy_test_migrations import test_06_up_migrations_are_idempotent

pytestmark = [pytest.mark.idempotency, pytest.mark.reference, pytest.mark.app, pytest.mark.audit]
