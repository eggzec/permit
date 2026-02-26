"""Unit smoke tests - verify the test infrastructure works."""

import pytest


@pytest.mark.unit
def test_marker_registered() -> None:
    """Confirm that the ``unit`` marker is registered and accepted.

    This is a placeholder test that simply passes. Its purpose is to
    verify that pytest recognises the custom ``unit`` marker without
    emitting unknown-marker warnings.
    """
