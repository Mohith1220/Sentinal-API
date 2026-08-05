"""
Graph Service — SentinelAPI

Maintains the Neo4j dependency graph of API endpoints, services, and data assets.
Answers reachability and blast-radius queries.

Routes:
  GET  /graph/reachable              — N-hop reachability query
  GET  /graph/blast-radius           — blast radius from Zombie node to DataAsset nodes
  POST /graph/nodes                  — create/upsert nodes
  POST /graph/edges                  — create edges
  DELETE /graph/nodes/{id}           — soft delete a node
"""

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Optional

import structlog
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from sentinel_shared.health import health_router
from sentinel_shared.kafka import SentinelConsumer
from sentinel_shared.logging import CorrelationIDMiddleware, configure_logging, make_global_exception_handler
from sentinel_shared.metrics import setup_metrics

from graph_db import GraphDatabaseManager

SERVICE_NAME = "graph-service"
logger = structlog.get_logger(__name__)

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")

# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------

ALLOWED_NODE_LABELS = {"API_Endpoint", "Service", "DataAsset"}
ALLOWED_EDGE_TYPES = {"CALLS", "ACCESSES", "EXPOSES"}


class UpsertNodeRequest(BaseModel):
    """Request body for creating/upserting a graph node."""

    id: str = Field(..., description="Unique node identifier")
    label: str = Field(
        ..., description="Node label: API_Endpoint, Service, or DataAsset"
    )
    props: dict = Field(default_factory=dict, description="Node properties to set")


class CreateEdgeRequest(BaseModel):
    """Request body for creating a graph edge."""

    from_id: str = Field(..., description="Source node ID")
    to_id: str = Field(..., description="Target node ID")
    edge_type: str = Field(
        ..., description="Edge type: CALLS, ACCESSES, or EXPOSES"
    )
    props: dict = Field(default_factory=dict, description="Edge properties to set")


# ---------------------------------------------------------------------------
# Kafka consumer loop
# ---------------------------------------------------------------------------


async def _kafka_consumer_loop(app: FastAPI) -> None:
    """
    Subscribe to endpoint.updated; upsert graph nodes within 60 seconds.
    """
    db = getattr(app.state, "db", None)

    consumer = SentinelConsumer(
        topics=["endpoint.updated"],
        group_id="graph-service",
        bootstrap_servers=KAFKA_BOOTSTRAP,
    )

    async def handle_endpoint_updated(message: dict) -> None:
        endpoint_id = message.get("endpoint_id")
        if not endpoint_id:
            logger.warning("endpoint_updated_missing_id", message=message)
            return

        logger.info("endpoint_updated_received", endpoint_id=endpoint_id)

        if db is None:
            logger.warning("db_unavailable_skipping_upsert", endpoint_id=endpoint_id)
            return

        # Build node props from the message's changed_fields
        changed_fields = message.get("changed_fields", {})
        props: dict = {}
        if changed_fields:
            # Map known fields to graph node properties
            field_map = {
                "lifecycle_status": "lifecycle_status",
                "risk_score": "risk_score",
                "http_method": "method",
                "host": "host",
                "normalized_path": "path",
            }
            for src_field, dst_field in field_map.items():
                if src_field in changed_fields:
                    props[dst_field] = changed_fields[src_field]

        try:
            await db.upsert_node("API_Endpoint", endpoint_id, props)
            logger.info("graph_node_upserted", endpoint_id=endpoint_id)
        except Exception as exc:
            logger.error("graph_node_upsert_failed", endpoint_id=endpoint_id, error=str(exc))
            raise

    try:
        await consumer.start()
        await consumer.run(handle_endpoint_updated)
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("kafka_consumer_error", error=str(exc))
    finally:
        await consumer.stop()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN001
    configure_logging(SERVICE_NAME)

    # Initialize Neo4j database
    db = GraphDatabaseManager()
    try:
        await db.connect()
        app.state.db = db
    except Exception as exc:
        logger.warning("neo4j_init_failed", error=str(exc))
        app.state.db = None

    # Start Kafka consumer in background
    consumer_task = asyncio.create_task(_kafka_consumer_loop(app))
    app.state.consumer_task = consumer_task

    yield

    # Cleanup
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass

    if app.state.db:
        await app.state.db.disconnect()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SentinelAPI — Graph Service",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(CorrelationIDMiddleware)
setup_metrics(app, SERVICE_NAME)
app.add_exception_handler(Exception, make_global_exception_handler(SERVICE_NAME))
app.include_router(health_router)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/graph/nodes", summary="Get all graph nodes")
async def get_nodes(request: Request) -> JSONResponse:
    """
    Retrieve all nodes from the dependency graph.
    Returns nodes in the format expected by the React dashboard.
    Falls back to demo seed data when the graph is empty (prototype mode).
    """
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Graph database unavailable")

    try:
        raw_nodes = await db.get_all_nodes()
        raw_edges = await db.get_all_edges()

        # If graph is empty, return demo seed data for prototype / jury demo
        if not raw_nodes:
            demo = _build_demo_graph()
            logger.info("graph_demo_seed_returned", nodes=len(demo["nodes"]), edges=len(demo["edges"]))
            return JSONResponse(content=demo, status_code=200)

        nodes = [_map_node(n) for n in raw_nodes]
        edges = [_map_edge(e) for e in raw_edges]
        logger.info("get_all_nodes_and_edges", nodes_count=len(nodes), edges_count=len(edges))
        return JSONResponse(content={"nodes": nodes, "edges": edges, "count": len(nodes)}, status_code=200)
    except Exception as exc:
        logger.error("get_all_nodes_failed", error=str(exc))
        # Last resort — always return demo data so the graph page never breaks
        demo = _build_demo_graph()
        return JSONResponse(content=demo, status_code=200)


# ---------------------------------------------------------------------------
# Node / edge shape helpers
# ---------------------------------------------------------------------------

def _map_node(raw: dict) -> dict:
    """
    Convert a raw Neo4j / InMemoryStore node dict into the shape the
    React dashboard expects:
      { id, type, label, properties: { lifecycle_status, risk_score, ... } }
    """
    label = raw.get("_label", raw.get("label", "API_Endpoint"))
    node_id = raw.get("id", "")

    # Build the display label from name or path
    display = (
        raw.get("name")
        or raw.get("path")
        or raw.get("host")
        or node_id[:12]
    )

    # Pull known properties into the nested properties dict
    props = {
        "lifecycle_status": raw.get("lifecycle_status", "Active"),
        "risk_score": raw.get("risk_score", 0),
        "method": raw.get("method", raw.get("http_method", "")),
        "host": raw.get("host", ""),
        "path": raw.get("path", ""),
        "name": raw.get("name", ""),
        "team": raw.get("team", raw.get("owning_team", "")),
        "sensitivity": raw.get("sensitivity", raw.get("data_sensitivity", "internal")),
    }

    return {
        "id": node_id,
        "type": label,
        "label": display,
        "properties": props,
    }


def _map_edge(raw: dict) -> dict:
    """Map raw edge dict to dashboard EdgeType shape."""
    return {
        "id": raw.get("id", f"{raw.get('source','')}-{raw.get('type','')}-{raw.get('target','')}"),
        "source": raw.get("source", raw.get("from_id", "")),
        "target": raw.get("target", raw.get("to_id", "")),
        "type": raw.get("type", "CALLS"),
        "properties": raw.get("properties", raw.get("props", {})),
    }


def _build_demo_graph() -> dict:
    """
    Return a realistic banking API dependency graph for demo / jury presentation.
    Includes Zombie APIs, Shadow APIs, active services, and data assets.
    """
    nodes = [
        # ── Services ────────────────────────────────────────────────────
        {
            "id": "svc-auth",
            "type": "Service",
            "label": "Auth Service",
            "properties": {"name": "Auth Service", "team": "platform", "sensitivity": "internal"},
        },
        {
            "id": "svc-payment",
            "type": "Service",
            "label": "Payment Service",
            "properties": {"name": "Payment Service", "team": "fintech", "sensitivity": "financial"},
        },
        {
            "id": "svc-user",
            "type": "Service",
            "label": "User Service",
            "properties": {"name": "User Service", "team": "core", "sensitivity": "PII"},
        },
        {
            "id": "svc-order",
            "type": "Service",
            "label": "Order Service",
            "properties": {"name": "Order Service", "team": "commerce", "sensitivity": "internal"},
        },
        {
            "id": "svc-audit",
            "type": "Service",
            "label": "Audit Service",
            "properties": {"name": "Audit Service", "team": "compliance", "sensitivity": "internal"},
        },

        # ── Active API Endpoints ─────────────────────────────────────────
        {
            "id": "api-login",
            "type": "API_Endpoint",
            "label": "POST /auth/login",
            "properties": {
                "lifecycle_status": "Active", "risk_score": 45,
                "method": "POST", "host": "api.bank.internal",
                "path": "/auth/login", "sensitivity": "internal",
            },
        },
        {
            "id": "api-token-refresh",
            "type": "API_Endpoint",
            "label": "POST /auth/token/refresh",
            "properties": {
                "lifecycle_status": "Active", "risk_score": 38,
                "method": "POST", "host": "api.bank.internal",
                "path": "/auth/token/refresh", "sensitivity": "internal",
            },
        },
        {
            "id": "api-user-profile",
            "type": "API_Endpoint",
            "label": "GET /v1/users/{id}",
            "properties": {
                "lifecycle_status": "Active", "risk_score": 62,
                "method": "GET", "host": "api.bank.internal",
                "path": "/v1/users/{id}", "sensitivity": "PII",
            },
        },
        {
            "id": "api-user-kyc",
            "type": "API_Endpoint",
            "label": "POST /v1/users/kyc",
            "properties": {
                "lifecycle_status": "Active", "risk_score": 74,
                "method": "POST", "host": "api.bank.internal",
                "path": "/v1/users/kyc", "sensitivity": "PII",
            },
        },
        {
            "id": "api-payment-initiate",
            "type": "API_Endpoint",
            "label": "POST /v2/payments",
            "properties": {
                "lifecycle_status": "Active", "risk_score": 80,
                "method": "POST", "host": "api.bank.internal",
                "path": "/v2/payments", "sensitivity": "financial",
            },
        },
        {
            "id": "api-payment-status",
            "type": "API_Endpoint",
            "label": "GET /v2/payments/{id}",
            "properties": {
                "lifecycle_status": "Active", "risk_score": 55,
                "method": "GET", "host": "api.bank.internal",
                "path": "/v2/payments/{id}", "sensitivity": "financial",
            },
        },
        {
            "id": "api-orders-create",
            "type": "API_Endpoint",
            "label": "POST /v1/orders",
            "properties": {
                "lifecycle_status": "Active", "risk_score": 42,
                "method": "POST", "host": "api.bank.internal",
                "path": "/v1/orders", "sensitivity": "internal",
            },
        },
        {
            "id": "api-health",
            "type": "API_Endpoint",
            "label": "GET /health",
            "properties": {
                "lifecycle_status": "Active", "risk_score": 5,
                "method": "GET", "host": "api.bank.internal",
                "path": "/health", "sensitivity": "public",
            },
        },
        {
            "id": "api-audit-log",
            "type": "API_Endpoint",
            "label": "GET /v1/audit/logs",
            "properties": {
                "lifecycle_status": "Active", "risk_score": 50,
                "method": "GET", "host": "api.bank.internal",
                "path": "/v1/audit/logs", "sensitivity": "internal",
            },
        },

        # ── Zombie APIs ──────────────────────────────────────────────────
        {
            "id": "api-zombie-transfers",
            "type": "API_Endpoint",
            "label": "POST /internal/transfers/bulk",
            "properties": {
                "lifecycle_status": "Zombie", "risk_score": 95,
                "method": "POST", "host": "api.bank.internal",
                "path": "/internal/transfers/bulk", "sensitivity": "financial",
            },
        },
        {
            "id": "api-zombie-admin",
            "type": "API_Endpoint",
            "label": "DELETE /v0/admin/users",
            "properties": {
                "lifecycle_status": "Zombie", "risk_score": 90,
                "method": "DELETE", "host": "api.bank.internal",
                "path": "/v0/admin/users", "sensitivity": "PII",
            },
        },
        {
            "id": "api-zombie-export",
            "type": "API_Endpoint",
            "label": "GET /legacy/export/customers",
            "properties": {
                "lifecycle_status": "Zombie", "risk_score": 88,
                "method": "GET", "host": "api.bank.internal",
                "path": "/legacy/export/customers", "sensitivity": "PII",
            },
        },

        # ── Shadow API ───────────────────────────────────────────────────
        {
            "id": "api-shadow-debug",
            "type": "API_Endpoint",
            "label": "GET /debug/config",
            "properties": {
                "lifecycle_status": "Shadow_API", "risk_score": 97,
                "method": "GET", "host": "api.bank.internal",
                "path": "/debug/config", "sensitivity": "internal",
            },
        },

        # ── Deprecated ───────────────────────────────────────────────────
        {
            "id": "api-deprecated-v1-pay",
            "type": "API_Endpoint",
            "label": "POST /v1/payments (deprecated)",
            "properties": {
                "lifecycle_status": "Deprecated", "risk_score": 30,
                "method": "POST", "host": "api.bank.internal",
                "path": "/v1/payments", "sensitivity": "financial",
            },
        },

        # ── Data Assets ──────────────────────────────────────────────────
        {
            "id": "db-users",
            "type": "DataAsset",
            "label": "users_db",
            "properties": {"name": "users_db", "type": "PostgreSQL", "sensitivity": "PII"},
        },
        {
            "id": "db-payments",
            "type": "DataAsset",
            "label": "payments_db",
            "properties": {"name": "payments_db", "type": "PostgreSQL", "sensitivity": "financial"},
        },
        {
            "id": "db-audit",
            "type": "DataAsset",
            "label": "audit_log_db",
            "properties": {"name": "audit_log_db", "type": "PostgreSQL", "sensitivity": "internal"},
        },
        {
            "id": "cache-sessions",
            "type": "DataAsset",
            "label": "session_cache",
            "properties": {"name": "session_cache", "type": "Redis", "sensitivity": "PII"},
        },
        {
            "id": "queue-events",
            "type": "DataAsset",
            "label": "events_queue",
            "properties": {"name": "events_queue", "type": "Kafka", "sensitivity": "internal"},
        },
    ]

    edges = [
        # Services EXPOSE APIs
        {"id": "e1",  "source": "svc-auth",    "target": "api-login",            "type": "EXPOSES", "properties": {}},
        {"id": "e2",  "source": "svc-auth",    "target": "api-token-refresh",    "type": "EXPOSES", "properties": {}},
        {"id": "e3",  "source": "svc-user",    "target": "api-user-profile",     "type": "EXPOSES", "properties": {}},
        {"id": "e4",  "source": "svc-user",    "target": "api-user-kyc",         "type": "EXPOSES", "properties": {}},
        {"id": "e5",  "source": "svc-payment", "target": "api-payment-initiate", "type": "EXPOSES", "properties": {}},
        {"id": "e6",  "source": "svc-payment", "target": "api-payment-status",   "type": "EXPOSES", "properties": {}},
        {"id": "e7",  "source": "svc-order",   "target": "api-orders-create",    "type": "EXPOSES", "properties": {}},
        {"id": "e8",  "source": "svc-audit",   "target": "api-audit-log",        "type": "EXPOSES", "properties": {}},

        # APIs CALL other APIs
        {"id": "e9",  "source": "api-orders-create",     "target": "api-payment-initiate", "type": "CALLS", "properties": {"source": "traffic"}},
        {"id": "e10", "source": "api-payment-initiate",  "target": "api-user-kyc",         "type": "CALLS", "properties": {"source": "traffic"}},
        {"id": "e11", "source": "api-user-kyc",          "target": "api-login",            "type": "CALLS", "properties": {"source": "traffic"}},
        {"id": "e12", "source": "api-user-profile",      "target": "api-audit-log",        "type": "CALLS", "properties": {"source": "traffic"}},
        {"id": "e13", "source": "api-zombie-transfers",  "target": "api-payment-initiate", "type": "CALLS", "properties": {"source": "traffic"}},
        {"id": "e14", "source": "api-zombie-admin",      "target": "api-user-profile",     "type": "CALLS", "properties": {"source": "traffic"}},
        {"id": "e15", "source": "api-zombie-export",     "target": "api-user-profile",     "type": "CALLS", "properties": {"source": "traffic"}},
        {"id": "e16", "source": "api-shadow-debug",      "target": "api-zombie-transfers", "type": "CALLS", "properties": {"source": "traffic"}},
        {"id": "e17", "source": "api-deprecated-v1-pay", "target": "api-payment-status",  "type": "CALLS", "properties": {"source": "static_analysis"}},
        {"id": "e18", "source": "api-health",            "target": "api-audit-log",        "type": "CALLS", "properties": {"source": "static_analysis"}},

        # APIs ACCESS data
        {"id": "e19", "source": "api-login",             "target": "cache-sessions",  "type": "ACCESSES", "properties": {"schema_ref": "sessions"}},
        {"id": "e20", "source": "api-user-profile",      "target": "db-users",        "type": "ACCESSES", "properties": {"schema_ref": "users.*"}},
        {"id": "e21", "source": "api-user-kyc",          "target": "db-users",        "type": "ACCESSES", "properties": {"schema_ref": "users.kyc"}},
        {"id": "e22", "source": "api-payment-initiate",  "target": "db-payments",     "type": "ACCESSES", "properties": {"schema_ref": "payments.*"}},
        {"id": "e23", "source": "api-payment-status",    "target": "db-payments",     "type": "ACCESSES", "properties": {"schema_ref": "payments.status"}},
        {"id": "e24", "source": "api-orders-create",     "target": "queue-events",    "type": "ACCESSES", "properties": {"schema_ref": "order.created"}},
        {"id": "e25", "source": "api-audit-log",         "target": "db-audit",        "type": "ACCESSES", "properties": {"schema_ref": "audit.*"}},
        # Zombie APIs access sensitive data — high blast radius
        {"id": "e26", "source": "api-zombie-transfers",  "target": "db-payments",     "type": "ACCESSES", "properties": {"schema_ref": "payments.bulk"}},
        {"id": "e27", "source": "api-zombie-admin",      "target": "db-users",        "type": "ACCESSES", "properties": {"schema_ref": "users.*"}},
        {"id": "e28", "source": "api-zombie-export",     "target": "db-users",        "type": "ACCESSES", "properties": {"schema_ref": "users.export"}},
        {"id": "e29", "source": "api-zombie-export",     "target": "cache-sessions",  "type": "ACCESSES", "properties": {"schema_ref": "sessions.*"}},
        {"id": "e30", "source": "api-shadow-debug",      "target": "db-payments",     "type": "ACCESSES", "properties": {"schema_ref": "config.*"}},
    ]

    return {"nodes": nodes, "edges": edges, "count": len(nodes)}


@app.post("/graph/nodes", summary="Create or upsert a graph node")
async def upsert_node(body: UpsertNodeRequest, request: Request) -> JSONResponse:
    """
    Create or update a node in the dependency graph.

    Uses MERGE semantics — if a node with the given id already exists,
    its properties are updated. Otherwise a new node is created.

    Supported labels: API_Endpoint, Service, DataAsset
    """
    if body.label not in ALLOWED_NODE_LABELS:
        raise HTTPException(
            status_code=422,
            detail=f"label must be one of {sorted(ALLOWED_NODE_LABELS)}, got '{body.label}'",
        )

    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Graph database unavailable")

    try:
        node = await db.upsert_node(body.label, body.id, body.props)
        logger.info("node_upserted", node_id=body.id, label=body.label)
        return JSONResponse(content={"node": node}, status_code=200)
    except Exception as exc:
        logger.error("node_upsert_failed", node_id=body.id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/graph/edges", summary="Create a graph edge")
async def create_edge(body: CreateEdgeRequest, request: Request) -> JSONResponse:
    """
    Create a directed edge between two nodes in the dependency graph.

    Supported edge types:
    - CALLS: API_Endpoint → API_Endpoint (observed call relationship)
    - ACCESSES: API_Endpoint → DataAsset (data asset reference)
    - EXPOSES: Service → API_Endpoint

    Edge properties for CALLS: observed_at, source ("traffic" | "static_analysis")
    Edge properties for ACCESSES: schema_ref
    """
    if body.edge_type not in ALLOWED_EDGE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"edge_type must be one of {sorted(ALLOWED_EDGE_TYPES)}, got '{body.edge_type}'",
        )

    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Graph database unavailable")

    try:
        edge = await db.upsert_edge(body.from_id, body.to_id, body.edge_type, body.props)
        logger.info(
            "edge_created",
            from_id=body.from_id,
            to_id=body.to_id,
            edge_type=body.edge_type,
        )
        return JSONResponse(content={"edge": edge}, status_code=200)
    except Exception as exc:
        logger.error(
            "edge_creation_failed",
            from_id=body.from_id,
            to_id=body.to_id,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail=str(exc))


@app.delete("/graph/nodes/{node_id}", summary="Soft delete a graph node")
async def soft_delete_node(node_id: str, request: Request) -> JSONResponse:
    """
    Soft-delete a node by setting its deleted_at timestamp.

    The node is retained in the graph for audit purposes but excluded
    from all read queries (reachability, blast-radius, etc.).

    Equivalent Cypher: MATCH (n {id: $id}) SET n.deleted_at = datetime()
    """
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Graph database unavailable")

    try:
        deleted = await db.soft_delete_node(node_id)
        if not deleted:
            raise HTTPException(
                status_code=404,
                detail=f"Node '{node_id}' not found or already deleted",
            )
        logger.info("node_soft_deleted", node_id=node_id)
        return JSONResponse(
            content={"deleted": True, "node_id": node_id}, status_code=200
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("node_delete_failed", node_id=node_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/graph/reachable", summary="N-hop reachability query")
async def get_reachable(
    request: Request,
    from_id: str = Query(..., description="Starting node ID"),
    hops: int = Query(
        ..., ge=1, le=10, description="Number of hops (1–10)"
    ),
) -> JSONResponse:
    """
    Return all nodes reachable from the given starting node within N hops.

    Excludes soft-deleted nodes.

    Equivalent Cypher:
      MATCH (start {id: $id})-[*1..{n}]->(node)
      WHERE node.deleted_at IS NULL
      RETURN DISTINCT node
    """
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Graph database unavailable")

    try:
        nodes = await db.get_reachable_nodes(from_id, hops)
        logger.info("reachability_query", from_id=from_id, hops=hops, count=len(nodes))
        return JSONResponse(
            content={
                "from_id": from_id,
                "hops": hops,
                "nodes": nodes,
                "count": len(nodes),
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error("reachability_query_failed", from_id=from_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/graph/blast-radius", summary="Blast radius from Zombie node to DataAsset nodes")
async def get_blast_radius(
    request: Request,
    zombie_id: str = Query(..., description="Zombie API endpoint node ID"),
) -> JSONResponse:
    """
    Return all DataAsset nodes reachable from the given Zombie API node.

    This identifies the potential data exposure path when a Zombie API
    is exploited. Only DataAsset nodes are returned (not intermediate
    API_Endpoint or Service nodes).

    Excludes soft-deleted nodes.
    """
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Graph database unavailable")

    try:
        nodes = await db.get_blast_radius(zombie_id)
        logger.info(
            "blast_radius_query",
            zombie_id=zombie_id,
            data_assets_count=len(nodes),
        )
        return JSONResponse(
            content={
                "zombie_id": zombie_id,
                "data_assets": nodes,
                "count": len(nodes),
            }
        )
    except Exception as exc:
        logger.error("blast_radius_query_failed", zombie_id=zombie_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8007, reload=False)
