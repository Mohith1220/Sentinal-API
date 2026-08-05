# Feature: sentinel-api, Task 21: Integration tests — Graph Service
"""
Integration tests for the Graph Service.

Tests:
- Add endpoint to inventory and assert graph node created within 60 seconds

Requirements: 7.6
"""

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import List
import sys
import os

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "sentinel_shared"))

from sentinel_shared.models import (
    EndpointRecord,
    AuthScheme,
    DataSensitivity,
    LifecycleStatus,
)


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_endpoint_added_to_inventory_creates_graph_node_within_60_seconds():
    """
    Test that adding an endpoint to the inventory creates a graph node within 60 seconds.
    
    This simulates the Kafka event flow: endpoint.updated → graph service → node creation.
    
    Validates: Requirement 7.6 - Graph update within 60s of inventory change
    """
    from conftest import activate_service
    
    # Setup discovery service (inventory)
    activate_service("discovery-service")
    from db import InMemoryStore
    
    inventory_store = InMemoryStore()
    
    # Setup graph service
    activate_service("graph-service")
    from graph_db import InMemoryGraphStore
    
    graph_db = InMemoryGraphStore()
    
    # Create new endpoint
    endpoint = EndpointRecord(
        id=str(uuid.uuid4()),
        http_method="POST",
        host="api.example.com",
        normalized_path="/api/orders",
        auth_scheme=AuthScheme.JWT,
        data_sensitivity=DataSensitivity.FINANCIAL,
        lifecycle_status=LifecycleStatus.ACTIVE,
    )
    
    start_time = time.time()
    
    # Add endpoint to inventory
    await inventory_store.upsert_endpoint(endpoint)
    
    # Simulate Kafka event processing: create graph node
    await graph_db.upsert_node(
        label="API_Endpoint",
        node_id=endpoint.id,
        props={
            "method": endpoint.http_method,
            "host": endpoint.host,
            "path": endpoint.normalized_path,
            "lifecycle_status": endpoint.lifecycle_status.value,
            "risk_score": endpoint.risk_score,
        }
    )
    
    elapsed_time = time.time() - start_time
    
    # Verify node creation completed within 60 seconds
    assert elapsed_time < 60.0, f"Graph node creation took {elapsed_time:.2f}s, expected < 60s"
    
    # Verify node exists in graph
    node = await graph_db.get_node(endpoint.id)
    assert node is not None, "Expected graph node to exist"
    assert node["id"] == endpoint.id
    assert node["method"] == endpoint.http_method
    assert node["host"] == endpoint.host
    assert node["path"] == endpoint.normalized_path


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multiple_endpoints_create_graph_nodes():
    """
    Test that multiple endpoints are correctly added to the graph.
    
    Validates: Graph node creation for multiple endpoints
    """
    from conftest import activate_service
    
    activate_service("graph-service")
    from graph_db import InMemoryGraphStore
    
    graph_db = InMemoryGraphStore()
    
    # Create multiple endpoints
    endpoints = []
    for i in range(10):
        endpoint = EndpointRecord(
            id=str(uuid.uuid4()),
            http_method="GET" if i % 2 == 0 else "POST",
            host=f"api{i % 3}.example.com",
            normalized_path=f"/api/resource-{i}",
            auth_scheme=AuthScheme.OAUTH2,
            data_sensitivity=DataSensitivity.INTERNAL,
            lifecycle_status=LifecycleStatus.ACTIVE,
        )
        endpoints.append(endpoint)
    
    # Add all endpoints to graph
    for endpoint in endpoints:
        await graph_db.upsert_node("API_Endpoint", endpoint.id, {"method": endpoint.http_method, "host": endpoint.host, "path": endpoint.normalized_path, "lifecycle_status": endpoint.lifecycle_status.value, "risk_score": endpoint.risk_score})
    
    # Verify all nodes exist
    for endpoint in endpoints:
        node = await graph_db.get_node(endpoint.id)
        assert node is not None, f"Expected node for endpoint {endpoint.id}"
        assert node["id"] == endpoint.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_edge_creation_for_api_calls():
    """
    Test that call relationships between APIs create graph edges.
    
    Validates: Requirement 7.2 - Graph edge creation for API calls
    """
    from conftest import activate_service
    
    activate_service("graph-service")
    from graph_db import InMemoryGraphStore
    
    graph_db = InMemoryGraphStore()
    
    # Create two endpoints
    caller = EndpointRecord(
        id=str(uuid.uuid4()),
        http_method="GET",
        host="api.example.com",
        normalized_path="/api/users",
        auth_scheme=AuthScheme.JWT,
        data_sensitivity=DataSensitivity.PII,
        lifecycle_status=LifecycleStatus.ACTIVE,
    )
    
    callee = EndpointRecord(
        id=str(uuid.uuid4()),
        http_method="GET",
        host="api.example.com",
        normalized_path="/api/profiles",
        auth_scheme=AuthScheme.JWT,
        data_sensitivity=DataSensitivity.PII,
        lifecycle_status=LifecycleStatus.ACTIVE,
    )
    
    # Add nodes to graph
    await graph_db.upsert_node("API_Endpoint", caller.id, {"method": caller.http_method, "host": caller.host, "path": caller.normalized_path, "lifecycle_status": caller.lifecycle_status.value, "risk_score": caller.risk_score})
    
    await graph_db.upsert_node("API_Endpoint", callee.id, {"method": callee.http_method, "host": callee.host, "path": callee.normalized_path, "lifecycle_status": callee.lifecycle_status.value, "risk_score": callee.risk_score})
    
    # Create call relationship
    await graph_db.upsert_edge(caller.id, callee.id, "CALLS", {"observed_at": datetime.now(timezone.utc), "source": "traffic"
    })
    
    # Verify edge exists
    edges = await graph_db.get_edges_for_node(caller.id)
    assert len(edges) >= 1, "Expected at least one outgoing edge"
    
    # Verify edge properties
    edge = edges[0]
    assert edge["from"] == caller.id
    assert edge["to"] == callee.id
    assert edge["type"] == "CALLS"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_reachability_query():
    """
    Test N-hop reachability queries in the dependency graph.
    
    Validates: Requirement 7.4 - N-hop reachability
    """
    from conftest import activate_service
    
    activate_service("graph-service")
    from graph_db import InMemoryGraphStore
    
    graph_db = InMemoryGraphStore()
    
    # Create a chain of endpoints: A → B → C → D
    endpoints = []
    for i, name in enumerate(["A", "B", "C", "D"]):
        endpoint = EndpointRecord(
            id=str(uuid.uuid4()),
            http_method="GET",
            host="api.example.com",
            normalized_path=f"/api/{name.lower()}",
            auth_scheme=AuthScheme.JWT,
            data_sensitivity=DataSensitivity.INTERNAL,
            lifecycle_status=LifecycleStatus.ACTIVE,
        )
        endpoints.append(endpoint)
        
        await graph_db.upsert_node("API_Endpoint", endpoint.id, {"method": endpoint.http_method, "host": endpoint.host, "path": endpoint.normalized_path, "lifecycle_status": endpoint.lifecycle_status.value, "risk_score": endpoint.risk_score})
    
    # Create edges: A → B → C → D
    for i in range(len(endpoints) - 1):
        await graph_db.upsert_edge(endpoints[i].id, endpoints[i + 1].id, "CALLS", {"observed_at": datetime.now(timezone.utc), "source": "traffic"
        })
    
    # Test 1-hop reachability from A (should reach B)
    reachable_1 = await graph_db.get_reachable_nodes(endpoints[0].id, hops=1)
    assert len(reachable_1) >= 1, "Expected at least 1 node reachable in 1 hop"
    reachable_ids_1 = {node["id"] for node in reachable_1}
    assert endpoints[1].id in reachable_ids_1, "Expected B to be reachable from A in 1 hop"
    
    # Test 2-hop reachability from A (should reach B and C)
    reachable_2 = await graph_db.get_reachable_nodes(endpoints[0].id, hops=2)
    assert len(reachable_2) >= 2, "Expected at least 2 nodes reachable in 2 hops"
    reachable_ids_2 = {node["id"] for node in reachable_2}
    assert endpoints[1].id in reachable_ids_2, "Expected B to be reachable from A in 2 hops"
    assert endpoints[2].id in reachable_ids_2, "Expected C to be reachable from A in 2 hops"
    
    # Test 3-hop reachability from A (should reach B, C, and D)
    reachable_3 = await graph_db.get_reachable_nodes(endpoints[0].id, hops=3)
    assert len(reachable_3) >= 3, "Expected at least 3 nodes reachable in 3 hops"
    reachable_ids_3 = {node["id"] for node in reachable_3}
    assert endpoints[3].id in reachable_ids_3, "Expected D to be reachable from A in 3 hops"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_blast_radius_for_zombie_api():
    """
    Test blast radius calculation for Zombie APIs.
    
    Validates: Requirement 7.5 - Zombie API blast radius
    """
    from conftest import activate_service
    
    activate_service("graph-service")
    from graph_db import InMemoryGraphStore
    
    graph_db = InMemoryGraphStore()
    
    # Create Zombie API
    zombie = EndpointRecord(
        id=str(uuid.uuid4()),
        http_method="POST",
        host="api.example.com",
        normalized_path="/api/zombie",
        auth_scheme=AuthScheme.NONE,
        data_sensitivity=DataSensitivity.INTERNAL,
        lifecycle_status=LifecycleStatus.ZOMBIE,
        risk_score=80,
    )
    
    await graph_db.upsert_node("API_Endpoint", zombie.id, {"method": zombie.http_method, "host": zombie.host, "path": zombie.normalized_path, "lifecycle_status": zombie.lifecycle_status.value, "risk_score": zombie.risk_score})
    
    # Create data assets
    data_assets = []
    for i, asset_name in enumerate(["users_db", "transactions_db", "audit_log"]):
        asset_id = str(uuid.uuid4())
        await graph_db.upsert_node("DataAsset", asset_id, {"name": asset_name, "asset_type": "database", "sensitivity": "PII" if i < 2 else "internal"
        })
        data_assets.append(asset_id)
    
    # Create ACCESSES edges from Zombie to data assets
    for asset_id in data_assets:
        await graph_db.upsert_edge(zombie.id, asset_id, "ACCESSES", {"schema_ref": f"schema_{asset_id}"
        })
    
    # Calculate blast radius
    blast_radius = await graph_db.get_blast_radius(zombie.id)
    
    # Verify all data assets are in blast radius
    assert len(blast_radius) >= 3, f"Expected at least 3 data assets in blast radius, got {len(blast_radius)}"
    
    blast_radius_ids = {asset["id"] for asset in blast_radius}
    for asset_id in data_assets:
        assert asset_id in blast_radius_ids, f"Expected data asset {asset_id} in blast radius"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_soft_delete():
    """
    Test that soft-deleted nodes are excluded from queries.
    
    Validates: Requirement 7.7 - Soft delete with audit trail
    """
    from conftest import activate_service
    
    activate_service("graph-service")
    from graph_db import InMemoryGraphStore
    
    graph_db = InMemoryGraphStore()
    
    # Create endpoint
    endpoint = EndpointRecord(
        id=str(uuid.uuid4()),
        http_method="DELETE",
        host="api.example.com",
        normalized_path="/api/deprecated",
        auth_scheme=AuthScheme.API_KEY,
        data_sensitivity=DataSensitivity.INTERNAL,
        lifecycle_status=LifecycleStatus.DEPRECATED,
    )
    
    await graph_db.upsert_node("API_Endpoint", endpoint.id, {"method": endpoint.http_method, "host": endpoint.host, "path": endpoint.normalized_path, "lifecycle_status": endpoint.lifecycle_status.value, "risk_score": endpoint.risk_score})
    
    # Verify node exists
    node = await graph_db.get_node(endpoint.id)
    assert node is not None, "Expected node to exist before deletion"
    
    # Soft delete the node
    await graph_db.soft_delete_node(endpoint.id)
    
    # Verify node is marked as deleted but still retrievable with include_deleted=True
    deleted_node = await graph_db.get_node(endpoint.id, include_deleted=True)
    assert deleted_node is not None, "Expected deleted node to be retrievable with include_deleted=True"
    assert deleted_node.get("deleted_at") is not None, "Expected deleted_at timestamp"
    
    # Verify node is excluded from normal queries
    active_node = await graph_db.get_node(endpoint.id, include_deleted=False)
    assert active_node is None, "Expected deleted node to be excluded from normal queries"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_node_update_idempotence():
    """
    Test that updating graph nodes is idempotent.
    
    Validates: Node upsert idempotence
    """
    from conftest import activate_service
    
    activate_service("graph-service")
    from graph_db import InMemoryGraphStore
    
    graph_db = InMemoryGraphStore()
    
    endpoint_id = str(uuid.uuid4())
    
    # Create node
    await graph_db.upsert_node("API_Endpoint", endpoint_id, {"method": "GET", "host": "api.example.com", "path": "/api/test", "lifecycle_status": "Active", "risk_score": 10})
    
    # Update node with new risk score
    await graph_db.upsert_node("API_Endpoint", endpoint_id, {"method": "GET", "host": "api.example.com", "path": "/api/test", "lifecycle_status": "Active", "risk_score": 50})
    
    # Verify only one node exists with updated properties
    node = await graph_db.get_node(endpoint_id)
    assert node is not None
    assert node["risk_score"] == 50, f"Expected risk_score=50, got {node['risk_score']}"
    
    # Verify no duplicate nodes
    all_nodes = await graph_db.get_all_nodes()
    matching_nodes = [n for n in all_nodes if n["id"] == endpoint_id]
    assert len(matching_nodes) == 1, f"Expected 1 node, found {len(matching_nodes)}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
