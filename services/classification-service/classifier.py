"""
Classification orchestrator for the Classification Service.

Combines the rule engine and ML classifier, applies conflict resolution,
persists results, and publishes Kafka events.
"""

from datetime import datetime, timezone
from typing import Optional, Any

import structlog

from sentinel_shared.models import LifecycleStatus

from rule_engine import ClassificationInput, apply_rules
from ml_classifier import MLClassifier

logger = structlog.get_logger(__name__)

# Singleton ML classifier (lazy model load)
_ml_classifier = MLClassifier()


async def classify_endpoint(
    endpoint_id: str,
    db: Any,
    kafka_producer: Optional[Any] = None,
) -> Optional[dict]:
    """
    Classify a single endpoint and persist the result.

    Steps:
    1. Fetch endpoint data from the store.
    2. Run rule engine → authoritative LifecycleStatus.
    3. Run ML classifier → advisory status + confidence (may be None).
    4. Write rule-based status to api_endpoints.lifecycle_status.
    5. Insert classification_history record with both statuses.
    6. Publish endpoint.classified Kafka event (if producer available).

    Args:
        endpoint_id: UUID of the endpoint to classify.
        db: Database store (InMemoryClassificationStore or ClassificationDatabaseManager).
        kafka_producer: Optional SentinelProducer for publishing results.

    Returns:
        Dict with classification result, or None if endpoint not found.
    """
    endpoint = await db.get_endpoint(endpoint_id)
    if endpoint is None:
        logger.warning("classify_endpoint_not_found", endpoint_id=endpoint_id)
        return None

    # Build rule engine inputs from endpoint data
    inputs = _build_classification_input(endpoint)

    # Rule-based classification (authoritative)
    rule_status = apply_rules(inputs)

    # ML classification (advisory)
    ml_result = _ml_classifier.predict(
        traffic_recency_days=inputs.traffic_recency_days,
        spec_presence=inputs.spec_presence,
        deprecated_flag=inputs.deprecated_flag,
        owner_present=inputs.owner_present,
        traffic_trend=float(endpoint.get("traffic_trend", 0.0)),
    )

    ml_status = ml_result.ml_status if ml_result else None
    ml_confidence = ml_result.ml_confidence if ml_result else None

    # Conflict resolution: rule-based is authoritative
    await db.update_lifecycle_status(endpoint_id, rule_status)

    # Persist classification history
    history_id = await db.insert_classification_history(
        endpoint_id=endpoint_id,
        rule_status=rule_status,
        ml_status=ml_status,
        ml_confidence=ml_confidence,
    )

    result = {
        "endpoint_id": endpoint_id,
        "rule_status": rule_status.value,
        "ml_status": ml_status.value if ml_status else None,
        "ml_confidence": ml_confidence,
        "history_id": history_id,
        "classified_at": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(
        "endpoint_classified",
        endpoint_id=endpoint_id,
        rule_status=rule_status.value,
        ml_status=ml_status.value if ml_status else None,
        ml_confidence=ml_confidence,
    )

    # Publish to endpoint.classified Kafka topic
    if kafka_producer is not None:
        try:
            await kafka_producer.send(
                "endpoint.classified",
                {
                    "endpoint_id": endpoint_id,
                    "lifecycle_status": rule_status.value,
                    "ml_status": ml_status.value if ml_status else None,
                    "ml_confidence": ml_confidence,
                },
                key=endpoint_id,
            )
        except Exception as exc:
            logger.error(
                "kafka_publish_failed",
                topic="endpoint.classified",
                endpoint_id=endpoint_id,
                error=str(exc),
            )

    return result


def _build_classification_input(endpoint: dict) -> ClassificationInput:
    """
    Build a ClassificationInput from an endpoint dict.

    Handles both direct feature fields (used in tests) and derived fields
    (computed from last_access_at, metadata, etc.).
    """
    # traffic_recency_days: prefer explicit field, else derive from last_access_at
    traffic_recency_days: Optional[float] = endpoint.get("traffic_recency_days")
    if traffic_recency_days is None:
        last_access_at = endpoint.get("last_access_at")
        if last_access_at is not None:
            if isinstance(last_access_at, str):
                try:
                    ts = datetime.fromisoformat(last_access_at.replace("Z", "+00:00"))
                except ValueError:
                    ts = None
            elif isinstance(last_access_at, datetime):
                ts = last_access_at
            else:
                ts = None

            if ts is not None:
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                delta = datetime.now(timezone.utc) - ts
                traffic_recency_days = delta.total_seconds() / 86400.0

    # spec_presence: prefer explicit field, else derive from source_file_id / metadata
    spec_presence: bool = endpoint.get("spec_presence", False)
    if not spec_presence:
        # If source_file_id is set, the endpoint came from a spec/gateway
        if endpoint.get("source_file_id"):
            spec_presence = True
        # Check metadata for gateway presence
        metadata = endpoint.get("metadata") or {}
        if metadata.get("gateway_present") or metadata.get("spec_present"):
            spec_presence = True

    # deprecated_flag: prefer explicit field, else check metadata
    deprecated_flag: bool = endpoint.get("deprecated_flag", False)
    if not deprecated_flag:
        metadata = endpoint.get("metadata") or {}
        if metadata.get("deprecated"):
            deprecated_flag = True

    # owner_present: prefer explicit field, else derive from owning_team
    owner_present: bool = endpoint.get("owner_present", False)
    if not owner_present:
        owning_team = endpoint.get("owning_team")
        if owning_team and str(owning_team).strip():
            owner_present = True

    return ClassificationInput(
        traffic_recency_days=traffic_recency_days,
        spec_presence=spec_presence,
        deprecated_flag=deprecated_flag,
        owner_present=owner_present,
    )
