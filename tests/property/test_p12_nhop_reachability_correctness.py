# Feature: sentinel-api, Property 12: N-Hop Reachability Correctness
"""
Property 12: N-Hop Reachability Correctness

For any starting node in the Dependency Graph and any integer N in [1, 10],
the set of nodes returned by the reachability query SHALL contain exactly those
nodes reachable from the starting node by following directed edges in N or fewer
hops — no more, no fewer — and SHALL exclude soft-deleted nodes.

**Validates: Requirements 7.4, 7.5**
"""

import sys
import os
import asyncio
import uuid
from typing import Optional

from hypothesis import given, settings, assume
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


def _bfs_reachable(
    edges: list[dict],
    start_id: str,
    hops: int,
    deleted_ids: set[str],
) -> set[str]:
    """
    Reference implementation: BFS to compute exactly reachable nodes within N hops.

    This is the ground-truth implementation used to verify the graph store.
    """
    visited: set[str] = set()
    frontier: set[str] = {start_id}
    reachable: set[str] = set()

    for _ in range(hops):
        next_frontier: set[str] = set()
        for node_id in frontier:
            for edge in edges:
                if edge["from_id"] == node_id:
                    target_id = edge["to_id"]
                    if target_id not in visited and target_id != start_id:
                        next_frontier.add(target_id)
                        if target_id not in deleted_ids:
                            reachable.add(target_id)
        visited.update(frontier)
        frontier = next_frontier - visited
        if not frontier:
            break

    return reachable


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate a small graph as a list of (from_idx, to_idx) edge pairs
# using node indices (0..N-1) to avoid duplicate IDs
@st.composite
def graph_st(draw):
    """
    Generate a random directed graph with:
    - 2 to 8 nodes
    - 0 to 12 edges (directed, no self-loops)
    - A random starting node index
    - A random N in [1, 10]
    - A set of node indices to soft-delete (0 to 2 nodes)
    """
    num_nodes = draw(st.integers(min_value=2, max_value=8))
    node_ids = [str(uuid.uuid4()) for _ in range(num_nodes)]

    # Generate edges as (from_idx, to_idx) pairs, no self-loops
    max_edges = min(12, num_nodes * (num_nodes - 1))
    num_edges = draw(st.integers(min_value=0, max_value=max_edges))

    # Generate unique edge pairs
    all_possible_edges = [
        (i, j) for i in range(num_nodes) for j in range(num_nodes) if i != j
    ]
    edge_pairs = draw(
        st.lists(
            st.sampled_from(all_possible_edges),
            min_size=0,
            max_size=min(num_edges, len(all_possible_edges)),
            unique=True,
        )
    )

    start_idx = draw(st.integers(min_value=0, max_value=num_nodes - 1))
    hops = draw(st.integers(min_value=1, max_value=10))

    # Optionally soft-delete some nodes (not the start node)
    deletable_indices = [i for i in range(num_nodes) if i != start_idx]
    if deletable_indices:
        num_to_delete = draw(st.integers(min_value=0, max_value=min(2, len(deletable_indices))))
        delete_indices = draw(
            st.lists(
                st.sampled_from(deletable_indices),
                min_size=num_to_delete,
                max_size=num_to_delete,
                unique=True,
            )
        )
    else:
        delete_indices = []

    return {
        "node_ids": node_ids,
        "edge_pairs": edge_pairs,
        "start_idx": start_idx,
        "hops": hops,
        "delete_indices": delete_indices,
    }


# ---------------------------------------------------------------------------
# Property 12a: Reachability returns exactly the correct set of nodes
# ---------------------------------------------------------------------------


@given(graph=graph_st())
@settings(max_examples=10)
def test_p12_reachability_returns_exactly_correct_nodes(graph: dict):
    """
    **Validates: Requirements 7.4**

    For any starting node and any N in [1, 10], the reachability query returns
    exactly those nodes reachable within N hops — no more, no fewer.
    """
    node_ids = graph["node_ids"]
    edge_pairs = graph["edge_pairs"]
    start_idx = graph["start_idx"]
    hops = graph["hops"]
    delete_indices = graph["delete_indices"]

    start_id = node_ids[start_idx]
    deleted_ids = {node_ids[i] for i in delete_indices}

    # Build the in-memory store
    store = InMemoryGraphStore()
    for node_id in node_ids:
        run(store.upsert_node("API_Endpoint", node_id, {}))

    for from_idx, to_idx in edge_pairs:
        run(store.upsert_edge(node_ids[from_idx], node_ids[to_idx], "CALLS", {}))

    for node_id in deleted_ids:
        run(store.soft_delete_node(node_id))

    # Compute expected reachable set using reference BFS
    edges_raw = [
        {"from_id": node_ids[f], "to_id": node_ids[t]}
        for f, t in edge_pairs
    ]
    expected = _bfs_reachable(edges_raw, start_id, hops, deleted_ids)

    # Query the store
    actual_nodes = run(store.get_reachable_nodes(start_id, hops))
    actual = {n["id"] for n in actual_nodes}

    assert actual == expected, (
        f"Reachability mismatch for start={start_id}, hops={hops}.\n"
        f"Expected: {expected}\n"
        f"Actual:   {actual}\n"
        f"Deleted:  {deleted_ids}\n"
        f"Edges:    {[(node_ids[f], node_ids[t]) for f, t in edge_pairs]}"
    )


# ---------------------------------------------------------------------------
# Property 12b: Soft-deleted nodes are always excluded
# ---------------------------------------------------------------------------


@given(graph=graph_st())
@settings(max_examples=10)
def test_p12_soft_deleted_nodes_excluded_from_reachability(graph: dict):
    """
    **Validates: Requirements 7.4**

    Soft-deleted nodes are never included in reachability results,
    regardless of N or graph structure.
    """
    node_ids = graph["node_ids"]
    edge_pairs = graph["edge_pairs"]
    start_idx = graph["start_idx"]
    hops = graph["hops"]
    delete_indices = graph["delete_indices"]

    start_id = node_ids[start_idx]
    deleted_ids = {node_ids[i] for i in delete_indices}

    store = InMemoryGraphStore()
    for node_id in node_ids:
        run(store.upsert_node("API_Endpoint", node_id, {}))

    for from_idx, to_idx in edge_pairs:
        run(store.upsert_edge(node_ids[from_idx], node_ids[to_idx], "CALLS", {}))

    for node_id in deleted_ids:
        run(store.soft_delete_node(node_id))

    actual_nodes = run(store.get_reachable_nodes(start_id, hops))
    actual_ids = {n["id"] for n in actual_nodes}

    # No deleted node should appear in results
    intersection = actual_ids & deleted_ids
    assert intersection == set(), (
        f"Soft-deleted nodes appeared in reachability results: {intersection}"
    )


# ---------------------------------------------------------------------------
# Property 12c: Start node is never included in results
# ---------------------------------------------------------------------------


@given(graph=graph_st())
@settings(max_examples=10)
def test_p12_start_node_not_in_reachability_results(graph: dict):
    """
    **Validates: Requirements 7.4**

    The starting node is never included in the reachability results.
    """
    node_ids = graph["node_ids"]
    edge_pairs = graph["edge_pairs"]
    start_idx = graph["start_idx"]
    hops = graph["hops"]

    start_id = node_ids[start_idx]

    store = InMemoryGraphStore()
    for node_id in node_ids:
        run(store.upsert_node("API_Endpoint", node_id, {}))

    for from_idx, to_idx in edge_pairs:
        run(store.upsert_edge(node_ids[from_idx], node_ids[to_idx], "CALLS", {}))

    actual_nodes = run(store.get_reachable_nodes(start_id, hops))
    actual_ids = {n["id"] for n in actual_nodes}

    assert start_id not in actual_ids, (
        f"Start node {start_id} appeared in reachability results"
    )


# ---------------------------------------------------------------------------
# Property 12d: Monotonicity — more hops means at least as many reachable nodes
# ---------------------------------------------------------------------------


@given(
    graph=graph_st(),
    extra_hops=st.integers(min_value=1, max_value=5),
)
@settings(max_examples=10)
def test_p12_reachability_is_monotone_in_hops(graph: dict, extra_hops: int):
    """
    **Validates: Requirements 7.4**

    For any graph, increasing N by any positive amount can only add nodes
    to the reachable set — never remove them.

    reachable(N) ⊆ reachable(N + k) for all k >= 1
    """
    node_ids = graph["node_ids"]
    edge_pairs = graph["edge_pairs"]
    start_idx = graph["start_idx"]
    hops = graph["hops"]

    # Ensure hops + extra_hops <= 10
    if hops + extra_hops > 10:
        return

    start_id = node_ids[start_idx]

    store = InMemoryGraphStore()
    for node_id in node_ids:
        run(store.upsert_node("API_Endpoint", node_id, {}))

    for from_idx, to_idx in edge_pairs:
        run(store.upsert_edge(node_ids[from_idx], node_ids[to_idx], "CALLS", {}))

    nodes_n = run(store.get_reachable_nodes(start_id, hops))
    nodes_n_plus_k = run(store.get_reachable_nodes(start_id, hops + extra_hops))

    ids_n = {n["id"] for n in nodes_n}
    ids_n_plus_k = {n["id"] for n in nodes_n_plus_k}

    assert ids_n <= ids_n_plus_k, (
        f"Monotonicity violated: reachable({hops})={ids_n} "
        f"is not a subset of reachable({hops + extra_hops})={ids_n_plus_k}"
    )


# ---------------------------------------------------------------------------
# Property 12e: Blast-radius returns only DataAsset nodes (Req 7.5)
# ---------------------------------------------------------------------------


@st.composite
def blast_radius_graph_st(draw):
    """
    Generate a graph with mixed node types for blast-radius testing.

    Contains API_Endpoint nodes and DataAsset nodes, with edges between them.
    """
    num_endpoints = draw(st.integers(min_value=1, max_value=5))
    num_assets = draw(st.integers(min_value=0, max_value=4))

    endpoint_ids = [str(uuid.uuid4()) for _ in range(num_endpoints)]
    asset_ids = [str(uuid.uuid4()) for _ in range(num_assets)]

    zombie_id = endpoint_ids[0]

    # Generate edges between endpoints
    ep_edges = []
    if num_endpoints > 1:
        for i in range(num_endpoints - 1):
            if draw(st.booleans()):
                ep_edges.append((endpoint_ids[i], endpoint_ids[i + 1]))

    # Generate ACCESSES edges from endpoints to assets
    asset_edges = []
    for ep_id in endpoint_ids:
        for asset_id in asset_ids:
            if draw(st.booleans()):
                asset_edges.append((ep_id, asset_id))

    # Optionally soft-delete some assets
    deleted_asset_ids = set()
    for asset_id in asset_ids:
        if draw(st.booleans()):
            deleted_asset_ids.add(asset_id)

    return {
        "zombie_id": zombie_id,
        "endpoint_ids": endpoint_ids,
        "asset_ids": asset_ids,
        "ep_edges": ep_edges,
        "asset_edges": asset_edges,
        "deleted_asset_ids": deleted_asset_ids,
    }


@given(graph=blast_radius_graph_st())
@settings(max_examples=10)
def test_p12_blast_radius_returns_only_data_assets(graph: dict):
    """
    **Validates: Requirements 7.5**

    The blast-radius query returns only DataAsset nodes reachable from the
    Zombie node — no API_Endpoint or Service nodes are included.
    """
    zombie_id = graph["zombie_id"]
    endpoint_ids = graph["endpoint_ids"]
    asset_ids = graph["asset_ids"]
    ep_edges = graph["ep_edges"]
    asset_edges = graph["asset_edges"]
    deleted_asset_ids = graph["deleted_asset_ids"]

    store = InMemoryGraphStore()

    for ep_id in endpoint_ids:
        run(store.upsert_node("API_Endpoint", ep_id, {"lifecycle_status": "Zombie"}))

    for asset_id in asset_ids:
        run(store.upsert_node("DataAsset", asset_id, {"sensitivity": "PII"}))

    for from_id, to_id in ep_edges:
        run(store.upsert_edge(from_id, to_id, "CALLS", {}))

    for ep_id, asset_id in asset_edges:
        run(store.upsert_edge(ep_id, asset_id, "ACCESSES", {}))

    for asset_id in deleted_asset_ids:
        run(store.soft_delete_node(asset_id))

    # Query blast radius
    result = run(store.get_blast_radius(zombie_id))

    # All returned nodes must be DataAsset nodes
    for node in result:
        assert node["_label"] == "DataAsset", (
            f"Expected only DataAsset nodes in blast-radius, "
            f"got node with label '{node['_label']}' (id={node['id']})"
        )

    # No deleted assets should appear
    result_ids = {n["id"] for n in result}
    assert result_ids.isdisjoint(deleted_asset_ids), (
        f"Soft-deleted assets appeared in blast-radius: "
        f"{result_ids & deleted_asset_ids}"
    )

    # All returned assets must be reachable from zombie_id
    all_reachable = run(store.get_reachable_nodes(zombie_id, hops=10))
    reachable_ids = {n["id"] for n in all_reachable}

    for node in result:
        assert node["id"] in reachable_ids, (
            f"Blast-radius returned node {node['id']} that is not reachable "
            f"from zombie {zombie_id}"
        )

