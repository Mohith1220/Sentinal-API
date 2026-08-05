"""
Unit tests for the Risk Scorer Service.

Tests cover:
  - score exactly 0 (no rules fire)
  - score exactly 100 (all four rules fire)
  - all four rules firing simultaneously (verify all 4 factors present)
  - each rule in isolation
  - missing-input substitution (conservative defaults)
"""

import sys
import os

import pytest

# ---------------------------------------------------------------------------
# Path setup — add risk-scorer-service to sys.path
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
    RULE_DEFAULT_AUTH_SCHEME,
    RULE_DEFAULT_DATA_SENSITIVITY,
    RULE_DEFAULT_TRAFFIC_STATS,
    POINTS_NO_AUTH,
    POINTS_SENSITIVE_DATA_WEAK_AUTH,
    POINTS_ZOMBIE_ORPHANED,
    POINTS_ABNORMAL_TRAFFIC,
)
from sentinel_shared.models import AuthScheme, DataSensitivity, LifecycleStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _factor_rules(result) -> list[str]:
    """Return the list of rule names from a RiskScoreResult's factors."""
    return [f.rule for f in result.factors]


def _factor_points(result) -> dict[str, int]:
    """Return a mapping of rule -> points from a RiskScoreResult's factors."""
    return {f.rule: f.points for f in result.factors}


# ---------------------------------------------------------------------------
# Test: score exactly 0
# ---------------------------------------------------------------------------


def test_score_zero():
    """
    An endpoint with strong auth, public data, Active status, and normal
    traffic should receive a risk score of 0 with no contributing factors.
    """
    endpoint_data = {
        "id": "ep-zero",
        "auth_scheme": AuthScheme.OAUTH2,
        "data_sensitivity": DataSensitivity.PUBLIC,
        "lifecycle_status": LifecycleStatus.ACTIVE,
        "is_traffic_abnormal": False,
    }
    result = compute_risk_score(endpoint_data)

    assert result.score == 0
    # No scoring rules should have fired
    scoring_rules = {
        RULE_NO_AUTH,
        RULE_SENSITIVE_DATA_WEAK_AUTH,
        RULE_ZOMBIE_ORPHANED,
        RULE_ABNORMAL_TRAFFIC,
    }
    fired_rules = set(_factor_rules(result))
    assert not fired_rules.intersection(scoring_rules), (
        f"Expected no scoring rules to fire, but got: {fired_rules}"
    )


# ---------------------------------------------------------------------------
# Test: score exactly 100
# ---------------------------------------------------------------------------


def test_score_100():
    """
    An endpoint with no auth, PII data, Zombie status, and abnormal traffic
    should receive a risk score of 100 (40+30+20+10=100).
    """
    endpoint_data = {
        "id": "ep-max",
        "auth_scheme": AuthScheme.NONE,
        "data_sensitivity": DataSensitivity.PII,
        "lifecycle_status": LifecycleStatus.ZOMBIE,
        "is_traffic_abnormal": True,
    }
    result = compute_risk_score(endpoint_data)

    assert result.score == 100


# ---------------------------------------------------------------------------
# Test: all four rules firing simultaneously
# ---------------------------------------------------------------------------


def test_all_rules_simultaneously():
    """
    When all four rules fire, the score is 100 and the factors list contains
    exactly one entry for each of the four scoring rules.
    """
    endpoint_data = {
        "id": "ep-all-rules",
        "auth_scheme": AuthScheme.NONE,
        "data_sensitivity": DataSensitivity.PII,
        "lifecycle_status": LifecycleStatus.ZOMBIE,
        "is_traffic_abnormal": True,
    }
    result = compute_risk_score(endpoint_data)

    assert result.score == 100

    rules = _factor_rules(result)
    assert RULE_NO_AUTH in rules, "Expected no_auth rule to fire"
    assert RULE_SENSITIVE_DATA_WEAK_AUTH in rules, (
        "Expected sensitive_data_weak_auth rule to fire"
    )
    assert RULE_ZOMBIE_ORPHANED in rules, "Expected zombie_orphaned rule to fire"
    assert RULE_ABNORMAL_TRAFFIC in rules, "Expected abnormal_traffic rule to fire"

    # Exactly one entry per scoring rule (no duplicates)
    scoring_rules = [
        r for r in rules
        if r in {
            RULE_NO_AUTH,
            RULE_SENSITIVE_DATA_WEAK_AUTH,
            RULE_ZOMBIE_ORPHANED,
            RULE_ABNORMAL_TRAFFIC,
        }
    ]
    assert len(scoring_rules) == 4, (
        f"Expected exactly 4 scoring rule factors, got {len(scoring_rules)}: {scoring_rules}"
    )


# ---------------------------------------------------------------------------
# Test: no-auth rule in isolation
# ---------------------------------------------------------------------------


def test_no_auth_rule_only():
    """
    Only the no-auth rule fires: score = 40, exactly 1 scoring factor.
    """
    endpoint_data = {
        "id": "ep-no-auth",
        "auth_scheme": AuthScheme.NONE,
        "data_sensitivity": DataSensitivity.PUBLIC,   # not sensitive → rule 2 won't fire
        "lifecycle_status": LifecycleStatus.ACTIVE,
        "is_traffic_abnormal": False,
    }
    result = compute_risk_score(endpoint_data)

    assert result.score == POINTS_NO_AUTH  # 40
    rules = _factor_rules(result)
    assert RULE_NO_AUTH in rules
    # Rule 2 must NOT fire (public data)
    assert RULE_SENSITIVE_DATA_WEAK_AUTH not in rules
    assert RULE_ZOMBIE_ORPHANED not in rules
    assert RULE_ABNORMAL_TRAFFIC not in rules


# ---------------------------------------------------------------------------
# Test: sensitive-data + weak-auth rule
# ---------------------------------------------------------------------------


def test_sensitive_data_weak_auth_rule():
    """
    PII data + unknown auth fires rule 2 (+30).
    No-auth rule does NOT fire (auth is 'unknown', not 'none').
    """
    endpoint_data = {
        "id": "ep-sensitive-unknown",
        "auth_scheme": AuthScheme.UNKNOWN,
        "data_sensitivity": DataSensitivity.PII,
        "lifecycle_status": LifecycleStatus.ACTIVE,
        "is_traffic_abnormal": False,
    }
    result = compute_risk_score(endpoint_data)

    assert result.score == POINTS_SENSITIVE_DATA_WEAK_AUTH  # 30
    rules = _factor_rules(result)
    assert RULE_SENSITIVE_DATA_WEAK_AUTH in rules
    assert RULE_NO_AUTH not in rules  # auth is 'unknown', not 'none'


def test_sensitive_data_weak_auth_with_none_auth():
    """
    PII data + no auth fires both rule 1 (+40) and rule 2 (+30) = 70.
    """
    endpoint_data = {
        "id": "ep-pii-no-auth",
        "auth_scheme": AuthScheme.NONE,
        "data_sensitivity": DataSensitivity.PII,
        "lifecycle_status": LifecycleStatus.ACTIVE,
        "is_traffic_abnormal": False,
    }
    result = compute_risk_score(endpoint_data)

    assert result.score == POINTS_NO_AUTH + POINTS_SENSITIVE_DATA_WEAK_AUTH  # 70
    rules = _factor_rules(result)
    assert RULE_NO_AUTH in rules
    assert RULE_SENSITIVE_DATA_WEAK_AUTH in rules


def test_financial_data_weak_auth_rule():
    """
    Financial data + unknown auth fires rule 2 (+30).
    """
    endpoint_data = {
        "id": "ep-financial",
        "auth_scheme": AuthScheme.UNKNOWN,
        "data_sensitivity": DataSensitivity.FINANCIAL,
        "lifecycle_status": LifecycleStatus.ACTIVE,
        "is_traffic_abnormal": False,
    }
    result = compute_risk_score(endpoint_data)

    assert result.score == POINTS_SENSITIVE_DATA_WEAK_AUTH  # 30
    rules = _factor_rules(result)
    assert RULE_SENSITIVE_DATA_WEAK_AUTH in rules


# ---------------------------------------------------------------------------
# Test: zombie/orphaned rule in isolation
# ---------------------------------------------------------------------------


def test_zombie_orphaned_rule_zombie():
    """
    Zombie lifecycle status fires rule 3 (+20).
    """
    endpoint_data = {
        "id": "ep-zombie",
        "auth_scheme": AuthScheme.JWT,
        "data_sensitivity": DataSensitivity.INTERNAL,
        "lifecycle_status": LifecycleStatus.ZOMBIE,
        "is_traffic_abnormal": False,
    }
    result = compute_risk_score(endpoint_data)

    assert result.score == POINTS_ZOMBIE_ORPHANED  # 20
    rules = _factor_rules(result)
    assert RULE_ZOMBIE_ORPHANED in rules
    assert RULE_NO_AUTH not in rules
    assert RULE_SENSITIVE_DATA_WEAK_AUTH not in rules
    assert RULE_ABNORMAL_TRAFFIC not in rules


def test_zombie_orphaned_rule_orphaned():
    """
    Orphaned lifecycle status also fires rule 3 (+20).
    """
    endpoint_data = {
        "id": "ep-orphaned",
        "auth_scheme": AuthScheme.JWT,
        "data_sensitivity": DataSensitivity.INTERNAL,
        "lifecycle_status": LifecycleStatus.ORPHANED,
        "is_traffic_abnormal": False,
    }
    result = compute_risk_score(endpoint_data)

    assert result.score == POINTS_ZOMBIE_ORPHANED  # 20
    rules = _factor_rules(result)
    assert RULE_ZOMBIE_ORPHANED in rules


# ---------------------------------------------------------------------------
# Test: abnormal traffic rule in isolation
# ---------------------------------------------------------------------------


def test_abnormal_traffic_rule():
    """
    Abnormal traffic flag fires rule 4 (+10).
    """
    endpoint_data = {
        "id": "ep-abnormal",
        "auth_scheme": AuthScheme.OAUTH2,
        "data_sensitivity": DataSensitivity.PUBLIC,
        "lifecycle_status": LifecycleStatus.ACTIVE,
        "is_traffic_abnormal": True,
    }
    result = compute_risk_score(endpoint_data)

    assert result.score == POINTS_ABNORMAL_TRAFFIC  # 10
    rules = _factor_rules(result)
    assert RULE_ABNORMAL_TRAFFIC in rules
    assert RULE_NO_AUTH not in rules
    assert RULE_SENSITIVE_DATA_WEAK_AUTH not in rules
    assert RULE_ZOMBIE_ORPHANED not in rules


def test_abnormal_traffic_derived_from_stats():
    """
    When is_traffic_abnormal is not set but traffic stats show current > mean + 3*stddev,
    the abnormal traffic rule fires.
    """
    endpoint_data = {
        "id": "ep-stats-abnormal",
        "auth_scheme": AuthScheme.OAUTH2,
        "data_sensitivity": DataSensitivity.PUBLIC,
        "lifecycle_status": LifecycleStatus.ACTIVE,
        # current = 1000, mean = 100, stddev = 10 → threshold = 130 → abnormal
        "traffic_current": 1000.0,
        "traffic_mean": 100.0,
        "traffic_stddev": 10.0,
    }
    result = compute_risk_score(endpoint_data)

    assert result.score == POINTS_ABNORMAL_TRAFFIC
    assert RULE_ABNORMAL_TRAFFIC in _factor_rules(result)


def test_normal_traffic_derived_from_stats():
    """
    When traffic stats show current <= mean + 3*stddev, the abnormal traffic rule
    does NOT fire.
    """
    endpoint_data = {
        "id": "ep-stats-normal",
        "auth_scheme": AuthScheme.OAUTH2,
        "data_sensitivity": DataSensitivity.PUBLIC,
        "lifecycle_status": LifecycleStatus.ACTIVE,
        # current = 100, mean = 100, stddev = 10 → threshold = 130 → normal
        "traffic_current": 100.0,
        "traffic_mean": 100.0,
        "traffic_stddev": 10.0,
    }
    result = compute_risk_score(endpoint_data)

    assert result.score == 0
    assert RULE_ABNORMAL_TRAFFIC not in _factor_rules(result)


# ---------------------------------------------------------------------------
# Test: missing-input substitution
# ---------------------------------------------------------------------------


def test_missing_auth_scheme():
    """
    None auth_scheme defaults to 'none'; score includes +40 and a
    default_auth_scheme factor is recorded.
    """
    endpoint_data = {
        "id": "ep-no-auth-field",
        "auth_scheme": None,
        "data_sensitivity": DataSensitivity.PUBLIC,
        "lifecycle_status": LifecycleStatus.ACTIVE,
        "is_traffic_abnormal": False,
    }
    result = compute_risk_score(endpoint_data)

    # Defaulted to 'none' → no-auth rule fires (+40)
    assert result.score == POINTS_NO_AUTH
    rules = _factor_rules(result)
    assert RULE_DEFAULT_AUTH_SCHEME in rules, (
        "Expected default_auth_scheme factor to be recorded"
    )
    assert RULE_NO_AUTH in rules


def test_missing_auth_scheme_absent_key():
    """
    Missing auth_scheme key (not present in dict at all) also defaults to 'none'.
    """
    endpoint_data = {
        "id": "ep-no-auth-key",
        # auth_scheme key is absent
        "data_sensitivity": DataSensitivity.PUBLIC,
        "lifecycle_status": LifecycleStatus.ACTIVE,
        "is_traffic_abnormal": False,
    }
    result = compute_risk_score(endpoint_data)

    assert result.score == POINTS_NO_AUTH
    rules = _factor_rules(result)
    assert RULE_DEFAULT_AUTH_SCHEME in rules
    assert RULE_NO_AUTH in rules


def test_missing_data_sensitivity():
    """
    None data_sensitivity defaults to 'PII'; conservative scoring applied.
    With auth_scheme=NONE, both rule 1 (+40) and rule 2 (+30) fire.
    """
    endpoint_data = {
        "id": "ep-no-sensitivity",
        "auth_scheme": AuthScheme.NONE,
        "data_sensitivity": None,
        "lifecycle_status": LifecycleStatus.ACTIVE,
        "is_traffic_abnormal": False,
    }
    result = compute_risk_score(endpoint_data)

    # Defaulted to PII + auth=none → rule 1 (+40) + rule 2 (+30) = 70
    assert result.score == POINTS_NO_AUTH + POINTS_SENSITIVE_DATA_WEAK_AUTH
    rules = _factor_rules(result)
    assert RULE_DEFAULT_DATA_SENSITIVITY in rules, (
        "Expected default_data_sensitivity factor to be recorded"
    )
    assert RULE_SENSITIVE_DATA_WEAK_AUTH in rules


def test_missing_data_sensitivity_with_strong_auth():
    """
    None data_sensitivity defaults to 'PII'; with strong auth, only the
    default substitution factor is recorded (rule 2 does not fire).
    """
    endpoint_data = {
        "id": "ep-no-sensitivity-strong-auth",
        "auth_scheme": AuthScheme.OAUTH2,
        "data_sensitivity": None,
        "lifecycle_status": LifecycleStatus.ACTIVE,
        "is_traffic_abnormal": False,
    }
    result = compute_risk_score(endpoint_data)

    # PII + OAuth2 → rule 2 does NOT fire (auth is not weak)
    assert result.score == 0
    rules = _factor_rules(result)
    assert RULE_DEFAULT_DATA_SENSITIVITY in rules
    assert RULE_SENSITIVE_DATA_WEAK_AUTH not in rules


def test_missing_traffic_stats():
    """
    None traffic stats (all missing) defaults to abnormal; +10 added and
    default_traffic_stats factor is recorded.
    """
    endpoint_data = {
        "id": "ep-no-traffic",
        "auth_scheme": AuthScheme.OAUTH2,
        "data_sensitivity": DataSensitivity.PUBLIC,
        "lifecycle_status": LifecycleStatus.ACTIVE,
        # No traffic fields at all
    }
    result = compute_risk_score(endpoint_data)

    assert result.score == POINTS_ABNORMAL_TRAFFIC  # 10
    rules = _factor_rules(result)
    assert RULE_DEFAULT_TRAFFIC_STATS in rules, (
        "Expected default_traffic_stats factor to be recorded"
    )
    assert RULE_ABNORMAL_TRAFFIC in rules


def test_missing_traffic_stats_explicit_none():
    """
    Explicitly None traffic stats also defaults to abnormal.
    """
    endpoint_data = {
        "id": "ep-explicit-none-traffic",
        "auth_scheme": AuthScheme.OAUTH2,
        "data_sensitivity": DataSensitivity.PUBLIC,
        "lifecycle_status": LifecycleStatus.ACTIVE,
        "is_traffic_abnormal": None,
        "traffic_current": None,
        "traffic_mean": None,
        "traffic_stddev": None,
    }
    result = compute_risk_score(endpoint_data)

    assert result.score == POINTS_ABNORMAL_TRAFFIC
    rules = _factor_rules(result)
    assert RULE_DEFAULT_TRAFFIC_STATS in rules
    assert RULE_ABNORMAL_TRAFFIC in rules


# ---------------------------------------------------------------------------
# Test: score cap at 100
# ---------------------------------------------------------------------------


def test_score_capped_at_100():
    """
    Even if all rules fire (40+30+20+10=100), the score is exactly 100.
    """
    endpoint_data = {
        "id": "ep-cap",
        "auth_scheme": AuthScheme.NONE,
        "data_sensitivity": DataSensitivity.FINANCIAL,
        "lifecycle_status": LifecycleStatus.ORPHANED,
        "is_traffic_abnormal": True,
    }
    result = compute_risk_score(endpoint_data)

    assert result.score == 100
    assert result.score <= 100


# ---------------------------------------------------------------------------
# Test: string values for enum fields
# ---------------------------------------------------------------------------


def test_string_enum_values():
    """
    Endpoint data with string values for enum fields should be handled correctly.
    """
    endpoint_data = {
        "id": "ep-strings",
        "auth_scheme": "none",
        "data_sensitivity": "PII",
        "lifecycle_status": "Zombie",
        "is_traffic_abnormal": True,
    }
    result = compute_risk_score(endpoint_data)

    assert result.score == 100
    rules = _factor_rules(result)
    assert RULE_NO_AUTH in rules
    assert RULE_SENSITIVE_DATA_WEAK_AUTH in rules
    assert RULE_ZOMBIE_ORPHANED in rules
    assert RULE_ABNORMAL_TRAFFIC in rules


# ---------------------------------------------------------------------------
# Test: result structure
# ---------------------------------------------------------------------------


def test_result_has_required_fields():
    """
    RiskScoreResult always has endpoint_id, score, factors, and computed_at.
    """
    endpoint_data = {
        "id": "ep-structure",
        "auth_scheme": AuthScheme.JWT,
        "data_sensitivity": DataSensitivity.INTERNAL,
        "lifecycle_status": LifecycleStatus.ACTIVE,
        "is_traffic_abnormal": False,
    }
    result = compute_risk_score(endpoint_data)

    assert result.endpoint_id == "ep-structure"
    assert isinstance(result.score, int)
    assert 0 <= result.score <= 100
    assert isinstance(result.factors, list)
    assert result.computed_at is not None


def test_each_factor_has_required_fields():
    """
    Each RiskFactor in the factors list has rule, points, and description.
    """
    endpoint_data = {
        "id": "ep-factors",
        "auth_scheme": AuthScheme.NONE,
        "data_sensitivity": DataSensitivity.PII,
        "lifecycle_status": LifecycleStatus.ZOMBIE,
        "is_traffic_abnormal": True,
    }
    result = compute_risk_score(endpoint_data)

    for factor in result.factors:
        assert factor.rule, "factor.rule must be non-empty"
        assert isinstance(factor.points, int)
        assert factor.points >= 0
        assert factor.description, "factor.description must be non-empty"
