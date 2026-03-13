from __future__ import annotations

import pytest

from .helpers import ALL_GROUP_ROLES

pytestmark = [pytest.mark.roles, pytest.mark.app]


@pytest.mark.parametrize(
    "role",
    [pytest.param(role, id=role) for role in ALL_GROUP_ROLES],
)
def test_role_exists(superconn, role):
    row = superconn.execute(
        "SELECT 1 FROM pg_roles WHERE rolname = %s",
        (role,),
    ).fetchone()
    assert row is not None, f"Role '{role}' does not exist"


@pytest.mark.parametrize(
    "role",
    [pytest.param(role, id=role) for role in ALL_GROUP_ROLES],
)
def test_role_is_nologin_noinherit(superconn, role):
    row = superconn.execute(
        "SELECT rolinherit, rolcanlogin FROM pg_roles WHERE rolname = %s",
        (role,),
    ).fetchone()
    assert row is not None, f"Role '{role}' not found"
    assert row[0] is False, f"{role}: expected NOINHERIT"
    assert row[1] is False, f"{role}: expected NOLOGIN"


def test_app_reader_bypass_has_bypassrls(superconn):
    row = superconn.execute(
        "SELECT rolbypassrls FROM pg_roles WHERE rolname = %s",
        ("app_reader_bypass",),
    ).fetchone()
    assert row is not None, "Role 'app_reader_bypass' not found"
    assert row[0] is True, "app_reader_bypass should have BYPASSRLS"


@pytest.mark.parametrize(
    "role",
    [
        pytest.param(role, id=role)
        for role in ALL_GROUP_ROLES
        if role != "app_reader_bypass"
    ],
)
def test_role_has_no_bypassrls(superconn, role):
    row = superconn.execute(
        "SELECT rolbypassrls FROM pg_roles WHERE rolname = %s",
        (role,),
    ).fetchone()
    assert row is not None, f"Role '{role}' not found"
    assert row[0] is False, f"{role} should not have BYPASSRLS"
