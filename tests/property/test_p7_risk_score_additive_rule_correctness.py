# Feature: sentinel-api, Property 7: Risk Score Additive Rule Correctness
"""
Property 7: Risk Score Additive Rule Correctness

For any endpoint record, the computed Risk_Score SHALL equal the sum of all
applicable rule contributions (no-auth: +40, sensitive-data-with-weak-auth: +30,
Zombie/Orphaned: +20, abnormal-traffic: +10), capped at 100, and the factors
list SHALL contain exactly one entry for each rule that contributed points —
no more, no fewer.

Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6
"""

import sys
import os

from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
SERVICE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "services", "risk-scorer-service"
)
if SERVICE_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(SERVICE_DIR))

from scorer import (
    compute_risk_score,
    RULE_NO_AUTH,
    RULE_SENSITIVE_DATA_WEAK_AUTH,
    RULE_ZOMBIE_ORPHANED,
    RULE_ABNORMAL_TRAFFIC,
    POINTS_NO_AUTH,
    POINTS_SENSITIVE_DATA_WEAK_AUTH,
    POINTS_ZOMBIE_ORPHANED,
    POINTS_ABNORMAL_TRAFFIC,
    MAX_SCORE,
)
from sentinel_shared.models import AuthScheme, DataSensitivity, LifecycleStatus

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

auth_scheme_st = st.sampled_from(list(AuthScheme))
data_sensitivity_st = st.sampled_from(list(DataSensitivity))
lifecycle_status_st = st.sampled_from(list(LifecycleStatus))

endpoint_data_st = st.fixed_dictionaries(
    {
        "id": st.uuids().map(str),
        "auth_scheme": auth_scheme_st,
        "data_sensitivity": data_sensitivity_st,
        "lifecycle_status": lifecycle_status_st,
        "is_traffic_abnormal": st.booleans(),
    }
)


# ---------------------------------------------------------------------------
# Reference implementation (oracle)
# ---------------------------------------------------------------------------


def _expected_score_and_rules(endpoint_data: dict) -> tuple[int, set[str]]:
    """
    Compute the expected score and set of contributing rule names
    using the same logic as scorer.py, expressed independently for
    cross-checking.
    """
    auth = endpoint_data["auth_scheme"]
    sensitivity = endpoint_data["data_sensitivity"]
    lifecycle = endpoint_data["lifecycle_status"]
    is_abnormal = endpoint_data["is_traffic_abnormal"]

    # Normalise to enum values if they are already enums
    if isinstance(auth, AuthScheme):
        auth = auth
    else:
        auth = AuthScheme(auth)

    if isinstance(sensitivity, DataSensitivity):
        sensitivity = sensitivity
    else:
        sensitivity = DataSensitivity(sensitivity)

    if isinstance(lifecycle, LifecycleStatus):
        lifecycle = lifecycle
    else:
        lifecycle = LifecycleStatus(lifecycle)

    total = 0
    rules: set[str] = set()

    # Rule 1: no auth
    if auth == AuthScheme.NONE:
        total += POINTS_NO_AUTH
        rules.add(RULE_NO_AUTH)

    # Rule 2: sensitive data + weak auth
    if sensitivity in {DataSensitivity.PII, DataSensitivity.FINANCIAL} and auth in {
        AuthScheme.NONE,
        AuthScheme.UNKNOWN,
    }:
        total += POINTS_SENSITIVE_DATA_WEAK_AUTH
        rules.add(RULE_SENSITIVE_DATA_WEAK_AUTH)

    # Rule 3: zombie or orphaned
    if lifecycle in {LifecycleStatus.ZOMBIE, LifecycleStatus.ORPHANED}:
        total += POINTS_ZOMBIE_ORPHANED
        rules.add(RULE_ZOMBIE_ORPHANED)

    # Rule 4: abnormal traffic
    if is_abnormal:
        total += POINTS_ABNORMAL_TRAFFIC
        rules.add(RULE_ABNORMAL_TRAFFIC)

    return min(total, MAX_SCORE), rules


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


@given(endpoint_data=endpoint_data_st)
@settings(max_examples=10)
def test_p7_score_equals_sum_of_applicable_rules(endpoint_data: dict):
    """
    **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5**

    The computed score equals the sum of all applicable rule contributions,
    capped at 100.
    """
    result = compute_risk_score(endpoint_data)
    expected_score, _ = _expected_score_and_rules(endpoint_data)

    assert result.score == expected_score, (
        f"Score mismatch for {endpoint_data}: "
        f"expected {expected_score}, got {result.score}"
    )


@given(endpoint_data=endpoint_data_st)
@settings(max_examples=10)
def test_p7_score_in_valid_range(endpoint_data: dict):
    """
    **Validates: Requirements 6.1**

    The computed score is always in [0, 100].
    """
    result = compute_risk_score(endpoint_data)
    assert 0 <= result.score <= 100, (
        f"Score {result.score} is outside [0, 100] for {endpoint_data}"
    )


@given(endpoint_data=endpoint_data_st)
@settings(max_examples=10)
def test_p7_factors_contain_exactly_one_entry_per_contributing_rule(
    endpoint_data: dict,
):
    """
    **Validates: Requirements 6.6**

    The factors list contains exactly one entry for each rule that contributed
    points — no more, no fewer (among the four scoring rules).
    """
    result = compute_risk_score(endpoint_data)
    _, expected_rules = _expected_score_and_rules(endpoint_data)

    # Extract only the four scoring rules from the factors list
    # (default substitution factors are allowed in addition)
    scoring_rule_names = {
        RULE_NO_AUTH,
        RULE_SENSITIVE_DATA_WEAK_AUTH,
        RULE_ZOMBIE_ORPHANED,
        RULE_ABNORMAL_TRAFFIC,
    }
    actual_scoring_rules = [
        f.rule for f in result.factors if f.rule in scoring_rule_names
    ]

    # No duplicates
    assert len(actual_scoring_rules) == len(set(actual_scoring_rules)), (
        f"Duplicate scoring rule entries in factors: {actual_scoring_rules}"
    )

    # Exactly the expected rules are present
    assert set(actual_scoring_rules) == expected_rules, (
        f"Factors mismatch for {endpoint_data}: "
        f"expected rules {expected_rules}, got {set(actual_scoring_rules)}"
    )


@given(endpoint_data=endpoint_data_st)
@settings(max_examples=10)
def test_p7_factor_points_match_rule_definitions(endpoint_data: dict):
    """
    **Validates: Requirements 6.2, 6.3, 6.4, 6.5**

    Each factor's points value matches the rule's defined contribution.
    """
    result = compute_risk_score(endpoint_data)

    expected_points = {
        RULE_NO_AUTH: POINTS_NO_AUTH,
        RULE_SENSITIVE_DATA_WEAK_AUTH: POINTS_SENSITIVE_DATA_WEAK_AUTH,
        RULE_ZOMBIE_ORPHANED: POINTS_ZOMBIE_ORPHANED,
        RULE_ABNORMAL_TRAFFIC: POINTS_ABNORMAL_TRAFFIC,
    }

    for factor in result.factors:
        if factor.rule in expected_points:
            assert factor.points == expected_points[factor.rule], (
                f"Rule '{factor.rule}' should contribute "
                f"{expected_points[factor.rule]} points, got {factor.points}"
            )


@given(endpoint_data=endpoint_data_st)
@settings(max_examples=10)
def test_p7_score_equals_sum_of_factor_points_capped(endpoint_data: dict):
    """
    **Validates: Requirements 6.1**

    The score equals min(sum of all factor points, 100).
    """
    result = compute_risk_score(endpoint_data)
    total_factor_points = sum(f.points for f in result.factors)
    expected_score = min(total_factor_points, MAX_SCORE)

    assert result.score == expected_score, (
        f"Score {result.score} != min(sum_of_factor_points={total_factor_points}, 100)"
    )


@given(endpoint_data=endpoint_data_st)
@settings(max_examples=10)
def test_p7_each_factor_has_non_empty_description(endpoint_data: dict):
    """
    **Validates: Requirements 6.6**

    Each factor in the factors list has a non-empty human-readable description.
    """
    result = compute_risk_score(endpoint_data)

    for factor in result.factors:
        assert factor.description and factor.description.strip(), (
            f"Factor '{factor.rule}' has empty description"
        )

