"""
Unit tests for the Remediation Service.

Tests cover:
  - Each trigger rule produces correct recommendation template (4 tests)
  - Priority boundary: score=69 → High for no-auth rule
  - Priority boundary: score=70 → Critical for no-auth rule
  - Priority boundary: score=69 → High for zombie/orphaned rule
  - Priority boundary: score=70 → Critical for zombie/orphaned rule
  - Empty recommendation list when risk_score < 40 (score=39)
  - Empty recommendation list when risk_score == 0
  - All four rules fire simultaneously when all conditions met
  - Rate limit threshold derived from p95_hourly_rate
  - Rate limit threshold uses conservative default when p95_hourly_rate missing
  - TLS rule cites correct regulatory standard
  - Resolution tracking: resolve_recommendation sets resolved_by and resolved_at
"""

import sys
import os
import asyncio

import pytest

# ---------------------------------------------------------------------------
# Path setup — activate remediation-service (evicts conflicting cached modules)
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, _REPO_ROOT)
from conftest import activate_service
activate_service("remediation-service")

from rule_engine import (
    generate_recommendations,
    RULE_NO_AUTH,
    RULE_ZOMBIE_ORPHANED,
    RULE_TRAFFIC_ANOMALY,
    RULE_TLS_MISSING,
    DEFAULT_RATE_LIMIT_RPM,
)
from db import InMemoryRemediationStore
from sentinel_shared.models import AuthScheme, DataSensitivity, LifecycleStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rules(recs) -> list[str]:
    """Return the list of trigger_rule values from a list of recommendations."""
    return [r.trigger_rule for r in recs]


def _rec_by_rule(recs, rule: str):
    """Return the first recommendation matching the given trigger_rule."""
    for r in recs:
        if r.trigger_rule == rule:
            return r
    return None


# ---------------------------------------------------------------------------
# Rule 1: No Auth → Add Authentication
# ---------------------------------------------------------------------------


def test_no_auth_rule_produces_recommendation():
    """
    When auth_scheme == 'none' and risk_score >= 40, the no_auth rule fires
    and produces a recommendation with non-empty summary_text and detail_json.
    """
    endpoint_data = {
        "id": "ep-no-auth",
        "risk_score": 50,
        "auth_scheme": AuthScheme.NONE,
        "data_sensitivity": DataSensitivity.INTERNAL,
        "lifecycle_status": LifecycleStatus.ACTIVE,
        "has_traffic_anomaly": False,
        "tls_enabled": True,
    }
    recs = generate_recommendations(endpoint_data)

    assert RULE_NO_AUTH in _rules(recs), "Expected no_auth rule to fire"
    rec = _rec_by_rule(recs, RULE_NO_AUTH)
    assert rec is not None
    assert rec.summary_text and rec.summary_text.strip()
    assert rec.detail_json and isinstance(rec.detail_json, dict)
    assert len(rec.detail_json) > 0
    assert rec.endpoint_id == "ep-no-auth"


def test_no_auth_rule_recommends_auth_mechanism():
    """
    The no_auth recommendation specifies a concrete authentication mechanism
    appropriate to the endpoint's data sensitivity.
    """
    endpoint_data = {
        "id": "ep-pii-no-auth",
        "risk_score": 70,
        "auth_scheme": AuthScheme.NONE,
        "data_sensitivity": DataSensitivity.PII,
        "lifecycle_status": LifecycleStatus.ACTIVE,
        "has_traffic_anomaly": False,
        "tls_enabled": True,
    }
    recs = generate_recommendations(endpoint_data)
    rec = _rec_by_rule(recs, RULE_NO_AUTH)

    assert rec is not None
    # PII data → OAuth2 recommended
    assert "OAuth2" in rec.detail_json.get("recommended_mechanism", "")


# ---------------------------------------------------------------------------
# Rule 2: Zombie/Orphaned → Disable at Gateway
# ---------------------------------------------------------------------------


def test_zombie_rule_produces_recommendation():
    """
    When lifecycle_status == 'Zombie' and risk_score >= 40, the zombie_orphaned
    rule fires and produces a recommendation with non-empty summary_text and detail_json.
    """
    endpoint_data = {
        "id": "ep-zombie",
        "risk_score": 60,
        "auth_scheme": AuthScheme.JWT,
        "data_sensitivity": DataSensitivity.INTERNAL,
        "lifecycle_status": LifecycleStatus.ZOMBIE,
        "has_traffic_anomaly": False,
        "tls_enabled": True,
    }
    recs = generate_recommendations(endpoint_data)

    assert RULE_ZOMBIE_ORPHANED in _rules(recs), "Expected zombie_orphaned rule to fire"
    rec = _rec_by_rule(recs, RULE_ZOMBIE_ORPHANED)
    assert rec is not None
    assert rec.summary_text and rec.summary_text.strip()
    assert rec.detail_json and isinstance(rec.detail_json, dict)
    assert len(rec.detail_json) > 0
    assert rec.endpoint_id == "ep-zombie"


def test_orphaned_rule_produces_recommendation():
    """
    When lifecycle_status == 'Orphaned' and risk_score >= 40, the zombie_orphaned
    rule fires.
    """
    endpoint_data = {
        "id": "ep-orphaned",
        "risk_score": 50,
        "auth_scheme": AuthScheme.JWT,
        "data_sensitivity": DataSensitivity.INTERNAL,
        "lifecycle_status": LifecycleStatus.ORPHANED,
        "has_traffic_anomaly": False,
        "tls_enabled": True,
    }
    recs = generate_recommendations(endpoint_data)

    assert RULE_ZOMBIE_ORPHANED in _rules(recs)


# ---------------------------------------------------------------------------
# Rule 3: Traffic Anomaly → Rate Limit
# ---------------------------------------------------------------------------


def test_traffic_anomaly_rule_produces_recommendation():
    """
    When has_traffic_anomaly == True and risk_score >= 40, the traffic_anomaly
    rule fires and produces a recommendation with non-empty summary_text and detail_json.
    """
    endpoint_data = {
        "id": "ep-anomaly",
        "risk_score": 50,
        "auth_scheme": AuthScheme.JWT,
        "data_sensitivity": DataSensitivity.INTERNAL,
        "lifecycle_status": LifecycleStatus.ACTIVE,
        "has_traffic_anomaly": True,
        "tls_enabled": True,
        "p95_hourly_rate": 3600.0,
    }
    recs = generate_recommendations(endpoint_data)

    assert RULE_TRAFFIC_ANOMALY in _rules(recs), "Expected traffic_anomaly rule to fire"
    rec = _rec_by_rule(recs, RULE_TRAFFIC_ANOMALY)
    assert rec is not None
    assert rec.summary_text and rec.summary_text.strip()
    assert rec.detail_json and isinstance(rec.detail_json, dict)
    assert len(rec.detail_json) > 0
    assert rec.endpoint_id == "ep-anomaly"


# ---------------------------------------------------------------------------
# Rule 4: PII/Financial + No TLS → Enforce TLS
# ---------------------------------------------------------------------------


def test_tls_missing_rule_produces_recommendation():
    """
    When data_sensitivity is PII and tls_enabled == False and risk_score >= 40,
    the tls_missing rule fires and produces a recommendation with non-empty
    summary_text and detail_json.
    """
    endpoint_data = {
        "id": "ep-no-tls",
        "risk_score": 50,
        "auth_scheme": AuthScheme.JWT,
        "data_sensitivity": DataSensitivity.PII,
        "lifecycle_status": LifecycleStatus.ACTIVE,
        "has_traffic_anomaly": False,
        "tls_enabled": False,
    }
    recs = generate_recommendations(endpoint_data)

    assert RULE_TLS_MISSING in _rules(recs), "Expected tls_missing rule to fire"
    rec = _rec_by_rule(recs, RULE_TLS_MISSING)
    assert rec is not None
    assert rec.summary_text and rec.summary_text.strip()
    assert rec.detail_json and isinstance(rec.detail_json, dict)
    assert len(rec.detail_json) > 0
    assert rec.endpoint_id == "ep-no-tls"


def test_tls_missing_rule_fires_when_tls_enabled_missing():
    """
    When tls_enabled is missing (None) and data is PII, the tls_missing rule fires.
    """
    endpoint_data = {
        "id": "ep-no-tls-missing",
        "risk_score": 50,
        "auth_scheme": AuthScheme.JWT,
        "data_sensitivity": DataSensitivity.PII,
        "lifecycle_status": LifecycleStatus.ACTIVE,
        "has_traffic_anomaly": False,
        # tls_enabled not set
    }
    recs = generate_recommendations(endpoint_data)

    assert RULE_TLS_MISSING in _rules(recs)


# ---------------------------------------------------------------------------
# Priority boundary tests: no-auth rule
# ---------------------------------------------------------------------------


def test_no_auth_priority_high_at_score_69():
    """
    score=69 → no_auth rule priority is High (below Critical threshold of 70).
    """
    endpoint_data = {
        "id": "ep-boundary-69",
        "risk_score": 69,
        "auth_scheme": AuthScheme.NONE,
        "data_sensitivity": DataSensitivity.PUBLIC,
        "lifecycle_status": LifecycleStatus.ACTIVE,
        "has_traffic_anomaly": False,
        "tls_enabled": True,
    }
    recs = generate_recommendations(endpoint_data)
    rec = _rec_by_rule(recs, RULE_NO_AUTH)

    assert rec is not None
    assert rec.priority == "High", (
        f"Expected High priority at score=69, got {rec.priority}"
    )


def test_no_auth_priority_critical_at_score_70():
    """
    score=70 → no_auth rule priority is Critical (at or above Critical threshold).
    """
    endpoint_data = {
        "id": "ep-boundary-70",
        "risk_score": 70,
        "auth_scheme": AuthScheme.NONE,
        "data_sensitivity": DataSensitivity.PUBLIC,
        "lifecycle_status": LifecycleStatus.ACTIVE,
        "has_traffic_anomaly": False,
        "tls_enabled": True,
    }
    recs = generate_recommendations(endpoint_data)
    rec = _rec_by_rule(recs, RULE_NO_AUTH)

    assert rec is not None
    assert rec.priority == "Critical", (
        f"Expected Critical priority at score=70, got {rec.priority}"
    )


# ---------------------------------------------------------------------------
# Priority boundary tests: zombie/orphaned rule
# ---------------------------------------------------------------------------


def test_zombie_orphaned_priority_high_at_score_69():
    """
    score=69 → zombie_orphaned rule priority is High.
    """
    endpoint_data = {
        "id": "ep-zombie-69",
        "risk_score": 69,
        "auth_scheme": AuthScheme.JWT,
        "data_sensitivity": DataSensitivity.INTERNAL,
        "lifecycle_status": LifecycleStatus.ZOMBIE,
        "has_traffic_anomaly": False,
        "tls_enabled": True,
    }
    recs = generate_recommendations(endpoint_data)
    rec = _rec_by_rule(recs, RULE_ZOMBIE_ORPHANED)

    assert rec is not None
    assert rec.priority == "High", (
        f"Expected High priority at score=69, got {rec.priority}"
    )


def test_zombie_orphaned_priority_critical_at_score_70():
    """
    score=70 → zombie_orphaned rule priority is Critical.
    """
    endpoint_data = {
        "id": "ep-zombie-70",
        "risk_score": 70,
        "auth_scheme": AuthScheme.JWT,
        "data_sensitivity": DataSensitivity.INTERNAL,
        "lifecycle_status": LifecycleStatus.ZOMBIE,
        "has_traffic_anomaly": False,
        "tls_enabled": True,
    }
    recs = generate_recommendations(endpoint_data)
    rec = _rec_by_rule(recs, RULE_ZOMBIE_ORPHANED)

    assert rec is not None
    assert rec.priority == "Critical", (
        f"Expected Critical priority at score=70, got {rec.priority}"
    )


# ---------------------------------------------------------------------------
# Empty recommendation list when risk_score < 40
# ---------------------------------------------------------------------------


def test_empty_recommendations_at_score_39():
    """
    risk_score=39 → no recommendations generated (below threshold of 40).
    """
    endpoint_data = {
        "id": "ep-below-threshold",
        "risk_score": 39,
        "auth_scheme": AuthScheme.NONE,
        "data_sensitivity": DataSensitivity.PII,
        "lifecycle_status": LifecycleStatus.ZOMBIE,
        "has_traffic_anomaly": True,
        "tls_enabled": False,
    }
    recs = generate_recommendations(endpoint_data)

    assert recs == [], (
        f"Expected empty list at score=39, got {len(recs)} recommendations"
    )


def test_empty_recommendations_at_score_0():
    """
    risk_score=0 → no recommendations generated.
    """
    endpoint_data = {
        "id": "ep-zero-score",
        "risk_score": 0,
        "auth_scheme": AuthScheme.NONE,
        "data_sensitivity": DataSensitivity.PII,
        "lifecycle_status": LifecycleStatus.ZOMBIE,
        "has_traffic_anomaly": True,
        "tls_enabled": False,
    }
    recs = generate_recommendations(endpoint_data)

    assert recs == [], (
        f"Expected empty list at score=0, got {len(recs)} recommendations"
    )


# ---------------------------------------------------------------------------
# All four rules fire simultaneously
# ---------------------------------------------------------------------------


def test_all_four_rules_fire_simultaneously():
    """
    When all conditions are met, all four rules fire and produce recommendations.
    """
    endpoint_data = {
        "id": "ep-all-rules",
        "risk_score": 80,
        "auth_scheme": AuthScheme.NONE,
        "data_sensitivity": DataSensitivity.PII,
        "lifecycle_status": LifecycleStatus.ZOMBIE,
        "has_traffic_anomaly": True,
        "tls_enabled": False,
    }
    recs = generate_recommendations(endpoint_data)

    rules = _rules(recs)
    assert RULE_NO_AUTH in rules, "Expected no_auth rule to fire"
    assert RULE_ZOMBIE_ORPHANED in rules, "Expected zombie_orphaned rule to fire"
    assert RULE_TRAFFIC_ANOMALY in rules, "Expected traffic_anomaly rule to fire"
    assert RULE_TLS_MISSING in rules, "Expected tls_missing rule to fire"
    assert len(recs) == 4, f"Expected 4 recommendations, got {len(recs)}"


# ---------------------------------------------------------------------------
# Rate limit threshold
# ---------------------------------------------------------------------------


def test_rate_limit_threshold_derived_from_p95_hourly_rate():
    """
    When p95_hourly_rate is provided, the rate limit threshold is derived as
    requests_per_minute = p95_hourly_rate / 60.
    """
    p95_hourly_rate = 3600.0  # 3600 requests/hour → 60 rpm
    endpoint_data = {
        "id": "ep-rate-limit",
        "risk_score": 50,
        "auth_scheme": AuthScheme.JWT,
        "data_sensitivity": DataSensitivity.INTERNAL,
        "lifecycle_status": LifecycleStatus.ACTIVE,
        "has_traffic_anomaly": True,
        "tls_enabled": True,
        "p95_hourly_rate": p95_hourly_rate,
    }
    recs = generate_recommendations(endpoint_data)
    rec = _rec_by_rule(recs, RULE_TRAFFIC_ANOMALY)

    assert rec is not None
    expected_rpm = int(p95_hourly_rate / 60)  # 60
    actual_rpm = rec.detail_json.get("recommended_rate_limit_rpm")
    assert actual_rpm == expected_rpm, (
        f"Expected rate limit {expected_rpm} rpm, got {actual_rpm}"
    )


def test_rate_limit_threshold_uses_default_when_p95_missing():
    """
    When p95_hourly_rate is missing, the rate limit uses the conservative
    default of 60 rpm.
    """
    endpoint_data = {
        "id": "ep-rate-limit-default",
        "risk_score": 50,
        "auth_scheme": AuthScheme.JWT,
        "data_sensitivity": DataSensitivity.INTERNAL,
        "lifecycle_status": LifecycleStatus.ACTIVE,
        "has_traffic_anomaly": True,
        "tls_enabled": True,
        # p95_hourly_rate not set
    }
    recs = generate_recommendations(endpoint_data)
    rec = _rec_by_rule(recs, RULE_TRAFFIC_ANOMALY)

    assert rec is not None
    actual_rpm = rec.detail_json.get("recommended_rate_limit_rpm")
    assert actual_rpm == DEFAULT_RATE_LIMIT_RPM, (
        f"Expected default rate limit {DEFAULT_RATE_LIMIT_RPM} rpm, got {actual_rpm}"
    )


# ---------------------------------------------------------------------------
# TLS rule cites correct regulatory standard
# ---------------------------------------------------------------------------


def test_tls_rule_cites_pci_dss():
    """
    When regulatory_standard is 'PCI-DSS', the TLS recommendation cites PCI-DSS.
    """
    endpoint_data = {
        "id": "ep-pci",
        "risk_score": 50,
        "auth_scheme": AuthScheme.JWT,
        "data_sensitivity": DataSensitivity.FINANCIAL,
        "lifecycle_status": LifecycleStatus.ACTIVE,
        "has_traffic_anomaly": False,
        "tls_enabled": False,
        "regulatory_standard": "PCI-DSS",
    }
    recs = generate_recommendations(endpoint_data)
    rec = _rec_by_rule(recs, RULE_TLS_MISSING)

    assert rec is not None
    assert "PCI-DSS" in rec.summary_text
    assert rec.detail_json.get("regulatory_standard") == "PCI-DSS"


def test_tls_rule_cites_gdpr():
    """
    When regulatory_standard is 'GDPR', the TLS recommendation cites GDPR.
    """
    endpoint_data = {
        "id": "ep-gdpr",
        "risk_score": 50,
        "auth_scheme": AuthScheme.JWT,
        "data_sensitivity": DataSensitivity.PII,
        "lifecycle_status": LifecycleStatus.ACTIVE,
        "has_traffic_anomaly": False,
        "tls_enabled": False,
        "regulatory_standard": "GDPR",
    }
    recs = generate_recommendations(endpoint_data)
    rec = _rec_by_rule(recs, RULE_TLS_MISSING)

    assert rec is not None
    assert "GDPR" in rec.summary_text
    assert rec.detail_json.get("regulatory_standard") == "GDPR"


# ---------------------------------------------------------------------------
# Resolution tracking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_recommendation_sets_resolved_by_and_resolved_at():
    """
    resolve_recommendation sets resolved_by and resolved_at on the record.
    """
    store = InMemoryRemediationStore()
    store.seed_endpoint(
        "ep-resolve",
        risk_score=50,
        auth_scheme="none",
        data_sensitivity="internal",
        lifecycle_status="Active",
        has_traffic_anomaly=False,
        tls_enabled=True,
    )

    # Generate and insert a recommendation
    endpoint_data = await store.get_endpoint("ep-resolve")
    recs = generate_recommendations(endpoint_data)
    assert len(recs) > 0, "Expected at least one recommendation"

    rec = recs[0]
    rec_id = await store.insert_recommendation(rec)

    # Resolve it
    updated = await store.resolve_recommendation(rec_id, resolved_by="alice@example.com")

    assert updated is not None
    assert updated["resolved_by"] == "alice@example.com"
    assert updated["resolved_at"] is not None
    assert updated["id"] == rec_id


@pytest.mark.asyncio
async def test_resolve_recommendation_returns_none_for_unknown_id():
    """
    resolve_recommendation returns None when the recommendation ID is not found.
    """
    store = InMemoryRemediationStore()
    result = await store.resolve_recommendation("nonexistent-id", resolved_by="bob")
    assert result is None


@pytest.mark.asyncio
async def test_get_recommendations_returns_inserted_records():
    """
    get_recommendations returns all recommendations for an endpoint.
    """
    store = InMemoryRemediationStore()
    store.seed_endpoint(
        "ep-list",
        risk_score=80,
        auth_scheme="none",
        data_sensitivity="PII",
        lifecycle_status="Zombie",
        has_traffic_anomaly=True,
        tls_enabled=False,
    )

    endpoint_data = await store.get_endpoint("ep-list")
    recs = generate_recommendations(endpoint_data)
    assert len(recs) == 4, f"Expected 4 recommendations, got {len(recs)}"

    for rec in recs:
        await store.insert_recommendation(rec)

    stored = await store.get_recommendations("ep-list")
    assert len(stored) == 4
    stored_rules = {r["trigger_rule"] for r in stored}
    assert RULE_NO_AUTH in stored_rules
    assert RULE_ZOMBIE_ORPHANED in stored_rules
    assert RULE_TRAFFIC_ANOMALY in stored_rules
    assert RULE_TLS_MISSING in stored_rules
