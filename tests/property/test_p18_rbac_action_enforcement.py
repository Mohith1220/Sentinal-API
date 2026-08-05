# Feature: sentinel-api, Property 18: RBAC Action Enforcement
"""
Property 18: RBAC Action Enforcement

For any (user_role, action) pair, the system SHALL permit the action
if and only if the role's permission matrix grants access to that action.
- viewer role SHALL never perform write actions
- analyst role SHALL never access administrative configuration

Validates: Requirements 12.5, 10.6, 10.7
"""

import sys
import os

from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
SERVICE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "services", "api-gateway"
)
if SERVICE_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(SERVICE_DIR))

from rbac import check_permission, is_write_method, get_path_category, CATEGORY_ADMIN

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

role_st = st.sampled_from(["admin", "analyst", "viewer"])
method_st = st.sampled_from(["GET", "POST", "PUT", "PATCH", "DELETE"])

# Paths covering all four resource categories
path_st = st.sampled_from([
    "/endpoints",
    "/endpoints/ep-abc-123",
    "/score/ep-abc-123",
    "/alerts",
    "/alerts/alert-456",
    "/baselines/ep-abc-123",
    "/recommendations",
    "/recommendations/rec-789",
    "/admin/settings",
    "/admin/users",
])


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


@given(method=method_st, path=path_st)
@settings(max_examples=10)
def test_p18_viewer_never_performs_write_actions(method: str, path: str):
    """
    **Validates: Requirements 12.5, 10.7**

    The viewer role SHALL never be permitted to perform write actions
    (POST, PUT, PATCH, DELETE) on any resource.
    """
    allowed, _ = check_permission("viewer", method, path)

    if is_write_method(method):
        assert not allowed, (
            f"viewer should NOT be allowed to {method} {path}, but was permitted"
        )


@given(method=method_st, path=path_st)
@settings(max_examples=10)
def test_p18_analyst_never_accesses_admin_config(method: str, path: str):
    """
    **Validates: Requirements 12.5, 10.6**

    The analyst role SHALL never be permitted to access administrative
    configuration endpoints (any method on /admin/...).
    """
    allowed, _ = check_permission("analyst", method, path)
    category = get_path_category(path)

    if category == CATEGORY_ADMIN:
        assert not allowed, (
            f"analyst should NOT be allowed to {method} {path} (admin config), "
            f"but was permitted"
        )


@given(method=method_st, path=path_st)
@settings(max_examples=10)
def test_p18_admin_permitted_everywhere(method: str, path: str):
    """
    **Validates: Requirements 12.5**

    The admin role SHALL be permitted to perform any action on any resource.
    """
    allowed, _ = check_permission("admin", method, path)
    assert allowed, (
        f"admin should be allowed to {method} {path}, but was denied"
    )


@given(role=role_st, method=method_st, path=path_st)
@settings(max_examples=10)
def test_p18_permission_result_is_boolean(role: str, method: str, path: str):
    """
    **Validates: Requirements 12.5**

    check_permission always returns a (bool, str) tuple — never raises.
    """
    result = check_permission(role, method, path)
    assert isinstance(result, tuple), "check_permission must return a tuple"
    assert len(result) == 2, "check_permission must return a 2-tuple"
    allowed, hint = result
    assert isinstance(allowed, bool), "First element must be bool"
    assert isinstance(hint, str), "Second element must be str"


@given(method=method_st, path=path_st)
@settings(max_examples=10)
def test_p18_viewer_can_read_non_admin_resources(method: str, path: str):
    """
    **Validates: Requirements 10.7**

    The viewer role SHALL be permitted to read (GET) non-admin resources.
    """
    category = get_path_category(path)
    if method == "GET" and category != CATEGORY_ADMIN:
        allowed, _ = check_permission("viewer", method, path)
        assert allowed, (
            f"viewer should be allowed to GET {path} (category={category}), "
            f"but was denied"
        )


@given(method=method_st, path=path_st)
@settings(max_examples=10)
def test_p18_forbidden_returns_required_role_hint(method: str, path: str):
    """
    **Validates: Requirements 12.5**

    When a role is denied, the required_role hint must be non-empty.
    """
    for role in ["viewer", "analyst"]:
        allowed, hint = check_permission(role, method, path)
        if not allowed:
            assert hint, (
                f"When {role} is denied {method} {path}, "
                f"required_role hint must be non-empty"
            )


