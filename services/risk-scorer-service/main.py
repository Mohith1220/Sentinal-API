"""
Risk Scorer Service — SentinelAPI

Computes additive risk scores for API endpoints using four rules:
  - No authentication:              +40 pts
  - Sensitive data + weak auth:     +30 pts
  - Zombie or Orphaned lifecycle:   +20 pts
  - Abnormal traffic:               +10 pts

Score is capped at 100. Missing inputs use conservative defaults.

Routes:
  POST /score/{endpoint_id}          — on-demand scoring
  GET  /score/{endpoint_id}/history  — score history
"""

import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from sentinel_shared.health import health_router
from sentinel_shared.logging import CorrelationIDMiddleware, configure_logging, make_global_exception_handler
from sentinel_shared.metrics import setup_metrics

from db import RiskScorerDatabaseManager
from kafka_consumer import _kafka_consumer_loop
from scorer import compute_risk_score

SERVICE_NAME = "risk-scorer-service"
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN001
    configure_logging(SERVICE_NAME)

    # Initialize database
    db = RiskScorerDatabaseManager()
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
    title="SentinelAPI — Risk Scorer Service",
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


@app.post("/score/{endpoint_id}", summary="On-demand risk scoring")
async def score_endpoint(endpoint_id: str, request: Request) -> JSONResponse:
    """
    Trigger on-demand risk scoring for a single endpoint.

    Fetches the endpoint's current metadata, applies all four scoring rules,
    persists the result to risk_score_history, and updates api_endpoints.risk_score.
    """
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    endpoint_data = await db.get_endpoint(endpoint_id)
    if endpoint_data is None:
        raise HTTPException(
            status_code=404, detail=f"Endpoint {endpoint_id} not found"
        )

    result = compute_risk_score(endpoint_data)

    try:
        await db.insert_risk_score_history(result)
    except Exception as exc:
        logger.error(
            "persist_risk_score_failed",
            endpoint_id=endpoint_id,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail="Failed to persist risk score")

    logger.info(
        "endpoint_scored",
        endpoint_id=endpoint_id,
        score=result.score,
        factors=[f.rule for f in result.factors],
    )

    return JSONResponse(
        content={
            "endpoint_id": result.endpoint_id,
            "score": result.score,
            "factors": [f.model_dump() for f in result.factors],
            "computed_at": result.computed_at.isoformat(),
        },
        status_code=200,
    )


@app.get(
    "/score/{endpoint_id}/history",
    summary="Risk score history for an endpoint",
)
async def get_score_history(
    endpoint_id: str,
    request: Request,
    limit: int = 50,
) -> JSONResponse:
    """
    Return the risk score history for an endpoint, newest first.
    """
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    history = await db.get_risk_score_history(endpoint_id, limit=limit)
    return JSONResponse(
        content={"endpoint_id": endpoint_id, "history": history}
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8004, reload=False)
