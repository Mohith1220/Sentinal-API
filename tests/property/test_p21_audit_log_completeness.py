# Feature: sentinel-api, Property 21: Audit Log Completeness
"""
Property 21: Audit Log Completeness

For any administrative action, an audit log entry SHALL be created
containing non-null values for all required fields: actor_identity,
action_type, affected resource_type, affected resource_id, and UTC timestamp.

Validates: Requirements 12.6
"""

import sys
import os
from datetime import datetime, timezone

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

from audit import AuditLogEntry, extract_resource_info

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

actor_st = st.text(min_size=1, max_size=100)
action_type_st = st.sampled_from([
    "POST /endpoints",
    "PUT /endpoints/ep-123",
    "DELETE /endpoints/ep-456",
    "POST /recommendations",
    "PUT /recommendations/rec-789/resolve",
    "DELETE /admin/settings",
    "POST /admin/users",
    "PATCH /score/ep-abc",
])

# Paths covering all resource categories
path_st = st.sampled_from([
    "/endpoints",
    "/endpoints/ep-abc-123",
    "/score/ep-abc-123",
    "/alerts",
    "/alerts/alert-456",
    "/baselines/ep-abc-123",
    "/recommendations",
    "/recommendations/rec-789",
    "/recommendations/rec-789/resolve",
    "/admin/settings",
    "/admin/users",
])

method_st = st.sampled_from(["GET", "POST", "PUT", "PATCH", "DELETE"])


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


@given(
    actor=actor_st,
    action_type=action_type_st,
)
@settings(max_examples=10)
def test_p21_audit_entry_has_non_null_required_fields(
    actor: str, action_type: str
):
    """
    **Validates: Requirements 12.6**

    AuditLogEntry SHALL always have non-null values for actor_identity,
    action_type, resource_type, and occurred_at.
    """
    now = datetime.now(timezone.utc)
    entry = AuditLogEntry(
        actor_identity=actor,
        action_type=action_type,
        resource_type="endpoint",
        occurred_at=now,
    )

    assert entry.actor_identity is not None and entry.actor_identity != "", (
        "actor_identity must be non-null and non-empty"
    )
    assert entry.action_type is not None and entry.action_type != "", (
        "action_type must be non-null and non-empty"
    )
    assert entry.resource_type is not None and entry.resource_type != "", (
        "resource_type must be non-null and non-empty"
    )
    assert entry.occurred_at is not None, (
        "occurred_at must be non-null"
    )


@given(path=path_st, method=method_st)
@settings(max_examples=10)
def test_p21_extract_resource_info_returns_non_empty_type(path: str, method: str):
    """
    **Validates: Requirements 12.6**

    extract_resource_info SHALL return a non-empty resource_type for any
    valid API path.
    """
    resource_type, resource_id = extract_resource_info(path, method)

    assert resource_type is not None, "resource_type must not be None"
    assert resource_type != "", "resource_type must not be empty"
    assert isinstance(resource_type, str), "resource_type must be a string"


@given(
    actor=actor_st,
    action_type=action_type_st,
)
@settings(max_examples=10)
def test_p21_audit_entry_occurred_at_is_utc(actor: str, action_type: str):
    """
    **Validates: Requirements 12.6**

    AuditLogEntry.occurred_at SHALL always be a UTC datetime.
    """
    now = datetime.now(timezone.utc)
    entry = AuditLogEntry(
        actor_identity=actor,
        action_type=action_type,
        resource_type="endpoint",
        occurred_at=now,
    )

    assert entry.occurred_at.tzinfo is not None, (
        "occurred_at must have timezone info"
    )
    assert entry.occurred_at.tzinfo == timezone.utc, (
        "occurred_at must be UTC"
    )


@given(path=path_st, method=method_st)
@settings(max_examples=10)
def test_p21_extract_resource_info_returns_tuple(path: str, method: str):
    """
    **Validates: Requirements 12.6**

    extract_resource_info SHALL always return a (str, str | None) tuple
    without raising.
    """
    result = extract_resource_info(path, method)

    assert isinstance(result, tuple), "extract_resource_info must return a tuple"
    assert len(result) == 2, "extract_resource_info must return a 2-tuple"
    resource_type, resource_id = result
    assert isinstance(resource_type, str), "resource_type must be a string"
    assert resource_id is None or isinstance(resource_id, str), (
        "resource_id must be None or a string"
    )


@given(
    actor=actor_st,
    action_type=action_type_st,
    path=path_st,
    method=method_st,
)
@settings(max_examples=10)
def test_p21_full_audit_entry_construction(
    actor: str, action_type: str, path: str, method: str
):
    """
    **Validates: Requirements 12.6**

    A complete AuditLogEntry can always be constructed from valid inputs
    without raising, and all required fields are populated.
    """
    resource_type, resource_id = extract_resource_info(path, method)
    now = datetime.now(timezone.utc)

    entry = AuditLogEntry(
        actor_identity=actor,
        action_type=action_type,
        resource_type=resource_type,
        resource_id=resource_id,
        occurred_at=now,
        payload={"method": method, "path": path},
    )

    # All required fields must be non-null
    assert entry.actor_identity
    assert entry.action_type
    assert entry.resource_type
    assert entry.occurred_at is not None
    assert entry.occurred_at.tzinfo == timezone.utc


