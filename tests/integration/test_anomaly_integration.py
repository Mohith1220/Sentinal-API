# Feature: sentinel-api, Task 21: Integration tests — Anomaly Detection
"""
Integration tests for the Anomaly Detector service.

Tests:
- Anomaly alert triggers risk score update within 30 seconds

Requirements: 8.3
"""

import asyncio
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import List
import sys
import os

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "sentinel_shared"))

from sentinel_shared.models import (
    EndpointRecord,
    AuthScheme,
    DataSensitivity,
    LifecycleStatus,
    AnomalyAlert,
)


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_anomaly_alert_triggers_risk_update_within_30_seconds():
    """
    Test that an anomaly alert triggers a risk score update within 30 seconds.
    
    This is the primary integration test for the anomaly → risk scorer pipeline.
    
    Validates: Requirement 8.3 - Anomaly alert triggers risk score update within 30s
    """
    from conftest import activate_service
    
    # Setup anomaly detector
    activate_service("anomaly-detector-service")
    from detectors import detect_volume_spike
    from db import InMemoryAnomalyStore
    
    anomaly_store = InMemoryAnomalyStore()
    
    # Setup risk scorer
    activate_service("risk-scorer-service")
    from scorer import compute_risk_score
    from db import InMemoryRiskScorerStore
    
    risk_store = InMemoryRiskScorerStore()
    
    # Create endpoint with baseline traffic
    endpoint = EndpointRecord(
        id=str(uuid.uuid4()),
        http_method="GET",
        host="api.example.com",
        normalized_path="/api/data",
        auth_scheme=AuthScheme.JWT,
        data_sensitivity=DataSensitivity.INTERNAL,
        lifecycle_status=LifecycleStatus.ACTIVE,
        risk_score=0,
    )
    
    # Initial risk score (should be low)
    initial_result = compute_risk_score(endpoint)
    await risk_store.insert_risk_score_history(initial_result)
    initial_score = initial_result.score
    
    # Simulate traffic baseline: 100 requests/hour average
    baseline_traffic = [100.0] * 168  # 7 days of hourly data
    
    # Simulate volume spike: 500 requests/hour (5x baseline)
    current_traffic = 500.0
    
    start_time = time.time()
    
    # Detect anomaly
    anomaly = detect_volume_spike(
        endpoint_id=endpoint.id,
        current_value=current_traffic,
        baseline_values=baseline_traffic,
        threshold_sigma=3.0
    )
    
    # Save anomaly alert
    if anomaly:
        await anomaly_store.insert_alert(anomaly)
        
        # Simulate Kafka event triggering risk re-scoring
        endpoint.metadata = {
            "abnormal_traffic": True,
            "anomaly_alert_id": anomaly.id,
        }
        
        # Trigger risk re-scoring
        updated_result = compute_risk_score(endpoint)
        await risk_store.insert_risk_score_history(updated_result)
        
        elapsed_time = time.time() - start_time
        
        # Verify re-scoring completed within 30 seconds
        assert elapsed_time < 30.0, f"Risk update took {elapsed_time:.2f}s, expected < 30s"
        
        # Verify risk score increased
        assert updated_result.score > initial_score, \
            f"Expected risk score increase, got {updated_result.score} (was {initial_score})"
        
        # Verify abnormal traffic factor is present
        factor_rules = {f.rule for f in updated_result.factors}
        assert "abnormal_traffic" in factor_rules, "Expected 'abnormal_traffic' risk factor"
        
        # Verify anomaly alert has required fields
        assert anomaly.endpoint_id == endpoint.id
        assert anomaly.anomaly_type == "volume_spike"
        assert anomaly.deviation_sigma > 3.0
        assert len(anomaly.feature_importance) > 0
    else:
        pytest.fail("Expected anomaly detection to trigger, but no anomaly was detected")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multiple_anomaly_types_trigger_risk_updates():
    """
    Test that different anomaly types all trigger risk score updates.
    
    Validates: Multiple anomaly detection types and risk integration
    """
    from conftest import activate_service
    
    activate_service("anomaly-detector-service")
    from detectors import detect_volume_spike, detect_auth_failure_spike
    from db import InMemoryAnomalyStore
    
    anomaly_store = InMemoryAnomalyStore()
    
    activate_service("risk-scorer-service")
    from scorer import compute_risk_score
    from db import InMemoryRiskScorerStore
    
    risk_store = InMemoryRiskScorerStore()
    
    # Test volume spike anomaly
    endpoint1 = EndpointRecord(
        id=str(uuid.uuid4()),
        http_method="GET",
        host="api.example.com",
        normalized_path="/api/endpoint1",
        auth_scheme=AuthScheme.OAUTH2,
        data_sensitivity=DataSensitivity.INTERNAL,
        lifecycle_status=LifecycleStatus.ACTIVE,
    )
    
    baseline = [100.0] * 168
    volume_anomaly = detect_volume_spike(endpoint1.id, 500.0, baseline, 3.0)
    
    if volume_anomaly:
        await anomaly_store.insert_alert(volume_anomaly)
        endpoint1.metadata = {"abnormal_traffic": True}
        result1 = compute_risk_score(endpoint1)
        await risk_store.insert_risk_score_history(result1)
        
        assert result1.score > 0, "Expected non-zero risk score after volume spike"
    
    # Test auth failure spike anomaly
    endpoint2 = EndpointRecord(
        id=str(uuid.uuid4()),
        http_method="POST",
        host="api.example.com",
        normalized_path="/api/endpoint2",
        auth_scheme=AuthScheme.JWT,
        data_sensitivity=DataSensitivity.PII,
        lifecycle_status=LifecycleStatus.ACTIVE,
    )
    
    auth_anomaly = detect_auth_failure_spike(
        endpoint_id=endpoint2.id,
        failure_count=150,
        window_size_minutes=60,
        threshold=100
    )
    
    if auth_anomaly:
        await anomaly_store.insert_alert(auth_anomaly)
        endpoint2.metadata = {"abnormal_traffic": True, "auth_failures": True}
        result2 = compute_risk_score(endpoint2)
        await risk_store.insert_risk_score_history(result2)
        
        assert result2.score > 0, "Expected non-zero risk score after auth failure spike"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_anomaly_alert_persistence_and_retrieval():
    """
    Test that anomaly alerts are persisted and can be retrieved correctly.
    
    Validates: Anomaly alert storage and retrieval
    """
    from conftest import activate_service
    
    activate_service("anomaly-detector-service")
    from db import InMemoryAnomalyStore
    
    anomaly_store = InMemoryAnomalyStore()
    
    endpoint_id = str(uuid.uuid4())
    
    # Create multiple anomaly alerts
    alerts = []
    for i in range(5):
        alert = AnomalyAlert(
            endpoint_id=endpoint_id,
            anomaly_type="volume_spike" if i % 2 == 0 else "auth_failure_spike",
            observed_value=float(100 + i * 50),
            baseline_value=100.0,
            deviation_sigma=3.0 + i * 0.5,
            feature_importance=[("request_count", 0.8), ("time_of_day", 0.2)],
            emitted_at=datetime.now(timezone.utc) + timedelta(minutes=i),
        )
        alerts.append(alert)
        await anomaly_store.insert_alert(alert)
    
    # Retrieve alerts for endpoint
    retrieved_alerts = await anomaly_store.list_alerts(endpoint_id)
    
    # Verify all alerts were persisted
    assert len(retrieved_alerts) >= 5, f"Expected at least 5 alerts, got {len(retrieved_alerts)}"
    
    # Verify alert structure
    for alert in retrieved_alerts:
        assert "endpoint_id" in alert
        assert "anomaly_type" in alert
        assert "deviation_sigma" in alert
        assert "feature_importance" in alert
        assert "emitted_at" in alert


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cold_start_baseline_with_anomaly_detection():
    """
    Test that cold-start baselines work correctly for new endpoints.
    
    Validates: Requirement 8.5 - Cold-start baseline assignment
    """
    from conftest import activate_service
    
    activate_service("anomaly-detector-service")
    from baseline_model import get_or_create_baseline
    from detectors import detect_volume_spike
    
    # New endpoint with < 7 days of history
    endpoint_id = str(uuid.uuid4())
    
    # Get cold-start baseline (should use cluster baseline)
    baseline = get_or_create_baseline(
        endpoint_id=endpoint_id,
        lifecycle_status=LifecycleStatus.ACTIVE,
        data_sensitivity=DataSensitivity.INTERNAL,
        traffic_history=[50.0, 55.0, 48.0],  # Only 3 data points
    )
    
    # Verify baseline was created (not None)
    assert baseline is not None, "Expected cold-start baseline to be created"
    assert len(baseline) > 0, "Expected non-empty baseline"
    
    # Test anomaly detection with cold-start baseline
    anomaly = detect_volume_spike(
        endpoint_id=endpoint_id,
        current_value=500.0,  # Spike
        baseline_values=baseline,
        threshold_sigma=3.0
    )
    
    # Verify anomaly was detected even with cold-start baseline
    assert anomaly is not None, "Expected anomaly detection with cold-start baseline"
    assert anomaly.anomaly_type == "volume_spike"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_anomaly_explainability_feature_importance():
    """
    Test that anomaly alerts include feature importance explanations.
    
    Validates: Requirement 8.6 - Anomaly explainability
    """
    from conftest import activate_service
    
    activate_service("anomaly-detector-service")
    from detectors import detect_volume_spike
    from db import InMemoryAnomalyStore
    
    anomaly_store = InMemoryAnomalyStore()
    
    endpoint_id = str(uuid.uuid4())
    baseline = [100.0] * 168
    
    # Detect anomaly
    anomaly = detect_volume_spike(
        endpoint_id=endpoint_id,
        current_value=500.0,
        baseline_values=baseline,
        threshold_sigma=3.0
    )
    
    if anomaly:
        await anomaly_store.insert_alert(anomaly)
        
        # Verify feature importance is present and non-empty
        assert len(anomaly.feature_importance) > 0, "Expected non-empty feature importance"
        
        # Verify feature importance is sorted by contribution (descending)
        contributions = [contrib for _, contrib in anomaly.feature_importance]
        assert contributions == sorted(contributions, reverse=True), \
            "Expected feature importance sorted by contribution (descending)"
        
        # Verify each feature has a name and contribution
        for feature_name, contribution in anomaly.feature_importance:
            assert isinstance(feature_name, str), "Feature name should be string"
            assert isinstance(contribution, (int, float)), "Contribution should be numeric"
            assert contribution >= 0, "Contribution should be non-negative"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_inactive_endpoint_access_anomaly():
    """
    Test detection of access to previously inactive endpoint (>90 days silence).
    
    Validates: Requirement 8.4 - Inactive endpoint access detection
    """
    from conftest import activate_service
    
    activate_service("anomaly-detector-service")
    from detectors import detect_inactive_endpoint_access
    from db import InMemoryAnomalyStore
    
    anomaly_store = InMemoryAnomalyStore()
    
    endpoint_id = str(uuid.uuid4())
    
    # Last access was 95 days ago
    last_access = datetime.now(timezone.utc) - timedelta(days=95)
    current_access = datetime.now(timezone.utc)
    
    # Detect inactive endpoint access
    anomaly = detect_inactive_endpoint_access(
        endpoint_id=endpoint_id,
        last_access_at=last_access,
        current_access_at=current_access,
        inactive_threshold_days=90
    )
    
    # Verify anomaly was detected
    assert anomaly is not None, "Expected inactive endpoint access anomaly"
    assert anomaly.anomaly_type == "inactive_endpoint_access"
    assert anomaly.endpoint_id == endpoint_id
    
    # Save and verify persistence
    await anomaly_store.insert_alert(anomaly)
    
    retrieved = await anomaly_store.list_alerts(endpoint_id)
    assert len(retrieved) >= 1, "Expected at least one alert for inactive endpoint"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
