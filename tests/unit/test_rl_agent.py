"""
Unit tests for the PPO agent — inference, fallback policy, SHAP explainer,
RL risk adjustment computation, and XGBoost probability heuristics.
"""
import sys
import os
import pytest
import numpy as np

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_RL_DIR = os.path.join(_REPO_ROOT, "services", "rl-intelligence-service")
_SHARED = os.path.join(_REPO_ROOT, "sentinel_shared")

for p in [_SHARED, _RL_DIR]:
    if p in sys.path:
        sys.path.remove(p)
sys.path.insert(0, _SHARED)
sys.path.insert(0, _RL_DIR)

from models import RLAction, STATE_DIM, ACTION_DIM, RLStateVector


def _make_state(**overrides) -> RLStateVector:
    defaults = {
        "auth_scheme_encoded": 0.0,
        "data_sensitivity_encoded": 1.0,
        "lifecycle_status_encoded": 0.0,
        "owner_present": 1.0,
        "spec_presence": 1.0,
        "traffic_recency_normalized": 0.1,
        "traffic_frequency_normalized": 0.5,
        "traffic_trend": 0.0,
        "pagerank_score": 0.01,
        "betweenness_centrality": 0.0,
        "blast_radius_normalized": 0.0,
        "attack_path_length_normalized": 0.5,
        "rule_risk_score_normalized": 0.0,
        "anomaly_sigma_normalized": 0.0,
        "historical_incident_rate": 0.0,
        "analyst_agreement_rate": 0.5,
        "remediation_success_rate": 0.5,
        "false_positive_rate": 0.1,
    }
    defaults.update(overrides)
    return RLStateVector(**defaults)


# ---------------------------------------------------------------------------
# PPO Agent — basic inference
# ---------------------------------------------------------------------------

def test_ppo_agent_predict_returns_dict():
    from ppo_agent import PPOAgent

    agent = PPOAgent()
    state = _make_state()
    result = agent.predict(state)

    assert "action" in result
    assert "action_name" in result
    assert "action_confidence" in result
    assert "action_probabilities" in result
    assert "rl_risk_adjustment" in result


def test_ppo_agent_action_in_valid_range():
    from ppo_agent import PPOAgent

    agent = PPOAgent()
    state = _make_state()
    result = agent.predict(state)

    assert 0 <= result["action"] < ACTION_DIM


def test_ppo_agent_confidence_in_01():
    from ppo_agent import PPOAgent

    agent = PPOAgent()
    state = _make_state()
    result = agent.predict(state)

    assert 0.0 <= result["action_confidence"] <= 1.0


def test_ppo_agent_probabilities_sum_to_one():
    from ppo_agent import PPOAgent

    agent = PPOAgent()
    state = _make_state()
    result = agent.predict(state)
    probs = result["action_probabilities"]

    assert len(probs) == ACTION_DIM
    assert abs(sum(probs) - 1.0) < 0.01


def test_rl_adjustment_in_bounds():
    from ppo_agent import PPOAgent

    agent = PPOAgent()
    for action_id in range(ACTION_DIM):
        state = _make_state()
        adj = agent._compute_rl_adjustment(action_id, state)
        assert -20 <= adj <= 20, f"Adjustment {adj} out of range for action {action_id}"


# ---------------------------------------------------------------------------
# Fallback policy tests (no trained model)
# ---------------------------------------------------------------------------

def test_fallback_predict_high_risk_triggers_alert():
    from ppo_agent import PPOAgent

    agent = PPOAgent()
    # High risk + high anomaly should trigger alert or auto-remediation
    state = _make_state(
        rule_risk_score_normalized=0.8,
        anomaly_sigma_normalized=0.7,
    )
    action, probs, conf = agent._fallback_predict(state)
    assert action in (
        RLAction.TRIGGER_AUTO_REMEDIATION.value,
        RLAction.TRIGGER_ALERT.value,
    )


def test_fallback_predict_zombie_marks_zombie():
    from ppo_agent import PPOAgent

    agent = PPOAgent()
    state = _make_state(lifecycle_status_encoded=0.75)  # Zombie encoding
    action, probs, conf = agent._fallback_predict(state)
    assert action == RLAction.MARK_ZOMBIE.value


def test_fallback_predict_safe_endpoint_ignores():
    from ppo_agent import PPOAgent

    agent = PPOAgent()
    state = _make_state(
        lifecycle_status_encoded=0.0,  # Active
        rule_risk_score_normalized=0.0,
        anomaly_sigma_normalized=0.0,
        spec_presence=1.0,
        owner_present=1.0,
    )
    action, probs, conf = agent._fallback_predict(state)
    assert action == RLAction.IGNORE.value


# ---------------------------------------------------------------------------
# XGBoost probability heuristics
# ---------------------------------------------------------------------------

def test_heuristic_zombie_probability_high_for_zombie():
    from ppo_agent import PPOAgent

    agent = PPOAgent()
    state = _make_state(
        lifecycle_status_encoded=0.75,  # Zombie
        spec_presence=0.0,
        owner_present=0.0,
    )
    result = agent._heuristic_probabilities(state)
    zombie_prob = result[0]
    assert zombie_prob >= 0.7


def test_heuristic_zombie_probability_low_for_active():
    from ppo_agent import PPOAgent

    agent = PPOAgent()
    state = _make_state(
        lifecycle_status_encoded=0.0,  # Active
        spec_presence=1.0,
        owner_present=1.0,
    )
    result = agent._heuristic_probabilities(state)
    zombie_prob = result[0]
    assert zombie_prob < 0.2


def test_heuristic_probabilities_all_in_01():
    from ppo_agent import PPOAgent

    agent = PPOAgent()
    state = _make_state(rule_risk_score_normalized=0.9, anomaly_sigma_normalized=0.8)
    zombie, threat, remediation = agent._heuristic_probabilities(state)
    assert 0.0 <= zombie <= 1.0
    assert 0.0 <= threat <= 1.0
    assert 0.0 <= remediation <= 1.0


def test_predict_probabilities_keys():
    from ppo_agent import PPOAgent

    agent = PPOAgent()
    state = _make_state()
    result = agent.predict_probabilities(state)

    assert "zombie_probability" in result
    assert "threat_probability" in result
    assert "remediation_probability" in result
    for v in result.values():
        assert 0.0 <= v <= 1.0


# ---------------------------------------------------------------------------
# State vector to_numpy
# ---------------------------------------------------------------------------

def test_state_to_numpy_shape_and_dtype():
    state = _make_state()
    arr = state.to_numpy()
    assert arr.shape == (STATE_DIM,)
    assert arr.dtype == np.float32


def test_state_to_numpy_values_match():
    state = _make_state(rule_risk_score_normalized=0.42)
    arr = state.to_numpy()
    # rule_risk_score is at index 12 per STATE_FEATURE_NAMES
    assert arr[12] == pytest.approx(0.42, abs=0.001)
