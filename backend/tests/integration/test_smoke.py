"""Integration smoke tests - verify Testcontainers and fixtures work end-to-end."""

import pytest


# TODO: this should be removed on adding real integration tests
@pytest.mark.integration
def test_marker_registered() -> None:
    """Confirm that the `integration` marker is registered and accepted.

    This is a placeholder test that simply passes. Its purpose is to
    verify that pytest recognises the custom `integration` marker without
    emitting unknown-marker warnings.
    """
