# Feature: sentinel-api, Property 22: Structured Log Format
"""
Property 22: Structured Log Format

For any request, error, or state transition processed by any SentinelAPI
microservice, the emitted log entry SHALL be valid JSON and SHALL contain a
non-null correlation ID that links related log entries across services.

Validates: Requirements 14.1
"""

import io
import json
import sys
import os
import uuid
import logging

import structlog
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
if REPO_ROOT not in sys.path:
    sys.path.insert(0, os.path.abspath(REPO_ROOT))

from sentinel_shared.logging import (
    set_correlation_id,
    get_correlation_id,
    CORRELATION_ID_HEADER,
    CorrelationIDMiddleware,
    get_logger,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid HTTP header values: ASCII printable characters only
_ASCII_PRINTABLE = "".join(chr(i) for i in range(32, 127) if chr(i) not in '"\r\n')

correlation_id_st = st.one_of(
    st.uuids().map(str),
    st.text(
        alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"),
        min_size=1,
        max_size=64,
    ).filter(lambda s: s.strip()),
)

# Log event names (ASCII only)
event_name_st = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz_"),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip())


# ---------------------------------------------------------------------------
# Helper: configure structlog to write to a StringIO buffer
# ---------------------------------------------------------------------------

def _make_log_buffer():
    """Return a (logger, buffer) pair for capturing log output."""
    buf = io.StringIO()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=buf),
        cache_logger_on_first_use=False,
    )
    return get_logger("test"), buf


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


@given(correlation_id=correlation_id_st, event=event_name_st)
@settings(max_examples=50)
def test_p22_log_entry_contains_correlation_id(correlation_id: str, event: str):
    """
    **Validates: Requirements 14.1**

    For any log entry emitted with a correlation ID set in context,
    the log output SHALL contain that correlation ID.
    """
    logger, buf = _make_log_buffer()

    set_correlation_id(correlation_id)
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

    logger.info(event)

    output = buf.getvalue()
    assert correlation_id in output, (
        f"correlation_id '{correlation_id}' not found in log output: {output!r}"
    )


@given(correlation_id=correlation_id_st, event=event_name_st)
@settings(max_examples=50)
def test_p22_log_entry_is_valid_json(correlation_id: str, event: str):
    """
    **Validates: Requirements 14.1**

    Log entries SHALL be valid JSON.
    """
    logger, buf = _make_log_buffer()

    set_correlation_id(correlation_id)
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

    logger.info(event)

    output = buf.getvalue().strip()
    lines = [line for line in output.splitlines() if line.strip()]
    assert lines, "No log output was produced"

    last_line = lines[-1]
    try:
        parsed = json.loads(last_line)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"Log entry is not valid JSON: {last_line!r}\nError: {exc}"
        ) from exc

    assert parsed.get("correlation_id") == correlation_id, (
        f"Expected correlation_id='{correlation_id}' in parsed log, got: {parsed}"
    )


@given(correlation_id=correlation_id_st)
@settings(max_examples=50)
def test_p22_middleware_injects_correlation_id_into_context(correlation_id: str):
    """
    **Validates: Requirements 14.1**

    The CorrelationIDMiddleware SHALL inject the correlation ID into the
    request context so that all log entries during that request carry it.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    captured_cids = []

    app = FastAPI()
    app.add_middleware(CorrelationIDMiddleware)

    @app.get("/test")
    async def test_route():
        captured_cids.append(get_correlation_id())
        return {"ok": True}

    client = TestClient(app, raise_server_exceptions=False)
    client.get("/test", headers={CORRELATION_ID_HEADER: correlation_id})

    assert len(captured_cids) == 1
    assert captured_cids[0] == correlation_id, (
        f"Expected correlation_id='{correlation_id}', got '{captured_cids[0]}'"
    )


@given(event=event_name_st)
@settings(max_examples=30)
def test_p22_log_entry_has_non_null_correlation_id_when_generated(event: str):
    """
    **Validates: Requirements 14.1**

    When no correlation ID is provided, the middleware generates one.
    The generated ID must be non-null and non-empty.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from prometheus_client import CollectorRegistry
    from sentinel_shared.metrics import setup_metrics

    captured_cids = []

    app = FastAPI()
    app.add_middleware(CorrelationIDMiddleware)
    setup_metrics(app, "test", registry=CollectorRegistry())

    @app.get("/test")
    async def test_route():
        cid = get_correlation_id()
        captured_cids.append(cid)
        return {"cid": cid}

    client = TestClient(app, raise_server_exceptions=False)
    # No X-Correlation-ID header — middleware should generate one
    response = client.get("/test")

    assert response.status_code == 200
    assert len(captured_cids) == 1
    cid = captured_cids[0]
    assert cid, "Generated correlation_id must be non-null and non-empty"
    # Should be a valid UUID
    uuid.UUID(cid)
