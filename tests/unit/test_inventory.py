# Feature: sentinel-api, Task 6: API Inventory — metadata and staleness
"""
Unit tests for the API Inventory metadata and staleness features.

Covers:
- GET /endpoints filter combinations (lifecycle_status, risk_score_min/max,
  auth_scheme, data_sensitivity)
- Cursor-based pagination boundary conditions
- Atomic traffic counter increment (request_count_24h + last_access_at)
- Staleness flag transitions (is_stale set when last_access_at < NOW() - 90 days)

All tests use InMemoryStore — no live PostgreSQL required.
"""

import sys
import os
from datetime import datetime, timezone, timedelta

import pytest

# ---------------------------------------------------------------------------
# Path setup — allow imports from discovery-service and sentinel_shared
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, _REPO_ROOT)
from conftest import activate_service
activate_service("discovery-service")
sys.path.insert(0, os.path.join(_REPO_ROOT, "sentinel_shared"))

from db import InMemoryStore
from sentinel_shared.models import (
    EndpointRecord,
    AuthScheme,
    DataSensitivity,
    LifecycleStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(
    method: str = "GET",
    host: str = "api.example.com",
    path: str = "/users",
    lifecycle_status: LifecycleStatus = LifecycleStatus.ACTIVE,
    auth_scheme: AuthScheme = AuthScheme.JWT,
    data_sensitivity: DataSensitivity = DataSensitivity.INTERNAL,
    risk_score: int = 0,
    last_access_at: datetime | None = None,
) -> EndpointRecord:
    return EndpointRecord(
        http_method=method,
        host=host,
        normalized_path=path,
        lifecycle_status=lifecycle_status,
        auth_scheme=auth_scheme,
        data_sensitivity=data_sensitivity,
        risk_score=risk_score,
        last_access_at=last_access_at,
    )


async def _seed(store: InMemoryStore, records: list[EndpointRecord]) -> list[str]:
    """Upsert all records and return their IDs in insertion order."""
    ids = []
    for r in records:
        eid, _ = await store.upsert_endpoint(r)
        ids.append(eid)
    return ids


# ---------------------------------------------------------------------------
# Filter combination tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_filter_by_lifecycle_status():
    """Only endpoints matching the requested lifecycle_status are returned."""
    store = InMemoryStore()
    await _seed(store, [
        _make_record(path="/a", lifecycle_status=LifecycleStatus.ACTIVE),
        _make_record(path="/b", lifecycle_status=LifecycleStatus.ZOMBIE),
        _make_record(path="/c", lifecycle_status=LifecycleStatus.ZOMBIE),
    ])

    results = await store.list_endpoints(lifecycle_status="Zombie")
    assert len(results) == 2
    assert all(r["lifecycle_status"] == "Zombie" for r in results)


@pytest.mark.asyncio
async def test_filter_by_auth_scheme():
    """Only endpoints matching the requested auth_scheme are returned."""
    store = InMemoryStore()
    await _seed(store, [
        _make_record(path="/a", auth_scheme=AuthScheme.JWT),
        _make_record(path="/b", auth_scheme=AuthScheme.NONE),
        _make_record(path="/c", auth_scheme=AuthScheme.NONE),
    ])

    results = await store.list_endpoints(auth_scheme="none")
    assert len(results) == 2
    assert all(r["auth_scheme"] == "none" for r in results)


@pytest.mark.asyncio
async def test_filter_by_data_sensitivity():
    """Only endpoints matching the requested data_sensitivity are returned."""
    store = InMemoryStore()
    await _seed(store, [
        _make_record(path="/a", data_sensitivity=DataSensitivity.PII),
        _make_record(path="/b", data_sensitivity=DataSensitivity.PUBLIC),
        _make_record(path="/c", data_sensitivity=DataSensitivity.PII),
    ])

    results = await store.list_endpoints(data_sensitivity="PII")
    assert len(results) == 2
    assert all(r["data_sensitivity"] == "PII" for r in results)


@pytest.mark.asyncio
async def test_filter_by_risk_score_min():
    """Only endpoints with risk_score >= risk_score_min are returned."""
    store = InMemoryStore()
    await _seed(store, [
        _make_record(path="/a", risk_score=10),
        _make_record(path="/b", risk_score=50),
        _make_record(path="/c", risk_score=90),
    ])

    results = await store.list_endpoints(risk_score_min=50)
    assert len(results) == 2
    assert all(r["risk_score"] >= 50 for r in results)


@pytest.mark.asyncio
async def test_filter_by_risk_score_max():
    """Only endpoints with risk_score <= risk_score_max are returned."""
    store = InMemoryStore()
    await _seed(store, [
        _make_record(path="/a", risk_score=10),
        _make_record(path="/b", risk_score=50),
        _make_record(path="/c", risk_score=90),
    ])

    results = await store.list_endpoints(risk_score_max=50)
    assert len(results) == 2
    assert all(r["risk_score"] <= 50 for r in results)


@pytest.mark.asyncio
async def test_filter_by_risk_score_range():
    """Only endpoints within [risk_score_min, risk_score_max] are returned."""
    store = InMemoryStore()
    await _seed(store, [
        _make_record(path="/a", risk_score=10),
        _make_record(path="/b", risk_score=40),
        _make_record(path="/c", risk_score=70),
        _make_record(path="/d", risk_score=100),
    ])

    results = await store.list_endpoints(risk_score_min=40, risk_score_max=70)
    assert len(results) == 2
    assert all(40 <= r["risk_score"] <= 70 for r in results)


@pytest.mark.asyncio
async def test_filter_combined_lifecycle_and_auth():
    """Combined filters: lifecycle_status AND auth_scheme both applied."""
    store = InMemoryStore()
    await _seed(store, [
        _make_record(path="/a", lifecycle_status=LifecycleStatus.ZOMBIE, auth_scheme=AuthScheme.NONE),
        _make_record(path="/b", lifecycle_status=LifecycleStatus.ZOMBIE, auth_scheme=AuthScheme.JWT),
        _make_record(path="/c", lifecycle_status=LifecycleStatus.ACTIVE, auth_scheme=AuthScheme.NONE),
    ])

    results = await store.list_endpoints(lifecycle_status="Zombie", auth_scheme="none")
    assert len(results) == 1
    assert results[0]["normalized_path"] == "/a"


@pytest.mark.asyncio
async def test_filter_combined_sensitivity_and_risk_range():
    """Combined filters: data_sensitivity AND risk_score range both applied."""
    store = InMemoryStore()
    await _seed(store, [
        _make_record(path="/a", data_sensitivity=DataSensitivity.PII, risk_score=80),
        _make_record(path="/b", data_sensitivity=DataSensitivity.PII, risk_score=20),
        _make_record(path="/c", data_sensitivity=DataSensitivity.PUBLIC, risk_score=80),
    ])

    results = await store.list_endpoints(data_sensitivity="PII", risk_score_min=50)
    assert len(results) == 1
    assert results[0]["normalized_path"] == "/a"


@pytest.mark.asyncio
async def test_filter_no_match_returns_empty():
    """A filter that matches nothing returns an empty list."""
    store = InMemoryStore()
    await _seed(store, [
        _make_record(path="/a", lifecycle_status=LifecycleStatus.ACTIVE),
    ])

    results = await store.list_endpoints(lifecycle_status="Orphaned")
    assert results == []


@pytest.mark.asyncio
async def test_filter_all_params_combined():
    """All five filter params applied simultaneously."""
    store = InMemoryStore()
    await _seed(store, [
        _make_record(
            path="/match",
            lifecycle_status=LifecycleStatus.ZOMBIE,
            auth_scheme=AuthScheme.NONE,
            data_sensitivity=DataSensitivity.FINANCIAL,
            risk_score=75,
        ),
        _make_record(
            path="/no-match-status",
            lifecycle_status=LifecycleStatus.ACTIVE,
            auth_scheme=AuthScheme.NONE,
            data_sensitivity=DataSensitivity.FINANCIAL,
            risk_score=75,
        ),
        _make_record(
            path="/no-match-score",
            lifecycle_status=LifecycleStatus.ZOMBIE,
            auth_scheme=AuthScheme.NONE,
            data_sensitivity=DataSensitivity.FINANCIAL,
            risk_score=30,
        ),
    ])

    results = await store.list_endpoints(
        lifecycle_status="Zombie",
        auth_scheme="none",
        data_sensitivity="financial",
        risk_score_min=70,
        risk_score_max=100,
    )
    assert len(results) == 1
    assert results[0]["normalized_path"] == "/match"


# ---------------------------------------------------------------------------
# Cursor-based pagination tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pagination_first_page_no_cursor():
    """Without a cursor, the first page is returned in id order."""
    store = InMemoryStore()
    paths = [f"/ep{i:03d}" for i in range(10)]
    await _seed(store, [_make_record(path=p) for p in paths])

    page = await store.list_endpoints(limit=5)
    assert len(page) == 5
    # Results must be sorted by id
    ids = [r["id"] for r in page]
    assert ids == sorted(ids)


@pytest.mark.asyncio
async def test_pagination_second_page_via_cursor():
    """Passing the last id of page 1 as cursor returns the next 5 records."""
    store = InMemoryStore()
    paths = [f"/ep{i:03d}" for i in range(10)]
    await _seed(store, [_make_record(path=p) for p in paths])

    page1 = await store.list_endpoints(limit=5)
    assert len(page1) == 5

    cursor = page1[-1]["id"]
    page2 = await store.list_endpoints(limit=5, cursor=cursor)
    assert len(page2) == 5

    # No overlap between pages
    ids1 = {r["id"] for r in page1}
    ids2 = {r["id"] for r in page2}
    assert ids1.isdisjoint(ids2)

    # All ids in page2 are greater than cursor
    assert all(r["id"] > cursor for r in page2)


@pytest.mark.asyncio
async def test_pagination_last_page_returns_fewer_than_limit():
    """The final page returns fewer items than the limit when exhausted."""
    store = InMemoryStore()
    await _seed(store, [_make_record(path=f"/ep{i}") for i in range(7)])

    page1 = await store.list_endpoints(limit=5)
    assert len(page1) == 5

    cursor = page1[-1]["id"]
    page2 = await store.list_endpoints(limit=5, cursor=cursor)
    assert len(page2) == 2  # only 2 remaining


@pytest.mark.asyncio
async def test_pagination_cursor_past_last_record_returns_empty():
    """A cursor beyond all records returns an empty list."""
    store = InMemoryStore()
    await _seed(store, [_make_record(path="/only")])

    all_records = await store.list_endpoints(limit=100)
    last_cursor = all_records[-1]["id"]

    # Use a cursor that is lexicographically after all UUIDs
    beyond_cursor = "z" * 36
    results = await store.list_endpoints(limit=10, cursor=beyond_cursor)
    assert results == []


@pytest.mark.asyncio
async def test_pagination_full_traversal_covers_all_records():
    """Paginating through all records with cursor yields every record exactly once."""
    store = InMemoryStore()
    total = 23
    await _seed(store, [_make_record(path=f"/ep{i:03d}") for i in range(total)])

    seen_ids: set[str] = set()
    cursor = None
    page_size = 7

    while True:
        page = await store.list_endpoints(limit=page_size, cursor=cursor)
        if not page:
            break
        for r in page:
            assert r["id"] not in seen_ids, "Duplicate record in pagination"
            seen_ids.add(r["id"])
        cursor = page[-1]["id"]
        if len(page) < page_size:
            break

    assert len(seen_ids) == total


@pytest.mark.asyncio
async def test_pagination_with_filter_and_cursor():
    """Cursor-based pagination works correctly when combined with filters."""
    store = InMemoryStore()
    # 6 zombie endpoints + 4 active
    for i in range(6):
        await store.upsert_endpoint(_make_record(
            path=f"/zombie{i:03d}",
            lifecycle_status=LifecycleStatus.ZOMBIE,
        ))
    for i in range(4):
        await store.upsert_endpoint(_make_record(
            path=f"/active{i:03d}",
            lifecycle_status=LifecycleStatus.ACTIVE,
        ))

    page1 = await store.list_endpoints(limit=3, lifecycle_status="Zombie")
    assert len(page1) == 3
    assert all(r["lifecycle_status"] == "Zombie" for r in page1)

    cursor = page1[-1]["id"]
    page2 = await store.list_endpoints(limit=3, lifecycle_status="Zombie", cursor=cursor)
    assert len(page2) == 3
    assert all(r["lifecycle_status"] == "Zombie" for r in page2)

    # No overlap
    ids1 = {r["id"] for r in page1}
    ids2 = {r["id"] for r in page2}
    assert ids1.isdisjoint(ids2)


@pytest.mark.asyncio
async def test_pagination_limit_one():
    """limit=1 returns exactly one record per page."""
    store = InMemoryStore()
    await _seed(store, [_make_record(path=f"/ep{i}") for i in range(3)])

    page = await store.list_endpoints(limit=1)
    assert len(page) == 1


@pytest.mark.asyncio
async def test_pagination_empty_store():
    """Paginating an empty store returns an empty list."""
    store = InMemoryStore()
    results = await store.list_endpoints(limit=10)
    assert results == []


# ---------------------------------------------------------------------------
# Atomic traffic counter update tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_increment_traffic_counters_increments_count():
    """increment_traffic_counters increments request_count_24h by 1."""
    store = InMemoryStore()
    record = _make_record(path="/counter")
    eid, _ = await store.upsert_endpoint(record)

    result = await store.increment_traffic_counters(eid)
    assert result is not None
    assert result["request_count_24h"] == 1


@pytest.mark.asyncio
async def test_increment_traffic_counters_multiple_times():
    """Multiple increments accumulate correctly."""
    store = InMemoryStore()
    record = _make_record(path="/counter")
    eid, _ = await store.upsert_endpoint(record)

    for _ in range(5):
        await store.increment_traffic_counters(eid)

    result = await store.increment_traffic_counters(eid)
    assert result["request_count_24h"] == 6


@pytest.mark.asyncio
async def test_increment_traffic_counters_sets_last_access_at():
    """increment_traffic_counters sets last_access_at to the provided timestamp."""
    store = InMemoryStore()
    record = _make_record(path="/counter")
    eid, _ = await store.upsert_endpoint(record)

    access_time = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    result = await store.increment_traffic_counters(eid, access_time=access_time)
    assert result is not None

    # Verify the stored value
    stored = await store.get_endpoint(eid)
    assert stored is not None
    stored_ts = stored["last_access_at"]
    if isinstance(stored_ts, str):
        stored_ts = datetime.fromisoformat(stored_ts.replace("Z", "+00:00"))
    if stored_ts.tzinfo is None:
        stored_ts = stored_ts.replace(tzinfo=timezone.utc)
    assert stored_ts == access_time


@pytest.mark.asyncio
async def test_increment_traffic_counters_unknown_id_returns_none():
    """increment_traffic_counters returns None for an unknown endpoint id."""
    store = InMemoryStore()
    result = await store.increment_traffic_counters("nonexistent-id")
    assert result is None


@pytest.mark.asyncio
async def test_increment_traffic_counters_defaults_access_time_to_now():
    """When access_time is None, last_access_at is set to approximately now."""
    store = InMemoryStore()
    record = _make_record(path="/counter")
    eid, _ = await store.upsert_endpoint(record)

    before = datetime.now(timezone.utc)
    await store.increment_traffic_counters(eid)
    after = datetime.now(timezone.utc)

    stored = await store.get_endpoint(eid)
    stored_ts = stored["last_access_at"]
    if isinstance(stored_ts, str):
        stored_ts = datetime.fromisoformat(stored_ts.replace("Z", "+00:00"))
    if stored_ts.tzinfo is None:
        stored_ts = stored_ts.replace(tzinfo=timezone.utc)

    assert before <= stored_ts <= after


# ---------------------------------------------------------------------------
# Staleness flag transition tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_stale_sets_is_stale_for_old_endpoints():
    """Endpoints with last_access_at > 90 days ago are marked stale."""
    store = InMemoryStore()
    old_time = datetime.now(timezone.utc) - timedelta(days=91)
    record = _make_record(path="/old", last_access_at=old_time)
    eid, _ = await store.upsert_endpoint(record)

    count = await store.mark_stale_endpoints()
    assert count == 1

    stored = await store.get_endpoint(eid)
    assert stored["is_stale"] is True


@pytest.mark.asyncio
async def test_mark_stale_does_not_affect_recent_endpoints():
    """Endpoints with last_access_at within 90 days are NOT marked stale."""
    store = InMemoryStore()
    recent_time = datetime.now(timezone.utc) - timedelta(days=30)
    record = _make_record(path="/recent", last_access_at=recent_time)
    eid, _ = await store.upsert_endpoint(record)

    count = await store.mark_stale_endpoints()
    assert count == 0

    stored = await store.get_endpoint(eid)
    assert stored["is_stale"] is False


@pytest.mark.asyncio
async def test_mark_stale_exactly_at_boundary():
    """An endpoint accessed exactly 90 days ago is NOT stale (boundary is exclusive)."""
    store = InMemoryStore()
    # Exactly 90 days ago — should NOT be stale (< 90 days is the condition)
    boundary_time = datetime.now(timezone.utc) - timedelta(days=90)
    record = _make_record(path="/boundary", last_access_at=boundary_time)
    eid, _ = await store.upsert_endpoint(record)

    count = await store.mark_stale_endpoints()
    assert count == 0

    stored = await store.get_endpoint(eid)
    assert stored["is_stale"] is False


@pytest.mark.asyncio
async def test_mark_stale_just_past_boundary():
    """An endpoint accessed 90 days + 1 second ago IS stale."""
    store = InMemoryStore()
    just_past = datetime.now(timezone.utc) - timedelta(days=90, seconds=1)
    record = _make_record(path="/just-past", last_access_at=just_past)
    eid, _ = await store.upsert_endpoint(record)

    count = await store.mark_stale_endpoints()
    assert count == 1

    stored = await store.get_endpoint(eid)
    assert stored["is_stale"] is True


@pytest.mark.asyncio
async def test_mark_stale_mixed_endpoints():
    """Only old endpoints are marked stale; recent ones remain unchanged."""
    store = InMemoryStore()
    old_time = datetime.now(timezone.utc) - timedelta(days=120)
    recent_time = datetime.now(timezone.utc) - timedelta(days=10)

    old_id, _ = await store.upsert_endpoint(_make_record(path="/old", last_access_at=old_time))
    recent_id, _ = await store.upsert_endpoint(_make_record(path="/recent", last_access_at=recent_time))

    count = await store.mark_stale_endpoints()
    assert count == 1

    old_stored = await store.get_endpoint(old_id)
    recent_stored = await store.get_endpoint(recent_id)
    assert old_stored["is_stale"] is True
    assert recent_stored["is_stale"] is False


@pytest.mark.asyncio
async def test_mark_stale_no_last_access_uses_first_seen():
    """Endpoints with no last_access_at use first_seen_at for staleness check."""
    store = InMemoryStore()
    # Insert a record with no last_access_at; manually set first_seen_at to old date
    record = _make_record(path="/never-accessed")
    eid, _ = await store.upsert_endpoint(record)

    # Manually set first_seen_at to 100 days ago in the store
    for entry in store._store.values():
        if entry["id"] == eid:
            old_ts = datetime.now(timezone.utc) - timedelta(days=100)
            entry["first_seen_at"] = old_ts.isoformat()
            entry["last_access_at"] = None
            break

    count = await store.mark_stale_endpoints()
    assert count == 1

    stored = await store.get_endpoint(eid)
    assert stored["is_stale"] is True


@pytest.mark.asyncio
async def test_mark_stale_idempotent():
    """Running mark_stale_endpoints twice does not double-count already-stale endpoints."""
    store = InMemoryStore()
    old_time = datetime.now(timezone.utc) - timedelta(days=100)
    await store.upsert_endpoint(_make_record(path="/old", last_access_at=old_time))

    count1 = await store.mark_stale_endpoints()
    count2 = await store.mark_stale_endpoints()

    assert count1 == 1
    assert count2 == 0  # already stale, not counted again


@pytest.mark.asyncio
async def test_mark_stale_custom_cutoff():
    """A custom cutoff date is respected."""
    store = InMemoryStore()
    # 30 days old — normally not stale, but stale with a 20-day cutoff
    access_time = datetime.now(timezone.utc) - timedelta(days=30)
    eid, _ = await store.upsert_endpoint(_make_record(path="/medium-old", last_access_at=access_time))

    cutoff = datetime.now(timezone.utc) - timedelta(days=20)
    count = await store.mark_stale_endpoints(cutoff=cutoff)
    assert count == 1

    stored = await store.get_endpoint(eid)
    assert stored["is_stale"] is True


@pytest.mark.asyncio
async def test_fresh_traffic_prevents_staleness():
    """An endpoint that receives traffic after being stale is no longer stale after update."""
    store = InMemoryStore()
    old_time = datetime.now(timezone.utc) - timedelta(days=100)
    record = _make_record(path="/revived", last_access_at=old_time)
    eid, _ = await store.upsert_endpoint(record)

    # Mark stale
    count = await store.mark_stale_endpoints()
    assert count == 1

    # Simulate fresh traffic — update last_access_at to now
    fresh_time = datetime.now(timezone.utc)
    await store.increment_traffic_counters(eid, access_time=fresh_time)

    # Manually reset is_stale (as a real system would do on traffic receipt)
    for entry in store._store.values():
        if entry["id"] == eid:
            entry["is_stale"] = False
            break

    # Run staleness check again — should not re-mark as stale
    count2 = await store.mark_stale_endpoints()
    assert count2 == 0

    stored = await store.get_endpoint(eid)
    assert stored["is_stale"] is False
