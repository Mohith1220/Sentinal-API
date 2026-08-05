"""
Classification Service — SentinelAPI

Applies rule-based and ML lifecycle classification to API endpoints.
Manages classification history and human override records.

Routes:
  POST /classify/{endpoint_id}           — on-demand classification
  GET  /classification/{endpoint_id}/history — classification history
  POST /classify/{endpoint_id}/override  — manual override
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from sentinel_shared.health import health_router
from sentinel_shared.logging import CorrelationIDMiddleware, configure_logging, make_global_exception_handler
from sentinel_shared.metrics import setup_metrics

from sentinel_shared.kafka import SentinelConsumer, SentinelProducer
from sentinel_shared.models import LifecycleStatus

from classifier import classify_endpoint
from db import ClassificationDatabaseManager

SERVICE_NAME = "classification-service"
logger = structlog.get_logger(__name__)

KAFKA_BOOTSTRAP = "kafka:9092"
BATCH_SIZE = 500


# ---------------------------------------------------------------------------
# Background jobs
# ---------------------------------------------------------------------------


async def _reclassify_all(app: FastAPI) -> None:
    """APScheduler job: re-classify all endpoints in batches of 500."""
    db = getattr(app.state, "db", None)
    kafka = getattr(app.state, "kafka_producer", None)
    if db is None:
        logger.warning("reclassify_all_skipped", reason="no_db")
        return

    try:
        all_ids = await db.list_all_endpoint_ids()
        total = len(all_ids)
        classified = 0
        for i in range(0, total, BATCH_SIZE):
            batch = all_ids[i : i + BATCH_SIZE]
            for endpoint_id in batch:
                try:
                    await classify_endpoint(endpoint_id, db, kafka)
                    classified += 1
                except Exception as exc:
                    logger.error(
                        "batch_classify_error",
                        endpoint_id=endpoint_id,
                        error=str(exc),
                    )
        logger.info("reclassify_all_complete", total=total, classified=classified)
    except Exception as exc:
        logger.error("reclassify_all_failed", error=str(exc))


async def _kafka_consumer_loop(app: FastAPI) -> None:
    """
    Subscribe to endpoint.updated; trigger re-classification for changed endpoints.
    """
    db = getattr(app.state, "db", None)
    kafka_producer = getattr(app.state, "kafka_producer", None)

    consumer = SentinelConsumer(
        topics=["endpoint.updated"],
        group_id="classification-service",
        bootstrap_servers=KAFKA_BOOTSTRAP,
    )

    async def handle_endpoint_updated(message: dict) -> None:
        endpoint_id = message.get("endpoint_id")
        if not endpoint_id:
            logger.warning("endpoint_updated_missing_id", message=message)
            return
        logger.info("endpoint_updated_received", endpoint_id=endpoint_id)
        await classify_endpoint(endpoint_id, db, kafka_producer)

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
    db = ClassificationDatabaseManager()
    try:
        await db.connect()
        app.state.db = db
    except Exception as exc:
        logger.warning("db_init_failed", error=str(exc))
        app.state.db = None

    # Initialize Kafka producer
    kafka_producer = SentinelProducer(bootstrap_servers=KAFKA_BOOTSTRAP)
    try:
        await kafka_producer.start()
        app.state.kafka_producer = kafka_producer
    except Exception as exc:
        logger.warning("kafka_producer_init_failed", error=str(exc))
        app.state.kafka_producer = None

    # Start APScheduler: re-classify all endpoints every 24 hours
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _reclassify_all,
        trigger="interval",
        hours=24,
        args=[app],
        id="reclassify_all",
        replace_existing=True,
    )
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info("scheduler_started", job="reclassify_all", interval_hours=24)

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

    scheduler.shutdown(wait=False)

    if app.state.db:
        await app.state.db.disconnect()

    if app.state.kafka_producer:
        await app.state.kafka_producer.stop()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SentinelAPI — Classification Service",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(CorrelationIDMiddleware)
setup_metrics(app, SERVICE_NAME)
app.add_exception_handler(Exception, make_global_exception_handler(SERVICE_NAME))
app.include_router(health_router)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class OverrideRequest(BaseModel):
    override_by: str
    new_status: LifecycleStatus
    override_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.post("/classify/{endpoint_id}", summary="On-demand classification")
async def classify(endpoint_id: str, request: Request) -> JSONResponse:
    """
    Trigger on-demand classification for a single endpoint.

    Runs the rule engine and ML classifier, writes the authoritative
    rule-based status to api_endpoints.lifecycle_status, and stores
    both results in classification_history.
    """
    db = getattr(request.app.state, "db", None)
    kafka = getattr(request.app.state, "kafka_producer", None)

    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    result = await classify_endpoint(endpoint_id, db, kafka)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Endpoint {endpoint_id} not found")

    return JSONResponse(content=result, status_code=200)


@app.get(
    "/classification/{endpoint_id}/history",
    summary="Classification history for an endpoint",
)
async def get_classification_history(
    endpoint_id: str,
    request: Request,
    limit: int = 50,
) -> JSONResponse:
    """
    Return the classification history for an endpoint, newest first.
    """
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    history = await db.get_classification_history(endpoint_id, limit=limit)
    return JSONResponse(content={"endpoint_id": endpoint_id, "history": history})


@app.post(
    "/classify/{endpoint_id}/override",
    summary="Manual classification override",
)
async def override_classification(
    endpoint_id: str,
    body: OverrideRequest,
    request: Request,
) -> JSONResponse:
    """
    Record a manual classification override.

    Stores override_by, previous status, new status, and timestamp in
    classification_history. Updates api_endpoints.lifecycle_status to the
    new (overridden) status.
    """
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    endpoint = await db.get_endpoint(endpoint_id)
    if endpoint is None:
        raise HTTPException(status_code=404, detail=f"Endpoint {endpoint_id} not found")

    previous_status_str = endpoint.get("lifecycle_status", LifecycleStatus.ACTIVE.value)
    # Normalise to LifecycleStatus enum
    try:
        previous_status = LifecycleStatus(previous_status_str)
    except ValueError:
        previous_status = LifecycleStatus.ACTIVE

    # Update lifecycle_status to the overridden value
    await db.update_lifecycle_status(endpoint_id, body.new_status)

    # Record override in classification_history
    history_id = await db.insert_classification_history(
        endpoint_id=endpoint_id,
        rule_status=body.new_status,
        ml_status=None,
        ml_confidence=None,
        override_by=body.override_by,
        override_reason=body.override_reason,
    )

    logger.info(
        "classification_overridden",
        endpoint_id=endpoint_id,
        override_by=body.override_by,
        previous_status=previous_status.value,
        new_status=body.new_status.value,
    )

    return JSONResponse(
        content={
            "endpoint_id": endpoint_id,
            "previous_status": previous_status.value,
            "new_status": body.new_status.value,
            "override_by": body.override_by,
            "override_reason": body.override_reason,
            "history_id": history_id,
        },
        status_code=200,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8003, reload=False)
