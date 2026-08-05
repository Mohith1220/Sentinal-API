"""
Unit tests for the RL Gymnasium environment and reward shaper.
"""
import sys
import os
import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_RL_DIR = os.path.join(_REPO_ROOT, "services", "rl-intelligence-service")
_SHARED = os.path.join(_REPO_ROOT, "sentinel_shared")

for p in [_SHARED, _RL_DIR]:
    if p in sys.path:
        sys.path.remove(p)
sys.path.insert(0, _SHARED)
sys.path.insert(0, _RL_DIR)

from models import (
    RLAction, RewardEventType, REWARD_VALUES, STATE_DIM, ACTION_DIM
)


# ---------------------------------------------------------------------------
# Test: Environment observation and action spaces
# ---------------------------------------------------------------------------

def test_environment_spaces():
    from environment import SentinelAPIEnvironment
    import numpy as np

    buffer = [
        {
            "endpoint_id": "abc",
            "state_vector": [0.5] * STATE_DIM,
            "action": 0,
            "event_type": RewardEventType.CORRECT_CLASSIFICATION.value,
            "next_state_vector": [0.5] * STATE_DIM,
            "reward_value": 10.0,
        }
    ]
    env = SentinelAPIEnvironment(replay_buffer=buffer)
    obs, info = env.reset()

    assert obs.shape == (STATE_DIM,)
    assert env.observation_space.shape == (STATE_DIM,)
    assert env.action_space.n == ACTION_DIM


def test_environment_step_returns_correct_types():
    from environment import SentinelAPIEnvironment
    import numpy as np

    buffer = [
        {
            "endpoint_id": "abc",
            "state_vector": [0.0] * STATE_DIM,
            "action": RLAction.TRIGGER_ALERT.value,
            "event_type": RewardEventType.THREAT_PREVENTION.value,
            "next_state_vector": [0.0] * STATE_DIM,
            "reward_value": 30.0,
        }
    ]
    env = SentinelAPIEnvironment(replay_buffer=buffer)
    env.reset()
    obs, reward, terminated, truncated, info = env.step(RLAction.TRIGGER_ALERT.value)

    assert isinstance(obs, np.ndarray)
    assert obs.shape == (STATE_DIM,)
    assert isinstance(reward, float)
    assert isinstance(terminated, bool)
    assert isinstance(truncated, bool)
    assert isinstance(info, dict)


def test_environment_empty_buffer():
    from environment import SentinelAPIEnvironment
    import numpy as np

    env = SentinelAPIEnvironment(replay_buffer=[])
    obs, _ = env.reset()
    assert obs.shape == (STATE_DIM,)
    obs2, reward, terminated, truncated, info = env.step(0)
    assert isinstance(reward, float)


def test_environment_truncates_after_max_steps():
    from environment import SentinelAPIEnvironment, MAX_EPISODE_STEPS

    buffer = [{"endpoint_id": "x", "state_vector": [0.0]*STATE_DIM,
               "action": 0, "event_type": "correct_classification",
               "next_state_vector": [0.0]*STATE_DIM, "reward_value": 0.0}]
    env = SentinelAPIEnvironment(replay_buffer=buffer)
    env.reset()

    truncated = False
    for _ in range(MAX_EPISODE_STEPS + 1):
        _, _, _, truncated, _ = env.step(0)
        if truncated:
            break

    assert truncated is True


# ---------------------------------------------------------------------------
# Test: Reward Shaper
# ---------------------------------------------------------------------------

def test_reward_correct_classification_base():
    from environment import RewardShaper

    shaper = RewardShaper()
    exp = {
        "state_vector": [0.0] * STATE_DIM,
        "action": RLAction.MARK_ZOMBIE.value,
        "event_type": RewardEventType.CORRECT_CLASSIFICATION.value,
    }
    reward = shaper.compute(RLAction.MARK_ZOMBIE.value, exp)
    # Base +10, alignment bonus +5 (MARK_ZOMBIE is optimal for CORRECT_CLASSIFICATION)
    assert reward > REWARD_VALUES[RewardEventType.CORRECT_CLASSIFICATION]


def test_reward_missed_attack_penalty():
    from environment import RewardShaper

    shaper = RewardShaper()
    exp = {
        "state_vector": [0.0] * STATE_DIM,
        "action": RLAction.IGNORE.value,
        "event_type": RewardEventType.MISSED_ATTACK.value,
    }
    reward = shaper.compute(RLAction.IGNORE.value, exp)
    # Base -50 plus wrong-action penalty -5 = -55, but clipped to REWARD_CLIP_MIN
    # Either way, reward must be <= base reward for MISSED_ATTACK
    assert reward <= REWARD_VALUES[RewardEventType.MISSED_ATTACK]


def test_reward_zombie_bonus_applied():
    from environment import RewardShaper

    shaper = RewardShaper()
    # State with lifecycle_status_encoded ≈ 0.75 (Zombie)
    state_vector = [0.0] * STATE_DIM
    state_vector[2] = 0.75  # lifecycle_status_encoded

    exp_zombie = {
        "state_vector": state_vector,
        "action": RLAction.MARK_ZOMBIE.value,
        "event_type": RewardEventType.CORRECT_CLASSIFICATION.value,
    }
    exp_ignore = {
        "state_vector": state_vector,
        "action": RLAction.IGNORE.value,
        "event_type": RewardEventType.CORRECT_CLASSIFICATION.value,
    }

    reward_zombie = shaper.compute(RLAction.MARK_ZOMBIE.value, exp_zombie)
    reward_ignore = shaper.compute(RLAction.IGNORE.value, exp_ignore)

    # Marking zombie should yield higher reward than ignoring when state is Zombie
    assert reward_zombie > reward_ignore


def test_reward_clipped_to_bounds():
    from environment import RewardShaper, REWARD_CLIP_MIN, REWARD_CLIP_MAX

    shaper = RewardShaper()
    # Event with the most negative base reward
    exp = {
        "state_vector": [0.0] * STATE_DIM,
        "action": RLAction.IGNORE.value,
        "event_type": RewardEventType.MISSED_ATTACK.value,
    }
    reward = shaper.compute(RLAction.IGNORE.value, exp)
    assert reward >= REWARD_CLIP_MIN
    assert reward <= REWARD_CLIP_MAX


def test_reward_unknown_event_type_zero_base():
    from environment import RewardShaper

    shaper = RewardShaper()
    exp = {
        "state_vector": [0.0] * STATE_DIM,
        "action": 0,
        "event_type": "completely_unknown_event_xyz",
    }
    # Should not raise; base reward is 0
    reward = shaper.compute(0, exp)
    assert isinstance(reward, float)


# ---------------------------------------------------------------------------
# Test: Reward Values correctness
# ---------------------------------------------------------------------------

def test_positive_rewards_positive():
    positive_types = [
        RewardEventType.CORRECT_CLASSIFICATION,
        RewardEventType.ANALYST_AGREEMENT,
        RewardEventType.SUCCESSFUL_REMEDIATION,
        RewardEventType.THREAT_PREVENTION,
        RewardEventType.REDUCED_FALSE_POSITIVE,
        RewardEventType.REDUCED_FALSE_NEGATIVE,
    ]
    for rt in positive_types:
        assert REWARD_VALUES[rt] > 0, f"{rt.value} should have positive reward"


def test_negative_rewards_negative():
    negative_types = [
        RewardEventType.FALSE_POSITIVE,
        RewardEventType.WRONG_CLASSIFICATION,
        RewardEventType.MISSED_ATTACK,
        RewardEventType.FAILED_REMEDIATION,
        RewardEventType.ANALYST_OVERRIDE,
        RewardEventType.ALERT_FATIGUE,
    ]
    for rt in negative_types:
        assert REWARD_VALUES[rt] < 0, f"{rt.value} should have negative reward"


def test_missed_attack_most_penalised():
    assert abs(REWARD_VALUES[RewardEventType.MISSED_ATTACK]) == max(
        abs(v) for v in REWARD_VALUES.values() if v < 0
    )
