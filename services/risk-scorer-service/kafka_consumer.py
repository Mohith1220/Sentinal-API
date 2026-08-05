"""
Kafka consumer for the Risk Scorer Service.

Subscribes to four topics and triggers re-scoring within the required SLAs:
  - endpoint.updated    → re-score within 30 s
  - endpoint.classified → re-score within 30 s
  - anomaly.alerts      → re-score within 30 s
  - endpoint.remediated → re-score within 60 s

Each handler fetches the endpoint from the database, runs compute_risk_score,
and persists the result.
"""

import asyncio
from typing import Any, Optional

import structlog

from sentinel_shared.kafka import SentinelConsumer

from scorer import compute_risk_score

logger = structlog.get_logger(__name__)

KAFKA_BOOTSTRAP = "kafka:9092"
GROUP_ID = "risk-scorer-service"

# SLA timeouts (seconds) — used only for logging/monitoring; the consumer
# processes messages as fast as possible and the SLA is met by the low
# end-to-end latency of the pipeline.
SLA_30S_TOPICS = {"endpoint.updated", "endpoint.classified", "anomaly.alerts"}
SLA_60S_TOPICS = {"endpoint.remediated"}


async def _rescore_endpoint(endpoint_id: str, db: Any, source_topic: str) -> None:
    """
    Fetch endpoint data, compute risk score, and persist the result.

    Args:
        endpoint_id: UUID of the endpoint to re-score.
        db: Database manager (InMemoryRiskScorerStore or RiskScorerDatabaseManager).
        source_topic: Kafka topic that triggered the re-scoring (for logging).
    """
    if not endpoint_id:
        logger.warning("rescore_missing_endpoint_id", topic=source_topic)
        return

    endpoint_data = await db.get_endpoint(endpoint_id)
    if endpoint_data is None:
        logger.warning(
            "rescore_endpoint_not_found",
            endpoint_id=endpoint_id,
            topic=source_topic,
        )
        return

    result = compute_risk_score(endpoint_data)

    await db.insert_risk_score_history(result)

    logger.info(
        "endpoint_rescored",
        endpoint_id=endpoint_id,
        score=result.score,
        factors=[f.rule for f in result.factors],
        source_topic=source_topic,
    )


async def _kafka_consumer_loop(app: Any) -> None:
    """
    Subscribe to all four Kafka topics and dispatch re-scoring tasks.

    Runs as a background asyncio task for the lifetime of the service.
    """
    db = getattr(app.state, "db", None)
    if db is None:
        logger.warning("kafka_consumer_no_db", reason="db_unavailable")
        return

    consumer = SentinelConsumer(
        topics=[
            "endpoint.updated",
            "endpoint.classified",
            "anomaly.alerts",
            "endpoint.remediated",
        ],
        group_id=GROUP_ID,
        bootstrap_servers=KAFKA_BOOTSTRAP,
    )

    async def handle_message(message: dict) -> None:
        # All four topics carry an endpoint_id field
        endpoint_id = message.get("endpoint_id")
        topic = message.get("_topic", "unknown")

        if not endpoint_id:
            logger.warning("kafka_message_missing_endpoint_id", message=message)
            return

        logger.info(
            "kafka_message_received",
            endpoint_id=endpoint_id,
            topic=topic,
        )

        await _rescore_endpoint(endpoint_id, db, topic)

    try:
        await consumer.start()
        await consumer.run(handle_message)
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("kafka_consumer_error", error=str(exc))
    finally:
        await consumer.stop()
