"""
Unit tests for the Anomaly Detector Service.

Tests cover:
  - Volume spike anomaly detection
  - Geo distribution anomaly detection
  - Auth failure rate anomaly detection
  - Inactive endpoint access anomaly detection
  - Cold-start cluster baseline lookup
  - SHAP failure graceful degradation
"""

import sys
import os
from datetime import datetime, timezone, timedelta
from typing import Optional
import asyncio

import pytest

# ---------------------------------------------------------------------------
# Path setup — add anomaly-detector-service to sys.path
# ---------------------------------------------------------------------------
import sys, os
_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, _REPO_ROOT)
from conftest import activate_service
activate_service("anomaly-detector-service")

from detectors import (
    detect_volume_spike,
    detect_geo_distribution,
    detect_auth_failure_rate,
    detect_inactive_endpoint_access,
    ANOMALY_VOLUME_SPIKE,
    ANOMALY_GEO_DISTRIBUTION,
    ANOMALY_AUTH_FAILURE,
    ANOMALY_INACTIVE_ACCESS,
    DEFAULT_VOLUME_SIGMA_THRESHOLD,
    DEFAULT_AUTH_FAILURE_THRESHOLD,
)
from db import InMemoryAnomalyStore
from anomaly_service import resolve_baseline, evaluate_anomalies
from sentinel_shared.models import AnomalyAlert


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    """Run a coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


EMPTY_FEATURES: list[tuple[str, float]] = []


# ---------------------------------------------------------------------------
# (a) Volume spike detector
# ---------------------------------------------------------------------------


class TestVolumeSpikeDetector:
    def test_spike_detected_above_threshold(self):
        """Z-score > 3σ triggers a volume spike alert."""
        alert = detect_volume_spike(
            endpoint_id="ep-1",
            current_count=1000.0,
            baseline_mean=100.0,
            baseline_stddev=10.0,
            feature_importance=EMPTY_FEATURES,
        )
        assert alert is not None
        assert alert.anomaly_type == ANOMALY_VOLUME_SPIKE
        assert alert.endpoint_id == "ep-1"
        assert alert.observed_value == 1000.0
        assert alert.baseline_value == 100.0
        assert alert.deviation_sigma > DEFAULT_VOLUME_SIGMA_THRESHOLD

    def test_no_spike_below_threshold(self):
        """Z-score <= 3σ does not trigger an alert."""
        alert = detect_volume_spike(
            endpoint_id="ep-2",
            current_count=110.0,  # only 1σ above mean
            baseline_mean=100.0,
            baseline_stddev=10.0,
            feature_importance=EMPTY_FEATURES,
        )
        assert alert is None

    def test_spike_at_exact_threshold_not_triggered(self):
        """Z-score exactly at threshold does not trigger (must be strictly greater)."""
        alert = detect_volume_spike(
            endpoint_id="ep-3",
            current_count=130.0,  # exactly 3σ above mean
            baseline_mean=100.0,
            baseline_stddev=10.0,
            feature_importance=EMPTY_FEATURES,
        )
        assert alert is None

    def test_spike_just_above_threshold(self):
        """Z-score just above threshold triggers alert."""
        alert = detect_volume_spike(
            endpoint_id="ep-4",
            current_count=130.1,  # just above 3σ
            baseline_mean=100.0,
            baseline_stddev=10.0,
            feature_importance=EMPTY_FEATURES,
        )
        assert alert is not None

    def test_alert_has_required_fields(self):
        """Volume spike alert contains all required AnomalyAlert fields."""
        alert = detect_volume_spike(
            endpoint_id="ep-5",
            current_count=500.0,
            baseline_mean=100.0,
            baseline_stddev=10.0,
            feature_importance=[("hourly_request_count", 0.8)],
        )
        assert alert is not None
        assert alert.endpoint_id == "ep-5"
        assert alert.anomaly_type is not None and alert.anomaly_type != ""
        assert alert.observed_value is not None
        assert alert.baseline_value is not None
        assert alert.deviation_sigma >= 0
        assert alert.emitted_at is not None
        assert isinstance(alert.id, str) and alert.id != ""

    def test_zero_stddev_with_nonzero_count(self):
        """Zero stddev with non-zero count on a zero-mean baseline triggers alert."""
        alert = detect_volume_spike(
            endpoint_id="ep-6",
            current_count=1.0,
            baseline_mean=0.0,
            baseline_stddev=0.0,
            feature_importance=EMPTY_FEATURES,
        )
        assert alert is not None

    def test_feature_importance_preserved(self):
        """Feature importance list is preserved in the alert."""
        features = [("hourly_request_count", 0.9), ("error_rate", 0.3)]
        alert = detect_volume_spike(
            endpoint_id="ep-7",
            current_count=500.0,
            baseline_mean=100.0,
            baseline_stddev=10.0,
            feature_importance=features,
        )
        assert alert is not None
        assert alert.feature_importance == features


# ---------------------------------------------------------------------------
# (b) Geo distribution detector
# ---------------------------------------------------------------------------


class TestGeoDistributionDetector:
    def test_geo_anomaly_detected(self):
        """High KL-divergence triggers a geo distribution alert."""
        baseline_geo = {"US": 0.8, "EU": 0.2}
        # Completely different distribution
        current_geo = {"CN": 0.9, "RU": 0.1}

        alert = detect_geo_distribution(
            endpoint_id="ep-geo-1",
            current_geo=current_geo,
            baseline_geo=baseline_geo,
            feature_importance=EMPTY_FEATURES,
        )
        assert alert is not None
        assert alert.anomaly_type == ANOMALY_GEO_DISTRIBUTION
        assert alert.endpoint_id == "ep-geo-1"

    def test_no_geo_anomaly_similar_distribution(self):
        """Low KL-divergence does not trigger an alert."""
        baseline_geo = {"US": 0.8, "EU": 0.2}
        current_geo = {"US": 0.79, "EU": 0.21}  # nearly identical

        alert = detect_geo_distribution(
            endpoint_id="ep-geo-2",
            current_geo=current_geo,
            baseline_geo=baseline_geo,
            feature_importance=EMPTY_FEATURES,
        )
        assert alert is None

    def test_empty_geo_data_returns_none(self):
        """Empty geo distributions return None (no alert)."""
        alert = detect_geo_distribution(
            endpoint_id="ep-geo-3",
            current_geo={},
            baseline_geo={"US": 1.0},
            feature_importance=EMPTY_FEATURES,
        )
        assert alert is None

    def test_alert_has_required_fields(self):
        """Geo distribution alert contains all required fields."""
        alert = detect_geo_distribution(
            endpoint_id="ep-geo-4",
            current_geo={"CN": 1.0},
            baseline_geo={"US": 1.0},
            feature_importance=EMPTY_FEATURES,
        )
        assert alert is not None
        assert alert.endpoint_id == "ep-geo-4"
        assert alert.anomaly_type == ANOMALY_GEO_DISTRIBUTION
        assert alert.observed_value >= 0
        assert alert.deviation_sigma >= 0
        assert alert.emitted_at is not None


# ---------------------------------------------------------------------------
# (c) Auth failure rate detector
# ---------------------------------------------------------------------------


class TestAuthFailureDetector:
    def test_auth_failure_detected(self):
        """Auth failure count above threshold triggers an alert."""
        alert = detect_auth_failure_rate(
            endpoint_id="ep-auth-1",
            auth_failure_count=50,
            window_minutes=60,
            feature_importance=EMPTY_FEATURES,
        )
        assert alert is not None
        assert alert.anomaly_type == ANOMALY_AUTH_FAILURE
        assert alert.endpoint_id == "ep-auth-1"
        assert alert.observed_value == 50.0
        assert alert.baseline_value == float(DEFAULT_AUTH_FAILURE_THRESHOLD)

    def test_no_auth_failure_below_threshold(self):
        """Auth failure count at or below threshold does not trigger."""
        alert = detect_auth_failure_rate(
            endpoint_id="ep-auth-2",
            auth_failure_count=DEFAULT_AUTH_FAILURE_THRESHOLD,
            window_minutes=60,
            feature_importance=EMPTY_FEATURES,
        )
        assert alert is None

    def test_zero_failures_no_alert(self):
        """Zero auth failures never triggers an alert."""
        alert = detect_auth_failure_rate(
            endpoint_id="ep-auth-3",
            auth_failure_count=0,
            window_minutes=60,
            feature_importance=EMPTY_FEATURES,
        )
        assert alert is None

    def test_alert_has_required_fields(self):
        """Auth failure alert contains all required fields."""
        alert = detect_auth_failure_rate(
            endpoint_id="ep-auth-4",
            auth_failure_count=100,
            window_minutes=30,
            feature_importance=EMPTY_FEATURES,
        )
        assert alert is not None
        assert alert.endpoint_id == "ep-auth-4"
        assert alert.anomaly_type == ANOMALY_AUTH_FAILURE
        assert alert.deviation_sigma > 1.0
        assert alert.emitted_at is not None


# ---------------------------------------------------------------------------
# (d) Inactive endpoint access detector
# ---------------------------------------------------------------------------


class TestInactiveEndpointDetector:
    def test_inactive_endpoint_detected(self):
        """Access after >90 days silence triggers an inactive endpoint alert."""
        last_access = datetime.now(timezone.utc) - timedelta(days=100)
        current_access = datetime.now(timezone.utc)

        alert = detect_inactive_endpoint_access(
            endpoint_id="ep-inactive-1",
            last_access_at=last_access,
            current_access_at=current_access,
            feature_importance=EMPTY_FEATURES,
        )
        assert alert is not None
        assert alert.anomaly_type == ANOMALY_INACTIVE_ACCESS
        assert alert.endpoint_id == "ep-inactive-1"
        assert alert.observed_value > 90

    def test_no_alert_for_recent_access(self):
        """Access within 90 days does not trigger an alert."""
        last_access = datetime.now(timezone.utc) - timedelta(days=30)
        current_access = datetime.now(timezone.utc)

        alert = detect_inactive_endpoint_access(
            endpoint_id="ep-inactive-2",
            last_access_at=last_access,
            current_access_at=current_access,
            feature_importance=EMPTY_FEATURES,
        )
        assert alert is None

    def test_never_accessed_triggers_alert(self):
        """Endpoint with no prior access (last_access_at=None) triggers alert."""
        alert = detect_inactive_endpoint_access(
            endpoint_id="ep-inactive-3",
            last_access_at=None,
            current_access_at=datetime.now(timezone.utc),
            feature_importance=EMPTY_FEATURES,
        )
        assert alert is not None
        assert alert.anomaly_type == ANOMALY_INACTIVE_ACCESS

    def test_exactly_90_days_no_alert(self):
        """Access exactly at 90 days does not trigger (must be strictly greater)."""
        last_access = datetime.now(timezone.utc) - timedelta(days=90)
        current_access = datetime.now(timezone.utc)

        alert = detect_inactive_endpoint_access(
            endpoint_id="ep-inactive-4",
            last_access_at=last_access,
            current_access_at=current_access,
            feature_importance=EMPTY_FEATURES,
        )
        assert alert is None

    def test_alert_has_required_fields(self):
        """Inactive endpoint alert contains all required fields."""
        last_access = datetime.now(timezone.utc) - timedelta(days=120)
        alert = detect_inactive_endpoint_access(
            endpoint_id="ep-inactive-5",
            last_access_at=last_access,
            current_access_at=datetime.now(timezone.utc),
            feature_importance=EMPTY_FEATURES,
        )
        assert alert is not None
        assert alert.endpoint_id == "ep-inactive-5"
        assert alert.anomaly_type == ANOMALY_INACTIVE_ACCESS
        assert alert.deviation_sigma >= 0
        assert alert.emitted_at is not None


# ---------------------------------------------------------------------------
# Cold-start cluster baseline lookup
# ---------------------------------------------------------------------------


class TestColdStartBaseline:
    def test_cold_start_uses_cluster_baseline(self):
        """
        When an endpoint has training_days < 7, resolve_baseline falls back
        to the cluster baseline keyed on lifecycle_status:data_sensitivity.
        """
        store = InMemoryAnomalyStore()
        endpoint_id = "ep-cold-1"

        # Seed endpoint with lifecycle_status and data_sensitivity
        store.seed_endpoint(
            endpoint_id,
            lifecycle_status="Zombie",
            data_sensitivity="PII",
        )

        # Seed an individual baseline with only 3 days of training
        store.seed_baseline(
            endpoint_id=endpoint_id,
            cluster_key=None,
            model_artifact=b"individual_model",
            training_days=3,
        )

        # Seed a cluster baseline for "Zombie:PII"
        store.seed_baseline(
            endpoint_id=None,
            cluster_key="Zombie:PII",
            model_artifact=b"cluster_model",
            training_days=30,
        )

        baseline = _run(resolve_baseline(endpoint_id, store))

        assert baseline is not None
        assert baseline["model_artifact"] == b"cluster_model"
        assert baseline["cluster_key"] == "Zombie:PII"

    def test_individual_baseline_used_when_sufficient(self):
        """
        When an endpoint has training_days >= 7, the individual baseline is used.
        """
        store = InMemoryAnomalyStore()
        endpoint_id = "ep-cold-2"

        store.seed_endpoint(endpoint_id, lifecycle_status="Active", data_sensitivity="internal")

        store.seed_baseline(
            endpoint_id=endpoint_id,
            cluster_key=None,
            model_artifact=b"individual_model_7days",
            training_days=7,
        )

        # Also seed a cluster baseline (should NOT be used)
        store.seed_baseline(
            endpoint_id=None,
            cluster_key="Active:internal",
            model_artifact=b"cluster_model",
            training_days=30,
        )

        baseline = _run(resolve_baseline(endpoint_id, store))

        assert baseline is not None
        assert baseline["model_artifact"] == b"individual_model_7days"

    def test_no_baseline_returns_none_without_error(self):
        """
        When no baseline exists at all, resolve_baseline returns None
        without raising an exception.
        """
        store = InMemoryAnomalyStore()
        endpoint_id = "ep-cold-3"

        store.seed_endpoint(endpoint_id, lifecycle_status="Active", data_sensitivity="internal")

        # No baselines seeded
        baseline = _run(resolve_baseline(endpoint_id, store))

        # Must return None, not raise an exception
        assert baseline is None

    def test_cold_start_cluster_key_format(self):
        """
        The cluster key is formatted as f"{lifecycle_status}:{data_sensitivity}".
        """
        store = InMemoryAnomalyStore()
        endpoint_id = "ep-cold-4"

        store.seed_endpoint(
            endpoint_id,
            lifecycle_status="Orphaned",
            data_sensitivity="financial",
        )

        # Seed cluster baseline with the expected key format
        store.seed_baseline(
            endpoint_id=None,
            cluster_key="Orphaned:financial",
            model_artifact=b"orphaned_financial_model",
            training_days=14,
        )

        baseline = _run(resolve_baseline(endpoint_id, store))

        assert baseline is not None
        assert baseline["cluster_key"] == "Orphaned:financial"


# ---------------------------------------------------------------------------
# SHAP failure graceful degradation
# ---------------------------------------------------------------------------


class TestShapGracefulDegradation:
    def test_shap_failure_returns_empty_list(self):
        """
        When SHAP computation fails, compute_shap_importance returns []
        without raising an exception.
        """
        from explainability import compute_shap_importance

        # Pass invalid model artifact to trigger failure
        result = compute_shap_importance(
            model_artifact=b"not_a_valid_model",
            input_window=[1.0] * 24,
        )

        assert result == []

    def test_shap_failure_empty_input_returns_empty_list(self):
        """
        Empty input window returns [] without raising.
        """
        from explainability import compute_shap_importance

        result = compute_shap_importance(
            model_artifact=b"",
            input_window=[],
        )

        assert result == []

    def test_alert_emitted_with_empty_feature_importance_on_shap_failure(self):
        """
        When SHAP fails, the anomaly alert is still emitted with
        feature_importance = [].
        """
        store = InMemoryAnomalyStore()
        endpoint_id = "ep-shap-1"

        store.seed_endpoint(
            endpoint_id,
            lifecycle_status="Active",
            data_sensitivity="internal",
            last_access_at=None,
        )

        # Seed a baseline with invalid model artifact
        store.seed_baseline(
            endpoint_id=endpoint_id,
            cluster_key=None,
            model_artifact=b"invalid_model",
            training_days=7,
        )

        traffic_event = {
            "current_count": 1000.0,
            "baseline_mean": 100.0,
            "baseline_stddev": 10.0,
            "input_window": [float(i) for i in range(25)],
            "current_access_at": datetime.now(timezone.utc),
        }

        alerts = _run(
            evaluate_anomalies(
                endpoint_id=endpoint_id,
                traffic_event=traffic_event,
                db=store,
            )
        )

        # Volume spike should be detected
        volume_alerts = [a for a in alerts if a.anomaly_type == ANOMALY_VOLUME_SPIKE]
        assert len(volume_alerts) == 1

        # Feature importance should be empty (SHAP failed)
        assert volume_alerts[0].feature_importance == []

    def test_shap_result_sorted_by_abs_contribution(self):
        """
        When SHAP succeeds, results are sorted descending by abs(contribution).
        """
        pytest.importorskip("torch", reason="PyTorch not installed")

        from explainability import compute_shap_importance
        from baseline_model import train_baseline

        # Train a real model
        hourly_counts = [float(i % 24 + 1) for i in range(7 * 24 + 1)]
        model_artifact = train_baseline(hourly_counts, history_days=7, epochs=5)

        result = compute_shap_importance(
            model_artifact=model_artifact,
            input_window=hourly_counts[:25],
        )

        if result:  # May be empty if model is trivial
            abs_contributions = [abs(c) for _, c in result]
            assert abs_contributions == sorted(abs_contributions, reverse=True), (
                "Feature importance should be sorted descending by abs(contribution)"
            )


# ---------------------------------------------------------------------------
# AnomalyAlert model validation
# ---------------------------------------------------------------------------


class TestAnomalyAlertModel:
    def test_alert_requires_non_empty_endpoint_id(self):
        """AnomalyAlert rejects empty endpoint_id."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AnomalyAlert(
                endpoint_id="",
                anomaly_type="volume_spike",
                observed_value=100.0,
                baseline_value=50.0,
                deviation_sigma=3.5,
                feature_importance=[],
                emitted_at=datetime.now(timezone.utc),
            )

    def test_alert_requires_non_negative_deviation_sigma(self):
        """AnomalyAlert rejects negative deviation_sigma."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            AnomalyAlert(
                endpoint_id="ep-1",
                anomaly_type="volume_spike",
                observed_value=100.0,
                baseline_value=50.0,
                deviation_sigma=-1.0,
                feature_importance=[],
                emitted_at=datetime.now(timezone.utc),
            )

    def test_alert_auto_generates_id(self):
        """AnomalyAlert auto-generates a unique ID."""
        alert1 = AnomalyAlert(
            endpoint_id="ep-1",
            anomaly_type="volume_spike",
            observed_value=100.0,
            baseline_value=50.0,
            deviation_sigma=3.5,
            feature_importance=[],
            emitted_at=datetime.now(timezone.utc),
        )
        alert2 = AnomalyAlert(
            endpoint_id="ep-1",
            anomaly_type="volume_spike",
            observed_value=100.0,
            baseline_value=50.0,
            deviation_sigma=3.5,
            feature_importance=[],
            emitted_at=datetime.now(timezone.utc),
        )
        assert alert1.id != alert2.id
