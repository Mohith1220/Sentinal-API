"""
Stream Processor — SentinelAPI

Kafka consumer that ingests live API traffic events from the `api.traffic` topic,
normalizes path parameters, anonymizes PII fields, and forwards endpoint records
to the discovery service.

This service exposes only a /health endpoint (no other HTTP routes).
The Kafka consumer pipeline runs as a background asyncio task.
"""

import asyncio
import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from sentinel_shared.health import health_router
from sentinel_shared.logging import CorrelationIDMiddleware, configure_logging, make_global_exception_handler
from sentinel_shared.metrics import setup_metrics

from consumer import StreamProcessor

SERVICE_NAME = "stream-processor"
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN001
    configure_logging(SERVICE_NAME)

    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    discovery_url = os.getenv("DISCOVERY_SERVICE_URL", "http://discovery-service:8001")

    processor = StreamProcessor(
        bootstrap_servers=bootstrap_servers,
        discovery_base_url=discovery_url,
    )
    app.state.processor = processor

    consumer_task: asyncio.Task | None = None
    try:
        await processor.start()
        consumer_task = asyncio.create_task(processor.run(), name="kafka-consumer")
        logger.info(
            "stream_processor_running",
            bootstrap_servers=bootstrap_servers,
            discovery_url=discovery_url,
        )
    except Exception as exc:
        logger.warning("stream_processor_start_failed", error=str(exc))

    yield

    # Graceful shutdown
    if consumer_task and not consumer_task.done():
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass

    try:
        await processor.stop()
    except Exception as exc:
        logger.warning("stream_processor_stop_failed", error=str(exc))


app = FastAPI(
    title="SentinelAPI — Stream Processor",
    version="0.1.0",
    lifespan=lifespan,
)

# Middleware
app.add_middleware(CorrelationIDMiddleware)

# Metrics
setup_metrics(app, SERVICE_NAME)

# Global exception handler
app.add_exception_handler(Exception, make_global_exception_handler(SERVICE_NAME))

# Routers — only /health; no other HTTP routes needed
app.include_router(health_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8002, reload=False)
