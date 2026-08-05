# Feature: sentinel-api, Property 25: Staleness Flag Correctness
"""
Property-based tests for Property 25: Staleness Flag Correctness.

For any endpoint record, `is_stale` SHALL be `true` if and only if
`last_access_at` is more than 90 days before the current evaluation time
(or `last_access_at` is null and `first_seen_at` is more than 90 days ago).

**Validates: Requirements 4.4**
"""

import asyncio
import sys
import os
from datetime import datetime, timezone, timedelta

from hypothesis import given, settings, assume
from hypothesis import strategies as st

_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, _REPO_ROOT)
from conftest import activate_service
activate_service("discovery-service")
sys.path.insert(0, os.path.join(_REPO_ROOT, "sentinel_shared"))

from db import InMemoryStore
from sentinel_shared.models import EndpointRecord, AuthScheme, DataSensitivity, LifecycleStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STALE_THRESHOLD_DAYS = 90

# Evaluation "now" pinned for each test run so comparisons are consistent.
# Use naive datetimes for Hypothesis bounds; timezone is applied via the
# timezones= parameter (Hypothesis requires naive min/max values).
_NOW_NAIVE = datetime(2024, 6, 15, 12, 0, 0)
_CUTOFF_NAIVE = _NOW_NAIVE - timedelta(days=_STALE_THRESHOLD_DAYS)

# Aware versions used for actual comparisons in test assertions.
_NOW = _NOW_NAIVE.replace(tzinfo=timezone.utc)
_CUTOFF = _CUTOFF_NAIVE.replace(tzinfo=timezone.utc)

# Strategies for last_access_at timestamps
# "stale" = strictly before the 90-day cutoff
_stale_ts = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=_CUTOFF_NAIVE - timedelta(seconds=1),
    timezones=st.just(timezone.utc),
)

# "fresh" = at or after the 90-day cutoff (not stale)
_fresh_ts = st.datetimes(
    min_value=_CUTOFF_NAIVE,
    max_value=_NOW_NAIVE,
    timezones=st.just(timezone.utc),
)

_segment = st.from_regex(r"[a-zA-Z][a-zA-Z0-9_]{0,10}", fullmatch=True)
_path = st.lists(_segment, min_size=1, max_size=2).map(lambda s: "/" + "/".join(s))
_host = st.from_regex(r"[a-zA-Z][a-zA-Z0-9\-]{0,15}\.example\.com", fullmatch=True)
_method = st.sampled_from(["GET", "POST", "PUT", "DELETE", "PATCH"])


def _make_record(
    method: str,
    host: str,
    path: str,
    last_access_at: datetime | None,
) -> EndpointRecord:
    return EndpointRecord(
        http_method=method,
        host=host,
        normalized_path=path,
        last_access_at=last_access_at,
    )


def _run(coro):
    """Run a coroutine synchronously (Hypothesis doesn't support async natively)."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Property 25a: Endpoints with last_access_at > 90 days ago are marked stale
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(
    method=_method,
    host=_host,
    path=_path,
    last_access_at=_stale_ts,
)
def test_stale_when_last_access_older_than_90_days(
    method: str,
    host: str,
    path: str,
    last_access_at: datetime,
):
    """
    **Validates: Requirements 4.4**

    When last_access_at is more than 90 days before the evaluation time,
    mark_stale_endpoints() SHALL set is_stale=True for that endpoint.
    """
    store = InMemoryStore()
    record = _make_record(method, host, path, last_access_at)

    async def run():
        await store.upsert_endpoint(record)
        await store.mark_stale_endpoints(cutoff=_CUTOFF)
        results = await store.list_endpoints(limit=1000)
        return results

    stored = _run(run())
    assert len(stored) == 1

    entry = stored[0]
    assert entry["is_stale"] is True, (
        f"Expected is_stale=True for last_access_at={last_access_at.isoformat()} "
        f"(cutoff={_CUTOFF.isoformat()}), but got is_stale={entry['is_stale']}"
    )


# ---------------------------------------------------------------------------
# Property 25b: Endpoints with last_access_at within 90 days are NOT stale
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(
    method=_method,
    host=_host,
    path=_path,
    last_access_at=_fresh_ts,
)
def test_not_stale_when_last_access_within_90_days(
    method: str,
    host: str,
    path: str,
    last_access_at: datetime,
):
    """
    **Validates: Requirements 4.4**

    When last_access_at is at or after the 90-day cutoff,
    mark_stale_endpoints() SHALL NOT set is_stale=True for that endpoint.
    """
    store = InMemoryStore()
    record = _make_record(method, host, path, last_access_at)

    async def run():
        await store.upsert_endpoint(record)
        await store.mark_stale_endpoints(cutoff=_CUTOFF)
        results = await store.list_endpoints(limit=1000)
        return results

    stored = _run(run())
    assert len(stored) == 1

    entry = stored[0]
    assert entry["is_stale"] is False, (
        f"Expected is_stale=False for last_access_at={last_access_at.isoformat()} "
        f"(cutoff={_CUTOFF.isoformat()}), but got is_stale={entry['is_stale']}"
    )


# ---------------------------------------------------------------------------
# Property 25c: is_stale is True iff last_access_at < cutoff (biconditional)
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(
    method=_method,
    host=_host,
    path=_path,
    last_access_at=st.one_of(_stale_ts, _fresh_ts),
)
def test_is_stale_iff_last_access_before_cutoff(
    method: str,
    host: str,
    path: str,
    last_access_at: datetime,
):
    """
    **Validates: Requirements 4.4**

    is_stale SHALL be True if and only if last_access_at < cutoff.
    This tests the biconditional: both directions of the implication.
    """
    store = InMemoryStore()
    record = _make_record(method, host, path, last_access_at)

    async def run():
        await store.upsert_endpoint(record)
        await store.mark_stale_endpoints(cutoff=_CUTOFF)
        results = await store.list_endpoints(limit=1000)
        return results

    stored = _run(run())
    assert len(stored) == 1

    entry = stored[0]
    expected_stale = last_access_at < _CUTOFF

    assert entry["is_stale"] == expected_stale, (
        f"is_stale={entry['is_stale']} but expected {expected_stale} "
        f"for last_access_at={last_access_at.isoformat()}, cutoff={_CUTOFF.isoformat()}"
    )


# ---------------------------------------------------------------------------
# Property 25d: Mixed batch — each endpoint's staleness is independently correct
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(
    endpoints=st.lists(
        st.tuples(
            _method,
            _host,
            _path,
            st.one_of(_stale_ts, _fresh_ts),
        ),
        min_size=2,
        max_size=8,
    ),
)
def test_mixed_batch_staleness_is_independent(
    endpoints: list[tuple[str, str, str, datetime]],
):
    """
    **Validates: Requirements 4.4**

    When a batch of endpoints with mixed last_access_at values is processed,
    each endpoint's is_stale flag SHALL be set independently and correctly.
    """
    # Deduplicate by (method, host, path) — keep last occurrence
    seen: dict[tuple[str, str, str], datetime] = {}
    for method, host, path, ts in endpoints:
        seen[(method, host, path)] = ts

    assume(len(seen) >= 2)

    store = InMemoryStore()

    async def run():
        for (method, host, path), ts in seen.items():
            record = _make_record(method, host, path, ts)
            await store.upsert_endpoint(record)
        await store.mark_stale_endpoints(cutoff=_CUTOFF)
        return await store.list_endpoints(limit=1000)

    stored = _run(run())
    assert len(stored) == len(seen)

    # Build lookup from (method, host, normalized_path) -> stored entry
    stored_map = {
        (e["http_method"], e["host"], e["normalized_path"]): e
        for e in stored
    }

    for (method, host, path), ts in seen.items():
        entry = stored_map.get((method, host, path))
        assert entry is not None, f"Endpoint ({method}, {host}, {path}) not found in store"

        expected_stale = ts < _CUTOFF
        assert entry["is_stale"] == expected_stale, (
            f"Endpoint ({method}, {host}, {path}): "
            f"is_stale={entry['is_stale']} but expected {expected_stale} "
            f"for last_access_at={ts.isoformat()}"
        )


# ---------------------------------------------------------------------------
# Property 25e: mark_stale_endpoints is idempotent
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(
    method=_method,
    host=_host,
    path=_path,
    last_access_at=_stale_ts,
)
def test_mark_stale_is_idempotent(
    method: str,
    host: str,
    path: str,
    last_access_at: datetime,
):
    """
    **Validates: Requirements 4.4**

    Calling mark_stale_endpoints() multiple times SHALL produce the same
    result as calling it once — the operation is idempotent.
    """
    store = InMemoryStore()
    record = _make_record(method, host, path, last_access_at)

    async def run():
        await store.upsert_endpoint(record)
        count1 = await store.mark_stale_endpoints(cutoff=_CUTOFF)
        count2 = await store.mark_stale_endpoints(cutoff=_CUTOFF)
        results = await store.list_endpoints(limit=1000)
        return count1, count2, results

    count1, count2, stored = _run(run())

    # First call should mark 1 endpoint stale
    assert count1 == 1, f"Expected 1 newly stale endpoint on first call, got {count1}"
    # Second call should mark 0 (already stale)
    assert count2 == 0, f"Expected 0 newly stale endpoints on second call, got {count2}"

    assert len(stored) == 1
    assert stored[0]["is_stale"] is True


# ---------------------------------------------------------------------------
# Property 25f: Boundary condition — exactly at the cutoff is NOT stale
# ---------------------------------------------------------------------------


@settings(max_examples=15)
@given(
    method=_method,
    host=_host,
    path=_path,
)
def test_exactly_at_cutoff_is_not_stale(
    method: str,
    host: str,
    path: str,
):
    """
    **Validates: Requirements 4.4**

    An endpoint whose last_access_at equals exactly the cutoff timestamp
    SHALL NOT be marked stale (the condition is strictly less-than).
    """
    store = InMemoryStore()
    # last_access_at == cutoff exactly
    record = _make_record(method, host, path, _CUTOFF)

    async def run():
        await store.upsert_endpoint(record)
        await store.mark_stale_endpoints(cutoff=_CUTOFF)
        results = await store.list_endpoints(limit=1000)
        return results

    stored = _run(run())
    assert len(stored) == 1

    entry = stored[0]
    assert entry["is_stale"] is False, (
        f"Expected is_stale=False when last_access_at == cutoff exactly, "
        f"but got is_stale={entry['is_stale']}"
    )


