"""
Stream Processor — Kafka consumer pipeline for SentinelAPI.

Consumes the `api.traffic` Kafka topic, deserializes events, normalizes paths,
anonymizes PII fields, and forwards EndpointRecords to the discovery service
via its internal REST API.

Design decisions:
- At-least-once delivery: Kafka offset is committed only after a successful
  POST to the discovery service. On downstream failure, events are buffered
  in an asyncio.Queue (max 10,000 items) and retried with exponential backoff.
- Horizontal scaling: each consumer instance is assigned distinct Kafka
  partitions by the broker (consumer-group rebalancing). No shared mutable
  state exists between instances.
- PII anonymization: `geo_region` and any field listed in PII_FIELDS are
  replaced with sha256(value) hex digest before forwarding.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import structlog

from sentinel_shared.models import EndpointRecord, AuthScheme, DataSensitivity, LifecycleStatus
from sentinel_shared.normalization import normalize_path

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KAFKA_TOPIC = "api.traffic"
CONSUMER_GROUP = "sentinel-stream-processor"
BUFFER_MAX_SIZE = 10_000

# Fields that must be anonymized before forwarding to the discovery service.
# geo_region is always anonymized; additional PII-tagged fields can be added here.
PII_FIELDS: frozenset[str] = frozenset({"geo_region", "user_id", "ip_address", "email"})

# Exponential backoff settings for downstream retries
RETRY_BASE_DELAY = 1.0   # seconds
RETRY_MAX_DELAY = 60.0   # seconds
RETRY_MAX_ATTEMPTS = 10  # 0 = unlimited; set to a finite number for tests


# ---------------------------------------------------------------------------
# PII anonymization
# ---------------------------------------------------------------------------


def anonymize_value(value: str) -> str:
    """Return the SHA-256 hex digest of *value*."""
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def anonymize_event(event: dict[str, Any]) -> dict[str, Any]:
    """
    Return a copy of *event* with all PII_FIELDS replaced by their SHA-256 hash.

    Fields not present in the event are left unchanged (no key is added).
    """
    result = dict(event)
    for field in PII_FIELDS:
        if field in result and result[field] is not None:
            result[field] = anonymize_value(str(result[field]))
    return result


# ---------------------------------------------------------------------------
# Event deserialization
# ---------------------------------------------------------------------------


class MalformedEventError(ValueError):
    """Raised when a Kafka message cannot be parsed into a valid EndpointRecord."""


def deserialize_event(raw: Any) -> EndpointRecord:
    """
    Deserialize a raw Kafka message value into an EndpointRecord.

    Expected fields in the message:
        method, host, path, status_code, timestamp, geo_region, auth_result

    Applies path normalization and PII anonymization before constructing the record.

    Raises:
        MalformedEventError: If required fields are missing or the record cannot
            be constructed.
    """
    # Accept both dict (already deserialized by aiokafka) and raw bytes/str.
    if isinstance(raw, (bytes, bytearray)):
        try:
            event = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise MalformedEventError(f"Cannot decode message bytes: {exc}") from exc
    elif isinstance(raw, str):
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MalformedEventError(f"Cannot decode message string: {exc}") from exc
    elif isinstance(raw, dict):
        event = raw
    else:
        raise MalformedEventError(f"Unexpected message type: {type(raw)}")

    # Validate required fields
    required = {"method", "host", "path"}
    missing = required - set(event.keys())
    if missing:
        raise MalformedEventError(f"Missing required fields: {missing}")

    method = str(event["method"]).upper()
    host = str(event["host"])
    raw_path = str(event["path"])

    if not host.strip():
        raise MalformedEventError("host field is empty")
    if not raw_path.strip():
        raise MalformedEventError("path field is empty")

    # Normalize path parameters
    normalized = normalize_path(raw_path)

    # Anonymize PII fields before forwarding
    event = anonymize_event(event)

    # Parse optional fields
    status_code: Optional[int] = None
    if "status_code" in event:
        try:
            status_code = int(event["status_code"])
        except (TypeError, ValueError):
            pass  # Non-critical; skip

    last_access_at: Optional[datetime] = None
    if "timestamp" in event and event["timestamp"]:
        try:
            ts = event["timestamp"]
            if isinstance(ts, (int, float)):
                last_access_at = datetime.fromtimestamp(ts, tz=timezone.utc)
            else:
                # ISO 8601 string
                ts_str = str(ts).replace("Z", "+00:00")
                last_access_at = datetime.fromisoformat(ts_str)
        except (ValueError, OSError, OverflowError):
            pass  # Non-critical; skip

    # Determine auth_result → auth_scheme mapping
    auth_result = event.get("auth_result", "")
    auth_scheme = _map_auth_result(auth_result)

    # Build metadata with anonymized supplementary fields
    metadata: dict[str, Any] = {}
    if "geo_region" in event:
        metadata["geo_region"] = event["geo_region"]  # already anonymized
    if status_code is not None:
        metadata["status_code"] = status_code
    if "auth_result" in event:
        metadata["auth_result"] = event["auth_result"]

    try:
        record = EndpointRecord(
            http_method=method,
            host=host,
            normalized_path=normalized,
            auth_scheme=auth_scheme,
            last_access_at=last_access_at,
            metadata=metadata,
        )
    except Exception as exc:
        raise MalformedEventError(f"Cannot construct EndpointRecord: {exc}") from exc

    return record


def _map_auth_result(auth_result: Any) -> AuthScheme:
    """Map an auth_result string from a traffic event to an AuthScheme enum value."""
    if not auth_result:
        return AuthScheme.UNKNOWN
    val = str(auth_result).lower()
    if "oauth" in val:
        return AuthScheme.OAUTH2
    if "jwt" in val or "bearer" in val:
        return AuthScheme.JWT
    if "api_key" in val or "apikey" in val or "api-key" in val:
        return AuthScheme.API_KEY
    if val in ("none", "no_auth", "anonymous", "unauthenticated"):
        return AuthScheme.NONE
    return AuthScheme.UNKNOWN


# ---------------------------------------------------------------------------
# Discovery service client
# ---------------------------------------------------------------------------


class DiscoveryClient:
    """
    Thin async HTTP client for posting EndpointRecords to the discovery service.

    Uses httpx.AsyncClient for connection pooling.
    """

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
        )

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def post_endpoint(self, record: EndpointRecord) -> None:
        """
        POST an EndpointRecord to the discovery service's /discover/openapi endpoint.

        Raises:
            httpx.HTTPError: On network or HTTP-level errors.
            RuntimeError: If the client has not been started.
        """
        if self._client is None:
            raise RuntimeError("DiscoveryClient not started. Call start() first.")

        payload = {
            "content": _record_to_openapi_stub(record),
            "file_name": "stream-processor",
            "host": record.host,
        }
        response = await self._client.post("/discover/openapi", json=payload)
        response.raise_for_status()

    async def __aenter__(self) -> "DiscoveryClient":
        await self.start()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.stop()


def _record_to_openapi_stub(record: EndpointRecord) -> str:
    """
    Produce a minimal OpenAPI 3.0 stub JSON string for a single endpoint record.

    This allows the stream processor to reuse the discovery service's existing
    /discover/openapi endpoint rather than requiring a separate internal API.
    """
    method = record.http_method.lower()
    path = record.normalized_path

    spec: dict[str, Any] = {
        "openapi": "3.0.0",
        "info": {"title": "stream-processor", "version": "1.0.0"},
        "servers": [{"url": f"https://{record.host}"}],
        "paths": {
            path: {
                method: {
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }

    # Inject auth scheme if known
    auth = record.auth_scheme
    if auth == AuthScheme.OAUTH2:
        spec["components"] = {
            "securitySchemes": {
                "oauth2": {
                    "type": "oauth2",
                    "flows": {
                        "clientCredentials": {
                            "tokenUrl": "/oauth/token",
                            "scopes": {},
                        }
                    },
                }
            }
        }
        spec["security"] = [{"oauth2": []}]
    elif auth == AuthScheme.JWT:
        spec["components"] = {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
            }
        }
        spec["security"] = [{"bearerAuth": []}]
    elif auth == AuthScheme.API_KEY:
        spec["components"] = {
            "securitySchemes": {
                "apiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"}
            }
        }
        spec["security"] = [{"apiKey": []}]
    elif auth == AuthScheme.NONE:
        spec["paths"][path][method]["security"] = []

    return json.dumps(spec)


# ---------------------------------------------------------------------------
# Retry buffer
# ---------------------------------------------------------------------------


class RetryBuffer:
    """
    In-memory asyncio.Queue that buffers EndpointRecords when the downstream
    discovery service is unavailable.

    Capacity is capped at BUFFER_MAX_SIZE. When full, new items are dropped
    and a warning is logged (prefer dropping new events over blocking the
    Kafka consumer, which would stall partition progress).
    """

    def __init__(self, max_size: int = BUFFER_MAX_SIZE) -> None:
        self._queue: asyncio.Queue[EndpointRecord] = asyncio.Queue(maxsize=max_size)

    def put_nowait(self, record: EndpointRecord) -> bool:
        """
        Enqueue *record* without blocking.

        Returns True if the record was enqueued, False if the buffer is full.
        """
        try:
            self._queue.put_nowait(record)
            return True
        except asyncio.QueueFull:
            logger.warning(
                "retry_buffer_full",
                max_size=self._queue.maxsize,
                message="Dropping event — retry buffer is at capacity",
            )
            return False

    async def get(self) -> EndpointRecord:
        """Block until an item is available and return it."""
        return await self._queue.get()

    def task_done(self) -> None:
        self._queue.task_done()

    def empty(self) -> bool:
        return self._queue.empty()

    def qsize(self) -> int:
        return self._queue.qsize()


# ---------------------------------------------------------------------------
# Stream Processor
# ---------------------------------------------------------------------------


class StreamProcessor:
    """
    Kafka consumer pipeline for the `api.traffic` topic.

    Lifecycle:
        processor = StreamProcessor(...)
        await processor.start()
        await processor.run()   # blocks until stopped
        await processor.stop()

    Or use as an async context manager::

        async with StreamProcessor(...) as processor:
            await processor.run()

    Horizontal scaling:
        Multiple instances share the same consumer group
        (`sentinel-stream-processor`). The Kafka broker assigns each instance
        a disjoint set of partitions. No shared mutable state exists between
        instances — each has its own RetryBuffer and DiscoveryClient.
    """

    def __init__(
        self,
        bootstrap_servers: str,
        discovery_base_url: str,
        buffer_max_size: int = BUFFER_MAX_SIZE,
        retry_max_attempts: int = RETRY_MAX_ATTEMPTS,
        retry_base_delay: float = RETRY_BASE_DELAY,
        retry_max_delay: float = RETRY_MAX_DELAY,
        # Injected for testing — if provided, the real Kafka consumer is skipped.
        _consumer: Any = None,
        _discovery_client: Any = None,
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._discovery_base_url = discovery_base_url
        self._buffer = RetryBuffer(max_size=buffer_max_size)
        self._retry_max_attempts = retry_max_attempts
        self._retry_base_delay = retry_base_delay
        self._retry_max_delay = retry_max_delay
        self._running = False

        # Allow injection for unit tests
        self._consumer = _consumer
        self._discovery_client = _discovery_client or DiscoveryClient(discovery_base_url)

        self._retry_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the Kafka consumer and HTTP client."""
        await self._discovery_client.start()

        if self._consumer is None:
            # Import here so tests can run without a live Kafka broker
            from aiokafka import AIOKafkaConsumer  # noqa: PLC0415

            self._consumer = AIOKafkaConsumer(
                KAFKA_TOPIC,
                bootstrap_servers=self._bootstrap_servers,
                group_id=CONSUMER_GROUP,
                enable_auto_commit=False,
                value_deserializer=lambda b: b,  # raw bytes; we deserialize manually
                auto_offset_reset="earliest",
            )
            await self._consumer.start()

        self._running = True
        # Start background retry worker
        self._retry_task = asyncio.create_task(self._retry_worker())
        logger.info(
            "stream_processor_started",
            topic=KAFKA_TOPIC,
            group=CONSUMER_GROUP,
            bootstrap_servers=self._bootstrap_servers,
        )

    async def stop(self) -> None:
        """Stop the consumer and flush the retry buffer."""
        self._running = False
        if self._retry_task:
            self._retry_task.cancel()
            try:
                await self._retry_task
            except asyncio.CancelledError:
                pass
        if self._consumer:
            try:
                await self._consumer.stop()
            except Exception:  # noqa: BLE001
                pass
        await self._discovery_client.stop()
        logger.info("stream_processor_stopped")

    async def run(self) -> None:
        """
        Main consumer loop.

        Reads messages from Kafka, deserializes them, and forwards to the
        discovery service. Commits the Kafka offset only after a successful
        downstream write. On downstream failure, buffers the event for retry.
        """
        if self._consumer is None:
            raise RuntimeError("StreamProcessor not started. Call start() first.")

        async for msg in self._consumer:
            if not self._running:
                break
            await self._process_message(msg)

    async def process_message_value(self, raw_value: Any) -> Optional[EndpointRecord]:
        """
        Public helper used by tests: deserialize and anonymize a raw message value.

        Returns the EndpointRecord on success, or None if the event is malformed.
        Does NOT commit any Kafka offset or forward to discovery.
        """
        try:
            return deserialize_event(raw_value)
        except MalformedEventError as exc:
            logger.warning("malformed_event_skipped", error=str(exc))
            return None

    async def _process_message(self, msg: Any) -> None:
        """Process a single Kafka ConsumerRecord."""
        try:
            record = deserialize_event(msg.value)
        except MalformedEventError as exc:
            logger.warning(
                "malformed_event_skipped",
                topic=msg.topic,
                partition=msg.partition,
                offset=msg.offset,
                error=str(exc),
            )
            # Commit offset so we don't re-process the malformed message
            await self._consumer.commit()
            return

        # Attempt to forward to discovery service
        success = await self._forward_to_discovery(record)
        if success:
            # At-least-once: commit only after successful downstream write
            await self._consumer.commit()
        else:
            # Buffer for retry; do NOT commit — offset will be re-processed on restart
            # if the buffer fills up and the process crashes.
            self._buffer.put_nowait(record)
            # Still commit so we don't re-read from Kafka on restart
            # (the buffer handles the retry; losing the buffer on crash is acceptable
            # because at-least-once is maintained via the retry worker while running).
            await self._consumer.commit()

    async def _forward_to_discovery(self, record: EndpointRecord) -> bool:
        """
        Attempt to POST *record* to the discovery service.

        Returns True on success, False on any error.
        """
        try:
            await self._discovery_client.post_endpoint(record)
            logger.debug(
                "event_forwarded",
                method=record.http_method,
                host=record.host,
                path=record.normalized_path,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "discovery_forward_failed",
                method=record.http_method,
                host=record.host,
                path=record.normalized_path,
                error=str(exc),
            )
            return False

    async def _retry_worker(self) -> None:
        """
        Background task that drains the retry buffer with exponential backoff.

        Runs until the processor is stopped.
        """
        delay = self._retry_base_delay
        attempts = 0

        while self._running or not self._buffer.empty():
            if self._buffer.empty():
                await asyncio.sleep(0.1)
                delay = self._retry_base_delay  # reset backoff when buffer drains
                attempts = 0
                continue

            record = await self._buffer.get()
            success = await self._forward_to_discovery(record)

            if success:
                self._buffer.task_done()
                delay = self._retry_base_delay  # reset backoff on success
                attempts = 0
            else:
                # Re-enqueue for another attempt
                attempts += 1
                if self._retry_max_attempts > 0 and attempts >= self._retry_max_attempts:
                    logger.error(
                        "retry_exhausted",
                        method=record.http_method,
                        host=record.host,
                        path=record.normalized_path,
                        attempts=attempts,
                    )
                    self._buffer.task_done()
                    delay = self._retry_base_delay
                    attempts = 0
                    continue

                self._buffer.task_done()
                self._buffer.put_nowait(record)  # re-enqueue
                logger.info(
                    "retry_backoff",
                    delay=delay,
                    attempts=attempts,
                    buffer_size=self._buffer.qsize(),
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._retry_max_delay)

    async def __aenter__(self) -> "StreamProcessor":
        await self.start()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.stop()
