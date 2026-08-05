"""
Structured JSON logging with correlation-ID middleware for SentinelAPI.

Uses structlog to emit JSON-formatted log entries. A FastAPI middleware
generates/propagates the X-Correlation-ID header and injects the correlation
ID into every log entry via a context variable.
"""

import traceback
import uuid
import logging
from contextvars import ContextVar
from typing import Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from fastapi.responses import JSONResponse

# Context variable that holds the current request's correlation ID.
_correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")

CORRELATION_ID_HEADER = "X-Correlation-ID"


def get_correlation_id() -> str:
    """Return the correlation ID for the current context."""
    return _correlation_id_var.get()


def set_correlation_id(correlation_id: str) -> None:
    """Set the correlation ID for the current context."""
    _correlation_id_var.set(correlation_id)


def _add_correlation_id(
    logger: logging.Logger,  # noqa: ARG001
    method: str,  # noqa: ARG001
    event_dict: dict,
) -> dict:
    """structlog processor that injects the correlation ID into every log entry."""
    cid = get_correlation_id()
    if cid:
        event_dict["correlation_id"] = cid
    return event_dict


def configure_logging(service_name: str, log_level: str = "INFO") -> None:
    """
    Configure structlog for JSON-formatted structured logging.

    Call once at application startup, e.g. in the FastAPI lifespan handler.

    Args:
        service_name: Human-readable name of the microservice (added to every entry).
        log_level: Standard Python log level string (default "INFO").
    """
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _add_correlation_id,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=shared_processors
        + [
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(log_level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Also configure stdlib logging so third-party libraries emit JSON.
    logging.basicConfig(
        format="%(message)s",
        level=logging.getLevelName(log_level),
    )

    # Bind the service name globally so it appears in every log entry.
    structlog.contextvars.bind_contextvars(service=service_name)


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Return a structlog bound logger."""
    return structlog.get_logger(name)


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """
    FastAPI/Starlette middleware that:
    1. Reads X-Correlation-ID from the incoming request (or generates a new UUID).
    2. Stores it in the context variable so all log entries in this request carry it.
    3. Echoes it back in the response header.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        correlation_id = request.headers.get(CORRELATION_ID_HEADER) or str(
            uuid.uuid4()
        )
        set_correlation_id(correlation_id)
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

        response: Response = await call_next(request)
        response.headers[CORRELATION_ID_HEADER] = correlation_id

        # Clean up context vars after the request completes.
        structlog.contextvars.unbind_contextvars("correlation_id")
        return response


def make_global_exception_handler(service_name: str):
    """
    Factory that returns a FastAPI exception handler function.

    The returned handler:
    1. Logs full error context (service, operation, input_summary, stack_trace)
       as structured JSON.
    2. Returns {"error": "internal_error", "correlation_id": "..."} with HTTP 500.
    3. Does NOT re-raise, so the service continues processing subsequent requests.

    Usage:
        app.add_exception_handler(Exception, make_global_exception_handler("my-service"))
    """
    _log = get_logger(service_name)

    async def handler(request: Request, exc: Exception) -> JSONResponse:
        correlation_id = get_correlation_id()
        _log.error(
            "unhandled_exception",
            service=service_name,
            operation=f"{request.method} {request.url.path}",
            input_summary={
                "method": request.method,
                "path": str(request.url.path),
                "query": str(request.url.query),
            },
            stack_trace=traceback.format_exc(),
            error=str(exc),
            correlation_id=correlation_id,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "correlation_id": correlation_id,
            },
        )

    return handler
