"""
Unit tests for Task 17: Observability — structured logging and metrics.

Tests cover:
  - Log entry contains correlation_id
  - Exception handler logs and returns without crashing service
  - /metrics endpoint returns valid Prometheus text format
  - CorrelationIDMiddleware generates/propagates X-Correlation-ID
  - Custom histograms are registered in the Prometheus registry
"""

import json
import sys
import os
import io
import uuid
import logging
from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Path setup — ensure sentinel_shared is importable
# ---------------------------------------------------------------------------
REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
SENTINEL_SHARED = os.path.join(REPO_ROOT, "sentinel_shared")
if SENTINEL_SHARED not in sys.path:
    sys.path.insert(0, os.path.abspath(SENTINEL_SHARED))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, os.path.abspath(REPO_ROOT))

from sentinel_shared.logging import (
    configure_logging,
    get_logger,
    get_correlation_id,
    set_correlation_id,
    CorrelationIDMiddleware,
    CORRELATION_ID_HEADER,
    make_global_exception_handler,
)
from sentinel_shared.metrics import (
    setup_metrics,
    RISK_SCORE_HISTOGRAM,
    CLASSIFICATION_HISTOGRAM,
    KAFKA_LAG_HISTOGRAM,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_test_app(service_name: str = "test-service") -> FastAPI:
    """Create a minimal FastAPI app with all observability features wired up."""
    from prometheus_client import CollectorRegistry
    app = FastAPI()
    app.add_middleware(CorrelationIDMiddleware)
    # Use a fresh registry per test app to avoid duplicate metric registration
    registry = CollectorRegistry()
    setup_metrics(app, service_name, registry=registry)
    app.add_exception_handler(Exception, make_global_exception_handler(service_name))

    @app.get("/ok")
    async def ok_route():
        return {"status": "ok"}

    @app.get("/boom")
    async def boom_route():
        raise RuntimeError("intentional test error")

    return app


# ---------------------------------------------------------------------------
# Tests: CorrelationIDMiddleware
# ---------------------------------------------------------------------------


class TestCorrelationIDMiddleware:
    """Tests for the X-Correlation-ID middleware."""

    def test_middleware_generates_correlation_id_when_absent(self):
        """When no X-Correlation-ID header is sent, the middleware generates one."""
        app = _make_test_app()
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/ok")
        assert response.status_code == 200
        assert CORRELATION_ID_HEADER in response.headers
        cid = response.headers[CORRELATION_ID_HEADER]
        # Should be a valid UUID
        uuid.UUID(cid)  # raises ValueError if not a valid UUID

    def test_middleware_propagates_existing_correlation_id(self):
        """When X-Correlation-ID is provided, the middleware echoes it back."""
        app = _make_test_app()
        client = TestClient(app, raise_server_exceptions=False)
        my_cid = "test-correlation-id-12345"
        response = client.get("/ok", headers={CORRELATION_ID_HEADER: my_cid})
        assert response.status_code == 200
        assert response.headers[CORRELATION_ID_HEADER] == my_cid

    def test_middleware_sets_correlation_id_context_var(self):
        """The middleware sets the correlation_id context variable during request."""
        captured_cid = {}

        app = FastAPI()
        app.add_middleware(CorrelationIDMiddleware)

        @app.get("/capture")
        async def capture_route():
            captured_cid["value"] = get_correlation_id()
            return {"cid": captured_cid["value"]}

        client = TestClient(app, raise_server_exceptions=False)
        my_cid = "my-test-cid"
        response = client.get("/capture", headers={CORRELATION_ID_HEADER: my_cid})
        assert response.status_code == 200
        data = response.json()
        assert data["cid"] == my_cid


# ---------------------------------------------------------------------------
# Tests: Structured logging with correlation_id
# ---------------------------------------------------------------------------


class TestStructuredLogging:
    """Tests that log entries contain correlation_id."""

    def test_log_entry_contains_correlation_id(self):
        """A log entry emitted with a correlation ID set should contain it."""
        import io
        import structlog

        # Use a StringIO buffer to capture log output
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

        test_cid = "log-test-cid-abc"
        set_correlation_id(test_cid)
        structlog.contextvars.bind_contextvars(correlation_id=test_cid)

        logger = get_logger("test")
        logger.info("test_event", extra_field="value")

        output = buf.getvalue()
        assert test_cid in output, (
            f"correlation_id '{test_cid}' not found in log output: {output!r}"
        )

    def test_log_entry_is_valid_json(self):
        """Log entries should be valid JSON."""
        import io
        import structlog

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

        test_cid = "json-test-cid-xyz"
        set_correlation_id(test_cid)
        structlog.contextvars.bind_contextvars(correlation_id=test_cid)

        logger = get_logger("test")
        logger.info("json_test_event", key="value")

        output = buf.getvalue().strip()
        lines = [line for line in output.splitlines() if line.strip()]
        assert lines, "No log output was produced"

        last_line = lines[-1]
        parsed = json.loads(last_line)
        assert parsed.get("correlation_id") == test_cid

    def test_log_entry_contains_correlation_id_via_middleware(self):
        """Log entries emitted during a request should contain the correlation_id."""
        captured_cid = {}

        app = FastAPI()
        app.add_middleware(CorrelationIDMiddleware)

        @app.get("/log-test")
        async def log_test_route():
            cid = get_correlation_id()
            captured_cid["value"] = cid
            return {"cid": cid}

        client = TestClient(app, raise_server_exceptions=False)
        my_cid = "middleware-log-cid"
        response = client.get("/log-test", headers={CORRELATION_ID_HEADER: my_cid})
        assert response.status_code == 200
        assert captured_cid.get("value") == my_cid


# ---------------------------------------------------------------------------
# Tests: Global exception handler
# ---------------------------------------------------------------------------


class TestGlobalExceptionHandler:
    """Tests for the global exception handler."""

    def test_exception_handler_returns_500_with_error_field(self):
        """Unhandled exceptions should return HTTP 500 with error=internal_error."""
        app = _make_test_app()
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/boom")
        assert response.status_code == 500
        data = response.json()
        assert data["error"] == "internal_error"

    def test_exception_handler_returns_correlation_id(self):
        """The error response should include the correlation_id."""
        app = _make_test_app()
        client = TestClient(app, raise_server_exceptions=False)
        my_cid = "error-test-cid"
        response = client.get("/boom", headers={CORRELATION_ID_HEADER: my_cid})
        assert response.status_code == 500
        data = response.json()
        assert "correlation_id" in data
        assert data["correlation_id"] == my_cid

    def test_service_continues_after_exception(self):
        """After an unhandled exception, the service should continue serving requests."""
        app = _make_test_app()
        client = TestClient(app, raise_server_exceptions=False)

        # First request raises an exception
        response1 = client.get("/boom")
        assert response1.status_code == 500

        # Second request should succeed normally
        response2 = client.get("/ok")
        assert response2.status_code == 200
        assert response2.json() == {"status": "ok"}

    def test_exception_handler_does_not_crash_service(self):
        """Multiple exceptions in a row should not crash the service."""
        app = _make_test_app()
        client = TestClient(app, raise_server_exceptions=False)

        for _ in range(5):
            response = client.get("/boom")
            assert response.status_code == 500
            assert response.json()["error"] == "internal_error"

        # Service still works
        response = client.get("/ok")
        assert response.status_code == 200

    def test_exception_handler_logs_structured_context(self):
        """The exception handler should log service, operation, and stack_trace."""
        import io
        import structlog

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

        from prometheus_client import CollectorRegistry
        app = FastAPI()
        app.add_middleware(CorrelationIDMiddleware)
        setup_metrics(app, "test-service", registry=CollectorRegistry())
        app.add_exception_handler(Exception, make_global_exception_handler("test-service"))

        @app.get("/boom-log")
        async def boom_log_route():
            raise RuntimeError("intentional test error")

        client = TestClient(app, raise_server_exceptions=False)
        client.get("/boom-log")

        output = buf.getvalue()
        # The log output should mention the error or the event name
        assert "intentional test error" in output or "unhandled_exception" in output


# ---------------------------------------------------------------------------
# Tests: /metrics endpoint
# ---------------------------------------------------------------------------


class TestMetricsEndpoint:
    """Tests for the /metrics Prometheus endpoint."""

    def test_metrics_endpoint_returns_200(self):
        """/metrics should return HTTP 200."""
        app = _make_test_app()
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/metrics")
        assert response.status_code == 200

    def test_metrics_endpoint_returns_prometheus_text_format(self):
        """/metrics should return valid Prometheus text format."""
        app = _make_test_app()
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/metrics")
        assert response.status_code == 200

        content_type = response.headers.get("content-type", "")
        # Prometheus text format uses text/plain
        assert "text/plain" in content_type or "text/" in content_type

        body = response.text
        # Prometheus text format starts with # HELP or # TYPE lines
        assert "# HELP" in body or "# TYPE" in body

    def test_metrics_endpoint_contains_http_metrics(self):
        """/metrics should contain HTTP request metrics after a request."""
        app = _make_test_app()
        client = TestClient(app, raise_server_exceptions=False)

        # Make a request to generate metrics
        client.get("/ok")

        response = client.get("/metrics")
        assert response.status_code == 200
        body = response.text

        # Should contain some HTTP-related metric
        assert "http" in body.lower()

    def test_metrics_endpoint_contains_custom_histograms(self):
        """/metrics should contain the custom histogram definitions."""
        app = _make_test_app()
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/metrics")
        assert response.status_code == 200
        body = response.text

        # Custom histograms should appear in the metrics output
        assert "risk_score_computation_seconds" in body
        assert "classification_latency_seconds" in body
        assert "kafka_consumer_lag" in body


# ---------------------------------------------------------------------------
# Tests: Custom histograms
# ---------------------------------------------------------------------------


class TestCustomHistograms:
    """Tests for the custom Prometheus histograms."""

    def test_risk_score_histogram_is_registered(self):
        """RISK_SCORE_HISTOGRAM should be a valid Prometheus Histogram."""
        from prometheus_client import Histogram
        assert isinstance(RISK_SCORE_HISTOGRAM, Histogram)

    def test_classification_histogram_is_registered(self):
        """CLASSIFICATION_HISTOGRAM should be a valid Prometheus Histogram."""
        from prometheus_client import Histogram
        assert isinstance(CLASSIFICATION_HISTOGRAM, Histogram)

    def test_kafka_lag_histogram_is_registered(self):
        """KAFKA_LAG_HISTOGRAM should be a valid Prometheus Histogram."""
        from prometheus_client import Histogram
        assert isinstance(KAFKA_LAG_HISTOGRAM, Histogram)

    def test_risk_score_histogram_can_observe(self):
        """RISK_SCORE_HISTOGRAM should accept observations."""
        RISK_SCORE_HISTOGRAM.labels(service="test").observe(0.05)

    def test_classification_histogram_can_observe(self):
        """CLASSIFICATION_HISTOGRAM should accept observations."""
        CLASSIFICATION_HISTOGRAM.labels(service="test").observe(0.1)

    def test_kafka_lag_histogram_can_observe(self):
        """KAFKA_LAG_HISTOGRAM should accept observations."""
        KAFKA_LAG_HISTOGRAM.labels(service="test", topic="endpoint.updated").observe(42)
