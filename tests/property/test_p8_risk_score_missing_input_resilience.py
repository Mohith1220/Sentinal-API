# Feature: sentinel-api, Property 8: Risk Score Missing-Input Resilience
"""
Property 8: Risk Score Missing-Input Resilience

For any endpoint record with one or more missing or null scoring input fields,
the Risk_Scorer SHALL produce a valid Risk_Score in [0, 100] (never an error
or exception), SHALL substitute conservative default values for the missing
fields, and SHALL record each substitution as a named entry in the factors list.

Validates: Requirements 6.8
"""

import sys
import os

from hypothesis import given, settings, assume
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
    RULE_DEFAULT_AUTH_SCHEME,
    RULE_DEFAULT_DATA_SENSITIVITY,
    RULE_DEFAULT_TRAFFIC_STATS,
    RULE_NO_AUTH,
    RULE_SENSITIVE_DATA_WEAK_AUTH,
    RULE_ABNORMAL_TRAFFIC,
    MAX_SCORE,
)
from sentinel_shared.models import AuthScheme, DataSensitivity, LifecycleStatus

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Optional enum values (may be None)
optional_auth_scheme_st = st.one_of(
    st.none(),
    st.sampled_from(list(AuthScheme)),
)
optional_data_sensitivity_st = st.one_of(
    st.none(),
    st.sampled_from(list(DataSensitivity)),
)
optional_lifecycle_status_st = st.one_of(
    st.none(),
    st.sampled_from(list(LifecycleStatus)),
)

# Traffic stats: all None, or all present, or partially present
optional_bool_st = st.one_of(st.none(), st.booleans())
optional_float_st = st.one_of(
    st.none(),
    st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
)

# Endpoint data with potentially missing fields
endpoint_with_missing_st = st.fixed_dictionaries(
    {
        "id": st.uuids().map(str),
        "auth_scheme": optional_auth_scheme_st,
        "data_sensitivity": optional_data_sensitivity_st,
        "lifecycle_status": optional_lifecycle_status_st,
        "is_traffic_abnormal": optional_bool_st,
        "traffic_current": optional_float_st,
        "traffic_mean": optional_float_st,
        "traffic_stddev": optional_float_st,
    }
)

# Endpoint data with at least one None field
endpoint_with_at_least_one_missing_st = endpoint_with_missing_st.filter(
    lambda d: any(
        d.get(k) is None
        for k in [
            "auth_scheme",
            "data_sensitivity",
            "is_traffic_abnormal",
            "traffic_current",
            "traffic_mean",
            "traffic_stddev",
        ]
    )
)

# Endpoint data with auth_scheme explicitly None
endpoint_missing_auth_st = st.fixed_dictionaries(
    {
        "id": st.uuids().map(str),
        "auth_scheme": st.none(),
        "data_sensitivity": st.sampled_from(list(DataSensitivity)),
        "lifecycle_status": st.sampled_from(list(LifecycleStatus)),
        "is_traffic_abnormal": st.booleans(),
    }
)

# Endpoint data with data_sensitivity explicitly None
endpoint_missing_sensitivity_st = st.fixed_dictionaries(
    {
        "id": st.uuids().map(str),
        "auth_scheme": st.sampled_from(list(AuthScheme)),
        "data_sensitivity": st.none(),
        "lifecycle_status": st.sampled_from(list(LifecycleStatus)),
        "is_traffic_abnormal": st.booleans(),
    }
)

# Endpoint data with all traffic stats None
endpoint_missing_traffic_st = st.fixed_dictionaries(
    {
        "id": st.uuids().map(str),
        "auth_scheme": st.sampled_from(list(AuthScheme)),
        "data_sensitivity": st.sampled_from(list(DataSensitivity)),
        "lifecycle_status": st.sampled_from(list(LifecycleStatus)),
        # No traffic fields at all
    }
)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


@given(endpoint_data=endpoint_with_missing_st)
@settings(max_examples=10)
def test_p8_no_exception_on_missing_inputs(endpoint_data: dict):
    """
    **Validates: Requirements 6.8**

    compute_risk_score never raises an exception, even when all scoring
    input fields are None.
    """
    # Should not raise
    result = compute_risk_score(endpoint_data)
    assert result is not None


@given(endpoint_data=endpoint_with_missing_st)
@settings(max_examples=10)
def test_p8_score_always_in_valid_range(endpoint_data: dict):
    """
    **Validates: Requirements 6.8**

    The score is always in [0, 100], even with missing inputs.
    """
    result = compute_risk_score(endpoint_data)
    assert 0 <= result.score <= MAX_SCORE, (
        f"Score {result.score} is outside [0, 100] for {endpoint_data}"
    )


@given(endpoint_data=endpoint_missing_auth_st)
@settings(max_examples=10)
def test_p8_missing_auth_scheme_recorded_in_factors(endpoint_data: dict):
    """
    **Validates: Requirements 6.8**

    When auth_scheme is None, the default substitution is recorded as a
    named factor entry (default_auth_scheme).
    """
    result = compute_risk_score(endpoint_data)

    factor_rules = [f.rule for f in result.factors]
    assert RULE_DEFAULT_AUTH_SCHEME in factor_rules, (
        f"Expected '{RULE_DEFAULT_AUTH_SCHEME}' in factors when auth_scheme is None, "
        f"got: {factor_rules}"
    )


@given(endpoint_data=endpoint_missing_auth_st)
@settings(max_examples=10)
def test_p8_missing_auth_scheme_treated_as_none(endpoint_data: dict):
    """
    **Validates: Requirements 6.8**

    When auth_scheme is None, it is treated as 'none' (conservative default),
    so the no-auth rule fires (+40).
    """
    result = compute_risk_score(endpoint_data)

    factor_rules = [f.rule for f in result.factors]
    assert RULE_NO_AUTH in factor_rules, (
        f"Expected '{RULE_NO_AUTH}' to fire when auth_scheme defaults to 'none', "
        f"got: {factor_rules}"
    )
    # Score must include at least the no-auth contribution
    assert result.score >= 40, (
        f"Score {result.score} should be >= 40 when auth defaults to 'none'"
    )


@given(endpoint_data=endpoint_missing_sensitivity_st)
@settings(max_examples=10)
def test_p8_missing_data_sensitivity_recorded_in_factors(endpoint_data: dict):
    """
    **Validates: Requirements 6.8**

    When data_sensitivity is None, the default substitution is recorded as a
    named factor entry (default_data_sensitivity).
    """
    result = compute_risk_score(endpoint_data)

    factor_rules = [f.rule for f in result.factors]
    assert RULE_DEFAULT_DATA_SENSITIVITY in factor_rules, (
        f"Expected '{RULE_DEFAULT_DATA_SENSITIVITY}' in factors when "
        f"data_sensitivity is None, got: {factor_rules}"
    )


@given(endpoint_data=endpoint_missing_sensitivity_st)
@settings(max_examples=10)
def test_p8_missing_data_sensitivity_treated_as_pii(endpoint_data: dict):
    """
    **Validates: Requirements 6.8**

    When data_sensitivity is None, it is treated as 'PII' (conservative default).
    If auth is also weak (none/unknown), the sensitive-data rule fires.
    """
    result = compute_risk_score(endpoint_data)

    auth = endpoint_data["auth_scheme"]
    if isinstance(auth, AuthScheme):
        auth_val = auth
    else:
        auth_val = AuthScheme(auth)

    factor_rules = [f.rule for f in result.factors]

    if auth_val in {AuthScheme.NONE, AuthScheme.UNKNOWN}:
        # PII + weak auth → sensitive_data_weak_auth rule should fire
        assert RULE_SENSITIVE_DATA_WEAK_AUTH in factor_rules, (
            f"Expected '{RULE_SENSITIVE_DATA_WEAK_AUTH}' to fire when "
            f"data_sensitivity defaults to PII and auth={auth_val}, "
            f"got: {factor_rules}"
        )


@given(endpoint_data=endpoint_missing_traffic_st)
@settings(max_examples=10)
def test_p8_missing_traffic_stats_recorded_in_factors(endpoint_data: dict):
    """
    **Validates: Requirements 6.8**

    When all traffic stats are missing, the default substitution is recorded
    as a named factor entry (default_traffic_stats).
    """
    result = compute_risk_score(endpoint_data)

    factor_rules = [f.rule for f in result.factors]
    assert RULE_DEFAULT_TRAFFIC_STATS in factor_rules, (
        f"Expected '{RULE_DEFAULT_TRAFFIC_STATS}' in factors when traffic stats "
        f"are missing, got: {factor_rules}"
    )


@given(endpoint_data=endpoint_missing_traffic_st)
@settings(max_examples=10)
def test_p8_missing_traffic_stats_treated_as_abnormal(endpoint_data: dict):
    """
    **Validates: Requirements 6.8**

    When all traffic stats are missing, traffic is treated as abnormal
    (conservative default), so the abnormal-traffic rule fires (+10).
    """
    result = compute_risk_score(endpoint_data)

    factor_rules = [f.rule for f in result.factors]
    assert RULE_ABNORMAL_TRAFFIC in factor_rules, (
        f"Expected '{RULE_ABNORMAL_TRAFFIC}' to fire when traffic stats are missing, "
        f"got: {factor_rules}"
    )


@given(endpoint_data=endpoint_with_at_least_one_missing_st)
@settings(max_examples=10)
def test_p8_each_substitution_recorded_as_named_factor(endpoint_data: dict):
    """
    **Validates: Requirements 6.8**

    For each missing field that triggers a substitution, a corresponding
    named factor entry is present in the factors list.
    """
    result = compute_risk_score(endpoint_data)
    factor_rules = [f.rule for f in result.factors]

    # Check auth_scheme substitution
    if endpoint_data.get("auth_scheme") is None:
        assert RULE_DEFAULT_AUTH_SCHEME in factor_rules, (
            f"Missing auth_scheme should produce '{RULE_DEFAULT_AUTH_SCHEME}' factor"
        )

    # Check data_sensitivity substitution
    if endpoint_data.get("data_sensitivity") is None:
        assert RULE_DEFAULT_DATA_SENSITIVITY in factor_rules, (
            f"Missing data_sensitivity should produce "
            f"'{RULE_DEFAULT_DATA_SENSITIVITY}' factor"
        )

    # Check traffic stats substitution (all three must be None for default to apply)
    is_abnormal = endpoint_data.get("is_traffic_abnormal")
    traffic_current = endpoint_data.get("traffic_current")
    traffic_mean = endpoint_data.get("traffic_mean")
    traffic_stddev = endpoint_data.get("traffic_stddev")

    all_traffic_missing = (
        is_abnormal is None
        and traffic_current is None
        and traffic_mean is None
        and traffic_stddev is None
    )
    if all_traffic_missing:
        assert RULE_DEFAULT_TRAFFIC_STATS in factor_rules, (
            f"Missing traffic stats should produce '{RULE_DEFAULT_TRAFFIC_STATS}' factor"
        )


@given(endpoint_data=endpoint_with_missing_st)
@settings(max_examples=10)
def test_p8_result_always_has_valid_structure(endpoint_data: dict):
    """
    **Validates: Requirements 6.8**

    The result always has a valid structure: endpoint_id, score in [0,100],
    non-None factors list, and a computed_at timestamp.
    """
    result = compute_risk_score(endpoint_data)

    assert result.endpoint_id is not None
    assert isinstance(result.score, int)
    assert 0 <= result.score <= MAX_SCORE
    assert isinstance(result.factors, list)
    assert result.computed_at is not None

    # Each factor has required fields
    for factor in result.factors:
        assert factor.rule and factor.rule.strip()
        assert isinstance(factor.points, int)
        assert factor.points >= 0
        assert factor.description and factor.description.strip()

