# Feature: sentinel-api, Property 6: Endpoint Record Round-Trip
"""
Property-based tests for Property 6: Endpoint Record Round-Trip.

For any valid EndpointRecord, serializing to JSON and deserializing back SHALL
produce an equivalent record with all fields preserved, and repeating the
round-trip SHALL yield the same result (idempotency).

**Validates: Requirements 1.7**
"""

from datetime import datetime, timezone
from typing import Optional

from hypothesis import given, settings
from hypothesis import strategies as st

from sentinel_shared.models import (
    AuthScheme,
    DataSensitivity,
    EndpointRecord,
    LifecycleStatus,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

HTTP_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"]


def http_method_strategy() -> st.SearchStrategy[str]:
    """Generate valid HTTP method strings."""
    return st.sampled_from(HTTP_METHODS)


def host_strategy() -> st.SearchStrategy[str]:
    """Generate non-empty host strings (simple domain-like values)."""
    return st.from_regex(r"[a-zA-Z][a-zA-Z0-9\-]{0,30}(\.[a-zA-Z]{2,6})?", fullmatch=True)


def normalized_path_strategy() -> st.SearchStrategy[str]:
    """Generate normalized path strings that start with '/'."""
    segment = st.from_regex(r"[a-zA-Z0-9_\-]{1,20}", fullmatch=True)
    segments = st.lists(segment, min_size=1, max_size=5)
    return segments.map(lambda segs: "/" + "/".join(segs))


def optional_str_strategy() -> st.SearchStrategy[Optional[str]]:
    """Generate an optional non-empty string."""
    return st.one_of(
        st.none(),
        st.from_regex(r"[a-zA-Z0-9_\-]{1,30}", fullmatch=True),
    )


def metadata_strategy() -> st.SearchStrategy[dict]:
    """Generate simple JSON-serializable dicts for metadata."""
    key = st.from_regex(r"[a-zA-Z][a-zA-Z0-9_]{0,15}", fullmatch=True)
    value = st.one_of(
        st.text(max_size=30),
        st.integers(),
        st.booleans(),
        st.none(),
    )
    return st.dictionaries(key, value, max_size=5)


def datetime_strategy() -> st.SearchStrategy[Optional[datetime]]:
    """Generate optional timezone-aware datetimes."""
    return st.one_of(
        st.none(),
        st.datetimes(
            min_value=datetime(2000, 1, 1),
            max_value=datetime(2099, 12, 31),
            timezones=st.just(timezone.utc),
        ),
    )


def endpoint_record_strategy() -> st.SearchStrategy[EndpointRecord]:
    """Build arbitrary valid EndpointRecord instances."""
    return st.builds(
        EndpointRecord,
        http_method=http_method_strategy(),
        host=host_strategy(),
        normalized_path=normalized_path_strategy(),
        auth_scheme=st.sampled_from(list(AuthScheme)),
        data_sensitivity=st.sampled_from(list(DataSensitivity)),
        lifecycle_status=st.sampled_from(list(LifecycleStatus)),
        risk_score=st.integers(min_value=0, max_value=100),
        request_count_24h=st.integers(min_value=0, max_value=10_000_000),
        last_access_at=datetime_strategy(),
        owning_team=optional_str_strategy(),
        source_file_id=optional_str_strategy(),
        metadata=metadata_strategy(),
        # id is auto-generated; let Pydantic handle the default
    )


# ---------------------------------------------------------------------------
# Property 6a: Single round-trip preserves all fields
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(record=endpoint_record_strategy())
def test_round_trip_preserves_all_fields(record: EndpointRecord):
    """
    **Validates: Requirements 1.7**

    For any valid EndpointRecord, serializing to JSON and deserializing back
    SHALL produce an equivalent record with all fields preserved.
    """
    json_str = record.model_dump_json()
    restored = EndpointRecord.model_validate_json(json_str)

    assert restored.http_method == record.http_method, (
        f"http_method mismatch: {restored.http_method!r} != {record.http_method!r}"
    )
    assert restored.host == record.host, (
        f"host mismatch: {restored.host!r} != {record.host!r}"
    )
    assert restored.normalized_path == record.normalized_path, (
        f"normalized_path mismatch: {restored.normalized_path!r} != {record.normalized_path!r}"
    )
    assert restored.auth_scheme == record.auth_scheme, (
        f"auth_scheme mismatch: {restored.auth_scheme!r} != {record.auth_scheme!r}"
    )
    assert restored.data_sensitivity == record.data_sensitivity, (
        f"data_sensitivity mismatch: {restored.data_sensitivity!r} != {record.data_sensitivity!r}"
    )
    assert restored.lifecycle_status == record.lifecycle_status, (
        f"lifecycle_status mismatch: {restored.lifecycle_status!r} != {record.lifecycle_status!r}"
    )
    assert restored.risk_score == record.risk_score, (
        f"risk_score mismatch: {restored.risk_score!r} != {record.risk_score!r}"
    )
    assert restored.request_count_24h == record.request_count_24h, (
        f"request_count_24h mismatch: {restored.request_count_24h!r} != {record.request_count_24h!r}"
    )
    assert restored.last_access_at == record.last_access_at, (
        f"last_access_at mismatch: {restored.last_access_at!r} != {record.last_access_at!r}"
    )
    assert restored.owning_team == record.owning_team, (
        f"owning_team mismatch: {restored.owning_team!r} != {record.owning_team!r}"
    )
    assert restored.source_file_id == record.source_file_id, (
        f"source_file_id mismatch: {restored.source_file_id!r} != {record.source_file_id!r}"
    )
    assert restored.metadata == record.metadata, (
        f"metadata mismatch: {restored.metadata!r} != {record.metadata!r}"
    )
    assert restored.id == record.id, (
        f"id mismatch: {restored.id!r} != {record.id!r}"
    )


# ---------------------------------------------------------------------------
# Property 6b: Round-trip is idempotent (doing it twice gives the same result)
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(record=endpoint_record_strategy())
def test_round_trip_is_idempotent(record: EndpointRecord):
    """
    **Validates: Requirements 1.7**

    Performing the JSON round-trip twice SHALL produce the same result as
    performing it once (idempotency).
    """
    # First round-trip
    json_str_1 = record.model_dump_json()
    restored_1 = EndpointRecord.model_validate_json(json_str_1)

    # Second round-trip
    json_str_2 = restored_1.model_dump_json()
    restored_2 = EndpointRecord.model_validate_json(json_str_2)

    assert restored_1.model_dump() == restored_2.model_dump(), (
        f"Round-trip is not idempotent.\n"
        f"After 1st trip: {restored_1.model_dump()}\n"
        f"After 2nd trip: {restored_2.model_dump()}"
    )


# ---------------------------------------------------------------------------
# Property 6c: JSON output is stable (same record → same JSON)
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(record=endpoint_record_strategy())
def test_json_serialization_is_stable(record: EndpointRecord):
    """
    **Validates: Requirements 1.7**

    Serializing the same EndpointRecord twice SHALL produce identical JSON
    strings (deterministic serialization).
    """
    json_a = record.model_dump_json()
    json_b = record.model_dump_json()

    assert json_a == json_b, (
        f"Serialization is not stable for record id={record.id!r}:\n"
        f"  First:  {json_a}\n"
        f"  Second: {json_b}"
    )

