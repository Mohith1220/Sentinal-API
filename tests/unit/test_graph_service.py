"""
Unit tests for the Graph Service.

Tests cover:
  - Node upsert idempotence
  - Edge creation (CALLS and ACCESSES)
  - Soft delete visibility
  - N=1 reachability
  - N=10 reachability
  - Blast-radius returns only DataAsset nodes
"""

import sys
import os
import asyncio

import pytest

# ---------------------------------------------------------------------------
# Path setup — add graph-service to sys.path
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


# ---------------------------------------------------------------------------
# Node upsert idempotence
# ---------------------------------------------------------------------------


def test_upsert_node_creates_new_node():
    """Upserting a node that doesn't exist creates it."""
    store = InMemoryGraphStore()
    node = run(store.upsert_node("API_Endpoint", "ep-1", {"method": "GET", "host": "api.example.com"}))
    assert node["id"] == "ep-1"
    assert node["method"] == "GET"
    assert node["_label"] == "API_Endpoint"


def test_upsert_node_is_idempotent():
    """Upserting the same node twice returns the same node with updated props."""
    store = InMemoryGraphStore()

    run(store.upsert_node("API_Endpoint", "ep-1", {"method": "GET", "risk_score": 10}))
    run(store.upsert_node("API_Endpoint", "ep-1", {"risk_score": 50}))

    node = run(store.get_node("ep-1"))
    assert node is not None
    assert node["id"] == "ep-1"
    # risk_score should be updated to 50
    assert node["risk_score"] == 50
    # method should still be present from first upsert
    assert node["method"] == "GET"


def test_upsert_node_multiple_times_single_record():
    """Upserting the same node N times results in exactly one node."""
    store = InMemoryGraphStore()

    for i in range(5):
        run(store.upsert_node("API_Endpoint", "ep-1", {"counter": i}))

    # Only one node should exist
    assert len(store._nodes) == 1
    node = run(store.get_node("ep-1"))
    assert node["counter"] == 4  # last value wins


def test_upsert_different_labels():
    """Nodes with different labels can coexist."""
    store = InMemoryGraphStore()

    run(store.upsert_node("API_Endpoint", "ep-1", {"method": "GET"}))
    run(store.upsert_node("Service", "svc-1", {"name": "auth-service"}))
    run(store.upsert_node("DataAsset", "da-1", {"name": "users_table"}))

    assert len(store._nodes) == 3

    ep = run(store.get_node("ep-1"))
    svc = run(store.get_node("svc-1"))
    da = run(store.get_node("da-1"))

    assert ep["_label"] == "API_Endpoint"
    assert svc["_label"] == "Service"
    assert da["_label"] == "DataAsset"


# ---------------------------------------------------------------------------
# Edge creation
# ---------------------------------------------------------------------------


def test_create_calls_edge():
    """Creating a CALLS edge between two API_Endpoint nodes succeeds."""
    store = InMemoryGraphStore()

    run(store.upsert_node("API_Endpoint", "ep-1", {"method": "GET"}))
    run(store.upsert_node("API_Endpoint", "ep-2", {"method": "POST"}))

    edge = run(store.upsert_edge("ep-1", "ep-2", "CALLS", {"observed_at": "2024-01-01T00:00:00Z", "source": "traffic"}))

    assert edge["from_id"] == "ep-1"
    assert edge["to_id"] == "ep-2"
    assert edge["type"] == "CALLS"
    assert edge["props"]["source"] == "traffic"


def test_create_accesses_edge():
    """Creating an ACCESSES edge from API_Endpoint to DataAsset succeeds."""
    store = InMemoryGraphStore()

    run(store.upsert_node("API_Endpoint", "ep-1", {"method": "GET"}))
    run(store.upsert_node("DataAsset", "da-1", {"name": "users_table"}))

    edge = run(store.upsert_edge("ep-1", "da-1", "ACCESSES", {"schema_ref": "#/components/schemas/User"}))

    assert edge["from_id"] == "ep-1"
    assert edge["to_id"] == "da-1"
    assert edge["type"] == "ACCESSES"
    assert edge["props"]["schema_ref"] == "#/components/schemas/User"


def test_edge_creation_is_idempotent():
    """Creating the same edge twice results in a single edge with updated props."""
    store = InMemoryGraphStore()

    run(store.upsert_node("API_Endpoint", "ep-1", {}))
    run(store.upsert_node("API_Endpoint", "ep-2", {}))

    run(store.upsert_edge("ep-1", "ep-2", "CALLS", {"source": "traffic"}))
    run(store.upsert_edge("ep-1", "ep-2", "CALLS", {"source": "static_analysis"}))

    # Only one edge should exist
    assert len(store._edges) == 1
    assert store._edges[0]["props"]["source"] == "static_analysis"


def test_get_edges_for_node_returns_all_edges():
    """get_edges_for_node returns edges where node is source or target."""
    store = InMemoryGraphStore()

    run(store.upsert_node("API_Endpoint", "ep-1", {}))
    run(store.upsert_node("API_Endpoint", "ep-2", {}))
    run(store.upsert_node("API_Endpoint", "ep-3", {}))

    run(store.upsert_edge("ep-1", "ep-2", "CALLS", {}))
    run(store.upsert_edge("ep-3", "ep-1", "CALLS", {}))

    edges = run(store.get_edges_for_node("ep-1"))
    assert len(edges) == 2


# ---------------------------------------------------------------------------
# Soft delete visibility
# ---------------------------------------------------------------------------


def test_soft_delete_hides_node_from_get():
    """After soft delete, get_node returns None."""
    store = InMemoryGraphStore()

    run(store.upsert_node("API_Endpoint", "ep-1", {"method": "GET"}))

    # Node is visible before delete
    node = run(store.get_node("ep-1"))
    assert node is not None

    # Soft delete
    deleted = run(store.soft_delete_node("ep-1"))
    assert deleted is True

    # Node is hidden after delete
    node = run(store.get_node("ep-1"))
    assert node is None


def test_soft_delete_sets_deleted_at():
    """Soft delete sets the deleted_at property on the node."""
    store = InMemoryGraphStore()

    run(store.upsert_node("API_Endpoint", "ep-1", {}))
    run(store.soft_delete_node("ep-1"))

    # Access internal state to verify deleted_at is set
    raw_node = store._nodes.get("ep-1")
    assert raw_node is not None
    assert raw_node.get("deleted_at") is not None


def test_soft_delete_nonexistent_node_returns_false():
    """Soft deleting a node that doesn't exist returns False."""
    store = InMemoryGraphStore()

    deleted = run(store.soft_delete_node("nonexistent"))
    assert deleted is False


def test_soft_deleted_node_excluded_from_reachability():
    """Soft-deleted nodes are excluded from reachability results."""
    store = InMemoryGraphStore()

    run(store.upsert_node("API_Endpoint", "ep-start", {}))
    run(store.upsert_node("API_Endpoint", "ep-deleted", {}))
    run(store.upsert_edge("ep-start", "ep-deleted", "CALLS", {}))

    # Before delete: ep-deleted is reachable
    nodes = run(store.get_reachable_nodes("ep-start", hops=1))
    assert any(n["id"] == "ep-deleted" for n in nodes)

    # After delete: ep-deleted is excluded
    run(store.soft_delete_node("ep-deleted"))
    nodes = run(store.get_reachable_nodes("ep-start", hops=1))
    assert not any(n["id"] == "ep-deleted" for n in nodes)


# ---------------------------------------------------------------------------
# N=1 reachability
# ---------------------------------------------------------------------------


def test_reachability_n1_returns_direct_neighbors():
    """N=1 reachability returns only direct neighbors."""
    store = InMemoryGraphStore()

    # ep-start -> ep-1 -> ep-2
    run(store.upsert_node("API_Endpoint", "ep-start", {}))
    run(store.upsert_node("API_Endpoint", "ep-1", {}))
    run(store.upsert_node("API_Endpoint", "ep-2", {}))

    run(store.upsert_edge("ep-start", "ep-1", "CALLS", {}))
    run(store.upsert_edge("ep-1", "ep-2", "CALLS", {}))

    nodes = run(store.get_reachable_nodes("ep-start", hops=1))
    node_ids = {n["id"] for n in nodes}

    assert "ep-1" in node_ids
    assert "ep-2" not in node_ids  # 2 hops away


def test_reachability_n1_empty_when_no_edges():
    """N=1 reachability returns empty list when no outgoing edges."""
    store = InMemoryGraphStore()

    run(store.upsert_node("API_Endpoint", "ep-start", {}))

    nodes = run(store.get_reachable_nodes("ep-start", hops=1))
    assert nodes == []


def test_reachability_n1_does_not_include_start_node():
    """N=1 reachability does not include the starting node itself."""
    store = InMemoryGraphStore()

    run(store.upsert_node("API_Endpoint", "ep-start", {}))
    run(store.upsert_node("API_Endpoint", "ep-1", {}))
    run(store.upsert_edge("ep-start", "ep-1", "CALLS", {}))

    nodes = run(store.get_reachable_nodes("ep-start", hops=1))
    node_ids = {n["id"] for n in nodes}

    assert "ep-start" not in node_ids


# ---------------------------------------------------------------------------
# N=10 reachability
# ---------------------------------------------------------------------------


def test_reachability_n10_traverses_full_chain():
    """N=10 reachability traverses a chain of 10 nodes."""
    store = InMemoryGraphStore()

    # Create a chain: ep-0 -> ep-1 -> ... -> ep-10
    for i in range(11):
        run(store.upsert_node("API_Endpoint", f"ep-{i}", {}))
    for i in range(10):
        run(store.upsert_edge(f"ep-{i}", f"ep-{i+1}", "CALLS", {}))

    nodes = run(store.get_reachable_nodes("ep-0", hops=10))
    node_ids = {n["id"] for n in nodes}

    # All nodes ep-1 through ep-10 should be reachable
    for i in range(1, 11):
        assert f"ep-{i}" in node_ids, f"ep-{i} should be reachable within 10 hops"


def test_reachability_n10_stops_at_boundary():
    """N=10 reachability does not return nodes beyond 10 hops."""
    store = InMemoryGraphStore()

    # Create a chain of 12 nodes
    for i in range(12):
        run(store.upsert_node("API_Endpoint", f"ep-{i}", {}))
    for i in range(11):
        run(store.upsert_edge(f"ep-{i}", f"ep-{i+1}", "CALLS", {}))

    nodes = run(store.get_reachable_nodes("ep-0", hops=10))
    node_ids = {n["id"] for n in nodes}

    # ep-11 is 11 hops away — should NOT be reachable
    assert "ep-11" not in node_ids


def test_reachability_invalid_hops_raises():
    """Reachability with hops outside [1, 10] raises ValueError."""
    store = InMemoryGraphStore()

    run(store.upsert_node("API_Endpoint", "ep-start", {}))

    with pytest.raises(ValueError):
        run(store.get_reachable_nodes("ep-start", hops=0))

    with pytest.raises(ValueError):
        run(store.get_reachable_nodes("ep-start", hops=11))


# ---------------------------------------------------------------------------
# Blast-radius returns only DataAsset nodes
# ---------------------------------------------------------------------------


def test_blast_radius_returns_only_data_assets():
    """Blast-radius query returns only DataAsset nodes, not API_Endpoint nodes."""
    store = InMemoryGraphStore()

    # zombie -> ep-intermediate -> da-1 (DataAsset)
    run(store.upsert_node("API_Endpoint", "zombie-1", {"lifecycle_status": "Zombie"}))
    run(store.upsert_node("API_Endpoint", "ep-intermediate", {}))
    run(store.upsert_node("DataAsset", "da-1", {"name": "users_table", "sensitivity": "PII"}))
    run(store.upsert_node("DataAsset", "da-2", {"name": "payments_table", "sensitivity": "financial"}))

    run(store.upsert_edge("zombie-1", "ep-intermediate", "CALLS", {}))
    run(store.upsert_edge("ep-intermediate", "da-1", "ACCESSES", {}))
    run(store.upsert_edge("zombie-1", "da-2", "ACCESSES", {}))

    data_assets = run(store.get_blast_radius("zombie-1"))
    labels = {n["_label"] for n in data_assets}

    # Only DataAsset nodes should be returned
    assert labels == {"DataAsset"}, f"Expected only DataAsset nodes, got {labels}"
    assert len(data_assets) == 2


def test_blast_radius_excludes_soft_deleted_data_assets():
    """Blast-radius excludes soft-deleted DataAsset nodes."""
    store = InMemoryGraphStore()

    run(store.upsert_node("API_Endpoint", "zombie-1", {}))
    run(store.upsert_node("DataAsset", "da-1", {"name": "active_table"}))
    run(store.upsert_node("DataAsset", "da-2", {"name": "deleted_table"}))

    run(store.upsert_edge("zombie-1", "da-1", "ACCESSES", {}))
    run(store.upsert_edge("zombie-1", "da-2", "ACCESSES", {}))

    # Soft delete da-2
    run(store.soft_delete_node("da-2"))

    data_assets = run(store.get_blast_radius("zombie-1"))
    asset_ids = {n["id"] for n in data_assets}

    assert "da-1" in asset_ids
    assert "da-2" not in asset_ids


def test_blast_radius_empty_when_no_data_assets():
    """Blast-radius returns empty list when no DataAsset nodes are reachable."""
    store = InMemoryGraphStore()

    run(store.upsert_node("API_Endpoint", "zombie-1", {}))
    run(store.upsert_node("API_Endpoint", "ep-1", {}))
    run(store.upsert_edge("zombie-1", "ep-1", "CALLS", {}))

    data_assets = run(store.get_blast_radius("zombie-1"))
    assert data_assets == []


def test_blast_radius_does_not_include_intermediate_api_endpoints():
    """Blast-radius does not include intermediate API_Endpoint nodes."""
    store = InMemoryGraphStore()

    run(store.upsert_node("API_Endpoint", "zombie-1", {}))
    run(store.upsert_node("API_Endpoint", "ep-intermediate", {}))
    run(store.upsert_node("DataAsset", "da-1", {"name": "sensitive_data"}))

    run(store.upsert_edge("zombie-1", "ep-intermediate", "CALLS", {}))
    run(store.upsert_edge("ep-intermediate", "da-1", "ACCESSES", {}))

    data_assets = run(store.get_blast_radius("zombie-1"))
    node_ids = {n["id"] for n in data_assets}

    assert "ep-intermediate" not in node_ids
    assert "da-1" in node_ids
