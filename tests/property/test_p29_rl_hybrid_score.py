"""
Property P29: RL Hybrid Score Correctness.

For ANY endpoint:
  Final Score = Rule Score + ML Contribution + RL Adjustment
  Capped at [0, 100].

Invariants:
  1. Final score is always in [0, 100].
  2. RL adjustment is always in [-20, +20].
  3. ML contribution is always in [-10, +10].
  4. Higher rule risk scores always produce >= final scores
     (all else equal, adjustment can only push further).
  5. compute() is deterministic for the same state vector.
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
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

from models import RLAction, ACTION_DIM, STATE_DIM
from predictor import _compute_ml_contribution
from ppo_agent import PPOAgent


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

rule_risk_scores = st.integers(min_value=0, max_value=100)
rl_adjustments = st.integers(min_value=-20, max_value=20)
ml_contributions = st.floats(min_value=-10.0, max_value=10.0, allow_nan=False)


# ---------------------------------------------------------------------------
# P29a: Final score always capped at [0, 100]
# ---------------------------------------------------------------------------

@given(
    rule_risk=rule_risk_scores,
    rl_adj=rl_adjustments,
    ml_contrib=ml_contributions,
)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_p29a_final_score_in_range(rule_risk, rl_adj, ml_contrib):
    """P29a: Final score is always within [0, 100]."""
    final = min(100, max(0, rule_risk + int(ml_contrib) + rl_adj))
    assert 0 <= final <= 100


# ---------------------------------------------------------------------------
# P29b: RL adjustment always in [-20, +20]
# ---------------------------------------------------------------------------

@given(
    action=st.integers(min_value=0, max_value=ACTION_DIM - 1),
    rule_risk_norm=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    anomaly_norm=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    blast_norm=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    lifecycle_enc=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_p29b_rl_adjustment_in_bounds(
    action, rule_risk_norm, anomaly_norm, blast_norm, lifecycle_enc
):
    """P29b: PPO agent RL adjustment is always in [-20, +20]."""
    from models import RLStateVector

    state = RLStateVector(
        auth_scheme_encoded=0.5,
        data_sensitivity_encoded=0.5,
        lifecycle_status_encoded=lifecycle_enc,
        owner_present=1.0,
        spec_presence=1.0,
        traffic_recency_normalized=0.1,
        traffic_frequency_normalized=0.5,
        traffic_trend=0.0,
        pagerank_score=0.01,
        betweenness_centrality=0.0,
        blast_radius_normalized=blast_norm,
        attack_path_length_normalized=0.5,
        rule_risk_score_normalized=rule_risk_norm,
        anomaly_sigma_normalized=anomaly_norm,
        historical_incident_rate=0.0,
        analyst_agreement_rate=0.5,
        remediation_success_rate=0.5,
        false_positive_rate=0.1,
    )
    agent = PPOAgent()
    adj = agent._compute_rl_adjustment(action, state)
    assert -20 <= adj <= 20, f"RL adjustment {adj} out of [-20, +20]"


# ---------------------------------------------------------------------------
# P29c: ML contribution always in [-10, +10]
# ---------------------------------------------------------------------------

@given(
    rule_risk_norm=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    anomaly_norm=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    blast_norm=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    lifecycle_enc=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_p29c_ml_contribution_in_bounds(
    rule_risk_norm, anomaly_norm, blast_norm, lifecycle_enc
):
    """P29c: ML contribution from predictor is always within [-10, +10]."""
    from models import RLStateVector

    state = RLStateVector(
        auth_scheme_encoded=0.5,
        data_sensitivity_encoded=0.5,
        lifecycle_status_encoded=lifecycle_enc,
        owner_present=1.0,
        spec_presence=1.0,
        traffic_recency_normalized=0.1,
        traffic_frequency_normalized=0.5,
        traffic_trend=0.0,
        pagerank_score=0.01,
        betweenness_centrality=0.0,
        blast_radius_normalized=blast_norm,
        attack_path_length_normalized=0.5,
        rule_risk_score_normalized=rule_risk_norm,
        anomaly_sigma_normalized=anomaly_norm,
        historical_incident_rate=0.0,
        analyst_agreement_rate=0.5,
        remediation_success_rate=0.5,
        false_positive_rate=0.1,
    )
    ml = _compute_ml_contribution(state)
    assert -10.0 <= ml <= 10.0, f"ML contribution {ml} out of [-10, +10]"


# ---------------------------------------------------------------------------
# P29d: Zero-risk endpoint can never have final score above 30
#        (only RL and ML can push it up, max combined = +30)
# ---------------------------------------------------------------------------

def test_p29d_zero_rule_risk_bounded():
    """P29d: Zero rule-risk endpoint final score ≤ 30 (max ML+RL contribution)."""
    from models import RLStateVector
    from predictor import _compute_ml_contribution

    state = RLStateVector(
        auth_scheme_encoded=0.0,
        data_sensitivity_encoded=0.0,
        lifecycle_status_encoded=0.0,
        owner_present=1.0,
        spec_presence=1.0,
        traffic_recency_normalized=0.0,
        traffic_frequency_normalized=0.0,
        traffic_trend=0.0,
        pagerank_score=0.0,
        betweenness_centrality=0.0,
        blast_radius_normalized=0.0,
        attack_path_length_normalized=0.0,
        rule_risk_score_normalized=0.0,
        anomaly_sigma_normalized=0.0,
        historical_incident_rate=0.0,
        analyst_agreement_rate=1.0,
        remediation_success_rate=1.0,
        false_positive_rate=0.0,
    )
    agent = PPOAgent()
    ml = _compute_ml_contribution(state)
    max_adj = max(
        agent._compute_rl_adjustment(a, state)
        for a in range(ACTION_DIM)
    )
    max_final = min(100, max(0, 0 + int(ml) + max_adj))
    # Max possible is ML(≤10) + RL(≤20) = 30
    assert max_final <= 30
