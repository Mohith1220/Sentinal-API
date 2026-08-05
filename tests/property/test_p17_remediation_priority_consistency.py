# Feature: sentinel-api, Property 17: Remediation Priority Consistency
"""
Property 17: Remediation Priority Consistency

For any remediation recommendation, the assigned priority level SHALL be
consistent with the endpoint's Risk_Score: recommendations for endpoints with
score >= 70 triggered by no-auth or Zombie/Orphaned rules SHALL be "Critical";
recommendations for scores 40–69 SHALL be "High" or lower; no recommendation
SHALL have a priority level outside {Critical, High, Medium, Low}.

Validates: Requirements 9.6
"""

import sys
import os

from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
SERVICE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "services", "remediation-service"
)
if SERVICE_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(SERVICE_DIR))

from rule_engine import (
    generate_recommendations,
    RULE_NO_AUTH,
    RULE_ZOMBIE_ORPHANED,
    RULE_TRAFFIC_ANOMALY,
    RULE_TLS_MISSING,
)
from sentinel_shared.models import AuthScheme, DataSensitivity, LifecycleStatus

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

VALID_PRIORITIES = {"Critical", "High", "Medium", "Low"}

auth_scheme_st = st.sampled_from(list(AuthScheme))
data_sensitivity_st = st.sampled_from(list(DataSensitivity))
lifecycle_status_st = st.sampled_from(list(LifecycleStatus))

# General endpoint strategy (risk_score >= 40 to get recommendations)
endpoint_st = st.fixed_dictionaries(
    {
        "id": st.uuids().map(str),
        "risk_score": st.integers(min_value=40, max_value=100),
        "auth_scheme": auth_scheme_st,
        "data_sensitivity": data_sensitivity_st,
        "lifecycle_status": lifecycle_status_st,
        "has_traffic_anomaly": st.booleans(),
        "tls_enabled": st.booleans(),
    }
)

# Endpoint strategy for no-auth rule with score >= 70
no_auth_high_score_st = st.fixed_dictionaries(
    {
        "id": st.uuids().map(str),
        "risk_score": st.integers(min_value=70, max_value=100),
        "auth_scheme": st.just(AuthScheme.NONE),
        "data_sensitivity": data_sensitivity_st,
        "lifecycle_status": lifecycle_status_st,
        "has_traffic_anomaly": st.booleans(),
        "tls_enabled": st.booleans(),
    }
)

# Endpoint strategy for no-auth rule with score 40–69
no_auth_low_score_st = st.fixed_dictionaries(
    {
        "id": st.uuids().map(str),
        "risk_score": st.integers(min_value=40, max_value=69),
        "auth_scheme": st.just(AuthScheme.NONE),
        "data_sensitivity": data_sensitivity_st,
        "lifecycle_status": lifecycle_status_st,
        "has_traffic_anomaly": st.booleans(),
        "tls_enabled": st.booleans(),
    }
)

# Endpoint strategy for zombie/orphaned rule with score >= 70
zombie_high_score_st = st.fixed_dictionaries(
    {
        "id": st.uuids().map(str),
        "risk_score": st.integers(min_value=70, max_value=100),
        "auth_scheme": auth_scheme_st,
        "data_sensitivity": data_sensitivity_st,
        "lifecycle_status": st.sampled_from([LifecycleStatus.ZOMBIE, LifecycleStatus.ORPHANED]),
        "has_traffic_anomaly": st.booleans(),
        "tls_enabled": st.booleans(),
    }
)

# Endpoint strategy for zombie/orphaned rule with score 40–69
zombie_low_score_st = st.fixed_dictionaries(
    {
        "id": st.uuids().map(str),
        "risk_score": st.integers(min_value=40, max_value=69),
        "auth_scheme": auth_scheme_st,
        "data_sensitivity": data_sensitivity_st,
        "lifecycle_status": st.sampled_from([LifecycleStatus.ZOMBIE, LifecycleStatus.ORPHANED]),
        "has_traffic_anomaly": st.booleans(),
        "tls_enabled": st.booleans(),
    }
)

# Endpoint strategy for TLS missing rule (PII/financial + no TLS)
tls_missing_st = st.fixed_dictionaries(
    {
        "id": st.uuids().map(str),
        "risk_score": st.integers(min_value=40, max_value=100),
        "auth_scheme": auth_scheme_st,
        "data_sensitivity": st.sampled_from([DataSensitivity.PII, DataSensitivity.FINANCIAL]),
        "lifecycle_status": lifecycle_status_st,
        "has_traffic_anomaly": st.booleans(),
        "tls_enabled": st.just(False),
    }
)

# Endpoint strategy for traffic anomaly rule
traffic_anomaly_st = st.fixed_dictionaries(
    {
        "id": st.uuids().map(str),
        "risk_score": st.integers(min_value=40, max_value=100),
        "auth_scheme": auth_scheme_st,
        "data_sensitivity": data_sensitivity_st,
        "lifecycle_status": lifecycle_status_st,
        "has_traffic_anomaly": st.just(True),
        "tls_enabled": st.booleans(),
    }
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _rec_by_rule(recs, rule: str):
    """Return the first recommendation matching the given trigger_rule."""
    for r in recs:
        if r.trigger_rule == rule:
            return r
    return None


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


@given(endpoint=endpoint_st)
@settings(max_examples=10)
def test_p17_all_priorities_are_valid(endpoint: dict):
    """
    **Validates: Requirements 9.6**

    No recommendation SHALL have a priority level outside
    {Critical, High, Medium, Low}.
    """
    recs = generate_recommendations(endpoint)
    for rec in recs:
        assert rec.priority in VALID_PRIORITIES, (
            f"Recommendation for rule '{rec.trigger_rule}' has invalid priority "
            f"'{rec.priority}'. Valid priorities: {VALID_PRIORITIES}"
        )


@given(endpoint=no_auth_high_score_st)
@settings(max_examples=10)
def test_p17_no_auth_rule_critical_at_score_70_or_above(endpoint: dict):
    """
    **Validates: Requirements 9.6**

    No-auth rule: score >= 70 → priority is Critical.
    """
    recs = generate_recommendations(endpoint)
    rec = _rec_by_rule(recs, RULE_NO_AUTH)

    assert rec is not None, (
        f"Expected no_auth recommendation for endpoint with "
        f"auth_scheme=none, risk_score={endpoint['risk_score']}"
    )
    assert rec.priority == "Critical", (
        f"Expected Critical priority for no_auth rule at score={endpoint['risk_score']}, "
        f"got {rec.priority}"
    )


@given(endpoint=no_auth_low_score_st)
@settings(max_examples=10)
def test_p17_no_auth_rule_high_at_score_40_to_69(endpoint: dict):
    """
    **Validates: Requirements 9.6**

    No-auth rule: score 40–69 → priority is High.
    """
    recs = generate_recommendations(endpoint)
    rec = _rec_by_rule(recs, RULE_NO_AUTH)

    assert rec is not None, (
        f"Expected no_auth recommendation for endpoint with "
        f"auth_scheme=none, risk_score={endpoint['risk_score']}"
    )
    assert rec.priority == "High", (
        f"Expected High priority for no_auth rule at score={endpoint['risk_score']}, "
        f"got {rec.priority}"
    )


@given(endpoint=zombie_high_score_st)
@settings(max_examples=10)
def test_p17_zombie_orphaned_rule_critical_at_score_70_or_above(endpoint: dict):
    """
    **Validates: Requirements 9.6**

    Zombie/Orphaned rule: score >= 70 → priority is Critical.
    """
    recs = generate_recommendations(endpoint)
    rec = _rec_by_rule(recs, RULE_ZOMBIE_ORPHANED)

    assert rec is not None, (
        f"Expected zombie_orphaned recommendation for endpoint with "
        f"lifecycle_status={endpoint['lifecycle_status']}, risk_score={endpoint['risk_score']}"
    )
    assert rec.priority == "Critical", (
        f"Expected Critical priority for zombie_orphaned rule at "
        f"score={endpoint['risk_score']}, got {rec.priority}"
    )


@given(endpoint=zombie_low_score_st)
@settings(max_examples=10)
def test_p17_zombie_orphaned_rule_high_at_score_40_to_69(endpoint: dict):
    """
    **Validates: Requirements 9.6**

    Zombie/Orphaned rule: score 40–69 → priority is High.
    """
    recs = generate_recommendations(endpoint)
    rec = _rec_by_rule(recs, RULE_ZOMBIE_ORPHANED)

    assert rec is not None, (
        f"Expected zombie_orphaned recommendation for endpoint with "
        f"lifecycle_status={endpoint['lifecycle_status']}, risk_score={endpoint['risk_score']}"
    )
    assert rec.priority == "High", (
        f"Expected High priority for zombie_orphaned rule at "
        f"score={endpoint['risk_score']}, got {rec.priority}"
    )


@given(endpoint=tls_missing_st)
@settings(max_examples=10)
def test_p17_tls_missing_rule_always_critical(endpoint: dict):
    """
    **Validates: Requirements 9.6**

    TLS missing rule → always Critical (regardless of score, as long as score >= 40).
    """
    recs = generate_recommendations(endpoint)
    rec = _rec_by_rule(recs, RULE_TLS_MISSING)

    assert rec is not None, (
        f"Expected tls_missing recommendation for endpoint with "
        f"data_sensitivity={endpoint['data_sensitivity']}, tls_enabled=False, "
        f"risk_score={endpoint['risk_score']}"
    )
    assert rec.priority == "Critical", (
        f"Expected Critical priority for tls_missing rule at "
        f"score={endpoint['risk_score']}, got {rec.priority}"
    )


@given(endpoint=traffic_anomaly_st)
@settings(max_examples=10)
def test_p17_traffic_anomaly_rule_always_high(endpoint: dict):
    """
    **Validates: Requirements 9.6**

    Traffic anomaly rule → always High.
    """
    recs = generate_recommendations(endpoint)
    rec = _rec_by_rule(recs, RULE_TRAFFIC_ANOMALY)

    assert rec is not None, (
        f"Expected traffic_anomaly recommendation for endpoint with "
        f"has_traffic_anomaly=True, risk_score={endpoint['risk_score']}"
    )
    assert rec.priority == "High", (
        f"Expected High priority for traffic_anomaly rule at "
        f"score={endpoint['risk_score']}, got {rec.priority}"
    )

