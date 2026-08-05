"""
Unit tests for the Stream Processor Kafka consumer pipeline.

Covers:
- Successful event processing (deserialization, normalization, PII anonymization)
- Malformed events are skipped without crashing
- Downstream unavailability triggers buffering with exponential backoff
- PII fields are anonymized before forwarding
- Path normalization is applied to raw traffic paths
- At-least-once delivery: offset committed only after successful forward

Feature: sentinel-api, Task 5: Stream Processor unit tests
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import os
from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup — allow imports from stream-processor and sentinel_shared
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(_REPO_ROOT, "services", "stream-processor"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "sentinel_shared"))

from consumer import (
    StreamProcessor,
    RetryBuffer,
    DiscoveryClient,
    MalformedEventError,
    anonymize_event,
    anonymize_value,
    deserialize_event,
    PII_FIELDS,
    _record_to_openapi_stub,
)
from sentinel_shared.models import EndpointRecord, AuthScheme
from sentinel_shared.normalization import normalize_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    method: str = "GET",
    host: str = "api.example.com",
    path: str = "/users/42",
    status_code: int = 200,
    timestamp: str = "2024-01-15T10:00:00Z",
    geo_region: str = "us-east-1",
    auth_result: str = "jwt",
) -> dict:
    return {
        "method": method,
        "host": host,
        "path": path,
        "status_code": status_code,
        "timestamp": timestamp,
        "geo_region": geo_region,
        "auth_result": auth_result,
    }


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _make_mock_consumer(messages: list[dict]) -> MagicMock:
    """
    Build a mock aiokafka consumer that yields ConsumerRecord-like objects
    for each dict in *messages*, then stops.
    """
    mock_records = []
    for msg_dict in messages:
        msg = MagicMock()
        msg.value = json.dumps(msg_dict).encode("utf-8")
        msg.topic = "api.traffic"
        msg.partition = 0
        msg.offset = len(mock_records)
        mock_records.append(msg)

    consumer = MagicMock()
    consumer.commit = AsyncMock()
    consumer.stop = AsyncMock()

    # Make the consumer async-iterable
    async def _aiter(self):
        for record in mock_records:
            yield record

    consumer.__aiter__ = _aiter
    return consumer


def _make_mock_discovery_client(fail: bool = False) -> MagicMock:
    """Build a mock DiscoveryClient that either succeeds or raises on post_endpoint."""
    client = MagicMock()
    client.start = AsyncMock()
    client.stop = AsyncMock()
    if fail:
        client.post_endpoint = AsyncMock(side_effect=Exception("discovery unavailable"))
    else:
        client.post_endpoint = AsyncMock(return_value=None)
    return client


# ---------------------------------------------------------------------------
# PII anonymization tests
# ---------------------------------------------------------------------------


def test_anonymize_value_returns_sha256():
    """anonymize_value must return the SHA-256 hex digest of the input."""
    value = "us-east-1"
    result = anonymize_value(value)
    assert result == _sha256(value)
    assert len(result) == 64  # SHA-256 hex is always 64 chars


def test_anonymize_event_replaces_geo_region():
    """geo_region must be replaced with its SHA-256 hash."""
    event = _make_event(geo_region="eu-west-2")
    result = anonymize_event(event)
    assert result["geo_region"] == _sha256("eu-west-2")


def test_anonymize_event_does_not_mutate_original():
    """anonymize_event must not mutate the original dict."""
    event = _make_event(geo_region="ap-southeast-1")
    original_geo = event["geo_region"]
    anonymize_event(event)
    assert event["geo_region"] == original_geo


def test_anonymize_event_leaves_non_pii_fields_unchanged():
    """Non-PII fields (method, host, path, etc.) must not be modified."""
    event = _make_event()
    result = anonymize_event(event)
    assert result["method"] == event["method"]
    assert result["host"] == event["host"]
    assert result["path"] == event["path"]
    assert result["status_code"] == event["status_code"]


def test_anonymize_event_handles_missing_pii_field():
    """If a PII field is absent, anonymize_event must not add it."""
    event = {"method": "GET", "host": "api.example.com", "path": "/health"}
    result = anonymize_event(event)
    assert "geo_region" not in result


def test_pii_fields_includes_geo_region():
    """geo_region must be in the PII_FIELDS set per the spec."""
    assert "geo_region" in PII_FIELDS


# ---------------------------------------------------------------------------
# Event deserialization tests
# ---------------------------------------------------------------------------


def test_deserialize_valid_event_returns_endpoint_record():
    """A well-formed event dict must produce a valid EndpointRecord."""
    event = _make_event()
    record = deserialize_event(event)
    assert isinstance(record, EndpointRecord)
    assert record.http_method == "GET"
    assert record.host == "api.example.com"


def test_deserialize_normalizes_path():
    """Path with numeric ID must be normalized to {n} template."""
    event = _make_event(path="/users/42")
    record = deserialize_event(event)
    assert record.normalized_path == "/users/{n}"


def test_deserialize_normalizes_uuid_path():
    """Path with UUID must be normalized to {id} template."""
    event = _make_event(path="/accounts/550e8400-e29b-41d4-a716-446655440000")
    record = deserialize_event(event)
    assert record.normalized_path == "/accounts/{id}"


def test_deserialize_normalizes_date_path():
    """Path with ISO date must be normalized to {date} template."""
    event = _make_event(path="/reports/2024-01-15")
    record = deserialize_event(event)
    assert record.normalized_path == "/reports/{date}"


def test_deserialize_anonymizes_geo_region_in_metadata():
    """geo_region in the event must be anonymized before being stored in metadata."""
    geo = "us-east-1"
    event = _make_event(geo_region=geo)
    record = deserialize_event(event)
    # geo_region should be stored as its hash in metadata
    assert record.metadata.get("geo_region") == _sha256(geo)


def test_deserialize_maps_jwt_auth_result():
    """auth_result='jwt' must map to AuthScheme.JWT."""
    event = _make_event(auth_result="jwt")
    record = deserialize_event(event)
    assert record.auth_scheme == AuthScheme.JWT


def test_deserialize_maps_oauth_auth_result():
    """auth_result containing 'oauth' must map to AuthScheme.OAUTH2."""
    event = _make_event(auth_result="oauth2_token")
    record = deserialize_event(event)
    assert record.auth_scheme == AuthScheme.OAUTH2


def test_deserialize_maps_none_auth_result():
    """auth_result='none' must map to AuthScheme.NONE."""
    event = _make_event(auth_result="none")
    record = deserialize_event(event)
    assert record.auth_scheme == AuthScheme.NONE


def test_deserialize_parses_iso_timestamp():
    """ISO 8601 timestamp must be parsed into last_access_at."""
    event = _make_event(timestamp="2024-06-01T12:30:00Z")
    record = deserialize_event(event)
    assert record.last_access_at is not None
    assert record.last_access_at.year == 2024
    assert record.last_access_at.month == 6


def test_deserialize_accepts_bytes():
    """Raw JSON bytes must be deserialized correctly."""
    event = _make_event()
    raw = json.dumps(event).encode("utf-8")
    record = deserialize_event(raw)
    assert record.http_method == "GET"


def test_deserialize_accepts_json_string():
    """Raw JSON string must be deserialized correctly."""
    event = _make_event()
    raw = json.dumps(event)
    record = deserialize_event(raw)
    assert record.http_method == "GET"


def test_deserialize_raises_on_missing_method():
    """Event missing 'method' must raise MalformedEventError."""
    event = {"host": "api.example.com", "path": "/users"}
    with pytest.raises(MalformedEventError):
        deserialize_event(event)


def test_deserialize_raises_on_missing_host():
    """Event missing 'host' must raise MalformedEventError."""
    event = {"method": "GET", "path": "/users"}
    with pytest.raises(MalformedEventError):
        deserialize_event(event)


def test_deserialize_raises_on_missing_path():
    """Event missing 'path' must raise MalformedEventError."""
    event = {"method": "GET", "host": "api.example.com"}
    with pytest.raises(MalformedEventError):
        deserialize_event(event)


def test_deserialize_raises_on_invalid_json_bytes():
    """Invalid JSON bytes must raise MalformedEventError."""
    with pytest.raises(MalformedEventError):
        deserialize_event(b"{not valid json")


def test_deserialize_raises_on_unexpected_type():
    """Passing an integer must raise MalformedEventError."""
    with pytest.raises(MalformedEventError):
        deserialize_event(12345)


def test_deserialize_raises_on_empty_host():
    """Event with empty host string must raise MalformedEventError."""
    event = {"method": "GET", "host": "   ", "path": "/users"}
    with pytest.raises(MalformedEventError):
        deserialize_event(event)


# ---------------------------------------------------------------------------
# RetryBuffer tests
# ---------------------------------------------------------------------------


def test_retry_buffer_put_and_get():
    """Items put into the buffer must be retrievable."""
    buf = RetryBuffer(max_size=10)
    record = EndpointRecord(http_method="GET", host="api.example.com", normalized_path="/users")
    result = buf.put_nowait(record)
    assert result is True
    assert buf.qsize() == 1


def test_retry_buffer_full_returns_false():
    """put_nowait on a full buffer must return False without raising."""
    buf = RetryBuffer(max_size=2)
    r1 = EndpointRecord(http_method="GET", host="a.com", normalized_path="/a")
    r2 = EndpointRecord(http_method="GET", host="b.com", normalized_path="/b")
    r3 = EndpointRecord(http_method="GET", host="c.com", normalized_path="/c")
    buf.put_nowait(r1)
    buf.put_nowait(r2)
    result = buf.put_nowait(r3)
    assert result is False
    assert buf.qsize() == 2


# ---------------------------------------------------------------------------
# StreamProcessor integration-style unit tests (no live Kafka/HTTP)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_event_processing():
    """
    A valid event must be deserialized, forwarded to discovery, and the
    Kafka offset committed.
    """
    event = _make_event()
    mock_consumer = _make_mock_consumer([event])
    mock_client = _make_mock_discovery_client(fail=False)

    processor = StreamProcessor(
        bootstrap_servers="localhost:9092",
        discovery_base_url="http://discovery:8001",
        _consumer=mock_consumer,
        _discovery_client=mock_client,
    )
    processor._running = True
    processor._retry_task = asyncio.create_task(asyncio.sleep(0))  # dummy task

    # Process a single message directly
    msg = MagicMock()
    msg.value = json.dumps(event).encode("utf-8")
    msg.topic = "api.traffic"
    msg.partition = 0
    msg.offset = 0

    await processor._process_message(msg)

    # Discovery client must have been called once
    mock_client.post_endpoint.assert_called_once()
    # Kafka offset must have been committed
    mock_consumer.commit.assert_called_once()


@pytest.mark.asyncio
async def test_malformed_event_is_skipped():
    """
    A malformed event (missing required fields) must be skipped without
    crashing, and the Kafka offset must still be committed.
    """
    bad_event = {"status_code": 200}  # missing method, host, path
    mock_consumer = _make_mock_consumer([bad_event])
    mock_client = _make_mock_discovery_client(fail=False)

    processor = StreamProcessor(
        bootstrap_servers="localhost:9092",
        discovery_base_url="http://discovery:8001",
        _consumer=mock_consumer,
        _discovery_client=mock_client,
    )
    processor._running = True
    processor._retry_task = asyncio.create_task(asyncio.sleep(0))

    msg = MagicMock()
    msg.value = json.dumps(bad_event).encode("utf-8")
    msg.topic = "api.traffic"
    msg.partition = 0
    msg.offset = 0

    await processor._process_message(msg)

    # Discovery client must NOT have been called for a malformed event
    mock_client.post_endpoint.assert_not_called()
    # Offset must still be committed so we don't re-process the bad message
    mock_consumer.commit.assert_called_once()


@pytest.mark.asyncio
async def test_downstream_unavailable_triggers_buffering():
    """
    When the discovery service is unavailable, the event must be placed in
    the retry buffer.
    """
    event = _make_event()
    mock_consumer = _make_mock_consumer([event])
    mock_client = _make_mock_discovery_client(fail=True)

    processor = StreamProcessor(
        bootstrap_servers="localhost:9092",
        discovery_base_url="http://discovery:8001",
        _consumer=mock_consumer,
        _discovery_client=mock_client,
    )
    processor._running = True
    processor._retry_task = asyncio.create_task(asyncio.sleep(0))

    msg = MagicMock()
    msg.value = json.dumps(event).encode("utf-8")
    msg.topic = "api.traffic"
    msg.partition = 0
    msg.offset = 0

    await processor._process_message(msg)

    # Discovery client was called (and failed)
    mock_client.post_endpoint.assert_called_once()
    # Event must be in the retry buffer
    assert processor._buffer.qsize() == 1


@pytest.mark.asyncio
async def test_retry_worker_retries_on_failure_then_succeeds():
    """
    The retry worker must retry buffered events and succeed when the
    discovery service becomes available.
    """
    event = _make_event()
    record = deserialize_event(event)

    # First call fails, second succeeds
    call_count = 0

    async def _post_endpoint(r):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("temporary failure")

    mock_client = MagicMock()
    mock_client.start = AsyncMock()
    mock_client.stop = AsyncMock()
    mock_client.post_endpoint = AsyncMock(side_effect=_post_endpoint)

    processor = StreamProcessor(
        bootstrap_servers="localhost:9092",
        discovery_base_url="http://discovery:8001",
        _consumer=MagicMock(),
        _discovery_client=mock_client,
        retry_base_delay=0.01,  # fast for tests
        retry_max_delay=0.1,
    )
    processor._running = True

    # Seed the buffer directly
    processor._buffer.put_nowait(record)

    # Run the retry worker briefly
    retry_task = asyncio.create_task(processor._retry_worker())
    await asyncio.sleep(0.2)  # allow retries to happen
    processor._running = False
    retry_task.cancel()
    try:
        await retry_task
    except asyncio.CancelledError:
        pass

    # Should have been called at least twice (1 fail + 1 success)
    assert call_count >= 2


@pytest.mark.asyncio
async def test_buffer_max_size_respected():
    """
    When the buffer is full, additional events must be dropped (not raise).
    """
    processor = StreamProcessor(
        bootstrap_servers="localhost:9092",
        discovery_base_url="http://discovery:8001",
        buffer_max_size=2,
        _consumer=MagicMock(),
        _discovery_client=MagicMock(),
    )

    r1 = EndpointRecord(http_method="GET", host="a.com", normalized_path="/a")
    r2 = EndpointRecord(http_method="GET", host="b.com", normalized_path="/b")
    r3 = EndpointRecord(http_method="GET", host="c.com", normalized_path="/c")

    processor._buffer.put_nowait(r1)
    processor._buffer.put_nowait(r2)
    result = processor._buffer.put_nowait(r3)  # should be dropped

    assert result is False
    assert processor._buffer.qsize() == 2


@pytest.mark.asyncio
async def test_pii_anonymization_applied_before_forwarding():
    """
    geo_region in the forwarded EndpointRecord metadata must be the SHA-256
    hash of the original value, not the plaintext.
    """
    geo = "ap-southeast-1"
    event = _make_event(geo_region=geo)

    captured_records: list[EndpointRecord] = []

    async def _capture(record: EndpointRecord) -> None:
        captured_records.append(record)

    mock_client = MagicMock()
    mock_client.start = AsyncMock()
    mock_client.stop = AsyncMock()
    mock_client.post_endpoint = AsyncMock(side_effect=_capture)

    mock_consumer = _make_mock_consumer([event])

    processor = StreamProcessor(
        bootstrap_servers="localhost:9092",
        discovery_base_url="http://discovery:8001",
        _consumer=mock_consumer,
        _discovery_client=mock_client,
    )
    processor._running = True
    processor._retry_task = asyncio.create_task(asyncio.sleep(0))

    msg = MagicMock()
    msg.value = json.dumps(event).encode("utf-8")
    msg.topic = "api.traffic"
    msg.partition = 0
    msg.offset = 0

    await processor._process_message(msg)

    assert len(captured_records) == 1
    forwarded = captured_records[0]
    # geo_region in metadata must be the hash, not the plaintext
    assert forwarded.metadata.get("geo_region") == _sha256(geo)
    assert forwarded.metadata.get("geo_region") != geo


@pytest.mark.asyncio
async def test_process_message_value_returns_none_for_malformed():
    """
    process_message_value must return None for malformed events without raising.
    """
    processor = StreamProcessor(
        bootstrap_servers="localhost:9092",
        discovery_base_url="http://discovery:8001",
        _consumer=MagicMock(),
        _discovery_client=MagicMock(),
    )
    result = await processor.process_message_value(b"{invalid json")
    assert result is None


@pytest.mark.asyncio
async def test_process_message_value_returns_record_for_valid():
    """
    process_message_value must return an EndpointRecord for a valid event.
    """
    processor = StreamProcessor(
        bootstrap_servers="localhost:9092",
        discovery_base_url="http://discovery:8001",
        _consumer=MagicMock(),
        _discovery_client=MagicMock(),
    )
    event = _make_event()
    result = await processor.process_message_value(json.dumps(event).encode())
    assert isinstance(result, EndpointRecord)
    assert result.http_method == "GET"


# ---------------------------------------------------------------------------
# DiscoveryClient helper tests
# ---------------------------------------------------------------------------


def test_record_to_openapi_stub_produces_valid_json():
    """_record_to_openapi_stub must produce valid JSON with the correct path and method."""
    record = EndpointRecord(
        http_method="POST",
        host="api.example.com",
        normalized_path="/orders",
    )
    stub_json = _record_to_openapi_stub(record)
    spec = json.loads(stub_json)
    assert "paths" in spec
    assert "/orders" in spec["paths"]
    assert "post" in spec["paths"]["/orders"]


def test_record_to_openapi_stub_includes_jwt_security():
    """Stub for a JWT-authenticated endpoint must include bearerAuth security scheme."""
    record = EndpointRecord(
        http_method="GET",
        host="api.example.com",
        normalized_path="/secure",
        auth_scheme=AuthScheme.JWT,
    )
    stub_json = _record_to_openapi_stub(record)
    spec = json.loads(stub_json)
    assert "components" in spec
    assert "bearerAuth" in spec["components"]["securitySchemes"]


def test_record_to_openapi_stub_includes_none_security():
    """Stub for an unauthenticated endpoint must include security: [] on the operation."""
    record = EndpointRecord(
        http_method="GET",
        host="api.example.com",
        normalized_path="/public",
        auth_scheme=AuthScheme.NONE,
    )
    stub_json = _record_to_openapi_stub(record)
    spec = json.loads(stub_json)
    assert spec["paths"]["/public"]["get"]["security"] == []
