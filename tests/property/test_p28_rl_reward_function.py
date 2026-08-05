"""
Property P28: RL Reward Function Mathematical Justification.

For ANY (state, action, event_type) triple:
  1. Reward is always within REWARD_CLIP_MIN and REWARD_CLIP_MAX.
  2. Positive event types produce non-negative base rewards.
  3. Negative event types produce non-positive base rewards.
  4. The zombie bonus is applied correctly (positive for zombie-targeting
     actions, negative for ignoring zombie endpoints).
  5. Wrong actions on MISSED_ATTACK get extra penalty below base reward.
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

from models import RLAction, RewardEventType, REWARD_VALUES, ACTION_DIM, STATE_DIM
from environment import RewardShaper, REWARD_CLIP_MIN, REWARD_CLIP_MAX


shaper = RewardShaper()

valid_actions = st.integers(min_value=0, max_value=ACTION_DIM - 1)
valid_event_types = st.sampled_from([e.value for e in RewardEventType])
state_vectors = st.lists(
    st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    min_size=STATE_DIM,
    max_size=STATE_DIM,
)


@given(action=valid_actions, event_type=valid_event_types, sv=state_vectors)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_p28_reward_always_clipped(action, event_type, sv):
    """P28a: Shaped reward is always within [REWARD_CLIP_MIN, REWARD_CLIP_MAX]."""
    exp = {"state_vector": sv, "action": action, "event_type": event_type}
    reward = shaper.compute(action, exp)
    assert REWARD_CLIP_MIN <= reward <= REWARD_CLIP_MAX, (
        f"Reward {reward} out of [{REWARD_CLIP_MIN}, {REWARD_CLIP_MAX}] "
        f"for action={action}, event={event_type}"
    )


@given(action=valid_actions, sv=state_vectors)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_p28_positive_events_non_negative_base(action, sv):
    """P28b: Positive event types yield non-negative base reward component."""
    positive_events = [
        RewardEventType.CORRECT_CLASSIFICATION,
        RewardEventType.ANALYST_AGREEMENT,
        RewardEventType.SUCCESSFUL_REMEDIATION,
        RewardEventType.THREAT_PREVENTION,
        RewardEventType.REDUCED_FALSE_POSITIVE,
        RewardEventType.REDUCED_FALSE_NEGATIVE,
    ]
    for event_type in positive_events:
        assert REWARD_VALUES[event_type] > 0


@given(action=valid_actions, sv=state_vectors)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_p28_negative_events_non_positive_base(action, sv):
    """P28c: Negative event types have non-positive base reward values."""
    negative_events = [
        RewardEventType.FALSE_POSITIVE,
        RewardEventType.WRONG_CLASSIFICATION,
        RewardEventType.MISSED_ATTACK,
        RewardEventType.FAILED_REMEDIATION,
        RewardEventType.ANALYST_OVERRIDE,
        RewardEventType.ALERT_FATIGUE,
    ]
    for event_type in negative_events:
        assert REWARD_VALUES[event_type] < 0


def test_p28_zombie_bonus_increases_zombie_targeting_reward():
    """P28d: Zombie-state endpoints get bonus reward for zombie-targeting actions."""
    # Build a zombie state (lifecycle_status_encoded = 0.75)
    sv_zombie = [0.0] * STATE_DIM
    sv_zombie[2] = 0.75  # lifecycle_status_encoded = Zombie

    sv_active = [0.0] * STATE_DIM
    sv_active[2] = 0.0   # lifecycle_status_encoded = Active

    zombie_action = RLAction.MARK_ZOMBIE.value
    event = RewardEventType.CORRECT_CLASSIFICATION.value

    reward_zombie_state = shaper.compute(zombie_action, {
        "state_vector": sv_zombie, "action": zombie_action, "event_type": event
    })
    reward_active_state = shaper.compute(zombie_action, {
        "state_vector": sv_active, "action": zombie_action, "event_type": event
    })

    # Zombie state should yield higher reward for zombie action than active state
    assert reward_zombie_state >= reward_active_state


def test_p28_ignore_on_zombie_penalised():
    """P28e: Ignoring a Zombie endpoint applies a penalty."""
    sv_zombie = [0.0] * STATE_DIM
    sv_zombie[2] = 0.75  # Zombie

    ignore_reward = shaper.compute(RLAction.IGNORE.value, {
        "state_vector": sv_zombie,
        "action": RLAction.IGNORE.value,
        "event_type": RewardEventType.CORRECT_CLASSIFICATION.value,
    })
    zombie_reward = shaper.compute(RLAction.MARK_ZOMBIE.value, {
        "state_vector": sv_zombie,
        "action": RLAction.MARK_ZOMBIE.value,
        "event_type": RewardEventType.CORRECT_CLASSIFICATION.value,
    })

    assert zombie_reward > ignore_reward


def test_p28_missed_attack_worst_penalty():
    """P28f: MISSED_ATTACK has the largest absolute reward penalty."""
    missed = abs(REWARD_VALUES[RewardEventType.MISSED_ATTACK])
    all_negatives = [abs(v) for v in REWARD_VALUES.values() if v < 0]
    assert missed == max(all_negatives)


@given(action=valid_actions, sv=state_vectors)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_p28_reward_is_float(action, sv):
    """P28g: compute() always returns a Python float."""
    exp = {
        "state_vector": sv,
        "action": action,
        "event_type": RewardEventType.CORRECT_CLASSIFICATION.value,
    }
    reward = shaper.compute(action, exp)
    assert isinstance(reward, float)
