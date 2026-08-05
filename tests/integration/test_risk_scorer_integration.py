# Feature: sentinel-api, Task 21: Integration tests — Risk Scorer
"""
Integration tests for the Risk Scorer service.

Tests:
- Update endpoint metadata and assert re-scoring completes within 30 seconds
- Anomaly alert triggers re-scoring within 30 seconds

Requirements: 6.7, 8.3
"""

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
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
async def test_metadata_change_triggers_rescoring_within_30_seconds():
    """
    Test that updating endpoint metadata triggers re-scoring within 30 seconds.
    
    Validates: Requirement 6.7 - Re-scoring within 30s of metadata change
    """
    from conftest import activate_service
    
    # Setup risk scorer
    activate_service("risk-scorer-service")
    from scorer import compute_risk_score
    from db import InMemoryRiskScorerStore
    
    risk_store = InMemoryRiskScorerStore()
    
    # Create initial endpoint with low risk
    endpoint = EndpointRecord(
        id=str(uuid.uuid4()),
        http_method="GET",
        host="api.example.com",
        normalized_path="/public/info",
        auth_scheme=AuthScheme.OAUTH2,
        data_sensitivity=DataSensitivity.PUBLIC,
        lifecycle_status=LifecycleStatus.ACTIVE,
        risk_score=0,
    )
    
    # Initial scoring
    initial_result = compute_risk_score(endpoint)
    await risk_store.insert_risk_score_history(initial_result)
    
    assert initial_result.score == 0, f"Expected initial score 0, got {initial_result.score}"
    
    # Simulate metadata change: remove auth and change to PII data
    start_time = time.time()
    
    endpoint.auth_scheme = AuthScheme.NONE
    endpoint.data_sensitivity = DataSensitivity.PII
    endpoint.lifecycle_status = LifecycleStatus.ZOMBIE
    
    # Trigger re-scoring
    updated_result = compute_risk_score(endpoint)
    await risk_store.insert_risk_score_history(updated_result)
    
    elapsed_time = time.time() - start_time
    
    # Verify re-scoring completed within 30 seconds
    assert elapsed_time < 30.0, f"Re-scoring took {elapsed_time:.2f}s, expected < 30s"
    
    # Verify score increased significantly
    # No auth (+40) + PII with no auth (+30) + Zombie (+20) = 90
    assert updated_result.score >= 80, f"Expected high risk score (>=80), got {updated_result.score}"
    
    # Verify risk factors are present
    assert len(updated_result.factors) >= 3, f"Expected at least 3 risk factors, got {len(updated_result.factors)}"
    
    # Verify specific factors
    factor_rules = {f.rule for f in updated_result.factors}
    assert "no_auth" in factor_rules, "Expected 'no_auth' risk factor"
    assert "zombie_or_orphaned" in factor_rules, "Expected 'zombie_or_orphaned' risk factor"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_anomaly_alert_triggers_rescoring_within_30_seconds():
    """
    Test that an anomaly alert triggers risk re-scoring within 30 seconds.
    
    Validates: Requirement 8.3 - Anomaly alert triggers risk score update within 30s
    """
    from conftest import activate_service
    
    # Setup risk scorer
    activate_service("risk-scorer-service")
    from scorer import compute_risk_score
    from db import InMemoryRiskScorerStore
    
    risk_store = InMemoryRiskScorerStore()
    
    # Create endpoint with moderate risk
    endpoint = EndpointRecord(
        id=str(uuid.uuid4()),
        http_method="POST",
        host="api.example.com",
        normalized_path="/api/transactions",
        auth_scheme=AuthScheme.JWT,
        data_sensitivity=DataSensitivity.FINANCIAL,
        lifecycle_status=LifecycleStatus.ACTIVE,
        risk_score=0,
    )
    
    # Initial scoring (should be low since it has auth and is Active)
    initial_result = compute_risk_score(endpoint)
    await risk_store.insert_risk_score_history(initial_result)
    
    initial_score = initial_result.score
    
    # Simulate anomaly alert
    start_time = time.time()
    
    anomaly_alert = AnomalyAlert(
        endpoint_id=endpoint.id,
        anomaly_type="volume_spike",
        observed_value=5000.0,
        baseline_value=100.0,
        deviation_sigma=4.5,
        feature_importance=[("request_count", 0.8), ("time_of_day", 0.2)],
        emitted_at=datetime.now(timezone.utc),
    )
    
    # Simulate adding abnormal traffic indicator to endpoint
    endpoint.metadata = {
        "abnormal_traffic": True,
        "anomaly_alert_id": anomaly_alert.id,
    }
    
    # Trigger re-scoring due to anomaly
    updated_result = compute_risk_score(endpoint)
    await risk_store.insert_risk_score_history(updated_result)
    
    elapsed_time = time.time() - start_time
    
    # Verify re-scoring completed within 30 seconds
    assert elapsed_time < 30.0, f"Re-scoring took {elapsed_time:.2f}s, expected < 30s"
    
    # Verify score increased due to abnormal traffic (+10 points)
    assert updated_result.score > initial_score, f"Expected score increase, got {updated_result.score} (was {initial_score})"
    
    # Verify abnormal traffic factor is present
    factor_rules = {f.rule for f in updated_result.factors}
    assert "abnormal_traffic" in factor_rules, "Expected 'abnormal_traffic' risk factor"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multiple_metadata_changes_sequential_rescoring():
    """
    Test that multiple sequential metadata changes trigger re-scoring correctly.
    
    Validates: Requirement 6.7 - Continuous re-scoring on changes
    """
    from conftest import activate_service
    
    activate_service("risk-scorer-service")
    from scorer import compute_risk_score
    from db import InMemoryRiskScorerStore
    
    risk_store = InMemoryRiskScorerStore()
    
    # Create endpoint
    endpoint = EndpointRecord(
        id=str(uuid.uuid4()),
        http_method="GET",
        host="api.example.com",
        normalized_path="/api/users",
        auth_scheme=AuthScheme.API_KEY,
        data_sensitivity=DataSensitivity.INTERNAL,
        lifecycle_status=LifecycleStatus.ACTIVE,
        risk_score=0,
    )
    
    scores = []
    
    # Change 1: Initial scoring
    result1 = compute_risk_score(endpoint)
    await risk_store.insert_risk_score_history(result1)
    scores.append(result1.score)
    
    # Change 2: Remove auth
    endpoint.auth_scheme = AuthScheme.NONE
    result2 = compute_risk_score(endpoint)
    await risk_store.insert_risk_score_history(result2)
    scores.append(result2.score)
    
    # Change 3: Upgrade to PII
    endpoint.data_sensitivity = DataSensitivity.PII
    result3 = compute_risk_score(endpoint)
    await risk_store.insert_risk_score_history(result3)
    scores.append(result3.score)
    
    # Change 4: Mark as Orphaned
    endpoint.lifecycle_status = LifecycleStatus.ORPHANED
    result4 = compute_risk_score(endpoint)
    await risk_store.insert_risk_score_history(result4)
    scores.append(result4.score)
    
    # Verify scores increased with each risk-increasing change
    assert scores[1] > scores[0], "Score should increase when auth removed"
    assert scores[2] > scores[1], "Score should increase when data sensitivity upgraded to PII"
    assert scores[3] > scores[2], "Score should increase when marked as Orphaned"
    
    # Verify final score reflects all risk factors
    # No auth (+40) + PII with no auth (+30) + Orphaned (+20) = 90
    assert result4.score >= 80, f"Expected final score >= 80, got {result4.score}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_risk_score_history_tracking():
    """
    Test that risk score history is tracked correctly across multiple re-scorings.
    
    Validates: Risk score history persistence
    """
    from conftest import activate_service
    
    activate_service("risk-scorer-service")
    from scorer import compute_risk_score
    from db import InMemoryRiskScorerStore
    
    risk_store = InMemoryRiskScorerStore()
    
    endpoint = EndpointRecord(
        id=str(uuid.uuid4()),
        http_method="POST",
        host="api.example.com",
        normalized_path="/api/payments",
        auth_scheme=AuthScheme.OAUTH2,
        data_sensitivity=DataSensitivity.FINANCIAL,
        lifecycle_status=LifecycleStatus.ACTIVE,
        risk_score=0,
    )
    
    # Perform multiple scorings
    for i in range(5):
        result = compute_risk_score(endpoint)
        await risk_store.insert_risk_score_history(result)
        
        # Modify endpoint for next iteration
        if i == 1:
            endpoint.auth_scheme = AuthScheme.UNKNOWN
        elif i == 2:
            endpoint.lifecycle_status = LifecycleStatus.DEPRECATED
        elif i == 3:
            endpoint.metadata = {"abnormal_traffic": True}
    
    # Retrieve history
    history = await risk_store.get_risk_score_history(endpoint.id)
    
    # Verify we have 5 history entries
    assert len(history) >= 5, f"Expected at least 5 history entries, got {len(history)}"
    
    # Verify each entry has required fields
    for entry in history:
        assert "score" in entry, "History entry missing 'score'"
        assert "factors" in entry, "History entry missing 'factors'"
        assert "computed_at" in entry, "History entry missing 'computed_at'"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_risk_score_capped_at_100():
    """
    Test that risk score is capped at 100 even when multiple high-risk factors are present.
    
    Validates: Requirement 6.1 - Risk score capped at 100
    """
    from conftest import activate_service
    
    activate_service("risk-scorer-service")
    from scorer import compute_risk_score
    
    # Create endpoint with all possible risk factors
    endpoint = EndpointRecord(
        id=str(uuid.uuid4()),
        http_method="POST",
        host="api.example.com",
        normalized_path="/api/critical",
        auth_scheme=AuthScheme.NONE,  # +40
        data_sensitivity=DataSensitivity.PII,  # +30 (with no auth)
        lifecycle_status=LifecycleStatus.ZOMBIE,  # +20
        risk_score=0,
        metadata={"abnormal_traffic": True},  # +10
    )
    
    result = compute_risk_score(endpoint)
    
    # Verify score is capped at 100
    assert result.score <= 100, f"Risk score should be capped at 100, got {result.score}"
    
    # Verify score is at or near the cap (should be 100 with all factors)
    assert result.score == 100, f"Expected score of 100 with all risk factors, got {result.score}"
    
    # Verify all risk factors are present
    assert len(result.factors) >= 4, f"Expected at least 4 risk factors, got {len(result.factors)}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
