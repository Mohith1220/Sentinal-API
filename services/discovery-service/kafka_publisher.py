"""
Kafka event publisher for Discovery Service.

Publishes endpoint.updated events after each upsert operation.
"""

import os
from typing import Optional

import structlog

from sentinel_shared.kafka import SentinelProducer

logger = structlog.get_logger(__name__)

ENDPOINT_UPDATED_TOPIC = "endpoint.updated"


class KafkaPublisher:
    """Publishes endpoint lifecycle events to Kafka."""

    def __init__(self, bootstrap_servers: Optional[str] = None):
        """
        Initialize the Kafka publisher.

        Args:
            bootstrap_servers: Kafka broker addresses. If None, reads from KAFKA_BOOTSTRAP_SERVERS env var.
        """
        self.bootstrap_servers = bootstrap_servers or os.getenv(
            "KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"
        )
        self._producer: Optional[SentinelProducer] = None

    async def connect(self) -> None:
        """Start the Kafka producer."""
        try:
            self._producer = SentinelProducer(bootstrap_servers=self.bootstrap_servers)
            await self._producer.start()
            logger.info("kafka_publisher_connected", bootstrap_servers=self.bootstrap_servers)
        except Exception as exc:
            logger.warning("kafka_publisher_connection_failed", error=str(exc))
            # Continue without Kafka - graceful degradation
            self._producer = None

    async def disconnect(self) -> None:
        """Stop the Kafka producer."""
        if self._producer:
            await self._producer.stop()
            logger.info("kafka_publisher_disconnected")

    async def publish_endpoint_updated(
        self,
        endpoint_id: str,
        change_type: str,
        changed_fields: list[str],
    ) -> None:
        """
        Publish an endpoint.updated event to Kafka.

        Args:
            endpoint_id: The UUID of the updated endpoint.
            change_type: Type of change: "created" or "updated".
            changed_fields: List of field names that were changed.
        """
        if not self._producer:
            logger.warning(
                "kafka_publish_skipped",
                reason="producer_not_connected",
                endpoint_id=endpoint_id,
                change_type=change_type,
            )
            return

        event = {
            "endpoint_id": endpoint_id,
            "change_type": change_type,
            "changed_fields": changed_fields,
        }

        try:
            await self._producer.send(
                topic=ENDPOINT_UPDATED_TOPIC,
                value=event,
                key=endpoint_id,
            )
            logger.info(
                "endpoint_updated_published",
                endpoint_id=endpoint_id,
                change_type=change_type,
                topic=ENDPOINT_UPDATED_TOPIC,
            )
        except Exception as exc:
            logger.error(
                "kafka_publish_failed",
                endpoint_id=endpoint_id,
                topic=ENDPOINT_UPDATED_TOPIC,
                error=str(exc),
            )
            # Don't re-raise — Kafka failure should not block the HTTP response
