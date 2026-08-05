# Feature: sentinel-api, Property 11: Dependency Graph Edge Creation
"""
Property 11: Dependency Graph Edge Creation

For any observed call relationship between two API endpoints, or any data-asset
reference in an OpenAPI response schema, the Dependency Graph SHALL contain a
directed edge of the appropriate type (CALLS or ACCESSES) between the
corresponding nodes, and that edge SHALL be retrievable by querying either
endpoint node.

**Validates: Requirements 7.2, 7.3**
"""

import sys
import os
import asyncio
import uuid

from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
SERVICE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "services", "graph-service"
)
if SERVICE_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(SERVICE_DIR))

from graph_db import InMemoryGraphStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run(coro):
    """Run a coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_store_with_endpoints(*endpoint_ids: str) -> InMemoryGraphStore:
    """Create a store pre-populated with API_Endpoint nodes."""
    store = InMemoryGraphStore()
    for ep_id in endpoint_ids:
        run(store.upsert_node("API_Endpoint", ep_id, {"method": "GET", "host": "api.example.com"}))
    return store


def _make_store_with_endpoint_and_asset(ep_id: str, asset_id: str) -> InMemoryGraphStore:
    """Create a store with one API_Endpoint and one DataAsset node."""
    store = InMemoryGraphStore()
    run(store.upsert_node("API_Endpoint", ep_id, {"method": "GET"}))
    run(store.upsert_node("DataAsset", asset_id, {"name": "users_table", "sensitivity": "PII"}))
    return store


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate valid node IDs (non-empty strings)
node_id_st = st.uuids().map(str)

# Generate CALLS edge properties
calls_props_st = st.fixed_dictionaries(
    {
        "observed_at": st.datetimes().map(lambda d: d.isoformat()),
        "source": st.sampled_from(["traffic", "static_analysis"]),
    }
)

# Generate ACCESSES edge properties
accesses_props_st = st.fixed_dictionaries(
    {
        "schema_ref": st.text(
            alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="/_#."),
            min_size=1,
            max_size=100,
        ).map(lambda s: f"#/components/schemas/{s}"),
    }
)


# ---------------------------------------------------------------------------
# Property 11a: CALLS edge creation and retrievability
# ---------------------------------------------------------------------------


@given(
    from_id=node_id_st,
    to_id=node_id_st,
    props=calls_props_st,
)
@settings(max_examples=10)
def test_p11_calls_edge_created_and_retrievable(
    from_id: str,
    to_id: str,
    props: dict,
):
    """
    **Validates: Requirements 7.2**

    For any observed call relationship between two API endpoints, the Dependency
    Graph SHALL contain a directed CALLS edge between the corresponding nodes,
    and that edge SHALL be retrievable by querying either endpoint node.
    """
    # Skip self-loops (same node calling itself) — not a meaningful test case
    if from_id == to_id:
        return

    store = _make_store_with_endpoints(from_id, to_id)

    # Create the CALLS edge
    edge = run(store.upsert_edge(from_id, to_id, "CALLS", props))

    # The edge must exist with the correct type and direction
    assert edge["from_id"] == from_id
    assert edge["to_id"] == to_id
    assert edge["type"] == "CALLS"

    # The edge must be retrievable by querying the source node
    edges_from_source = run(store.get_edges_for_node(from_id))
    assert any(
        e["from_id"] == from_id and e["to_id"] == to_id and e["type"] == "CALLS"
        for e in edges_from_source
    ), f"CALLS edge not found when querying source node {from_id}"

    # The edge must be retrievable by querying the target node
    edges_from_target = run(store.get_edges_for_node(to_id))
    assert any(
        e["from_id"] == from_id and e["to_id"] == to_id and e["type"] == "CALLS"
        for e in edges_from_target
    ), f"CALLS edge not found when querying target node {to_id}"


# ---------------------------------------------------------------------------
# Property 11b: ACCESSES edge creation and retrievability
# ---------------------------------------------------------------------------


@given(
    ep_id=node_id_st,
    asset_id=node_id_st,
    props=accesses_props_st,
)
@settings(max_examples=10)
def test_p11_accesses_edge_created_and_retrievable(
    ep_id: str,
    asset_id: str,
    props: dict,
):
    """
    **Validates: Requirements 7.3**

    For any data-asset reference in an OpenAPI response schema, the Dependency
    Graph SHALL contain a directed ACCESSES edge from the API endpoint node to
    the data asset node, and that edge SHALL be retrievable by querying either
    endpoint node.
    """
    # Skip if same ID (endpoint and asset can't be the same node)
    if ep_id == asset_id:
        return

    store = _make_store_with_endpoint_and_asset(ep_id, asset_id)

    # Create the ACCESSES edge
    edge = run(store.upsert_edge(ep_id, asset_id, "ACCESSES", props))

    # The edge must exist with the correct type and direction
    assert edge["from_id"] == ep_id
    assert edge["to_id"] == asset_id
    assert edge["type"] == "ACCESSES"

    # The edge must be retrievable by querying the API endpoint node
    edges_from_ep = run(store.get_edges_for_node(ep_id))
    assert any(
        e["from_id"] == ep_id and e["to_id"] == asset_id and e["type"] == "ACCESSES"
        for e in edges_from_ep
    ), f"ACCESSES edge not found when querying endpoint node {ep_id}"

    # The edge must be retrievable by querying the data asset node
    edges_from_asset = run(store.get_edges_for_node(asset_id))
    assert any(
        e["from_id"] == ep_id and e["to_id"] == asset_id and e["type"] == "ACCESSES"
        for e in edges_from_asset
    ), f"ACCESSES edge not found when querying data asset node {asset_id}"


# ---------------------------------------------------------------------------
# Property 11c: Edge creation is idempotent (MERGE semantics)
# ---------------------------------------------------------------------------


@given(
    from_id=node_id_st,
    to_id=node_id_st,
    props1=calls_props_st,
    props2=calls_props_st,
)
@settings(max_examples=10)
def test_p11_calls_edge_creation_is_idempotent(
    from_id: str,
    to_id: str,
    props1: dict,
    props2: dict,
):
    """
    **Validates: Requirements 7.2**

    Creating the same CALLS edge twice (MERGE semantics) results in exactly
    one edge in the graph, with the most recently set properties.
    """
    if from_id == to_id:
        return

    store = _make_store_with_endpoints(from_id, to_id)

    # Create the edge twice
    run(store.upsert_edge(from_id, to_id, "CALLS", props1))
    run(store.upsert_edge(from_id, to_id, "CALLS", props2))

    # Only one edge should exist between these two nodes
    edges = run(store.get_edges_for_node(from_id))
    calls_edges = [
        e for e in edges
        if e["from_id"] == from_id and e["to_id"] == to_id and e["type"] == "CALLS"
    ]
    assert len(calls_edges) == 1, (
        f"Expected exactly 1 CALLS edge, found {len(calls_edges)} "
        f"after two upserts between {from_id} and {to_id}"
    )


# ---------------------------------------------------------------------------
# Property 11d: Edge direction is preserved
# ---------------------------------------------------------------------------


@given(
    from_id=node_id_st,
    to_id=node_id_st,
    props=calls_props_st,
)
@settings(max_examples=10)
def test_p11_calls_edge_direction_is_preserved(
    from_id: str,
    to_id: str,
    props: dict,
):
    """
    **Validates: Requirements 7.2**

    The CALLS edge is directed: from_id -> to_id. The reverse direction
    (to_id -> from_id) must NOT be created.
    """
    if from_id == to_id:
        return

    store = _make_store_with_endpoints(from_id, to_id)
    run(store.upsert_edge(from_id, to_id, "CALLS", props))

    # Verify the edge is directed correctly
    all_edges = store._edges
    forward_edges = [
        e for e in all_edges
        if e["from_id"] == from_id and e["to_id"] == to_id
    ]
    reverse_edges = [
        e for e in all_edges
        if e["from_id"] == to_id and e["to_id"] == from_id
    ]

    assert len(forward_edges) == 1, "Expected exactly one forward edge"
    assert len(reverse_edges) == 0, "Expected no reverse edge to be created"

