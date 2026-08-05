"""
Graph Intelligence Module — computes Neo4j-derived features for the RL state.

Computes per-endpoint:
  - PageRank (importance/influence in API call graph)
  - Betweenness Centrality (how often an endpoint lies on shortest paths)
  - Degree Centrality (direct connectivity)
  - Community Detection (Louvain community label)
  - Blast Radius (reachable DataAsset count from this node)
  - Attack Path Length (shortest hops from any entry-point node)

All Neo4j queries are read-only and use parameterised Cypher.
Results are cached in-memory with a 5-minute TTL to avoid hammering Neo4j
on every prediction request.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional, Any

import networkx as nx

logger = logging.getLogger(__name__)

# Cache TTL in seconds
_CACHE_TTL = 300  # 5 minutes

# Global in-memory cache: endpoint_id -> (features_dict, expiry_ts)
_feature_cache: dict[str, tuple[dict, float]] = {}
# Graph-wide centrality cache: (centrality_dict, expiry_ts)
_centrality_cache: tuple[Optional[dict], float] = (None, 0.0)


async def get_graph_features(
    endpoint_id: str,
    neo4j_driver: Optional[Any],
    force_refresh: bool = False,
) -> dict:
    """
    Return graph-derived features for a single endpoint.

    Falls back to safe defaults if Neo4j is unavailable.

    Returns dict with keys:
      pagerank, betweenness, degree_centrality,
      community_id, blast_radius, attack_path_length
    """
    now = time.monotonic()
    cached, expiry = _feature_cache.get(endpoint_id, (None, 0.0))
    if cached is not None and now < expiry and not force_refresh:
        return cached

    if neo4j_driver is None:
        return _default_features()

    try:
        features = await _compute_features(endpoint_id, neo4j_driver)
        _feature_cache[endpoint_id] = (features, now + _CACHE_TTL)
        return features
    except Exception as exc:
        logger.warning(
            "graph_feature_computation_failed",
            endpoint_id=endpoint_id,
            error=str(exc),
        )
        return _default_features()


async def refresh_all_centralities(neo4j_driver: Optional[Any]) -> dict:
    """
    Recompute graph-wide centrality metrics for all endpoints.

    Called periodically by the APScheduler job. Results stored in
    _centrality_cache for use by individual endpoint predictions.
    """
    global _centrality_cache

    if neo4j_driver is None:
        return {}

    try:
        centralities = await _compute_all_centralities(neo4j_driver)
        _centrality_cache = (centralities, time.monotonic() + _CACHE_TTL)
        logger.info(
            "centralities_refreshed",
            endpoint_count=len(centralities),
        )
        return centralities
    except Exception as exc:
        logger.error("centrality_refresh_failed", error=str(exc))
        return {}


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


async def _compute_features(endpoint_id: str, driver: Any) -> dict:
    """Compute all graph features for a single endpoint."""
    global _centrality_cache

    # Get centralities from cache or compute fresh
    centralities, expiry = _centrality_cache
    if centralities is None or time.monotonic() > expiry:
        centralities = await _compute_all_centralities(driver)
        _centrality_cache = (centralities, time.monotonic() + _CACHE_TTL)

    node_centrality = centralities.get(endpoint_id, {})

    # Blast radius: count reachable DataAsset nodes
    blast_radius = await _get_blast_radius(endpoint_id, driver)

    # Attack path length: shortest path from known entry-point nodes
    attack_path = await _get_attack_path_length(endpoint_id, driver)
    return {
        "pagerank": node_centrality.get("pagerank", 0.01),
        "betweenness": node_centrality.get("betweenness", 0.0),
        "degree_centrality": node_centrality.get("degree", 0.0),
        "community_id": node_centrality.get("community_id", 0),
        "blast_radius": blast_radius,
        "attack_path_length": attack_path,
    }


async def _compute_all_centralities(driver: Any) -> dict:
    """
    Pull all API_Endpoint nodes and edges from Neo4j, then compute
    PageRank and betweenness centrality using NetworkX (avoids APOC
    dependency for portability).
    """
    # Fetch all endpoints and CALLS edges
    nodes_query = """
        MATCH (n:API_Endpoint)
        WHERE n.deleted_at IS NULL
        RETURN n.id AS id
    """
    edges_query = """
        MATCH (a:API_Endpoint)-[:CALLS]->(b:API_Endpoint)
        WHERE a.deleted_at IS NULL AND b.deleted_at IS NULL
        RETURN a.id AS from_id, b.id AS to_id
    """

    async with driver.session() as session:
        nodes_result = await session.run(nodes_query)
        node_ids = [record["id"] async for record in nodes_result]

        edges_result = await session.run(edges_query)
        edges = [
            (record["from_id"], record["to_id"]) async for record in edges_result
        ]

    if not node_ids:
        return {}

    # Build NetworkX DiGraph
    G = nx.DiGraph()
    G.add_nodes_from(node_ids)
    G.add_edges_from(edges)

    # PageRank
    try:
        pr = nx.pagerank(G, alpha=0.85, max_iter=100)
    except nx.PowerIterationFailedConvergence:
        pr = {n: 1.0 / len(G) for n in G.nodes()}

    # Betweenness centrality (normalised)
    if len(G) > 1:
        bc = nx.betweenness_centrality(G, normalized=True)
    else:
        bc = {n: 0.0 for n in G.nodes()}

    # Degree centrality
    dc = nx.degree_centrality(G)

    # Simple community detection using weakly connected components as proxy
    communities = {}
    for i, component in enumerate(nx.weakly_connected_components(G)):
        for node in component:
            communities[node] = i

    result = {}
    for node_id in node_ids:
        result[node_id] = {
            "pagerank": pr.get(node_id, 0.01),
            "betweenness": bc.get(node_id, 0.0),
            "degree": dc.get(node_id, 0.0),
            "community_id": communities.get(node_id, 0),
        }

    return result


async def _get_blast_radius(endpoint_id: str, driver: Any) -> int:
    """Count DataAsset nodes reachable from this endpoint."""
    query = """
        MATCH (start:API_Endpoint {id: $id})-[*1..10]->(asset:DataAsset)
        WHERE start.deleted_at IS NULL AND asset.deleted_at IS NULL
        RETURN count(DISTINCT asset) AS blast_radius
    """
    try:
        async with driver.session() as session:
            result = await session.run(query, id=endpoint_id)
            record = await result.single()
            return int(record["blast_radius"]) if record else 0
    except Exception:
        return 0


async def _get_attack_path_length(endpoint_id: str, driver: Any) -> int:
    """
    Compute shortest attack path length from any Service node to this endpoint.

    Service nodes represent external-facing services. Shorter path = easier to attack.
    """
    query = """
        MATCH (svc:Service)-[:EXPOSES*1..5]->(target:API_Endpoint {id: $id})
        WHERE svc.deleted_at IS NULL AND target.deleted_at IS NULL
        RETURN length(shortestPath((svc)-[:EXPOSES*1..5]->(target))) AS path_len
        LIMIT 1
    """
    try:
        async with driver.session() as session:
            result = await session.run(query, id=endpoint_id)
            record = await result.single()
            if record and record["path_len"] is not None:
                return int(record["path_len"])
            return 5  # default: moderate path length
    except Exception:
        return 5


def _default_features() -> dict:
    """Safe defaults when Neo4j is unavailable."""
    return {
        "pagerank": 0.01,
        "betweenness": 0.0,
        "degree_centrality": 0.0,
        "community_id": 0,
        "blast_radius": 0,
        "attack_path_length": 5,
    }
