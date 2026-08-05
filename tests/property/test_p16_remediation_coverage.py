# Feature: sentinel-api, Property 16: Remediation Coverage
"""
Property 16: Remediation Coverage

For any endpoint whose Risk_Score is 40 or above, the Remediation Engine SHALL
generate at least one recommendation, and every recommendation SHALL contain
both a non-empty detail_json object and a non-empty summary_text string.

Validates: Requirements 9.1, 9.8
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

from rule_engine import generate_recommendations
from sentinel_shared.models import AuthScheme, DataSensitivity, LifecycleStatus

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

auth_scheme_st = st.sampled_from(list(AuthScheme))
data_sensitivity_st = st.sampled_from(list(DataSensitivity))
lifecycle_status_st = st.sampled_from(list(LifecycleStatus))

# Endpoint strategy for risk_score >= 40 (at least one rule must fire)
# We ensure at least one trigger condition is true so the engine always
# produces at least one recommendation.
endpoint_above_threshold_st = st.fixed_dictionaries(
    {
        "id": st.uuids().map(str),
        "risk_score": st.integers(min_value=40, max_value=100),
        "auth_scheme": auth_scheme_st,
        "data_sensitivity": data_sensitivity_st,
        "lifecycle_status": lifecycle_status_st,
        "has_traffic_anomaly": st.booleans(),
        "tls_enabled": st.booleans(),
    }
).filter(
    lambda ep: (
        # At least one rule must be triggerable:
        # Rule 1: no auth
        ep["auth_scheme"] == AuthScheme.NONE
        # Rule 2: zombie or orphaned
        or ep["lifecycle_status"] in (LifecycleStatus.ZOMBIE, LifecycleStatus.ORPHANED)
        # Rule 3: traffic anomaly
        or ep["has_traffic_anomaly"]
        # Rule 4: PII/financial + no TLS
        or (
            ep["data_sensitivity"] in (DataSensitivity.PII, DataSensitivity.FINANCIAL)
            and not ep["tls_enabled"]
        )
    )
)

# Endpoint strategy for risk_score < 40
endpoint_below_threshold_st = st.fixed_dictionaries(
    {
        "id": st.uuids().map(str),
        "risk_score": st.integers(min_value=0, max_value=39),
        "auth_scheme": auth_scheme_st,
        "data_sensitivity": data_sensitivity_st,
        "lifecycle_status": lifecycle_status_st,
        "has_traffic_anomaly": st.booleans(),
        "tls_enabled": st.booleans(),
    }
)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


@given(endpoint=endpoint_above_threshold_st)
@settings(max_examples=10)
def test_p16_at_least_one_recommendation_for_score_above_threshold(endpoint: dict):
    """
    **Validates: Requirements 9.1**

    For any endpoint with risk_score >= 40 (and at least one trigger condition),
    generate_recommendations() returns at least one recommendation.
    """
    recs = generate_recommendations(endpoint)
    assert len(recs) >= 1, (
        f"Expected at least one recommendation for endpoint with "
        f"risk_score={endpoint['risk_score']}, got 0. "
        f"auth_scheme={endpoint['auth_scheme']}, "
        f"lifecycle_status={endpoint['lifecycle_status']}, "
        f"has_traffic_anomaly={endpoint['has_traffic_anomaly']}, "
        f"data_sensitivity={endpoint['data_sensitivity']}, "
        f"tls_enabled={endpoint['tls_enabled']}"
    )


@given(endpoint=endpoint_above_threshold_st)
@settings(max_examples=10)
def test_p16_every_recommendation_has_non_empty_summary_text(endpoint: dict):
    """
    **Validates: Requirements 9.8**

    Every recommendation has a non-empty summary_text string.
    """
    recs = generate_recommendations(endpoint)
    for rec in recs:
        assert rec.summary_text and rec.summary_text.strip(), (
            f"Recommendation for rule '{rec.trigger_rule}' has empty summary_text. "
            f"endpoint_id={rec.endpoint_id}"
        )


@given(endpoint=endpoint_above_threshold_st)
@settings(max_examples=10)
def test_p16_every_recommendation_has_non_empty_detail_json(endpoint: dict):
    """
    **Validates: Requirements 9.8**

    Every recommendation has a non-empty detail_json dict.
    """
    recs = generate_recommendations(endpoint)
    for rec in recs:
        assert isinstance(rec.detail_json, dict), (
            f"Recommendation for rule '{rec.trigger_rule}' has non-dict detail_json: "
            f"{type(rec.detail_json)}"
        )
        assert len(rec.detail_json) > 0, (
            f"Recommendation for rule '{rec.trigger_rule}' has empty detail_json. "
            f"endpoint_id={rec.endpoint_id}"
        )


@given(endpoint=endpoint_below_threshold_st)
@settings(max_examples=10)
def test_p16_empty_recommendations_for_score_below_threshold(endpoint: dict):
    """
    **Validates: Requirements 9.1**

    For any endpoint with risk_score < 40, generate_recommendations() returns
    an empty list.
    """
    recs = generate_recommendations(endpoint)
    assert recs == [], (
        f"Expected empty list for endpoint with risk_score={endpoint['risk_score']}, "
        f"got {len(recs)} recommendations"
    )

