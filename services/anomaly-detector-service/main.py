"""
Anomaly Detector Service — SentinelAPI

Trains per-endpoint PyTorch LSTM baselines on traffic history.
Detects deviations and emits anomaly alerts with SHAP explainability.

Routes:
  GET /baselines/{endpoint_id}  — retrieve baseline info for an endpoint
  GET /alerts                   — list anomaly alerts (optionally filtered)
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

import structlog
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from sentinel_shared.health import health_router
from sentinel_shared.kafka import SentinelConsumer
from sentinel_shared.logging import CorrelationIDMiddleware, configure_logging, make_global_exception_handler
from sentinel_shared.metrics import setup_metrics

from anomaly_service import evaluate_anomalies, resolve_baseline
from db import AnomalyDatabaseManager

SERVICE_NAME = "anomaly-detector-service"
logger = structlog.get_logger(__name__)

KAFKA_BOOTSTRAP = "kafka:9092"


# ---------------------------------------------------------------------------
# Kafka consumer loop
# ---------------------------------------------------------------------------


async def _kafka_consumer_loop(app: FastAPI) -> None:
    """
    Subscribe to endpoint.updated; trigger anomaly evaluation for changed endpoints.
    """
    db = getattr(app.state, "db", None)
    kafka_producer = getattr(app.state, "kafka_producer", None)

    consumer = SentinelConsumer(
        topics=["endpoint.updated"],
        group_id="anomaly-detector-service",
        bootstrap_servers=KAFKA_BOOTSTRAP,
    )

    async def handle_endpoint_updated(message: dict) -> None:
        endpoint_id = message.get("endpoint_id")
        if not endpoint_id:
            logger.warning("endpoint_updated_missing_id", message=message)
            return
        logger.info("endpoint_updated_received", endpoint_id=endpoint_id)
        # Evaluate anomalies with the latest traffic data from the message
        traffic_event = message.get("traffic_event", {})
        if traffic_event:
            await evaluate_anomalies(
                endpoint_id=endpoint_id,
                traffic_event=traffic_event,
                db=db,
                kafka_producer=kafka_producer,
            )

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

    # Initialize database
    db = AnomalyDatabaseManager()
    try:
        await db.connect()
        app.state.db = db
    except Exception as exc:
        logger.warning("db_init_failed", error=str(exc))
        app.state.db = None

    # Initialize Kafka producer
    from sentinel_shared.kafka import SentinelProducer

    kafka_producer = SentinelProducer(bootstrap_servers=KAFKA_BOOTSTRAP)
    try:
        await kafka_producer.start()
        app.state.kafka_producer = kafka_producer
    except Exception as exc:
        logger.warning("kafka_producer_init_failed", error=str(exc))
        app.state.kafka_producer = None

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

    if app.state.kafka_producer:
        await app.state.kafka_producer.stop()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SentinelAPI — Anomaly Detector Service",
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


@app.get("/baselines/{endpoint_id}", summary="Get baseline info for an endpoint")
async def get_baseline(endpoint_id: str, request: Request) -> JSONResponse:
    """
    Retrieve the current baseline model info for an endpoint.

    Returns the individual baseline if training_days >= 7, otherwise
    returns the cluster baseline (cold-start fallback).
    """
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    baseline = await resolve_baseline(endpoint_id, db)
    if baseline is None:
        raise HTTPException(
            status_code=404,
            detail=f"No baseline found for endpoint {endpoint_id}",
        )

    # Don't return the raw model artifact bytes in the API response
    response_data = {k: v for k, v in baseline.items() if k != "model_artifact"}
    response_data["has_model_artifact"] = bool(baseline.get("model_artifact"))

    return JSONResponse(content=response_data)


@app.get("/alerts", summary="List anomaly alerts")
async def list_alerts(
    request: Request,
    endpoint_id: Optional[str] = Query(default=None, description="Filter by endpoint ID"),
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum number of alerts"),
) -> JSONResponse:
    """
    Return anomaly alerts, optionally filtered by endpoint_id.

    Results are sorted by emitted_at descending (newest first).
    """
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    alerts = await db.list_alerts(endpoint_id=endpoint_id, limit=limit)
    return JSONResponse(
        content={
            "alerts": alerts,
            "count": len(alerts),
        }
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8005, reload=False)
