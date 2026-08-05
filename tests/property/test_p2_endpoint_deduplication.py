# Feature: sentinel-api, Property 2: Endpoint Deduplication and Upsert Idempotence
"""
Property-based tests for Property 2: Endpoint Deduplication and Upsert Idempotence.

For any sequence of EndpointRecord upserts (including re-ingestion of the same
record with updated metadata), the API Inventory SHALL contain exactly one record
per unique (http_method, host, normalized_path) triple, and the record's metadata
SHALL reflect the most recently ingested values.

**Validates: Requirements 1.4, 1.5**
"""

import asyncio
import sys
import os

from hypothesis import given, settings
from hypothesis import strategies as st

_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, _REPO_ROOT)
from conftest import activate_service
activate_service("discovery-service")
sys.path.insert(0, os.path.join(_REPO_ROOT, "sentinel_shared"))

from db import InMemoryStore
from sentinel_shared.models import EndpointRecord, AuthScheme, DataSensitivity

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

HTTP_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH"]

_segment = st.from_regex(r"[a-zA-Z][a-zA-Z0-9_]{0,10}", fullmatch=True)
_path = st.lists(_segment, min_size=1, max_size=3).map(lambda s: "/" + "/".join(s))
_host = st.from_regex(r"[a-zA-Z][a-zA-Z0-9\-]{0,15}\.example\.com", fullmatch=True)
_method = st.sampled_from(HTTP_METHODS)

_meta_key = st.from_regex(r"[a-zA-Z][a-zA-Z0-9_]{0,10}", fullmatch=True)
_meta_val = st.one_of(st.text(max_size=20), st.integers(min_value=0, max_value=999))
_metadata = st.dictionaries(_meta_key, _meta_val, max_size=4)


def endpoint_record_strategy() -> st.SearchStrategy[EndpointRecord]:
    """Generate arbitrary EndpointRecord instances."""
    return st.builds(
        EndpointRecord,
        http_method=_method,
        host=_host,
        normalized_path=_path,
        auth_scheme=st.sampled_from(list(AuthScheme)),
        data_sensitivity=st.sampled_from(list(DataSensitivity)),
        metadata=_metadata,
    )


def _run(coro):
    """Run a coroutine synchronously (Hypothesis doesn't support async natively)."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Property 2a: Exactly one record per unique dedup key after any upsert sequence
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(records=st.lists(endpoint_record_strategy(), min_size=1, max_size=10))
def test_exactly_one_record_per_dedup_key(records: list[EndpointRecord]):
    """
    **Validates: Requirements 1.4, 1.5**

    After upserting any sequence of EndpointRecords, the store SHALL contain
    exactly one entry per unique (http_method, host, normalized_path) triple.
    """
    store = InMemoryStore()

    async def run():
        for record in records:
            await store.upsert_endpoint(record)
        return await store.list_endpoints(limit=10_000)

    stored = _run(run())

    # Compute expected unique keys
    unique_keys = {
        (r.http_method, r.host, r.normalized_path)
        for r in records
    }

    assert len(stored) == len(unique_keys), (
        f"Expected {len(unique_keys)} unique records, got {len(stored)}.\n"
        f"Input records: {[(r.http_method, r.host, r.normalized_path) for r in records]}\n"
        f"Stored: {[(s['http_method'], s['host'], s['normalized_path']) for s in stored]}"
    )


# ---------------------------------------------------------------------------
# Property 2b: Re-upserting the same record is idempotent
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(record=endpoint_record_strategy(), n=st.integers(min_value=2, max_value=5))
def test_repeated_upsert_is_idempotent(record: EndpointRecord, n: int):
    """
    **Validates: Requirements 1.4, 1.5**

    Upserting the same EndpointRecord N times SHALL result in exactly one
    record in the store (idempotence).
    """
    store = InMemoryStore()

    async def run():
        for _ in range(n):
            await store.upsert_endpoint(record)
        return await store.list_endpoints(limit=10_000)

    stored = _run(run())
    assert len(stored) == 1, (
        f"Expected 1 record after {n} upserts of the same record, got {len(stored)}"
    )


# ---------------------------------------------------------------------------
# Property 2c: Metadata reflects the most recently ingested values
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(
    base=endpoint_record_strategy(),
    meta_v1=_metadata,
    meta_v2=_metadata,
)
def test_metadata_reflects_latest_ingested_values(
    base: EndpointRecord,
    meta_v1: dict,
    meta_v2: dict,
):
    """
    **Validates: Requirements 1.4, 1.5**

    When the same endpoint is ingested twice with different metadata, the stored
    record's metadata SHALL reflect the most recently ingested values (merge with
    new values overriding old ones).
    """
    store = InMemoryStore()

    r1 = EndpointRecord(
        http_method=base.http_method,
        host=base.host,
        normalized_path=base.normalized_path,
        metadata=meta_v1,
    )
    r2 = EndpointRecord(
        http_method=base.http_method,
        host=base.host,
        normalized_path=base.normalized_path,
        metadata=meta_v2,
    )

    async def run():
        await store.upsert_endpoint(r1)
        await store.upsert_endpoint(r2)
        results = await store.list_endpoints(limit=10_000)
        return results

    stored = _run(run())
    assert len(stored) == 1

    stored_meta = stored[0]["metadata"]
    # All keys from meta_v2 must be present with their v2 values
    for key, value in meta_v2.items():
        assert stored_meta.get(key) == value, (
            f"Key '{key}' in stored metadata has value {stored_meta.get(key)!r}, "
            f"expected {value!r} (from latest ingestion)"
        )


# ---------------------------------------------------------------------------
# Property 2d: was_inserted flag is correct
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(record=endpoint_record_strategy())
def test_was_inserted_flag_correct(record: EndpointRecord):
    """
    **Validates: Requirements 1.4, 1.5**

    The first upsert of a record SHALL return was_inserted=True.
    All subsequent upserts of the same dedup key SHALL return was_inserted=False.
    """
    store = InMemoryStore()

    async def run():
        _, first_inserted = await store.upsert_endpoint(record)
        _, second_inserted = await store.upsert_endpoint(record)
        return first_inserted, second_inserted

    first_inserted, second_inserted = _run(run())

    assert first_inserted is True, "First upsert must return was_inserted=True"
    assert second_inserted is False, "Second upsert of same key must return was_inserted=False"

