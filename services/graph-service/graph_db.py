"""
Graph database layer for the Graph Service.

Provides:
- InMemoryGraphStore: in-memory store for unit tests (no live Neo4j).
- GraphDatabaseManager: async Neo4j store for production.

Both implement the same interface so the service layer can swap them.
"""

import os
from datetime import datetime, timezone
from typing import Optional, Any

import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# In-memory store (for unit tests and property tests)
# ---------------------------------------------------------------------------


class InMemoryGraphStore:
    """
    In-memory graph store for testing.

    Stores nodes and edges in plain dicts — no live Neo4j required.
    Supports soft deletes via deleted_at timestamp.
    """

    def __init__(self) -> None:
        # node_id -> dict with node fields (includes label)
        self._nodes: dict[str, dict] = {}
        # list of edge dicts: {from_id, to_id, type, props}
        self._edges: list[dict] = []

    def clear(self) -> None:
        """Reset all state (useful between tests)."""
        self._nodes.clear()
        self._edges.clear()

    async def connect(self) -> None:
        """No-op."""

    async def disconnect(self) -> None:
        """No-op."""

    # ------------------------------------------------------------------
    # Node operations
    # ------------------------------------------------------------------

    async def upsert_node(self, label: str, node_id: str, props: dict) -> dict:
        """
        Create or update a node with the given label and id.

        Equivalent to: MERGE (n:Label {id: $id}) SET n += $props
        """
        if node_id in self._nodes:
            # Update existing node (merge props)
            self._nodes[node_id].update(props)
            # Preserve label
            self._nodes[node_id]["_label"] = label
        else:
            self._nodes[node_id] = {"id": node_id, "_label": label, **props}
        return dict(self._nodes[node_id])

    async def get_node(self, node_id: str, include_deleted: bool = False) -> Optional[dict]:
        """Return the node dict or None. Excludes soft-deleted nodes unless include_deleted=True."""
        node = self._nodes.get(node_id)
        if node is None:
            return None
        if not include_deleted and node.get("deleted_at") is not None:
            return None
        return dict(node)
    
    async def get_all_nodes(self, include_deleted: bool = False) -> list[dict]:
        """Return all nodes. Excludes soft-deleted nodes unless include_deleted=True."""
        result = []
        for node in self._nodes.values():
            if include_deleted or node.get("deleted_at") is None:
                result.append(dict(node))
        return result

    async def soft_delete_node(self, node_id: str) -> bool:
        """
        Soft-delete a node by setting deleted_at = now().

        Returns True if the node was found and deleted, False otherwise.
        """
        node = self._nodes.get(node_id)
        if node is None:
            return False
        node["deleted_at"] = datetime.now(timezone.utc).isoformat()
        return True

    # ------------------------------------------------------------------
    # Edge operations
    # ------------------------------------------------------------------

    async def upsert_edge(
        self,
        from_id: str,
        to_id: str,
        edge_type: str,
        props: dict,
    ) -> dict:
        """
        Create or update an edge between two nodes.

        Equivalent to:
          MATCH (a {id: $from}), (b {id: $to})
          MERGE (a)-[:TYPE {key_props}]->(b)
          SET r += $props
        """
        # Find existing edge
        for edge in self._edges:
            if (
                edge["from"] == from_id
                and edge["to"] == to_id
                and edge["type"] == edge_type
            ):
                edge["props"].update(props)
                return dict(edge)

        # Create new edge
        edge = {
            "from": from_id,
            "to": to_id,
            "type": edge_type,
            "props": dict(props),
        }
        self._edges.append(edge)
        return dict(edge)

    async def get_edges_for_node(self, node_id: str) -> list[dict]:
        """Return all edges where the node is either source or target."""
        return [
            dict(e)
            for e in self._edges
            if e["from"] == node_id or e["to"] == node_id
        ]

    async def get_all_edges(self) -> list[dict]:
        """Return all edges mapped to standard frontend schema."""
        result = []
        for e in self._edges:
            s_node = self._nodes.get(e["from"])
            t_node = self._nodes.get(e["to"])
            if (s_node and s_node.get("deleted_at") is None) and (t_node and t_node.get("deleted_at") is None):
                result.append({
                    "id": f"{e['from']}-{e['type']}-{e['to']}",
                    "source": e["from"],
                    "target": e["to"],
                    "type": e["type"],
                    "properties": dict(e["props"]),
                })
        return result

    # ------------------------------------------------------------------
    # Reachability queries
    # ------------------------------------------------------------------

    async def get_reachable_nodes(
        self,
        start_id: str,
        hops: int,
    ) -> list[dict]:
        """
        Return all nodes reachable from start_id within `hops` directed hops.

        Excludes soft-deleted nodes.
        Equivalent to:
          MATCH (start {id: $id})-[*1..{n}]->(node)
          WHERE node.deleted_at IS NULL
          RETURN DISTINCT node
        """
        if hops < 1 or hops > 10:
            raise ValueError(f"hops must be in [1, 10], got {hops}")

        visited: set[str] = set()
        frontier: set[str] = {start_id}
        reachable: set[str] = set()

        for _ in range(hops):
            next_frontier: set[str] = set()
            for node_id in frontier:
                # Find all outgoing edges from this node
                for edge in self._edges:
                    if edge["from"] == node_id:
                        target_id = edge["to"]
                        if target_id not in visited and target_id != start_id:
                            next_frontier.add(target_id)
                            reachable.add(target_id)
            visited.update(frontier)
            frontier = next_frontier - visited
            if not frontier:
                break

        # Return non-deleted nodes
        result = []
        for node_id in reachable:
            node = self._nodes.get(node_id)
            if node is not None and node.get("deleted_at") is None:
                result.append(dict(node))

        return result

    async def get_blast_radius(self, zombie_id: str) -> list[dict]:
        """
        Return all DataAsset nodes reachable from the given Zombie node.

        Equivalent to N-hop reachability filtered to DataAsset label only.
        """
        all_reachable = await self.get_reachable_nodes(zombie_id, hops=10)
        return [n for n in all_reachable if n.get("_label") == "DataAsset"]


# ---------------------------------------------------------------------------
# Neo4j store (for production)
# ---------------------------------------------------------------------------


class GraphDatabaseManager:
    """Manages async Neo4j connections for the graph service."""

    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        self.uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = user or os.getenv("NEO4J_USER", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD", "sentinel_secret")
        self._driver: Optional[Any] = None

    async def connect(self) -> None:
        from neo4j import AsyncGraphDatabase

        try:
            self._driver = AsyncGraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password),
            )
            # Verify connectivity
            await self._driver.verify_connectivity()
            logger.info("neo4j_connected", uri=self.uri)
        except Exception as exc:
            logger.warning("neo4j_connection_failed", error=str(exc))
            self._driver = None

    async def disconnect(self) -> None:
        if self._driver:
            await self._driver.close()
            logger.info("neo4j_disconnected")

    async def upsert_node(self, label: str, node_id: str, props: dict) -> dict:
        """
        Create or update a node using MERGE.

        Cypher: MERGE (n:Label {id: $id}) SET n += $props RETURN n
        """
        if not self._driver:
            raise RuntimeError("Neo4j not connected")

        # Build safe label (only allow known labels)
        _ALLOWED_LABELS = {"API_Endpoint", "Service", "DataAsset"}
        if label not in _ALLOWED_LABELS:
            raise ValueError(f"Unknown node label: {label}")

        query = f"""
            MERGE (n:{label} {{id: $id}})
            SET n += $props
            RETURN n
        """
        async with self._driver.session() as session:
            result = await session.run(query, id=node_id, props=props)
            record = await result.single()
            if record is None:
                raise RuntimeError(f"Failed to upsert node {node_id}")
            node = dict(record["n"])
            node["_label"] = label
            return node

    async def get_node(self, node_id: str) -> Optional[dict]:
        """Return the node dict or None. Excludes soft-deleted nodes."""
        if not self._driver:
            raise RuntimeError("Neo4j not connected")

        query = """
            MATCH (n {id: $id})
            WHERE n.deleted_at IS NULL
            RETURN n, labels(n)[0] AS label
        """
        async with self._driver.session() as session:
            result = await session.run(query, id=node_id)
            record = await result.single()
            if record is None:
                return None
            node = dict(record["n"])
            node["_label"] = record["label"]
            return node

    async def get_all_nodes(self) -> list[dict]:
        """Return all nodes. Excludes soft-deleted nodes."""
        if not self._driver:
            raise RuntimeError("Neo4j not connected")

        query = """
            MATCH (n)
            WHERE n.deleted_at IS NULL
            RETURN n, labels(n)[0] AS label
        """
        async with self._driver.session() as session:
            result = await session.run(query)
            nodes = []
            async for record in result:
                node = dict(record["n"])
                node["_label"] = record["label"]
                nodes.append(node)
            return nodes

    async def get_all_edges(self) -> list[dict]:
        """Return all edges in the Neo4j database mapped to standard frontend schema."""
        if not self._driver:
            raise RuntimeError("Neo4j not connected")

        query = """
            MATCH (a)-[r]->(b)
            WHERE a.deleted_at IS NULL AND b.deleted_at IS NULL
            RETURN type(r) AS edge_type,
                   a.id AS from_id,
                   b.id AS to_id,
                   properties(r) AS props
        """
        async with self._driver.session() as session:
            result = await session.run(query)
            edges = []
            async for record in result:
                edges.append(
                    {
                        "id": f"{record['from_id']}-{record['edge_type']}-{record['to_id']}",
                        "source": record["from_id"],
                        "target": record["to_id"],
                        "type": record["edge_type"],
                        "properties": dict(record["props"]),
                    }
                )
            return edges

    async def soft_delete_node(self, node_id: str) -> bool:
        """Soft-delete a node by setting deleted_at = datetime()."""
        if not self._driver:
            raise RuntimeError("Neo4j not connected")

        query = """
            MATCH (n {id: $id})
            WHERE n.deleted_at IS NULL
            SET n.deleted_at = datetime()
            RETURN n
        """
        async with self._driver.session() as session:
            result = await session.run(query, id=node_id)
            record = await result.single()
            return record is not None

    async def upsert_edge(
        self,
        from_id: str,
        to_id: str,
        edge_type: str,
        props: dict,
    ) -> dict:
        """
        Create or update an edge between two nodes.

        Supports CALLS and ACCESSES edge types.
        """
        if not self._driver:
            raise RuntimeError("Neo4j not connected")

        _ALLOWED_EDGE_TYPES = {"CALLS", "ACCESSES", "EXPOSES"}
        if edge_type not in _ALLOWED_EDGE_TYPES:
            raise ValueError(f"Unknown edge type: {edge_type}")

        if edge_type == "CALLS":
            query = """
                MATCH (a:API_Endpoint {id: $from_id}), (b:API_Endpoint {id: $to_id})
                MERGE (a)-[r:CALLS]->(b)
                SET r += $props
                RETURN r
            """
        elif edge_type == "ACCESSES":
            query = """
                MATCH (a:API_Endpoint {id: $from_id}), (b:DataAsset {id: $to_id})
                MERGE (a)-[r:ACCESSES]->(b)
                SET r += $props
                RETURN r
            """
        else:  # EXPOSES
            query = """
                MATCH (a:Service {id: $from_id}), (b:API_Endpoint {id: $to_id})
                MERGE (a)-[r:EXPOSES]->(b)
                SET r += $props
                RETURN r
            """

        async with self._driver.session() as session:
            result = await session.run(
                query, from_id=from_id, to_id=to_id, props=props
            )
            record = await result.single()
            if record is None:
                raise RuntimeError(
                    f"Failed to create edge {from_id} -[{edge_type}]-> {to_id}. "
                    "Ensure both nodes exist."
                )
            return {
                "from_id": from_id,
                "to_id": to_id,
                "type": edge_type,
                "props": dict(record["r"]),
            }

    async def get_edges_for_node(self, node_id: str) -> list[dict]:
        """Return all edges where the node is either source or target."""
        if not self._driver:
            raise RuntimeError("Neo4j not connected")

        query = """
            MATCH (n {id: $id})-[r]-(m)
            RETURN type(r) AS edge_type,
                   startNode(r).id AS from_id,
                   endNode(r).id AS to_id,
                   properties(r) AS props
        """
        async with self._driver.session() as session:
            result = await session.run(query, id=node_id)
            edges = []
            async for record in result:
                edges.append(
                    {
                        "from_id": record["from_id"],
                        "to_id": record["to_id"],
                        "type": record["edge_type"],
                        "props": dict(record["props"]),
                    }
                )
            return edges

    async def get_reachable_nodes(
        self,
        start_id: str,
        hops: int,
    ) -> list[dict]:
        """
        Return all nodes reachable from start_id within `hops` directed hops.

        Excludes soft-deleted nodes.
        Cypher: MATCH (start {id: $id})-[*1..{n}]->(node)
                WHERE node.deleted_at IS NULL
                RETURN DISTINCT node
        """
        if not self._driver:
            raise RuntimeError("Neo4j not connected")

        if hops < 1 or hops > 10:
            raise ValueError(f"hops must be in [1, 10], got {hops}")

        query = f"""
            MATCH (start {{id: $id}})-[*1..{hops}]->(node)
            WHERE node.deleted_at IS NULL
            RETURN DISTINCT node, labels(node)[0] AS label
        """
        async with self._driver.session() as session:
            result = await session.run(query, id=start_id)
            nodes = []
            async for record in result:
                node = dict(record["node"])
                node["_label"] = record["label"]
                nodes.append(node)
            return nodes

    async def get_blast_radius(self, zombie_id: str) -> list[dict]:
        """
        Return all DataAsset nodes reachable from the given Zombie node.

        Cypher: MATCH (start {id: $id})-[*1..10]->(node:DataAsset)
                WHERE node.deleted_at IS NULL
                RETURN DISTINCT node
        """
        if not self._driver:
            raise RuntimeError("Neo4j not connected")

        query = """
            MATCH (start {id: $id})-[*1..10]->(node:DataAsset)
            WHERE node.deleted_at IS NULL
            RETURN DISTINCT node
        """
        async with self._driver.session() as session:
            result = await session.run(query, id=zombie_id)
            nodes = []
            async for record in result:
                node = dict(record["node"])
                node["_label"] = "DataAsset"
                nodes.append(node)
            return nodes
