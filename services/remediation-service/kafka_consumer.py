"""
Kafka consumer for the Remediation Service.

Subscribes to two topics and triggers recommendation generation:
  - endpoint.classified → generate recommendations if risk_score >= 40
  - endpoint.updated    → generate recommendations if risk_score >= 40

After a recommendation is resolved, publishes endpoint.remediated events.
"""

import asyncio
from typing import Any

import structlog

from sentinel_shared.kafka import SentinelConsumer, SentinelProducer

from rule_engine import generate_recommendations

logger = structlog.get_logger(__name__)

KAFKA_BOOTSTRAP = "kafka:9092"
GROUP_ID = "remediation-service"


async def _process_endpoint(endpoint_id: str, db: Any, source_topic: str) -> None:
    """
    Fetch endpoint data, run rule engine, and persist recommendations.

    Args:
        endpoint_id: UUID of the endpoint to process.
        db: Database manager (InMemoryRemediationStore or RemediationDatabaseManager).
        source_topic: Kafka topic that triggered the processing (for logging).
    """
    if not endpoint_id:
        logger.warning("process_missing_endpoint_id", topic=source_topic)
        return

    endpoint_data = await db.get_endpoint(endpoint_id)
    if endpoint_data is None:
        logger.warning(
            "process_endpoint_not_found",
            endpoint_id=endpoint_id,
            topic=source_topic,
        )
        return

    risk_score = int(endpoint_data.get("risk_score", 0))
    if risk_score < 40:
        logger.debug(
            "endpoint_below_threshold",
            endpoint_id=endpoint_id,
            risk_score=risk_score,
        )
        return

    recommendations = generate_recommendations(endpoint_data)

    for rec in recommendations:
        await db.insert_recommendation(rec)

    logger.info(
        "recommendations_generated",
        endpoint_id=endpoint_id,
        risk_score=risk_score,
        count=len(recommendations),
        rules=[r.trigger_rule for r in recommendations],
        source_topic=source_topic,
    )


async def publish_remediated_event(
    endpoint_id: str,
    recommendation_id: str,
    resolved_by: str,
) -> None:
    """
    Publish an endpoint.remediated event to Kafka.

    Called after a recommendation is marked as resolved.
    """
    producer = SentinelProducer(bootstrap_servers=KAFKA_BOOTSTRAP)
    try:
        await producer.start()
        await producer.send(
            "endpoint.remediated",
            {
                "endpoint_id": endpoint_id,
                "recommendation_id": recommendation_id,
                "resolved_by": resolved_by,
            },
        )
        logger.info(
            "remediated_event_published",
            endpoint_id=endpoint_id,
            recommendation_id=recommendation_id,
            resolved_by=resolved_by,
        )
    except Exception as exc:
        logger.error(
            "remediated_event_publish_failed",
            endpoint_id=endpoint_id,
            recommendation_id=recommendation_id,
            error=str(exc),
        )
    finally:
        await producer.stop()


async def _kafka_consumer_loop(app: Any) -> None:
    """
    Subscribe to endpoint.classified and endpoint.updated Kafka topics
    and dispatch recommendation generation tasks.

    Runs as a background asyncio task for the lifetime of the service.
    """
    db = getattr(app.state, "db", None)
    if db is None:
        logger.warning("kafka_consumer_no_db", reason="db_unavailable")
        return

    consumer = SentinelConsumer(
        topics=[
            "endpoint.classified",
            "endpoint.updated",
        ],
        group_id=GROUP_ID,
        bootstrap_servers=KAFKA_BOOTSTRAP,
    )

    async def handle_message(message: dict) -> None:
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

        await _process_endpoint(endpoint_id, db, topic)

    try:
        await consumer.start()
        await consumer.run(handle_message)
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("kafka_consumer_error", error=str(exc))
    finally:
        await consumer.stop()
