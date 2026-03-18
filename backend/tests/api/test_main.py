from __future__ import annotations

import pytest

from app.api.main import api_router


@pytest.mark.unit
def test_api_router_includes_health_and_auth_routes() -> None:
    """
    Purpose:
        Verifies that `app.api.main.api_router` includes the health and auth route trees expected by the public API.
        This matters because the main API router is the composition point for the endpoints clients depend on.

    Covers:
        - `app.api.main.api_router`

    Rationale:
        This test inspects the router object directly because the contract under test is route registration, not request handling.

    Fixtures:
        None.
    """
    route_paths = {route.path for route in api_router.routes}
    expected_paths = {"/health", "/auth/signup", "/auth/login", "/auth/refresh"}

    assert expected_paths <= route_paths, (
        f"Expected API router paths {expected_paths}, got {route_paths}"
    )
