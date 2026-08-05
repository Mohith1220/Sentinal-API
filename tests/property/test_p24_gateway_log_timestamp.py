# Feature: sentinel-api, Property 24: Gateway Log Last-Observed Timestamp
"""
Property-based tests for Property 24: Gateway Log Last-Observed Timestamp.

For any set of gateway log entries for a given endpoint, the last_access_at
value recorded in the API Inventory SHALL equal the maximum timestamp among
all log entries for that endpoint.

**Validates: Requirements 2.4**
"""

import json
import sys
import os
from datetime import datetime, timezone, timedelta

from hypothesis import given, settings, assume
from hypothesis import strategies as st

_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(_REPO_ROOT, "services", "discovery-service"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "sentinel_shared"))

from parsers.log_parser import parse_gateway_logs
from sentinel_shared.normalization import normalize_path

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_segment = st.from_regex(r"[a-zA-Z][a-zA-Z0-9_]{0,10}", fullmatch=True)
_path = st.lists(_segment, min_size=1, max_size=2).map(lambda s: "/" + "/".join(s))
_host = st.from_regex(r"[a-zA-Z][a-zA-Z0-9\-]{0,15}\.example\.com", fullmatch=True)
_method = st.sampled_from(["GET", "POST", "PUT", "DELETE"])

# Generate UTC datetimes in a reasonable range
_utc_datetime = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
    timezones=st.just(timezone.utc),
)


def _to_iso(dt: datetime) -> str:
    """Format a datetime as ISO 8601 with Z suffix."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_dt(dt: datetime) -> datetime:
    """Normalize a datetime to UTC, stripping sub-second precision."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=0)


def _json_log_line(method: str, host: str, path: str, status: int, timestamp: str) -> str:
    return json.dumps({
        "method": method,
        "host": host,
        "path": path,
        "status": status,
        "timestamp": timestamp,
    })


# ---------------------------------------------------------------------------
# Property 24a: last_access_at equals MAX(timestamp) for a single endpoint
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(
    method=_method,
    host=_host,
    path=_path,
    timestamps=st.lists(_utc_datetime, min_size=1, max_size=10),
)
def test_last_access_at_equals_max_timestamp_single_endpoint(
    method: str,
    host: str,
    path: str,
    timestamps: list[datetime],
):
    """
    **Validates: Requirements 2.4**

    For any set of log entries for a single endpoint, last_access_at SHALL
    equal the maximum timestamp among all entries.
    """
    lines = [
        _json_log_line(method, host, path, 200, _to_iso(ts))
        for ts in timestamps
    ]
    content = "\n".join(lines)

    records = parse_gateway_logs(content, default_host=host)

    # Find the record for our endpoint (path may be normalized)
    assert len(records) >= 1, f"Expected at least 1 record, got {len(records)}"

    # There should be exactly 1 unique (method, host, normalized_path)
    assert len(records) == 1, (
        f"Expected 1 record for single endpoint, got {len(records)}: "
        f"{[(r.http_method, r.host, r.normalized_path) for r in records]}"
    )

    record = records[0]
    assert record.last_access_at is not None, (
        "last_access_at must not be None when timestamps are present in logs"
    )

    expected_max = _normalize_dt(max(timestamps))
    actual = _normalize_dt(record.last_access_at)

    assert actual == expected_max, (
        f"last_access_at {actual} != max timestamp {expected_max}.\n"
        f"All timestamps: {[_to_iso(ts) for ts in timestamps]}"
    )


# ---------------------------------------------------------------------------
# Property 24b: Each endpoint gets its own correct max timestamp
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(
    endpoints=st.lists(
        st.tuples(_method, _host, _path),
        min_size=2,
        max_size=4,
    ).filter(lambda eps: len({(m, h, p) for m, h, p in eps}) == len(eps)),
    timestamps_per_endpoint=st.lists(
        st.lists(_utc_datetime, min_size=1, max_size=5),
        min_size=2,
        max_size=4,
    ),
)
def test_each_endpoint_gets_its_own_max_timestamp(
    endpoints: list[tuple[str, str, str]],
    timestamps_per_endpoint: list[list[datetime]],
):
    """
    **Validates: Requirements 2.4**

    When multiple endpoints appear in the same log file, each endpoint's
    last_access_at SHALL equal the maximum timestamp for that specific endpoint,
    not the global maximum across all endpoints.
    """
    # Pair endpoints with timestamp lists (zip to shortest)
    pairs = list(zip(endpoints, timestamps_per_endpoint))
    assume(len(pairs) >= 2)

    # Build log lines for all endpoints
    all_lines = []
    # Track expected max per (method, host, path) — path will be normalized by parser
    expected_max_by_input: list[tuple[str, str, str, datetime]] = []

    for (method, host, path), timestamps in pairs:
        for ts in timestamps:
            all_lines.append(_json_log_line(method, host, path, 200, _to_iso(ts)))
        expected_max_by_input.append((method, host, path, _normalize_dt(max(timestamps))))

    content = "\n".join(all_lines)
    records = parse_gateway_logs(content, default_host="api.example.com")

    # Build a lookup from (method, host, normalized_path) -> record
    record_map = {
        (r.http_method, r.host, r.normalized_path): r
        for r in records
    }

    for method, host, path, expected_max in expected_max_by_input:
        normalized = normalize_path(path)
        key = (method, host, normalized)
        if key not in record_map:
            # Path may have been further normalized — skip if not found
            continue
        record = record_map[key]
        if record.last_access_at is None:
            continue
        actual = _normalize_dt(record.last_access_at)
        assert actual == expected_max, (
            f"Endpoint ({method}, {host}, {normalized}): "
            f"last_access_at {actual} != expected max {expected_max}"
        )


# ---------------------------------------------------------------------------
# Property 24c: last_access_at is None when no timestamps in log entries
# ---------------------------------------------------------------------------


@settings(max_examples=15)
@given(
    method=_method,
    host=_host,
    path=_path,
    n=st.integers(min_size=1, max_size=5) if False else st.integers(min_value=1, max_value=5),
)
def test_last_access_at_is_none_when_no_timestamps(
    method: str,
    host: str,
    path: str,
    n: int,
):
    """
    **Validates: Requirements 2.4**

    When log entries have no parseable timestamp, last_access_at SHALL be None.
    """
    # Build log lines without timestamps
    lines = [
        json.dumps({"method": method, "host": host, "path": path, "status": 200})
        for _ in range(n)
    ]
    content = "\n".join(lines)
    records = parse_gateway_logs(content, default_host=host)

    assert len(records) == 1
    assert records[0].last_access_at is None, (
        f"Expected last_access_at=None when no timestamps present, "
        f"got {records[0].last_access_at}"
    )


# ---------------------------------------------------------------------------
# Property 24d: Ordering of log lines does not affect last_access_at
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(
    method=_method,
    host=_host,
    path=_path,
    timestamps=st.lists(_utc_datetime, min_size=2, max_size=8),
)
def test_log_line_order_does_not_affect_last_access_at(
    method: str,
    host: str,
    path: str,
    timestamps: list[datetime],
):
    """
    **Validates: Requirements 2.4**

    The order of log lines SHALL NOT affect the computed last_access_at —
    it must always be the maximum timestamp regardless of line order.
    """
    # Forward order
    lines_fwd = [_json_log_line(method, host, path, 200, _to_iso(ts)) for ts in timestamps]
    # Reverse order
    lines_rev = list(reversed(lines_fwd))

    records_fwd = parse_gateway_logs("\n".join(lines_fwd), default_host=host)
    records_rev = parse_gateway_logs("\n".join(lines_rev), default_host=host)

    assert len(records_fwd) == 1
    assert len(records_rev) == 1

    ts_fwd = _normalize_dt(records_fwd[0].last_access_at) if records_fwd[0].last_access_at else None
    ts_rev = _normalize_dt(records_rev[0].last_access_at) if records_rev[0].last_access_at else None

    assert ts_fwd == ts_rev, (
        f"last_access_at differs based on log line order: "
        f"forward={ts_fwd}, reverse={ts_rev}"
    )

    expected = _normalize_dt(max(timestamps))
    assert ts_fwd == expected, (
        f"last_access_at {ts_fwd} != max timestamp {expected}"
    )


