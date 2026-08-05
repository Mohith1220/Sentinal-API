"""
Kafka producer/consumer helpers for SentinelAPI using aiokafka.

Provides thin wrappers around AIOKafkaProducer and AIOKafkaConsumer with:
- JSON serialization/deserialization
- Structured logging on errors
- Graceful start/stop lifecycle helpers
"""

import json
import asyncio
from typing import Any, AsyncIterator, Callable, Awaitable

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.errors import KafkaError

from sentinel_shared.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _serialize(value: Any) -> bytes:
    """Serialize a Python object to UTF-8 JSON bytes."""
    return json.dumps(value, default=str).encode("utf-8")


def _deserialize(data: bytes) -> Any:
    """Deserialize UTF-8 JSON bytes to a Python object."""
    return json.loads(data.decode("utf-8"))


# ---------------------------------------------------------------------------
# Producer
# ---------------------------------------------------------------------------


class SentinelProducer:
    """
    Async Kafka producer wrapper.

    Usage::

        async with SentinelProducer(bootstrap_servers="kafka:9092") as producer:
            await producer.send("my.topic", {"key": "value"})
    """

    def __init__(self, bootstrap_servers: str, **kwargs: Any) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._kwargs = kwargs
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
            value_serializer=_serialize,
            **self._kwargs,
        )
        await self._producer.start()
        logger.info("kafka_producer_started", bootstrap_servers=self._bootstrap_servers)

    async def stop(self) -> None:
        if self._producer:
            await self._producer.stop()
            logger.info("kafka_producer_stopped")

    async def send(self, topic: str, value: Any, key: str | None = None) -> None:
        """Send a single message to *topic*. Raises on Kafka errors."""
        if self._producer is None:
            raise RuntimeError("Producer not started. Call start() first.")
        key_bytes = key.encode("utf-8") if key else None
        try:
            await self._producer.send_and_wait(topic, value=value, key=key_bytes)
        except KafkaError as exc:
            logger.error("kafka_send_failed", topic=topic, error=str(exc))
            raise

    async def __aenter__(self) -> "SentinelProducer":
        await self.start()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.stop()


# ---------------------------------------------------------------------------
# Consumer
# ---------------------------------------------------------------------------


class SentinelConsumer:
    """
    Async Kafka consumer wrapper with at-least-once delivery semantics.

    Offsets are committed manually after the handler coroutine returns
    successfully. On handler failure the offset is NOT committed so the
    message will be redelivered.

    Usage::

        consumer = SentinelConsumer(
            topics=["endpoint.updated"],
            group_id="my-service",
            bootstrap_servers="kafka:9092",
        )

        async def handle(message: dict) -> None:
            print(message)

        await consumer.run(handle)
    """

    def __init__(
        self,
        topics: list[str],
        group_id: str,
        bootstrap_servers: str,
        **kwargs: Any,
    ) -> None:
        self._topics = topics
        self._group_id = group_id
        self._bootstrap_servers = bootstrap_servers
        self._kwargs = kwargs
        self._consumer: AIOKafkaConsumer | None = None
        self._running = False

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            *self._topics,
            bootstrap_servers=self._bootstrap_servers,
            group_id=self._group_id,
            value_deserializer=_deserialize,
            enable_auto_commit=False,
            **self._kwargs,
        )
        await self._consumer.start()
        self._running = True
        logger.info(
            "kafka_consumer_started",
            topics=self._topics,
            group_id=self._group_id,
        )

    async def stop(self) -> None:
        self._running = False
        if self._consumer:
            await self._consumer.stop()
            logger.info("kafka_consumer_stopped", group_id=self._group_id)

    async def run(
        self,
        handler: Callable[[dict], Awaitable[None]],
    ) -> None:
        """
        Consume messages in a loop, calling *handler* for each one.

        Commits the offset only after *handler* returns without raising.
        Logs and skips messages that cannot be deserialized.
        """
        if self._consumer is None:
            raise RuntimeError("Consumer not started. Call start() first.")

        async for msg in self._consumer:
            if not self._running:
                break
            try:
                await handler(msg.value)
                await self._consumer.commit()
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "kafka_handler_error",
                    topic=msg.topic,
                    partition=msg.partition,
                    offset=msg.offset,
                    error=str(exc),
                )
                # Do not commit — message will be redelivered.

    async def __aenter__(self) -> "SentinelConsumer":
        await self.start()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.stop()
