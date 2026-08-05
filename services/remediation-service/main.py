"""
Remediation Service — SentinelAPI

Generates prioritized, human-readable and machine-readable remediation
recommendations for endpoints with Risk_Score >= 40.

Routes:
  GET  /recommendations/{endpoint_id}              — list recommendations for an endpoint
  POST /recommendations/{recommendation_id}/resolve — mark resolved
  GET  /recommendations                            — paginated list
"""

import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from sentinel_shared.health import health_router
from sentinel_shared.logging import CorrelationIDMiddleware, configure_logging, get_correlation_id, make_global_exception_handler
from sentinel_shared.metrics import setup_metrics

from db import RemediationDatabaseManager
from kafka_consumer import _kafka_consumer_loop, publish_remediated_event

SERVICE_NAME = "remediation-service"
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------


class ResolveRequest(BaseModel):
    resolved_by: str


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN001
    configure_logging(SERVICE_NAME)

    # Initialize database
    db = RemediationDatabaseManager()
    try:
        await db.connect()
        app.state.db = db
    except Exception as exc:
        logger.warning("db_init_failed", error=str(exc))
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
    title="SentinelAPI — Remediation Service",
    version="0.1.0",
    lifespan=lifespan,
)

# Middleware
app.add_middleware(CorrelationIDMiddleware)

# Metrics
setup_metrics(app, SERVICE_NAME)

# Routers
app.include_router(health_router)


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Log full error context and return a structured error response.
    """
    correlation_id = get_correlation_id()
    logger.error(
        "unhandled_exception",
        service=SERVICE_NAME,
        operation=str(request.url.path),
        method=request.method,
        error=str(exc),
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "correlation_id": correlation_id,
        },
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get(
    "/recommendations/{endpoint_id}",
    summary="List recommendations for an endpoint",
)
async def get_recommendations(endpoint_id: str, request: Request) -> JSONResponse:
    """
    Return all remediation recommendations for a given endpoint.
    """
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    recommendations = await db.get_recommendations(endpoint_id)
    return JSONResponse(
        content={
            "endpoint_id": endpoint_id,
            "recommendations": recommendations,
        }
    )


@app.post(
    "/recommendations/{recommendation_id}/resolve",
    summary="Mark a recommendation as resolved",
)
async def resolve_recommendation(
    recommendation_id: str,
    body: ResolveRequest,
    request: Request,
) -> JSONResponse:
    """
    Mark a remediation recommendation as resolved.

    Sets resolved_by and resolved_at, then publishes an endpoint.remediated
    event to Kafka so the risk scorer can re-evaluate the endpoint.
    """
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    updated = await db.resolve_recommendation(recommendation_id, body.resolved_by)
    if updated is None:
        raise HTTPException(
            status_code=404,
            detail=f"Recommendation {recommendation_id} not found",
        )

    # Publish endpoint.remediated event to Kafka
    endpoint_id = updated.get("endpoint_id", "")
    try:
        await publish_remediated_event(
            endpoint_id=endpoint_id,
            recommendation_id=recommendation_id,
            resolved_by=body.resolved_by,
        )
    except Exception as exc:
        logger.warning(
            "remediated_event_failed",
            recommendation_id=recommendation_id,
            error=str(exc),
        )

    logger.info(
        "recommendation_resolved",
        recommendation_id=recommendation_id,
        endpoint_id=endpoint_id,
        resolved_by=body.resolved_by,
    )

    return JSONResponse(content=updated)


@app.get(
    "/recommendations",
    summary="Paginated list of all recommendations",
)
async def list_recommendations(
    request: Request,
    cursor: str = None,
    limit: int = 50,
) -> JSONResponse:
    """
    Return a paginated list of all remediation recommendations.

    Query params:
        cursor: Opaque pagination cursor from a previous response.
        limit: Maximum number of items to return (default 50).
    """
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    result = await db.list_recommendations(cursor=cursor, limit=limit)
    return JSONResponse(content=result)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8006, reload=False)
