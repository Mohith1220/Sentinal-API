# Feature: sentinel-api, Property 23: Error Resilience — Continue After Unhandled Error
"""
Property 23: Error Resilience — Continue After Unhandled Error

For any unhandled error encountered during request processing, the microservice
SHALL log the full error context (service name, operation, input summary,
stack trace) as a structured JSON entry and SHALL successfully process the next
valid request without requiring a restart.

Validates: Requirements 14.6
"""

import sys
import os

from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
if REPO_ROOT not in sys.path:
    sys.path.insert(0, os.path.abspath(REPO_ROOT))

from sentinel_shared.logging import (
    configure_logging,
    CorrelationIDMiddleware,
    CORRELATION_ID_HEADER,
    make_global_exception_handler,
)
from sentinel_shared.metrics import setup_metrics

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Error messages to raise
error_message_st = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters=" _-!."),
    min_size=1,
    max_size=100,
).filter(lambda s: s.strip())

# Correlation IDs
correlation_id_st = st.uuids().map(str)

# Number of error requests before a successful one
error_count_st = st.integers(min_value=1, max_value=5)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_resilient_app(service_name: str = "test-service"):
    """Create a FastAPI app with the global exception handler installed."""
    from fastapi import FastAPI
    from prometheus_client import CollectorRegistry
    from sentinel_shared.metrics import setup_metrics

    app = FastAPI()
    app.add_middleware(CorrelationIDMiddleware)
    setup_metrics(app, service_name, registry=CollectorRegistry())
    app.add_exception_handler(Exception, make_global_exception_handler(service_name))

    @app.get("/ok")
    async def ok_route():
        return {"status": "ok"}

    @app.get("/error")
    async def error_route():
        raise RuntimeError("test error")

    return app


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


@given(error_count=error_count_st)
@settings(max_examples=20)
def test_p23_service_continues_after_unhandled_error(error_count: int):
    """
    **Validates: Requirements 14.6**

    After N unhandled errors, the service SHALL successfully process the
    next valid request without restarting.
    """
    from fastapi.testclient import TestClient

    app = _make_resilient_app()
    client = TestClient(app, raise_server_exceptions=False)

    # Trigger N errors
    for _ in range(error_count):
        response = client.get("/error")
        assert response.status_code == 500, (
            f"Expected 500 from error route, got {response.status_code}"
        )
        data = response.json()
        assert data["error"] == "internal_error", (
            f"Expected error='internal_error', got {data}"
        )

    # Service should still work after errors
    response = client.get("/ok")
    assert response.status_code == 200, (
        f"Service failed after {error_count} errors: status={response.status_code}"
    )
    assert response.json() == {"status": "ok"}


@given(correlation_id=correlation_id_st)
@settings(max_examples=30)
def test_p23_error_response_contains_correlation_id(correlation_id: str):
    """
    **Validates: Requirements 14.6**

    The error response SHALL contain the correlation_id from the request context.
    """
    from fastapi.testclient import TestClient

    app = _make_resilient_app()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(
        "/error", headers={CORRELATION_ID_HEADER: correlation_id}
    )
    assert response.status_code == 500
    data = response.json()
    assert "correlation_id" in data, (
        f"Error response missing correlation_id: {data}"
    )
    assert data["correlation_id"] == correlation_id, (
        f"Expected correlation_id='{correlation_id}', got '{data['correlation_id']}'"
    )


@given(error_message=error_message_st)
@settings(max_examples=30)
def test_p23_error_response_structure_is_consistent(error_message: str):
    """
    **Validates: Requirements 14.6**

    The error response SHALL always have the structure
    {"error": "internal_error", "correlation_id": "..."}.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from prometheus_client import CollectorRegistry
    from sentinel_shared.metrics import setup_metrics

    app = FastAPI()
    app.add_middleware(CorrelationIDMiddleware)
    setup_metrics(app, "test-service", registry=CollectorRegistry())
    app.add_exception_handler(Exception, make_global_exception_handler("test-service"))

    @app.get("/dynamic-error")
    async def dynamic_error_route():
        raise ValueError(error_message)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/dynamic-error")

    assert response.status_code == 500
    data = response.json()

    # Must have exactly these two fields (plus possibly others)
    assert "error" in data, f"Missing 'error' field in response: {data}"
    assert "correlation_id" in data, f"Missing 'correlation_id' field in response: {data}"
    assert data["error"] == "internal_error", (
        f"Expected error='internal_error', got '{data['error']}'"
    )
    # correlation_id must be non-null
    assert data["correlation_id"] is not None
    assert data["correlation_id"] != ""


@given(error_count=error_count_st, correlation_id=correlation_id_st)
@settings(max_examples=20)
def test_p23_service_processes_valid_request_after_errors_with_correct_cid(
    error_count: int, correlation_id: str
):
    """
    **Validates: Requirements 14.6**

    After N errors, the service SHALL process a valid request and return
    the correct correlation_id in the response header.
    """
    from fastapi.testclient import TestClient

    app = _make_resilient_app()
    client = TestClient(app, raise_server_exceptions=False)

    # Trigger errors
    for _ in range(error_count):
        client.get("/error")

    # Valid request with a specific correlation ID
    response = client.get("/ok", headers={CORRELATION_ID_HEADER: correlation_id})
    assert response.status_code == 200
    assert response.headers.get(CORRELATION_ID_HEADER) == correlation_id, (
        f"Expected X-Correlation-ID='{correlation_id}' in response headers"
    )
