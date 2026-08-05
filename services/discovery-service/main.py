"""
Discovery Service — SentinelAPI

Parses OpenAPI/Swagger files, GitHub repos, gateway configs, and gateway logs.
Normalizes, deduplicates, and upserts endpoint records into the API Inventory.
"""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from sentinel_shared.health import health_router
from sentinel_shared.logging import CorrelationIDMiddleware, configure_logging, make_global_exception_handler
from sentinel_shared.metrics import setup_metrics

from db import DatabaseManager
from kafka_publisher import KafkaPublisher
from routers.discover import discover_router
from routers.endpoints import endpoints_router

SERVICE_NAME = "discovery-service"
logger = structlog.get_logger(__name__)


async def _run_staleness_check(app: FastAPI) -> None:
    """Background job: mark endpoints stale when last_access_at < NOW() - 90 days."""
    db = getattr(app.state, "db", None)
    if db is None:
        logger.warning("staleness_check_skipped", reason="no_db")
        return
    try:
        count = await db.mark_stale_endpoints()
        logger.info("staleness_check_complete", marked_stale=count)
    except Exception as exc:
        logger.error("staleness_check_failed", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN001
    configure_logging(SERVICE_NAME)

    # Initialize database
    db = DatabaseManager()
    try:
        await db.connect()
        app.state.db = db
    except Exception as exc:
        logger.warning("db_init_failed", error=str(exc))
        app.state.db = None

    # Initialize Kafka publisher
    kafka = KafkaPublisher()
    try:
        await kafka.connect()
        app.state.kafka = kafka
    except Exception as exc:
        logger.warning("kafka_init_failed", error=str(exc))
        app.state.kafka = None

    # Start APScheduler: staleness check every hour
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _run_staleness_check,
        trigger="interval",
        hours=1,
        args=[app],
        id="staleness_check",
        replace_existing=True,
    )
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info("scheduler_started", job="staleness_check", interval_hours=1)

    yield

    # Cleanup
    scheduler.shutdown(wait=False)
    if app.state.db:
        await app.state.db.disconnect()
    if app.state.kafka:
        await app.state.kafka.disconnect()


app = FastAPI(
    title="SentinelAPI — Discovery Service",
    version="0.1.0",
    lifespan=lifespan,
)

# Middleware
app.add_middleware(CorrelationIDMiddleware)

# Metrics
setup_metrics(app, SERVICE_NAME)

# Global exception handler
app.add_exception_handler(Exception, make_global_exception_handler(SERVICE_NAME))

# Routers
app.include_router(health_router)
app.include_router(discover_router)
app.include_router(endpoints_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=False)
