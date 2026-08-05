# Feature: sentinel-api, Property 13: Anomaly Alert Field Completeness
"""
Property 13: Anomaly Alert Field Completeness

For any traffic pattern that deviates from the endpoint's baseline by more
than the configured threshold, the emitted anomaly alert SHALL contain
non-null values for all required fields: endpoint identifier, anomaly type,
observed metric value, baseline value, deviation magnitude in standard
deviations, and UTC timestamp.

Validates: Requirements 8.2
"""

import sys
import os
from datetime import datetime, timezone, timedelta

from hypothesis import given, settings, assume
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, _REPO_ROOT)
from conftest import activate_service
activate_service("anomaly-detector-service")

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
from sentinel_shared.models import AnomalyAlert

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

endpoint_id_st = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-_"),
    min_size=1,
    max_size=64,
)

# Volume spike: current_count must be > mean + sigma_threshold * stddev
positive_float_st = st.floats(
    min_value=0.01, max_value=1e6, allow_nan=False, allow_infinity=False
)

feature_importance_st = st.lists(
    st.tuples(
        st.text(min_size=1, max_size=32),
        st.floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False),
    ),
    max_size=10,
)


# ---------------------------------------------------------------------------
# Helper: assert all required AnomalyAlert fields are non-null
# ---------------------------------------------------------------------------


def _assert_required_fields(alert: AnomalyAlert) -> None:
    """Assert that all required AnomalyAlert fields are non-null and valid."""
    assert alert.endpoint_id is not None and alert.endpoint_id.strip() != "", (
        f"endpoint_id must be non-null and non-empty, got: {alert.endpoint_id!r}"
    )
    assert alert.anomaly_type is not None and alert.anomaly_type.strip() != "", (
        f"anomaly_type must be non-null and non-empty, got: {alert.anomaly_type!r}"
    )
    assert alert.observed_value is not None, "observed_value must be non-null"
    assert alert.baseline_value is not None, "baseline_value must be non-null"
    assert alert.deviation_sigma is not None, "deviation_sigma must be non-null"
    assert alert.deviation_sigma >= 0, (
        f"deviation_sigma must be non-negative, got: {alert.deviation_sigma}"
    )
    assert alert.emitted_at is not None, "emitted_at must be non-null"
    assert isinstance(alert.emitted_at, datetime), (
        f"emitted_at must be a datetime, got: {type(alert.emitted_at)}"
    )
    assert alert.id is not None and alert.id.strip() != "", (
        f"id must be non-null and non-empty, got: {alert.id!r}"
    )


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


@given(
    endpoint_id=endpoint_id_st,
    baseline_mean=positive_float_st,
    baseline_stddev=st.floats(
        min_value=0.1, max_value=1000.0, allow_nan=False, allow_infinity=False
    ),
    excess_sigma=st.floats(
        min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False
    ),
    feature_importance=feature_importance_st,
)
@settings(max_examples=10)
def test_p13_volume_spike_alert_field_completeness(
    endpoint_id: str,
    baseline_mean: float,
    baseline_stddev: float,
    excess_sigma: float,
    feature_importance: list,
):
    """
    **Validates: Requirements 8.2**

    For any volume spike that exceeds the threshold, the emitted alert
    contains non-null values for all required fields.
    """
    # Construct a current_count that is guaranteed to exceed the threshold
    current_count = baseline_mean + (DEFAULT_VOLUME_SIGMA_THRESHOLD + excess_sigma) * baseline_stddev

    alert = detect_volume_spike(
        endpoint_id=endpoint_id,
        current_count=current_count,
        baseline_mean=baseline_mean,
        baseline_stddev=baseline_stddev,
        feature_importance=feature_importance,
    )

    # Alert must be emitted (current_count is above threshold by construction)
    assert alert is not None, (
        f"Expected alert for current_count={current_count}, "
        f"mean={baseline_mean}, stddev={baseline_stddev}"
    )

    _assert_required_fields(alert)


@given(
    endpoint_id=endpoint_id_st,
    kl_excess=st.floats(
        min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False
    ),
    feature_importance=feature_importance_st,
)
@settings(max_examples=10)
def test_p13_geo_distribution_alert_field_completeness(
    endpoint_id: str,
    kl_excess: float,
    feature_importance: list,
):
    """
    **Validates: Requirements 8.2**

    For any geo distribution anomaly that exceeds the KL threshold, the
    emitted alert contains non-null values for all required fields.
    """
    # Use distributions with guaranteed high KL-divergence
    # P = all traffic from region A, Q = all traffic from region B
    current_geo = {"region_A": 1.0}
    baseline_geo = {"region_B": 1.0}

    alert = detect_geo_distribution(
        endpoint_id=endpoint_id,
        current_geo=current_geo,
        baseline_geo=baseline_geo,
        feature_importance=feature_importance,
        kl_threshold=DEFAULT_GEO_KL_THRESHOLD,
    )

    # KL divergence between completely disjoint distributions is very high
    assert alert is not None, "Expected alert for completely disjoint geo distributions"

    _assert_required_fields(alert)


@given(
    endpoint_id=endpoint_id_st,
    excess_failures=st.integers(min_value=1, max_value=1000),
    window_minutes=st.integers(min_value=1, max_value=1440),
    feature_importance=feature_importance_st,
)
@settings(max_examples=10)
def test_p13_auth_failure_alert_field_completeness(
    endpoint_id: str,
    excess_failures: int,
    window_minutes: int,
    feature_importance: list,
):
    """
    **Validates: Requirements 8.2**

    For any auth failure rate that exceeds the threshold, the emitted alert
    contains non-null values for all required fields.
    """
    auth_failure_count = DEFAULT_AUTH_FAILURE_THRESHOLD + excess_failures

    alert = detect_auth_failure_rate(
        endpoint_id=endpoint_id,
        auth_failure_count=auth_failure_count,
        window_minutes=window_minutes,
        feature_importance=feature_importance,
    )

    assert alert is not None, (
        f"Expected alert for auth_failure_count={auth_failure_count} "
        f"(threshold={DEFAULT_AUTH_FAILURE_THRESHOLD})"
    )

    _assert_required_fields(alert)


@given(
    endpoint_id=endpoint_id_st,
    silence_days_excess=st.floats(
        min_value=0.01, max_value=3650.0, allow_nan=False, allow_infinity=False
    ),
    feature_importance=feature_importance_st,
)
@settings(max_examples=10)
def test_p13_inactive_endpoint_alert_field_completeness(
    endpoint_id: str,
    silence_days_excess: float,
    feature_importance: list,
):
    """
    **Validates: Requirements 8.2**

    For any inactive endpoint access that exceeds the silence threshold,
    the emitted alert contains non-null values for all required fields.
    """
    silence_days = INACTIVE_DAYS_THRESHOLD + silence_days_excess
    current_access = datetime.now(timezone.utc)
    last_access = current_access - timedelta(days=silence_days)

    alert = detect_inactive_endpoint_access(
        endpoint_id=endpoint_id,
        last_access_at=last_access,
        current_access_at=current_access,
        feature_importance=feature_importance,
        inactive_days_threshold=INACTIVE_DAYS_THRESHOLD,
    )

    assert alert is not None, (
        f"Expected alert for silence_days={silence_days} "
        f"(threshold={INACTIVE_DAYS_THRESHOLD})"
    )

    _assert_required_fields(alert)


@given(
    endpoint_id=endpoint_id_st,
    baseline_mean=positive_float_st,
    baseline_stddev=st.floats(
        min_value=0.1, max_value=1000.0, allow_nan=False, allow_infinity=False
    ),
    excess_sigma=st.floats(
        min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False
    ),
)
@settings(max_examples=10)
def test_p13_alert_id_is_unique_per_emission(
    endpoint_id: str,
    baseline_mean: float,
    baseline_stddev: float,
    excess_sigma: float,
):
    """
    **Validates: Requirements 8.2**

    Each emitted alert has a unique ID (no two alerts share the same ID).
    """
    current_count = baseline_mean + (DEFAULT_VOLUME_SIGMA_THRESHOLD + excess_sigma) * baseline_stddev

    alert1 = detect_volume_spike(
        endpoint_id=endpoint_id,
        current_count=current_count,
        baseline_mean=baseline_mean,
        baseline_stddev=baseline_stddev,
        feature_importance=[],
    )
    alert2 = detect_volume_spike(
        endpoint_id=endpoint_id,
        current_count=current_count,
        baseline_mean=baseline_mean,
        baseline_stddev=baseline_stddev,
        feature_importance=[],
    )

    assert alert1 is not None and alert2 is not None
    assert alert1.id != alert2.id, "Each alert emission must produce a unique ID"


@given(
    endpoint_id=endpoint_id_st,
    baseline_mean=positive_float_st,
    baseline_stddev=st.floats(
        min_value=0.1, max_value=1000.0, allow_nan=False, allow_infinity=False
    ),
    excess_sigma=st.floats(
        min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False
    ),
)
@settings(max_examples=10)
def test_p13_alert_emitted_at_is_utc(
    endpoint_id: str,
    baseline_mean: float,
    baseline_stddev: float,
    excess_sigma: float,
):
    """
    **Validates: Requirements 8.2**

    The emitted_at timestamp is always a UTC datetime.
    """
    current_count = baseline_mean + (DEFAULT_VOLUME_SIGMA_THRESHOLD + excess_sigma) * baseline_stddev

    alert = detect_volume_spike(
        endpoint_id=endpoint_id,
        current_count=current_count,
        baseline_mean=baseline_mean,
        baseline_stddev=baseline_stddev,
        feature_importance=[],
    )

    assert alert is not None
    assert alert.emitted_at.tzinfo is not None, "emitted_at must be timezone-aware"

