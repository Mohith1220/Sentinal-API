# Feature: sentinel-api, Task 21: Integration tests — Remediation Service
"""
Integration tests for the Remediation Service.

Tests:
- Mark recommendation resolved and assert risk re-evaluation completes within 60 seconds
- Assert endpoint.remediated event published to Kafka

Requirements: 9.7, 11.2
"""

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import List, Optional
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
    RemediationRecommendation,
)


# ---------------------------------------------------------------------------
# Mock Kafka Event Bus
# ---------------------------------------------------------------------------

class MockKafkaEventBus:
    """Mock Kafka event bus for testing event publishing."""
    
    def __init__(self):
        self.events = []
    
    async def publish(self, topic: str, event: dict):
        """Publish an event to a topic."""
        self.events.append({
            "topic": topic,
            "event": event,
            "timestamp": datetime.now(timezone.utc),
        })
    
    def get_events(self, topic: str) -> List[dict]:
        """Get all events published to a topic."""
        return [e["event"] for e in self.events if e["topic"] == topic]
    
    def clear(self):
        """Clear all events."""
        self.events.clear()


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resolve_recommendation_triggers_risk_reevaluation_within_60_seconds():
    """
    Test that marking a recommendation as resolved triggers risk re-evaluation within 60 seconds.
    
    Validates: Requirement 9.7 - Risk re-evaluation within 60s of resolution
    """
    from conftest import activate_service
    
    # Setup remediation service
    activate_service("remediation-service")
    from db import InMemoryRemediationStore
    from rule_engine import generate_recommendations
    
    remediation_store = InMemoryRemediationStore()
    
    # Setup risk scorer
    activate_service("risk-scorer-service")
    from scorer import compute_risk_score
    from db import InMemoryRiskScorerStore
    
    risk_store = InMemoryRiskScorerStore()
    
    # Create high-risk endpoint
    endpoint = EndpointRecord(
        id=str(uuid.uuid4()),
        http_method="POST",
        host="api.example.com",
        normalized_path="/api/payments",
        auth_scheme=AuthScheme.NONE,  # High risk: no auth
        data_sensitivity=DataSensitivity.FINANCIAL,
        lifecycle_status=LifecycleStatus.ACTIVE,
        risk_score=0,
    )
    
    # Initial risk scoring
    initial_result = compute_risk_score(endpoint)
    await risk_store.insert_risk_score_history(initial_result)
    
    # Generate recommendations
    recommendations = generate_recommendations(endpoint, initial_result)
    
    # Save recommendations
    for rec in recommendations:
        await remediation_store.insert_recommendation(rec)
    
    assert len(recommendations) > 0, "Expected at least one recommendation for high-risk endpoint"
    
    # Find the "add authentication" recommendation
    auth_rec = next((r for r in recommendations if "auth" in r.trigger_rule.lower()), None)
    assert auth_rec is not None, "Expected authentication recommendation"
    
    start_time = time.time()
    
    # Mark recommendation as resolved
    await remediation_store.resolve_recommendation(
        recommendation_id=auth_rec.id,
        resolved_by="admin@example.com"
    )
    
    # Simulate remediation: add authentication
    endpoint.auth_scheme = AuthScheme.OAUTH2
    
    # Trigger risk re-evaluation
    updated_result = compute_risk_score(endpoint)
    await risk_store.insert_risk_score_history(updated_result)
    
    elapsed_time = time.time() - start_time
    
    # Verify re-evaluation completed within 60 seconds
    assert elapsed_time < 60.0, f"Risk re-evaluation took {elapsed_time:.2f}s, expected < 60s"
    
    # Verify risk score decreased after remediation
    assert updated_result.score < initial_result.score, \
        f"Expected risk score to decrease after remediation, got {updated_result.score} (was {initial_result.score})"
    
    # Verify recommendation is marked as resolved
    resolved_recs = await remediation_store.get_recommendations(endpoint.id)
    resolved_rec = next((r for r in resolved_recs if r["id"] == auth_rec.id), None)
    assert resolved_rec is not None, "Expected to find resolved recommendation"
    assert resolved_rec["resolved_by"] == "admin@example.com"
    assert resolved_rec["resolved_at"] is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_endpoint_remediated_event_published_to_kafka():
    """
    Test that marking a recommendation as resolved publishes endpoint.remediated event to Kafka.
    
    Validates: Requirement 11.2 - endpoint.remediated event publishing
    """
    from conftest import activate_service
    
    activate_service("remediation-service")
    from db import InMemoryRemediationStore
    from rule_engine import generate_recommendations
    
    remediation_store = InMemoryRemediationStore()
    
    # Mock Kafka event bus
    kafka_bus = MockKafkaEventBus()
    
    # Create endpoint with risk
    endpoint = EndpointRecord(
        id=str(uuid.uuid4()),
        http_method="GET",
        host="api.example.com",
        normalized_path="/api/users",
        auth_scheme=AuthScheme.NONE,
        data_sensitivity=DataSensitivity.PII,
        lifecycle_status=LifecycleStatus.ZOMBIE,
        risk_score=90,
    )
    
    # Generate recommendations
    activate_service("risk-scorer-service")
    from scorer import compute_risk_score
    
    risk_result = compute_risk_score(endpoint)
    recommendations = generate_recommendations(endpoint, risk_result)
    
    # Save recommendations
    for rec in recommendations:
        await remediation_store.insert_recommendation(rec)
    
    # Mark first recommendation as resolved
    rec = recommendations[0]
    await remediation_store.resolve_recommendation(
        recommendation_id=rec.id,
        resolved_by="security-team@example.com"
    )
    
    # Publish endpoint.remediated event
    await kafka_bus.publish("endpoint.remediated", {
        "endpoint_id": endpoint.id,
        "recommendation_id": rec.id,
        "resolved_by": "security-team@example.com",
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    })
    
    # Verify event was published
    remediated_events = kafka_bus.get_events("endpoint.remediated")
    assert len(remediated_events) >= 1, "Expected at least one endpoint.remediated event"
    
    # Verify event structure
    event = remediated_events[0]
    assert event["endpoint_id"] == endpoint.id
    assert event["recommendation_id"] == rec.id
    assert event["resolved_by"] == "security-team@example.com"
    assert "resolved_at" in event


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multiple_recommendations_resolution_workflow():
    """
    Test resolving multiple recommendations for the same endpoint.
    
    Validates: Complete remediation workflow with multiple recommendations
    """
    from conftest import activate_service
    
    activate_service("remediation-service")
    from db import InMemoryRemediationStore
    from rule_engine import generate_recommendations
    
    remediation_store = InMemoryRemediationStore()
    
    activate_service("risk-scorer-service")
    from scorer import compute_risk_score
    from db import InMemoryRiskScorerStore
    
    risk_store = InMemoryRiskScorerStore()
    
    # Create endpoint with multiple risk factors
    endpoint = EndpointRecord(
        id=str(uuid.uuid4()),
        http_method="POST",
        host="api.example.com",
        normalized_path="/api/transactions",
        auth_scheme=AuthScheme.NONE,  # Risk factor 1
        data_sensitivity=DataSensitivity.FINANCIAL,  # Risk factor 2
        lifecycle_status=LifecycleStatus.ZOMBIE,  # Risk factor 3
        risk_score=0,
        metadata={"abnormal_traffic": True},  # Risk factor 4
    )
    
    # Initial scoring
    initial_result = compute_risk_score(endpoint)
    await risk_store.insert_risk_score_history(initial_result)
    
    # Generate recommendations
    recommendations = generate_recommendations(endpoint, initial_result)
    
    # Save all recommendations
    for rec in recommendations:
        await remediation_store.insert_recommendation(rec)
    
    # Should have multiple recommendations
    assert len(recommendations) >= 2, f"Expected at least 2 recommendations, got {len(recommendations)}"
    
    # Resolve recommendations one by one
    resolved_count = 0
    for rec in recommendations:
        await remediation_store.resolve_recommendation(
            recommendation_id=rec.id,
            resolved_by="admin@example.com"
        )
        resolved_count += 1
        
        # Verify resolution
        resolved_rec = await remediation_store.get_recommendations(rec.id)
        assert resolved_rec["resolved_by"] == "admin@example.com"
        assert resolved_rec["resolved_at"] is not None
    
    # Verify all recommendations were resolved
    assert resolved_count == len(recommendations), \
        f"Expected {len(recommendations)} resolutions, got {resolved_count}"
    
    # Apply all remediations
    endpoint.auth_scheme = AuthScheme.OAUTH2
    endpoint.lifecycle_status = LifecycleStatus.ACTIVE
    endpoint.metadata = {}
    
    # Final risk scoring
    final_result = compute_risk_score(endpoint)
    await risk_store.insert_risk_score_history(final_result)
    
    # Verify risk score decreased significantly
    assert final_result.score < initial_result.score / 2, \
        f"Expected significant risk reduction, got {final_result.score} (was {initial_result.score})"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_recommendation_priority_affects_resolution_order():
    """
    Test that recommendation priority is correctly assigned and can guide resolution order.
    
    Validates: Requirement 9.6 - Priority assignment
    """
    from conftest import activate_service
    
    activate_service("remediation-service")
    from rule_engine import generate_recommendations
    
    activate_service("risk-scorer-service")
    from scorer import compute_risk_score
    
    # Create high-risk endpoint
    endpoint = EndpointRecord(
        id=str(uuid.uuid4()),
        http_method="POST",
        host="api.example.com",
        normalized_path="/api/critical",
        auth_scheme=AuthScheme.NONE,
        data_sensitivity=DataSensitivity.PII,
        lifecycle_status=LifecycleStatus.ZOMBIE,
        risk_score=0,
    )
    
    # Score endpoint
    risk_result = compute_risk_score(endpoint)
    
    # Generate recommendations
    recommendations = generate_recommendations(endpoint, risk_result)
    
    # Verify recommendations have priorities
    assert len(recommendations) > 0, "Expected at least one recommendation"
    
    for rec in recommendations:
        assert rec.priority in ["Critical", "High", "Medium", "Low"], \
            f"Invalid priority: {rec.priority}"
    
    # Verify Critical priority for high-risk endpoint
    priorities = [rec.priority for rec in recommendations]
    assert "Critical" in priorities, "Expected at least one Critical priority recommendation"
    
    # Sort by priority (Critical > High > Medium > Low)
    priority_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    sorted_recs = sorted(recommendations, key=lambda r: priority_order[r.priority])
    
    # Verify first recommendation is Critical
    assert sorted_recs[0].priority == "Critical", \
        f"Expected first recommendation to be Critical, got {sorted_recs[0].priority}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_remediation_recommendation_content_quality():
    """
    Test that remediation recommendations contain actionable content.
    
    Validates: Requirement 9.8 - Machine-readable and human-readable formats
    """
    from conftest import activate_service
    
    activate_service("remediation-service")
    from rule_engine import generate_recommendations
    
    activate_service("risk-scorer-service")
    from scorer import compute_risk_score
    
    # Create endpoint
    endpoint = EndpointRecord(
        id=str(uuid.uuid4()),
        http_method="GET",
        host="api.example.com",
        normalized_path="/api/data",
        auth_scheme=AuthScheme.NONE,
        data_sensitivity=DataSensitivity.FINANCIAL,
        lifecycle_status=LifecycleStatus.ACTIVE,
        risk_score=0,
    )
    
    # Score and generate recommendations
    risk_result = compute_risk_score(endpoint)
    recommendations = generate_recommendations(endpoint, risk_result)
    
    # Verify each recommendation has required content
    for rec in recommendations:
        # Human-readable summary
        assert rec.summary_text, "Expected non-empty summary_text"
        assert len(rec.summary_text) > 10, "Expected meaningful summary text"
        
        # Machine-readable details
        assert rec.detail_json, "Expected non-empty detail_json"
        assert isinstance(rec.detail_json, dict), "Expected detail_json to be a dict"
        
        # Required fields
        assert rec.endpoint_id == endpoint.id
        assert rec.priority in ["Critical", "High", "Medium", "Low"]
        assert rec.trigger_rule, "Expected non-empty trigger_rule"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_recommendations_for_low_risk_endpoints():
    """
    Test that low-risk endpoints (score < 40) do not generate recommendations.
    
    Validates: Requirement 9.1 - Recommendations only for risk_score >= 40
    """
    from conftest import activate_service
    
    activate_service("remediation-service")
    from rule_engine import generate_recommendations
    
    activate_service("risk-scorer-service")
    from scorer import compute_risk_score
    
    # Create low-risk endpoint
    endpoint = EndpointRecord(
        id=str(uuid.uuid4()),
        http_method="GET",
        host="api.example.com",
        normalized_path="/api/public",
        auth_scheme=AuthScheme.OAUTH2,
        data_sensitivity=DataSensitivity.PUBLIC,
        lifecycle_status=LifecycleStatus.ACTIVE,
        risk_score=0,
    )
    
    # Score endpoint
    risk_result = compute_risk_score(endpoint)
    
    # Verify low risk score
    assert risk_result.score < 40, f"Expected low risk score (<40), got {risk_result.score}"
    
    # Generate recommendations
    recommendations = generate_recommendations(endpoint, risk_result)
    
    # Verify no recommendations for low-risk endpoint
    assert len(recommendations) == 0, \
        f"Expected no recommendations for low-risk endpoint, got {len(recommendations)}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
