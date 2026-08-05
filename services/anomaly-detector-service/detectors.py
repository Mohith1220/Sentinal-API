"""
Anomaly detectors for the Anomaly Detector Service.

Implements four anomaly detection strategies:
  (a) Volume spike       — z-score > threshold (default 3σ)
  (b) Geo distribution   — KL-divergence from baseline distribution
  (c) Auth failure rate  — sliding-window count > threshold
  (d) Inactive endpoint  — first traffic after >90 days silence

Each detector returns an Optional[AnomalyAlert] — None if no anomaly detected.
"""

import math
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
import structlog

from sentinel_shared.models import AnomalyAlert

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Anomaly type constants
# ---------------------------------------------------------------------------

ANOMALY_VOLUME_SPIKE = "volume_spike"
ANOMALY_GEO_DISTRIBUTION = "geo_distribution"
ANOMALY_AUTH_FAILURE = "auth_failure_rate"
ANOMALY_INACTIVE_ACCESS = "inactive_endpoint_access"

# Default thresholds
DEFAULT_VOLUME_SIGMA_THRESHOLD = 3.0
DEFAULT_GEO_KL_THRESHOLD = 0.5
DEFAULT_AUTH_FAILURE_THRESHOLD = 10  # failures in sliding window
INACTIVE_DAYS_THRESHOLD = 90


# ---------------------------------------------------------------------------
# (a) Volume spike detector
# ---------------------------------------------------------------------------


def detect_volume_spike(
    endpoint_id: str,
    current_count: float = None,
    baseline_mean: float = None,
    baseline_stddev: float = None,
    feature_importance: list[tuple[str, float]] = None,
    sigma_threshold: float = DEFAULT_VOLUME_SIGMA_THRESHOLD,
    # Alternative API for tests
    current_value: float = None,
    baseline_values: list[float] = None,
    threshold_sigma: float = None,
) -> Optional[AnomalyAlert]:
    """
    Detect a request volume spike using z-score.

    Args:
        endpoint_id: The endpoint being evaluated.
        current_count: Observed request count in the current 1-hour window.
        baseline_mean: Mean hourly request count from the 30-day baseline.
        baseline_stddev: Standard deviation of hourly request count from baseline.
        feature_importance: Pre-computed SHAP feature importance list.
        sigma_threshold: Z-score threshold above which a spike is flagged.
        
        # Alternative parameters (for test compatibility):
        current_value: Alias for current_count
        baseline_values: List of baseline values (mean/stddev computed automatically)
        threshold_sigma: Alias for sigma_threshold

    Returns:
        AnomalyAlert if z-score > sigma_threshold, else None.
    """
    # Handle alternative API
    if current_value is not None:
        current_count = current_value
    if baseline_values is not None:
        baseline_mean = float(np.mean(baseline_values))
        baseline_stddev = float(np.std(baseline_values))
    if threshold_sigma is not None:
        sigma_threshold = threshold_sigma
    if feature_importance is None:
        feature_importance = [("request_count", 1.0)]
    
    # Validate we have all required values
    if current_count is None or baseline_mean is None or baseline_stddev is None:
        logger.warning(
            "detect_volume_spike_missing_params",
            endpoint_id=endpoint_id,
            has_current=current_count is not None,
            has_mean=baseline_mean is not None,
            has_stddev=baseline_stddev is not None,
        )
        return None
    
    if baseline_stddev <= 0:
        # Avoid division by zero; treat any non-zero count as a spike
        if current_count > 0 and baseline_mean == 0:
            deviation_sigma = float("inf")
        else:
            return None
    else:
        deviation_sigma = (current_count - baseline_mean) / baseline_stddev

    if deviation_sigma <= sigma_threshold:
        return None

    logger.info(
        "anomaly_detected",
        anomaly_type=ANOMALY_VOLUME_SPIKE,
        endpoint_id=endpoint_id,
        deviation_sigma=deviation_sigma,
    )

    return AnomalyAlert(
        endpoint_id=endpoint_id,
        anomaly_type=ANOMALY_VOLUME_SPIKE,
        observed_value=current_count,
        baseline_value=baseline_mean,
        deviation_sigma=deviation_sigma,
        feature_importance=feature_importance,
        emitted_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# (b) Geo distribution detector
# ---------------------------------------------------------------------------


def _kl_divergence(p: dict[str, float], q: dict[str, float]) -> float:
    """
    Compute KL divergence KL(P || Q) between two discrete distributions.

    Both dicts map region -> probability. Missing keys in Q are treated as
    a small epsilon to avoid log(0).
    """
    epsilon = 1e-10
    total = 0.0
    for region, p_val in p.items():
        if p_val <= 0:
            continue
        q_val = q.get(region, epsilon)
        if q_val <= 0:
            q_val = epsilon
        total += p_val * math.log(p_val / q_val)
    return total


def detect_geo_distribution(
    endpoint_id: str,
    current_geo: dict[str, float],
    baseline_geo: dict[str, float],
    feature_importance: list[tuple[str, float]],
    kl_threshold: float = DEFAULT_GEO_KL_THRESHOLD,
) -> Optional[AnomalyAlert]:
    """
    Detect unusual geographic origin distribution using KL-divergence.

    Args:
        endpoint_id: The endpoint being evaluated.
        current_geo: Current distribution {region: fraction} (values sum to ~1).
        baseline_geo: Baseline distribution {region: fraction}.
        feature_importance: Pre-computed SHAP feature importance list.
        kl_threshold: KL-divergence threshold above which an anomaly is flagged.

    Returns:
        AnomalyAlert if KL-divergence > kl_threshold, else None.
    """
    if not current_geo or not baseline_geo:
        return None

    kl_div = _kl_divergence(current_geo, baseline_geo)

    if kl_div <= kl_threshold:
        return None

    logger.info(
        "anomaly_detected",
        anomaly_type=ANOMALY_GEO_DISTRIBUTION,
        endpoint_id=endpoint_id,
        kl_divergence=kl_div,
    )

    return AnomalyAlert(
        endpoint_id=endpoint_id,
        anomaly_type=ANOMALY_GEO_DISTRIBUTION,
        observed_value=kl_div,
        baseline_value=kl_threshold,
        deviation_sigma=kl_div / max(kl_threshold, 1e-10),
        feature_importance=feature_importance,
        emitted_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# (c) Auth failure rate detector
# ---------------------------------------------------------------------------


def detect_auth_failure_rate(
    endpoint_id: str,
    auth_failure_count: int = None,
    window_minutes: int = None,
    feature_importance: list[tuple[str, float]] = None,
    failure_threshold: int = DEFAULT_AUTH_FAILURE_THRESHOLD,
    # Alternative API for tests
    failure_count: int = None,
    window_size_minutes: int = None,
    threshold: int = None,
) -> Optional[AnomalyAlert]:
    """
    Detect repeated authentication failures in a sliding window.

    Args:
        endpoint_id: The endpoint being evaluated.
        auth_failure_count: Number of auth failures in the current window.
        window_minutes: Duration of the sliding window in minutes.
        feature_importance: Pre-computed SHAP feature importance list.
        failure_threshold: Number of failures above which an anomaly is flagged.
        
        # Alternative parameters (for test compatibility):
        failure_count: Alias for auth_failure_count
        window_size_minutes: Alias for window_minutes
        threshold: Alias for failure_threshold

    Returns:
        AnomalyAlert if auth_failure_count > failure_threshold, else None.
    """
    # Handle alternative API
    if failure_count is not None:
        auth_failure_count = failure_count
    if window_size_minutes is not None:
        window_minutes = window_size_minutes
    if threshold is not None:
        failure_threshold = threshold
    if feature_importance is None:
        feature_importance = [("auth_failures", 1.0)]
    
    if auth_failure_count <= failure_threshold:
        return None

    # Express deviation as multiples of the threshold
    deviation_sigma = auth_failure_count / max(failure_threshold, 1)

    logger.info(
        "anomaly_detected",
        anomaly_type=ANOMALY_AUTH_FAILURE,
        endpoint_id=endpoint_id,
        auth_failure_count=auth_failure_count,
        window_minutes=window_minutes,
    )

    return AnomalyAlert(
        endpoint_id=endpoint_id,
        anomaly_type=ANOMALY_AUTH_FAILURE,
        observed_value=float(auth_failure_count),
        baseline_value=float(failure_threshold),
        deviation_sigma=deviation_sigma,
        feature_importance=feature_importance,
        emitted_at=datetime.now(timezone.utc),
    )


# Alias for test compatibility
detect_auth_failure_spike = detect_auth_failure_rate


# ---------------------------------------------------------------------------
# (d) Inactive endpoint access detector
# ---------------------------------------------------------------------------


def detect_inactive_endpoint_access(
    endpoint_id: str,
    last_access_at: Optional[datetime],
    current_access_at: datetime,
    feature_importance: list[tuple[str, float]] = None,
    inactive_days_threshold: int = INACTIVE_DAYS_THRESHOLD,
    # Alternative API for tests
    inactive_threshold_days: int = None,
) -> Optional[AnomalyAlert]:
    """
    Detect first traffic to a previously inactive endpoint.

    Args:
        endpoint_id: The endpoint being evaluated.
        last_access_at: Timestamp of the last known access (None if never accessed).
        current_access_at: Timestamp of the current access event.
        feature_importance: Pre-computed SHAP feature importance list.
        inactive_days_threshold: Days of silence that qualify as "inactive".
        inactive_threshold_days: Alias for inactive_days_threshold (for test compatibility)

    Returns:
        AnomalyAlert if the endpoint was inactive for > inactive_days_threshold days,
        else None.
    """
    # Handle alternative API
    if inactive_threshold_days is not None:
        inactive_days_threshold = inactive_threshold_days
    if feature_importance is None:
        feature_importance = [("silence_days", 1.0)]
    
    if last_access_at is None:
        # Never accessed before — treat as inactive
        silence_days = float(inactive_days_threshold + 1)
    else:
        # Ensure both datetimes are timezone-aware
        if last_access_at.tzinfo is None:
            last_access_at = last_access_at.replace(tzinfo=timezone.utc)
        if current_access_at.tzinfo is None:
            current_access_at = current_access_at.replace(tzinfo=timezone.utc)

        delta = current_access_at - last_access_at
        silence_days = delta.total_seconds() / 86400.0

    if silence_days <= inactive_days_threshold:
        return None

    logger.info(
        "anomaly_detected",
        anomaly_type=ANOMALY_INACTIVE_ACCESS,
        endpoint_id=endpoint_id,
        silence_days=silence_days,
    )

    return AnomalyAlert(
        endpoint_id=endpoint_id,
        anomaly_type=ANOMALY_INACTIVE_ACCESS,
        observed_value=silence_days,
        baseline_value=float(inactive_days_threshold),
        deviation_sigma=silence_days / max(inactive_days_threshold, 1),
        feature_importance=feature_importance,
        emitted_at=datetime.now(timezone.utc),
    )
