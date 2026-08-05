"""
Unit tests for the RL Intelligence Service state builder.

Tests normalisation, encoding, and edge cases for all 18 state dimensions.
"""
import math
import sys
import os
import pytest

# Activate the rl-intelligence-service directory
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_RL_DIR = os.path.join(_REPO_ROOT, "services", "rl-intelligence-service")
_SHARED = os.path.join(_REPO_ROOT, "sentinel_shared")

# RL service must be at position 0 so its `models.py` takes precedence
# over sentinel_shared/models.py
for p in [_SHARED, _RL_DIR]:
    if p in sys.path:
        sys.path.remove(p)
sys.path.insert(0, _SHARED)
sys.path.insert(0, _RL_DIR)

from state_builder import build_state_vector, MAX_TRAFFIC_RECENCY_DAYS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def minimal_endpoint(**overrides):
    base = {
        "id": "00000000-0000-0000-0000-000000000001",
        "auth_scheme": "unknown",
        "data_sensitivity": "internal",
        "lifecycle_status": "Active",
        "risk_score": 0,
        "request_count_24h": 0,
        "owning_team": None,
        "source_file_id": None,
        "last_access_at": None,
        "traffic_trend": 0.0,
        "metadata": {},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Test: output is always a valid RLStateVector
# ---------------------------------------------------------------------------

def test_build_state_vector_returns_rlstatevector():
    from models import RLStateVector
    ep = minimal_endpoint()
    sv = build_state_vector(ep)
    assert isinstance(sv, RLStateVector)


def test_all_features_in_range():
    from models import RLStateVector
    ep = minimal_endpoint(
        auth_scheme="none",
        data_sensitivity="PII",
        lifecycle_status="Zombie",
        risk_score=90,
        request_count_24h=5000,
        traffic_trend=0.8,
        owning_team=None,
        source_file_id=None,
    )
    sv = build_state_vector(ep)
    # All except traffic_trend must be in [0, 1]
    assert 0.0 <= sv.auth_scheme_encoded <= 1.0
    assert 0.0 <= sv.data_sensitivity_encoded <= 1.0
    assert 0.0 <= sv.lifecycle_status_encoded <= 1.0
    assert sv.owner_present in (0.0, 1.0)
    assert sv.spec_presence in (0.0, 1.0)
    assert 0.0 <= sv.traffic_recency_normalized <= 1.0
    assert 0.0 <= sv.traffic_frequency_normalized <= 1.0
    assert -1.0 <= sv.traffic_trend <= 1.0
    assert 0.0 <= sv.rule_risk_score_normalized <= 1.0
    assert 0.0 <= sv.anomaly_sigma_normalized <= 1.0
    assert 0.0 <= sv.historical_incident_rate <= 1.0
    assert 0.0 <= sv.analyst_agreement_rate <= 1.0
    assert 0.0 <= sv.remediation_success_rate <= 1.0
    assert 0.0 <= sv.false_positive_rate <= 1.0


# ---------------------------------------------------------------------------
# Test: API metadata encoding
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("auth_scheme,expected", [
    ("none", 0.00),
    ("api_key", 0.25),
    ("JWT", 0.50),
    ("OAuth2", 0.75),
    ("unknown", 1.00),
])
def test_auth_scheme_encoding(auth_scheme, expected):
    ep = minimal_endpoint(auth_scheme=auth_scheme)
    sv = build_state_vector(ep)
    assert sv.auth_scheme_encoded == pytest.approx(expected, abs=0.01)


@pytest.mark.parametrize("lifecycle,expected", [
    ("Active",     0.00),
    ("Deprecated", 0.25),
    ("Orphaned",   0.50),
    ("Zombie",     0.75),
    ("Shadow_API", 1.00),
])
def test_lifecycle_encoding(lifecycle, expected):
    ep = minimal_endpoint(lifecycle_status=lifecycle)
    sv = build_state_vector(ep)
    assert sv.lifecycle_status_encoded == pytest.approx(expected, abs=0.01)


def test_owner_present_true():
    ep = minimal_endpoint(owning_team="platform-team")
    sv = build_state_vector(ep)
    assert sv.owner_present == 1.0


def test_owner_present_false():
    ep = minimal_endpoint(owning_team=None)
    sv = build_state_vector(ep)
    assert sv.owner_present == 0.0


def test_spec_presence_true():
    ep = minimal_endpoint(source_file_id="openapi_v3.yaml")
    sv = build_state_vector(ep)
    assert sv.spec_presence == 1.0


# ---------------------------------------------------------------------------
# Test: Traffic features
# ---------------------------------------------------------------------------

def test_stale_endpoint_max_recency():
    ep = minimal_endpoint(last_access_at=None)
    sv = build_state_vector(ep)
    assert sv.traffic_recency_normalized == pytest.approx(1.0, abs=0.01)


def test_zero_traffic_frequency():
    ep = minimal_endpoint(request_count_24h=0)
    sv = build_state_vector(ep)
    assert sv.traffic_frequency_normalized == 0.0


def test_high_traffic_capped_at_one():
    ep = minimal_endpoint(request_count_24h=10_000_000)
    sv = build_state_vector(ep)
    assert sv.traffic_frequency_normalized <= 1.0


def test_traffic_trend_clamping():
    ep = minimal_endpoint(traffic_trend=999.0)
    sv = build_state_vector(ep)
    assert sv.traffic_trend == pytest.approx(1.0, abs=0.01)

    ep2 = minimal_endpoint(traffic_trend=-999.0)
    sv2 = build_state_vector(ep2)
    assert sv2.traffic_trend == pytest.approx(-1.0, abs=0.01)


# ---------------------------------------------------------------------------
# Test: Risk and anomaly scores
# ---------------------------------------------------------------------------

def test_risk_score_normalization():
    ep = minimal_endpoint(risk_score=50)
    sv = build_state_vector(ep)
    assert sv.rule_risk_score_normalized == pytest.approx(0.5, abs=0.01)


def test_risk_score_100():
    ep = minimal_endpoint(risk_score=100)
    sv = build_state_vector(ep)
    assert sv.rule_risk_score_normalized == pytest.approx(1.0, abs=0.01)


def test_anomaly_sigma_from_history():
    anomaly_history = [
        {"deviation_sigma": 4.5},
        {"deviation_sigma": 2.0},
    ]
    ep = minimal_endpoint(risk_score=30)
    sv = build_state_vector(ep, anomaly_history=anomaly_history)
    # max sigma is 4.5; normalised by 10 → 0.45
    assert sv.anomaly_sigma_normalized == pytest.approx(0.45, abs=0.01)


def test_no_anomaly_history_zero_sigma():
    ep = minimal_endpoint()
    sv = build_state_vector(ep, anomaly_history=[])
    assert sv.anomaly_sigma_normalized == 0.0


# ---------------------------------------------------------------------------
# Test: Graph features
# ---------------------------------------------------------------------------

def test_default_graph_features():
    ep = minimal_endpoint()
    sv = build_state_vector(ep, graph_features=None)
    # Defaults: pagerank=0.01 → 0.01*100 capped at 1.0, betweenness=0, blast=0, attack_path=5/10=0.5
    assert sv.pagerank_score == pytest.approx(1.0, abs=0.01)   # 0.01 * 100 = 1.0 (capped)
    assert sv.betweenness_centrality == 0.0
    assert sv.blast_radius_normalized == 0.0
    assert sv.attack_path_length_normalized == pytest.approx(0.5, abs=0.01)  # 5/10


def test_graph_blast_radius_capped():
    ep = minimal_endpoint()
    sv = build_state_vector(ep, graph_features={"blast_radius": 1000, "pagerank": 0.01,
                                                 "betweenness": 0.0, "attack_path_length": 2})
    assert sv.blast_radius_normalized <= 1.0


# ---------------------------------------------------------------------------
# Test: Historical context features
# ---------------------------------------------------------------------------

def test_feedback_stats_defaults():
    ep = minimal_endpoint()
    sv = build_state_vector(ep, feedback_stats={})
    assert sv.analyst_agreement_rate == pytest.approx(0.5, abs=0.01)
    assert sv.remediation_success_rate == pytest.approx(0.5, abs=0.01)
    assert sv.false_positive_rate == pytest.approx(0.1, abs=0.01)


def test_high_incident_rate_capped():
    ep = minimal_endpoint()
    sv = build_state_vector(ep, feedback_stats={"historical_incident_rate": 1000.0})
    assert sv.historical_incident_rate <= 1.0


# ---------------------------------------------------------------------------
# Test: to_numpy shape and dtype
# ---------------------------------------------------------------------------

def test_to_numpy_shape():
    import numpy as np
    ep = minimal_endpoint()
    sv = build_state_vector(ep)
    arr = sv.to_numpy()
    assert arr.shape == (18,)
    assert arr.dtype == np.float32
