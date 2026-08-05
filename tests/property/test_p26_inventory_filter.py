# Feature: sentinel-api, Property 26: Inventory Filter Correctness
"""
Property-based tests for Property 26: Inventory Filter Correctness.

For any combination of filter parameters (lifecycle_status, risk_score_min,
risk_score_max, auth_scheme, data_sensitivity), the list_endpoints() result
SHALL contain exactly those endpoints that satisfy ALL the specified filter
conditions — no more, no fewer.

**Validates: Requirements 4.5**
"""

import asyncio
import sys
import os
from typing import Optional

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
# Strategies
# ---------------------------------------------------------------------------

_segment = st.from_regex(r"[a-zA-Z][a-zA-Z0-9_]{0,10}", fullmatch=True)
_path = st.lists(_segment, min_size=1, max_size=3).map(lambda s: "/" + "/".join(s))
_host = st.from_regex(r"[a-zA-Z][a-zA-Z0-9\-]{0,15}\.example\.com", fullmatch=True)
_method = st.sampled_from(["GET", "POST", "PUT", "DELETE", "PATCH"])
_auth_scheme = st.sampled_from(list(AuthScheme))
_data_sensitivity = st.sampled_from(list(DataSensitivity))
_lifecycle_status = st.sampled_from(list(LifecycleStatus))
_risk_score = st.integers(min_value=0, max_value=100)

_endpoint_attrs = st.fixed_dictionaries({
    "method": _method,
    "host": _host,
    "path": _path,
    "auth_scheme": _auth_scheme,
    "data_sensitivity": _data_sensitivity,
    "lifecycle_status": _lifecycle_status,
    "risk_score": _risk_score,
})

# Optional filter strategies — None means "no filter applied"
_opt_lifecycle = st.one_of(st.none(), _lifecycle_status)
_opt_auth = st.one_of(st.none(), _auth_scheme)
_opt_sensitivity = st.one_of(st.none(), _data_sensitivity)
_opt_score = st.one_of(st.none(), _risk_score)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(attrs: dict) -> EndpointRecord:
    return EndpointRecord(
        http_method=attrs["method"],
        host=attrs["host"],
        normalized_path=attrs["path"],
        auth_scheme=attrs["auth_scheme"],
        data_sensitivity=attrs["data_sensitivity"],
        lifecycle_status=attrs["lifecycle_status"],
        risk_score=attrs["risk_score"],
    )


def _naive_filter(
    entries: list[dict],
    lifecycle_status: Optional[LifecycleStatus],
    auth_scheme: Optional[AuthScheme],
    data_sensitivity: Optional[DataSensitivity],
    risk_score_min: Optional[int],
    risk_score_max: Optional[int],
) -> list[dict]:
    """Reference implementation: plain Python filter matching InMemoryStore logic."""
    result = list(entries)
    if lifecycle_status is not None:
        ls_val = lifecycle_status.value if isinstance(lifecycle_status, LifecycleStatus) else lifecycle_status
        result = [r for r in result if r["lifecycle_status"] == ls_val]
    if auth_scheme is not None:
        as_val = auth_scheme.value if isinstance(auth_scheme, AuthScheme) else auth_scheme
        result = [r for r in result if r["auth_scheme"] == as_val]
    if data_sensitivity is not None:
        ds_val = data_sensitivity.value if isinstance(data_sensitivity, DataSensitivity) else data_sensitivity
        result = [r for r in result if r["data_sensitivity"] == ds_val]
    if risk_score_min is not None:
        result = [r for r in result if r["risk_score"] >= risk_score_min]
    if risk_score_max is not None:
        result = [r for r in result if r["risk_score"] <= risk_score_max]
    return result


def _run(coro):
    """Run a coroutine synchronously (Hypothesis doesn't support async natively)."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _ids(entries: list[dict]) -> set[str]:
    return {e["id"] for e in entries}


# ---------------------------------------------------------------------------
# Property 26a: Single filter — lifecycle_status
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(
    endpoint_list=st.lists(_endpoint_attrs, min_size=1, max_size=10),
    filter_status=_lifecycle_status,
)
def test_filter_by_lifecycle_status(
    endpoint_list: list[dict],
    filter_status: LifecycleStatus,
):
    """
    **Validates: Requirements 4.5**

    list_endpoints(lifecycle_status=X) SHALL return exactly those endpoints
    whose lifecycle_status equals X.
    """
    # Deduplicate by (method, host, path) — keep last occurrence
    seen: dict[tuple, dict] = {}
    for attrs in endpoint_list:
        key = (attrs["method"], attrs["host"], attrs["path"])
        seen[key] = attrs

    store = InMemoryStore()

    async def run():
        for attrs in seen.values():
            await store.upsert_endpoint(_make_record(attrs))
        all_entries = await store.list_endpoints(limit=1000)
        filtered = await store.list_endpoints(
            limit=1000,
            lifecycle_status=filter_status.value,
        )
        return all_entries, filtered

    all_entries, filtered = _run(run())

    expected = _naive_filter(
        all_entries,
        lifecycle_status=filter_status,
        auth_scheme=None,
        data_sensitivity=None,
        risk_score_min=None,
        risk_score_max=None,
    )

    assert _ids(filtered) == _ids(expected), (
        f"lifecycle_status filter '{filter_status.value}': "
        f"got {_ids(filtered)}, expected {_ids(expected)}"
    )


# ---------------------------------------------------------------------------
# Property 26b: Single filter — auth_scheme
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(
    endpoint_list=st.lists(_endpoint_attrs, min_size=1, max_size=10),
    filter_auth=_auth_scheme,
)
def test_filter_by_auth_scheme(
    endpoint_list: list[dict],
    filter_auth: AuthScheme,
):
    """
    **Validates: Requirements 4.5**

    list_endpoints(auth_scheme=X) SHALL return exactly those endpoints
    whose auth_scheme equals X.
    """
    seen: dict[tuple, dict] = {}
    for attrs in endpoint_list:
        key = (attrs["method"], attrs["host"], attrs["path"])
        seen[key] = attrs

    store = InMemoryStore()

    async def run():
        for attrs in seen.values():
            await store.upsert_endpoint(_make_record(attrs))
        all_entries = await store.list_endpoints(limit=1000)
        filtered = await store.list_endpoints(
            limit=1000,
            auth_scheme=filter_auth.value,
        )
        return all_entries, filtered

    all_entries, filtered = _run(run())

    expected = _naive_filter(
        all_entries,
        lifecycle_status=None,
        auth_scheme=filter_auth,
        data_sensitivity=None,
        risk_score_min=None,
        risk_score_max=None,
    )

    assert _ids(filtered) == _ids(expected), (
        f"auth_scheme filter '{filter_auth.value}': "
        f"got {_ids(filtered)}, expected {_ids(expected)}"
    )


# ---------------------------------------------------------------------------
# Property 26c: Single filter — data_sensitivity
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(
    endpoint_list=st.lists(_endpoint_attrs, min_size=1, max_size=10),
    filter_sensitivity=_data_sensitivity,
)
def test_filter_by_data_sensitivity(
    endpoint_list: list[dict],
    filter_sensitivity: DataSensitivity,
):
    """
    **Validates: Requirements 4.5**

    list_endpoints(data_sensitivity=X) SHALL return exactly those endpoints
    whose data_sensitivity equals X.
    """
    seen: dict[tuple, dict] = {}
    for attrs in endpoint_list:
        key = (attrs["method"], attrs["host"], attrs["path"])
        seen[key] = attrs

    store = InMemoryStore()

    async def run():
        for attrs in seen.values():
            await store.upsert_endpoint(_make_record(attrs))
        all_entries = await store.list_endpoints(limit=1000)
        filtered = await store.list_endpoints(
            limit=1000,
            data_sensitivity=filter_sensitivity.value,
        )
        return all_entries, filtered

    all_entries, filtered = _run(run())

    expected = _naive_filter(
        all_entries,
        lifecycle_status=None,
        auth_scheme=None,
        data_sensitivity=filter_sensitivity,
        risk_score_min=None,
        risk_score_max=None,
    )

    assert _ids(filtered) == _ids(expected), (
        f"data_sensitivity filter '{filter_sensitivity.value}': "
        f"got {_ids(filtered)}, expected {_ids(expected)}"
    )


# ---------------------------------------------------------------------------
# Property 26d: Risk score range filter
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(
    endpoint_list=st.lists(_endpoint_attrs, min_size=1, max_size=10),
    score_bounds=st.tuples(_risk_score, _risk_score).map(
        lambda t: (min(t), max(t))
    ),
)
def test_filter_by_risk_score_range(
    endpoint_list: list[dict],
    score_bounds: tuple[int, int],
):
    """
    **Validates: Requirements 4.5**

    list_endpoints(risk_score_min=lo, risk_score_max=hi) SHALL return exactly
    those endpoints whose risk_score is in [lo, hi] (inclusive on both ends).
    """
    risk_score_min, risk_score_max = score_bounds

    seen: dict[tuple, dict] = {}
    for attrs in endpoint_list:
        key = (attrs["method"], attrs["host"], attrs["path"])
        seen[key] = attrs

    store = InMemoryStore()

    async def run():
        for attrs in seen.values():
            await store.upsert_endpoint(_make_record(attrs))
        all_entries = await store.list_endpoints(limit=1000)
        filtered = await store.list_endpoints(
            limit=1000,
            risk_score_min=risk_score_min,
            risk_score_max=risk_score_max,
        )
        return all_entries, filtered

    all_entries, filtered = _run(run())

    expected = _naive_filter(
        all_entries,
        lifecycle_status=None,
        auth_scheme=None,
        data_sensitivity=None,
        risk_score_min=risk_score_min,
        risk_score_max=risk_score_max,
    )

    assert _ids(filtered) == _ids(expected), (
        f"risk_score range [{risk_score_min}, {risk_score_max}]: "
        f"got {_ids(filtered)}, expected {_ids(expected)}"
    )


# ---------------------------------------------------------------------------
# Property 26e: Combined filters — all five parameters simultaneously
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(
    endpoint_list=st.lists(_endpoint_attrs, min_size=1, max_size=15),
    filter_status=_opt_lifecycle,
    filter_auth=_opt_auth,
    filter_sensitivity=_opt_sensitivity,
    score_min=_opt_score,
    score_max=_opt_score,
)
def test_combined_filters_exact_match(
    endpoint_list: list[dict],
    filter_status: Optional[LifecycleStatus],
    filter_auth: Optional[AuthScheme],
    filter_sensitivity: Optional[DataSensitivity],
    score_min: Optional[int],
    score_max: Optional[int],
):
    """
    **Validates: Requirements 4.5**

    For any combination of filter parameters, list_endpoints() SHALL return
    exactly those endpoints satisfying ALL specified conditions simultaneously —
    no more, no fewer.
    """
    # Normalize score range so min <= max when both are set
    if score_min is not None and score_max is not None:
        score_min, score_max = min(score_min, score_max), max(score_min, score_max)

    # Deduplicate by (method, host, path)
    seen: dict[tuple, dict] = {}
    for attrs in endpoint_list:
        key = (attrs["method"], attrs["host"], attrs["path"])
        seen[key] = attrs

    store = InMemoryStore()

    async def run():
        for attrs in seen.values():
            await store.upsert_endpoint(_make_record(attrs))
        all_entries = await store.list_endpoints(limit=1000)
        filtered = await store.list_endpoints(
            limit=1000,
            lifecycle_status=filter_status.value if filter_status is not None else None,
            auth_scheme=filter_auth.value if filter_auth is not None else None,
            data_sensitivity=filter_sensitivity.value if filter_sensitivity is not None else None,
            risk_score_min=score_min,
            risk_score_max=score_max,
        )
        return all_entries, filtered

    all_entries, filtered = _run(run())

    expected = _naive_filter(
        all_entries,
        lifecycle_status=filter_status,
        auth_scheme=filter_auth,
        data_sensitivity=filter_sensitivity,
        risk_score_min=score_min,
        risk_score_max=score_max,
    )

    assert _ids(filtered) == _ids(expected), (
        f"Combined filters "
        f"(lifecycle={filter_status}, auth={filter_auth}, "
        f"sensitivity={filter_sensitivity}, "
        f"score_min={score_min}, score_max={score_max}): "
        f"got {len(filtered)} results, expected {len(expected)}"
    )


# ---------------------------------------------------------------------------
# Property 26f: No false positives — every returned endpoint satisfies filters
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(
    endpoint_list=st.lists(_endpoint_attrs, min_size=2, max_size=15),
    filter_status=_opt_lifecycle,
    filter_auth=_opt_auth,
    filter_sensitivity=_opt_sensitivity,
    score_min=_opt_score,
    score_max=_opt_score,
)
def test_no_false_positives(
    endpoint_list: list[dict],
    filter_status: Optional[LifecycleStatus],
    filter_auth: Optional[AuthScheme],
    filter_sensitivity: Optional[DataSensitivity],
    score_min: Optional[int],
    score_max: Optional[int],
):
    """
    **Validates: Requirements 4.5**

    Every endpoint returned by list_endpoints() with filters applied SHALL
    satisfy ALL the specified filter conditions (no false positives).
    """
    if score_min is not None and score_max is not None:
        score_min, score_max = min(score_min, score_max), max(score_min, score_max)

    seen: dict[tuple, dict] = {}
    for attrs in endpoint_list:
        key = (attrs["method"], attrs["host"], attrs["path"])
        seen[key] = attrs

    store = InMemoryStore()

    async def run():
        for attrs in seen.values():
            await store.upsert_endpoint(_make_record(attrs))
        return await store.list_endpoints(
            limit=1000,
            lifecycle_status=filter_status.value if filter_status is not None else None,
            auth_scheme=filter_auth.value if filter_auth is not None else None,
            data_sensitivity=filter_sensitivity.value if filter_sensitivity is not None else None,
            risk_score_min=score_min,
            risk_score_max=score_max,
        )

    filtered = _run(run())

    for entry in filtered:
        if filter_status is not None:
            assert entry["lifecycle_status"] == filter_status.value, (
                f"False positive: lifecycle_status={entry['lifecycle_status']} "
                f"does not match filter {filter_status.value}"
            )
        if filter_auth is not None:
            assert entry["auth_scheme"] == filter_auth.value, (
                f"False positive: auth_scheme={entry['auth_scheme']} "
                f"does not match filter {filter_auth.value}"
            )
        if filter_sensitivity is not None:
            assert entry["data_sensitivity"] == filter_sensitivity.value, (
                f"False positive: data_sensitivity={entry['data_sensitivity']} "
                f"does not match filter {filter_sensitivity.value}"
            )
        if score_min is not None:
            assert entry["risk_score"] >= score_min, (
                f"False positive: risk_score={entry['risk_score']} < score_min={score_min}"
            )
        if score_max is not None:
            assert entry["risk_score"] <= score_max, (
                f"False positive: risk_score={entry['risk_score']} > score_max={score_max}"
            )


# ---------------------------------------------------------------------------
# Property 26g: No false negatives — every matching endpoint is returned
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(
    endpoint_list=st.lists(_endpoint_attrs, min_size=2, max_size=15),
    filter_status=_opt_lifecycle,
    filter_auth=_opt_auth,
    filter_sensitivity=_opt_sensitivity,
    score_min=_opt_score,
    score_max=_opt_score,
)
def test_no_false_negatives(
    endpoint_list: list[dict],
    filter_status: Optional[LifecycleStatus],
    filter_auth: Optional[AuthScheme],
    filter_sensitivity: Optional[DataSensitivity],
    score_min: Optional[int],
    score_max: Optional[int],
):
    """
    **Validates: Requirements 4.5**

    Every endpoint that satisfies ALL filter conditions SHALL appear in the
    list_endpoints() result (no false negatives / missing results).
    """
    if score_min is not None and score_max is not None:
        score_min, score_max = min(score_min, score_max), max(score_min, score_max)

    seen: dict[tuple, dict] = {}
    for attrs in endpoint_list:
        key = (attrs["method"], attrs["host"], attrs["path"])
        seen[key] = attrs

    store = InMemoryStore()

    async def run():
        for attrs in seen.values():
            await store.upsert_endpoint(_make_record(attrs))
        all_entries = await store.list_endpoints(limit=1000)
        filtered = await store.list_endpoints(
            limit=1000,
            lifecycle_status=filter_status.value if filter_status is not None else None,
            auth_scheme=filter_auth.value if filter_auth is not None else None,
            data_sensitivity=filter_sensitivity.value if filter_sensitivity is not None else None,
            risk_score_min=score_min,
            risk_score_max=score_max,
        )
        return all_entries, filtered

    all_entries, filtered = _run(run())
    filtered_ids = _ids(filtered)

    for entry in all_entries:
        # Check if this entry satisfies all active filters
        matches = True
        if filter_status is not None and entry["lifecycle_status"] != filter_status.value:
            matches = False
        if filter_auth is not None and entry["auth_scheme"] != filter_auth.value:
            matches = False
        if filter_sensitivity is not None and entry["data_sensitivity"] != filter_sensitivity.value:
            matches = False
        if score_min is not None and entry["risk_score"] < score_min:
            matches = False
        if score_max is not None and entry["risk_score"] > score_max:
            matches = False

        if matches:
            assert entry["id"] in filtered_ids, (
                f"False negative: endpoint {entry['id']} satisfies all filters "
                f"(lifecycle={filter_status}, auth={filter_auth}, "
                f"sensitivity={filter_sensitivity}, "
                f"score_min={score_min}, score_max={score_max}) "
                f"but was not returned"
            )


# ---------------------------------------------------------------------------
# Property 26h: No-filter returns all endpoints
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(
    endpoint_list=st.lists(_endpoint_attrs, min_size=1, max_size=15),
)
def test_no_filter_returns_all(endpoint_list: list[dict]):
    """
    **Validates: Requirements 4.5**

    When no filter parameters are specified, list_endpoints() SHALL return
    all stored endpoints.
    """
    seen: dict[tuple, dict] = {}
    for attrs in endpoint_list:
        key = (attrs["method"], attrs["host"], attrs["path"])
        seen[key] = attrs

    store = InMemoryStore()

    async def run():
        for attrs in seen.values():
            await store.upsert_endpoint(_make_record(attrs))
        return await store.list_endpoints(limit=1000)

    all_entries = _run(run())
    assert len(all_entries) == len(seen), (
        f"Expected {len(seen)} endpoints with no filter, got {len(all_entries)}"
    )

