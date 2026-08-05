"""
Property P27: RL State Vector Normalisation Invariant.

For ANY valid endpoint metadata, the 18-dimensional state vector produced by
build_state_vector SHALL have every component in [-1.0, 1.0], with all
non-traffic-trend features in [0.0, 1.0].
"""
import sys
import os

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_RL_DIR = os.path.join(_REPO_ROOT, "services", "rl-intelligence-service")
_SHARED = os.path.join(_REPO_ROOT, "sentinel_shared")

for p in [_SHARED, _RL_DIR]:
    if p in sys.path:
        sys.path.remove(p)
sys.path.insert(0, _SHARED)
sys.path.insert(0, _RL_DIR)

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from state_builder import build_state_vector
from models import RLStateVector


# Strategies for valid endpoint field values
auth_schemes = st.sampled_from(["none", "api_key", "JWT", "OAuth2", "unknown"])
data_sensitivities = st.sampled_from(["public", "internal", "financial", "PII"])
lifecycle_statuses = st.sampled_from(["Active", "Deprecated", "Orphaned", "Zombie", "Shadow_API"])
risk_scores = st.integers(min_value=0, max_value=100)
request_counts = st.integers(min_value=0, max_value=10_000_000)
traffic_trends = st.floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False)
owning_teams = st.one_of(st.none(), st.text(min_size=1, max_size=64))
source_files = st.one_of(st.none(), st.text(min_size=1, max_size=64))

anomaly_sigmas = st.lists(
    st.fixed_dictionaries({"deviation_sigma": st.floats(min_value=0.0, max_value=20.0,
                                                         allow_nan=False, allow_infinity=False)}),
    min_size=0,
    max_size=10,
)

feedback_stats = st.fixed_dictionaries({
    "analyst_agreement_rate":   st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    "remediation_success_rate": st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    "false_positive_rate":      st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    "historical_incident_rate": st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
})

graph_features = st.fixed_dictionaries({
    "pagerank":           st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    "betweenness":        st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    "blast_radius":       st.integers(min_value=0, max_value=200),
    "attack_path_length": st.integers(min_value=0, max_value=20),
})


@given(
    auth=auth_schemes,
    sens=data_sensitivities,
    lifecycle=lifecycle_statuses,
    risk=risk_scores,
    count=request_counts,
    trend=traffic_trends,
    owner=owning_teams,
    source=source_files,
    anomalies=anomaly_sigmas,
    fb=feedback_stats,
    gf=graph_features,
)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_p27_state_vector_all_components_in_range(
    auth, sens, lifecycle, risk, count, trend, owner, source,
    anomalies, fb, gf,
):
    """P27: All state vector components must be in valid normalised range."""
    endpoint = {
        "id": "test-ep-001",
        "auth_scheme": auth,
        "data_sensitivity": sens,
        "lifecycle_status": lifecycle,
        "risk_score": risk,
        "request_count_24h": count,
        "traffic_trend": trend,
        "owning_team": owner,
        "source_file_id": source,
        "last_access_at": None,
        "metadata": {},
    }

    sv = build_state_vector(
        endpoint=endpoint,
        graph_features=gf,
        anomaly_history=anomalies,
        feedback_stats=fb,
    )

    # All fields except traffic_trend must be in [0, 1]
    non_trend_fields = [
        sv.auth_scheme_encoded,
        sv.data_sensitivity_encoded,
        sv.lifecycle_status_encoded,
        sv.owner_present,
        sv.spec_presence,
        sv.traffic_recency_normalized,
        sv.traffic_frequency_normalized,
        sv.pagerank_score,
        sv.betweenness_centrality,
        sv.blast_radius_normalized,
        sv.attack_path_length_normalized,
        sv.rule_risk_score_normalized,
        sv.anomaly_sigma_normalized,
        sv.historical_incident_rate,
        sv.analyst_agreement_rate,
        sv.remediation_success_rate,
        sv.false_positive_rate,
    ]
    for val in non_trend_fields:
        assert 0.0 <= val <= 1.0, f"State component {val} out of [0, 1]"

    # traffic_trend must be in [-1, 1]
    assert -1.0 <= sv.traffic_trend <= 1.0

    # numpy array must have exactly 18 elements
    arr = sv.to_numpy()
    assert arr.shape == (18,)


@given(
    auth=auth_schemes,
    sens=data_sensitivities,
    lifecycle=lifecycle_statuses,
    risk=risk_scores,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_p27_state_vector_deterministic(auth, sens, lifecycle, risk):
    """P27b: For the same inputs, build_state_vector always returns the same result."""
    endpoint = {
        "id": "det-ep",
        "auth_scheme": auth,
        "data_sensitivity": sens,
        "lifecycle_status": lifecycle,
        "risk_score": risk,
        "request_count_24h": 0,
        "traffic_trend": 0.0,
        "owning_team": None,
        "source_file_id": None,
        "last_access_at": None,
        "metadata": {},
    }
    sv1 = build_state_vector(endpoint)
    sv2 = build_state_vector(endpoint)
    assert sv1.to_numpy().tolist() == sv2.to_numpy().tolist()
