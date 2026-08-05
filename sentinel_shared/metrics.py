"""
Prometheus metrics for SentinelAPI microservices.

Exposes Prometheus-compatible metrics via prometheus-fastapi-instrumentator.
Provides custom histograms for:
  - risk_score_computation_seconds
  - classification_latency_seconds
  - kafka_consumer_lag

Usage:
    from sentinel_shared.metrics import setup_metrics, RISK_SCORE_HISTOGRAM, \
        CLASSIFICATION_HISTOGRAM, KAFKA_LAG_HISTOGRAM

    # In your FastAPI lifespan or app setup:
    setup_metrics(app, service_name="my-service")
"""

from typing import Optional

from prometheus_client import Histogram, CollectorRegistry, REGISTRY
from prometheus_fastapi_instrumentator import Instrumentator


# ---------------------------------------------------------------------------
# Custom histograms (registered in the global default registry)
# ---------------------------------------------------------------------------

def _get_or_create_histogram(
    name: str,
    documentation: str,
    labelnames: list,
    buckets=None,
    registry: Optional[CollectorRegistry] = None,
) -> Histogram:
    """
    Return an existing histogram by name or create a new one.

    Avoids ValueError from duplicate registration when the module is
    imported multiple times (e.g. during testing).
    """
    target_registry = registry or REGISTRY
    # Check if already registered under this name
    collectors = list(target_registry._names_to_collectors.values())
    for collector in collectors:
        if hasattr(collector, "_name") and collector._name == name:
            return collector  # type: ignore[return-value]
    kwargs: dict = {"labelnames": labelnames}
    if buckets is not None:
        kwargs["buckets"] = buckets
    if registry is not None:
        kwargs["registry"] = registry
    return Histogram(name, documentation, **kwargs)


RISK_SCORE_HISTOGRAM: Histogram = _get_or_create_histogram(
    name="risk_score_computation_seconds",
    documentation="Time spent computing risk scores for API endpoints",
    labelnames=["service"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
)

CLASSIFICATION_HISTOGRAM: Histogram = _get_or_create_histogram(
    name="classification_latency_seconds",
    documentation="Time spent classifying API endpoint lifecycle status",
    labelnames=["service"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
)

KAFKA_LAG_HISTOGRAM: Histogram = _get_or_create_histogram(
    name="kafka_consumer_lag",
    documentation="Kafka consumer lag (number of messages behind the latest offset)",
    labelnames=["service", "topic"],
    buckets=(0, 1, 5, 10, 50, 100, 500, 1000, 5000, 10000),
)


# ---------------------------------------------------------------------------
# Instrumentator setup
# ---------------------------------------------------------------------------


def setup_metrics(
    app,
    service_name: str,
    registry: Optional[CollectorRegistry] = None,
) -> Instrumentator:
    """
    Attach prometheus-fastapi-instrumentator to a FastAPI app and expose
    the /metrics endpoint.

    Args:
        app: The FastAPI application instance.
        service_name: Human-readable service name (used for labelling).
        registry: Optional Prometheus registry. Defaults to the global REGISTRY.
                  Pass a fresh CollectorRegistry() in tests to avoid duplicate
                  metric registration errors across multiple app instances.

    Returns:
        The configured Instrumentator instance.
    """
    # If a custom registry is provided, also register the custom histograms in it
    # so they appear in the /metrics output for this app.
    if registry is not None:
        _get_or_create_histogram(
            name="risk_score_computation_seconds",
            documentation="Time spent computing risk scores for API endpoints",
            labelnames=["service"],
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
            registry=registry,
        )
        _get_or_create_histogram(
            name="classification_latency_seconds",
            documentation="Time spent classifying API endpoint lifecycle status",
            labelnames=["service"],
            buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
            registry=registry,
        )
        _get_or_create_histogram(
            name="kafka_consumer_lag",
            documentation="Kafka consumer lag (number of messages behind the latest offset)",
            labelnames=["service", "topic"],
            buckets=(0, 1, 5, 10, 50, 100, 500, 1000, 5000, 10000),
            registry=registry,
        )

    instrumentator = Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=False,
        should_respect_env_var=False,
        should_instrument_requests_inprogress=False,
        excluded_handlers=["/health", "/metrics"],
        registry=registry,
    )
    instrumentator.instrument(app)
    instrumentator.expose(app, endpoint="/metrics", include_in_schema=False)
    return instrumentator
