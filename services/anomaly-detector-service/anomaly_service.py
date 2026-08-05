"""
Anomaly detection orchestrator for the Anomaly Detector Service.

Coordinates baseline lookup (with cold-start fallback), anomaly detection,
SHAP explainability, alert emission to Kafka, and persistence to PostgreSQL.
"""

from datetime import datetime, timezone
from typing import Optional, Any

import structlog

from sentinel_shared.models import AnomalyAlert

from detectors import (
    detect_volume_spike,
    detect_geo_distribution,
    detect_auth_failure_rate,
    detect_inactive_endpoint_access,
    DEFAULT_VOLUME_SIGMA_THRESHOLD,
    DEFAULT_GEO_KL_THRESHOLD,
    DEFAULT_AUTH_FAILURE_THRESHOLD,
    INACTIVE_DAYS_THRESHOLD,
)
from explainability import compute_shap_importance

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Baseline resolution (with cold-start fallback)
# ---------------------------------------------------------------------------


async def resolve_baseline(
    endpoint_id: str,
    db: Any,
) -> Optional[dict]:
    """
    Resolve the baseline for an endpoint.

    Strategy:
    1. Try to load the individual endpoint baseline.
    2. If training_days < 7 (cold-start), fall back to the cluster baseline
       keyed on f"{lifecycle_status}:{data_sensitivity}".
    3. If no cluster baseline exists either, return None (caller must handle).

    Per the spec, this function NEVER raises "no baseline available" —
    it always returns a baseline dict or None (which callers treat gracefully).
    """
    # Try individual baseline first
    baseline = await db.get_baseline(endpoint_id)

    if baseline is not None and baseline.get("training_days", 0) >= 7:
        return baseline

    # Cold-start: look up cluster baseline
    endpoint = await db.get_endpoint(endpoint_id)
    if endpoint is None:
        logger.warning("resolve_baseline_endpoint_not_found", endpoint_id=endpoint_id)
        return baseline  # Return whatever we have (may be None)

    lifecycle_status = endpoint.get("lifecycle_status", "Active")
    data_sensitivity = endpoint.get("data_sensitivity", "internal")
    cluster_key = f"{lifecycle_status}:{data_sensitivity}"

    cluster_baseline = await db.get_cluster_baseline(cluster_key)
    if cluster_baseline is not None:
        logger.info(
            "cold_start_cluster_baseline_used",
            endpoint_id=endpoint_id,
            cluster_key=cluster_key,
        )
        return cluster_baseline

    # Return individual baseline even if training_days < 7 (better than nothing)
    if baseline is not None:
        logger.info(
            "cold_start_individual_baseline_used",
            endpoint_id=endpoint_id,
            training_days=baseline.get("training_days"),
        )
        return baseline

    logger.warning(
        "no_baseline_available",
        endpoint_id=endpoint_id,
        cluster_key=cluster_key,
    )
    return None


# ---------------------------------------------------------------------------
# Main anomaly evaluation
# ---------------------------------------------------------------------------


async def evaluate_anomalies(
    endpoint_id: str,
    traffic_event: dict,
    db: Any,
    kafka_producer: Optional[Any] = None,
) -> list[AnomalyAlert]:
    """
    Evaluate all four anomaly detectors for a traffic event.

    Args:
        endpoint_id: The endpoint being evaluated.
        traffic_event: Dict with traffic metrics:
            - current_count (float): requests in current 1-hour window
            - baseline_mean (float): mean from 30-day baseline
            - baseline_stddev (float): stddev from 30-day baseline
            - current_geo (dict): {region: fraction} current geo distribution
            - baseline_geo (dict): {region: fraction} baseline geo distribution
            - auth_failure_count (int): auth failures in sliding window
            - window_minutes (int): sliding window duration
            - current_access_at (datetime): timestamp of current access
            - input_window (list[float]): recent hourly counts for SHAP
        db: Database store.
        kafka_producer: Optional Kafka producer for emitting alerts.

    Returns:
        List of AnomalyAlert objects for all detected anomalies.
    """
    alerts: list[AnomalyAlert] = []

    # Resolve baseline (with cold-start fallback)
    baseline = await resolve_baseline(endpoint_id, db)

    # Compute SHAP feature importance (graceful degradation on failure)
    input_window = traffic_event.get("input_window", [])
    feature_importance: list[tuple[str, float]] = []

    if baseline is not None and input_window:
        model_artifact = baseline.get("model_artifact", b"")
        if model_artifact:
            feature_importance = compute_shap_importance(
                model_artifact=model_artifact,
                input_window=input_window,
            )

    # (a) Volume spike
    current_count = traffic_event.get("current_count")
    baseline_mean = traffic_event.get("baseline_mean")
    baseline_stddev = traffic_event.get("baseline_stddev")

    if all(v is not None for v in [current_count, baseline_mean, baseline_stddev]):
        alert = detect_volume_spike(
            endpoint_id=endpoint_id,
            current_count=float(current_count),
            baseline_mean=float(baseline_mean),
            baseline_stddev=float(baseline_stddev),
            feature_importance=feature_importance,
        )
        if alert:
            alerts.append(alert)

    # (b) Geo distribution
    current_geo = traffic_event.get("current_geo", {})
    baseline_geo = traffic_event.get("baseline_geo", {})

    if current_geo and baseline_geo:
        alert = detect_geo_distribution(
            endpoint_id=endpoint_id,
            current_geo=current_geo,
            baseline_geo=baseline_geo,
            feature_importance=feature_importance,
        )
        if alert:
            alerts.append(alert)

    # (c) Auth failure rate
    auth_failure_count = traffic_event.get("auth_failure_count")
    window_minutes = traffic_event.get("window_minutes", 60)

    if auth_failure_count is not None:
        alert = detect_auth_failure_rate(
            endpoint_id=endpoint_id,
            auth_failure_count=int(auth_failure_count),
            window_minutes=int(window_minutes),
            feature_importance=feature_importance,
        )
        if alert:
            alerts.append(alert)

    # (d) Inactive endpoint access
    endpoint = await db.get_endpoint(endpoint_id)
    if endpoint is not None:
        last_access_raw = endpoint.get("last_access_at")
        last_access_at: Optional[datetime] = None
        if last_access_raw is not None:
            if isinstance(last_access_raw, str):
                try:
                    last_access_at = datetime.fromisoformat(
                        last_access_raw.replace("Z", "+00:00")
                    )
                except ValueError:
                    last_access_at = None
            elif isinstance(last_access_raw, datetime):
                last_access_at = last_access_raw

        current_access_at = traffic_event.get(
            "current_access_at", datetime.now(timezone.utc)
        )
        if isinstance(current_access_at, str):
            try:
                current_access_at = datetime.fromisoformat(
                    current_access_at.replace("Z", "+00:00")
                )
            except ValueError:
                current_access_at = datetime.now(timezone.utc)

        alert = detect_inactive_endpoint_access(
            endpoint_id=endpoint_id,
            last_access_at=last_access_at,
            current_access_at=current_access_at,
            feature_importance=feature_importance,
        )
        if alert:
            alerts.append(alert)

    # Persist and emit all detected alerts
    for alert in alerts:
        try:
            await db.insert_alert(alert)
        except Exception as exc:
            logger.error(
                "alert_persist_failed",
                endpoint_id=endpoint_id,
                anomaly_type=alert.anomaly_type,
                error=str(exc),
            )

        if kafka_producer is not None:
            try:
                await kafka_producer.send(
                    "anomaly.alerts",
                    {
                        "alert_id": alert.id,
                        "endpoint_id": alert.endpoint_id,
                        "anomaly_type": alert.anomaly_type,
                        "deviation_sigma": alert.deviation_sigma,
                        "feature_importance": list(alert.feature_importance),
                        "emitted_at": alert.emitted_at.isoformat(),
                    },
                    key=alert.endpoint_id,
                )
            except Exception as exc:
                logger.error(
                    "kafka_alert_publish_failed",
                    endpoint_id=endpoint_id,
                    anomaly_type=alert.anomaly_type,
                    error=str(exc),
                )

    return alerts
