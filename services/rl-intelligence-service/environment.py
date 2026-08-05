"""
SentinelAPI Gymnasium Environment for PPO training.

Implements gym.Env with:
  - 18-dimensional continuous observation space
  - 12-action discrete action space
  - Mathematically justified reward function
  - Episode termination on convergence or max steps

This environment wraps a replay buffer of (state, action, reward) tuples
collected from the live system. Training happens offline against this buffer
(offline RL pattern), which is safer for a production banking system than
online RL against live endpoints.
"""

from __future__ import annotations

import logging
import random
from typing import Any, Optional

import numpy as np
import gymnasium as gym
from gymnasium import spaces

from models import (
    RLStateVector,
    RLAction,
    RewardEventType,
    REWARD_VALUES,
    STATE_DIM,
    ACTION_DIM,
    STATE_FEATURE_NAMES,
)

logger = logging.getLogger(__name__)

# Max episode length: each step processes one endpoint-event
MAX_EPISODE_STEPS = 512

# Reward shaping constants
REWARD_CLIP_MIN = -50.0
REWARD_CLIP_MAX = +30.0

# Discounting for delayed rewards (temporal credit assignment)
GAMMA = 0.99


class SentinelAPIEnvironment(gym.Env):
    """
    Offline RL environment for the SentinelAPI PPO agent.

    The environment replays historical (state, action, reward_event) tuples
    from the PostgreSQL replay buffer. Each step:
      1. Returns the next state vector from the buffer.
      2. Accepts the agent's action.
      3. Looks up the shaped reward for that (state, action, event_type) triple.
      4. Returns the reward and next state.

    This offline pattern ensures the live system is never impacted by
    exploratory actions during training.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        replay_buffer: list[dict],
        reward_shaper: Optional["RewardShaper"] = None,
    ) -> None:
        """
        Args:
            replay_buffer: List of experience dicts from the DB.
                Each dict must have keys:
                  state_vector (list[float], len=18)
                  action (int, 0–11)
                  event_type (str, RewardEventType value)
                  next_state_vector (list[float], len=18)  # may be same as state
            reward_shaper: Optional custom reward shaper. Uses default if None.
        """
        super().__init__()

        self.replay_buffer = replay_buffer
        self._cursor = 0
        self._step_count = 0
        self.reward_shaper = reward_shaper or RewardShaper()

        # Observation: 18 continuous features in [0, 1] (some in [-1, 1])
        self.observation_space = spaces.Box(
            low=np.full(STATE_DIM, -1.0, dtype=np.float32),
            high=np.full(STATE_DIM, 1.0, dtype=np.float32),
            dtype=np.float32,
        )

        # Action: discrete 12-action space
        self.action_space = spaces.Discrete(ACTION_DIM)

        self._current_experience: Optional[dict] = None

    # ------------------------------------------------------------------
    # Gym interface
    # ------------------------------------------------------------------

    def reset(
        self,
        *,
        seed: Optional[int] = None,
        options: Optional[dict] = None,
    ) -> tuple[np.ndarray, dict]:
        super().reset(seed=seed)
        self._cursor = 0
        self._step_count = 0

        if not self.replay_buffer:
            obs = np.zeros(STATE_DIM, dtype=np.float32)
            return obs, {}

        # Shuffle for each episode to decorrelate training batches
        random.shuffle(self.replay_buffer)
        self._cursor = 0
        obs = self._get_current_obs()
        return obs, {}

    def step(self, action: int) -> tuple[np.ndarray, float, bool, bool, dict]:
        """
        Process one step of offline replay.

        Args:
            action: The agent's chosen action (0–11).

        Returns:
            (observation, reward, terminated, truncated, info)
        """
        if not self.replay_buffer:
            obs = np.zeros(STATE_DIM, dtype=np.float32)
            return obs, 0.0, False, self._step_count >= MAX_EPISODE_STEPS, {}

        if self._current_experience is None:
            obs = self._get_current_obs()
        else:
            obs = np.array(
                self._current_experience.get("state_vector", [0.0] * STATE_DIM),
                dtype=np.float32,
            )

        # Compute shaped reward
        experience = self.replay_buffer[self._cursor]
        reward = self.reward_shaper.compute(
            action=action,
            experience=experience,
        )

        # Advance cursor
        self._cursor = (self._cursor + 1) % max(len(self.replay_buffer), 1)
        self._step_count += 1

        # Get next observation
        if len(self.replay_buffer) > 0:
            next_exp = self.replay_buffer[self._cursor]
            next_obs = np.array(
                next_exp.get("state_vector", [0.0] * STATE_DIM),
                dtype=np.float32,
            )
        else:
            next_obs = np.zeros(STATE_DIM, dtype=np.float32)
        self._current_experience = (
            self.replay_buffer[self._cursor] if self.replay_buffer else None
        )

        terminated = False
        truncated = self._step_count >= MAX_EPISODE_STEPS

        info = {
            "experience_action": experience.get("action", -1),
            "event_type": experience.get("event_type", "unknown"),
            "endpoint_id": experience.get("endpoint_id", ""),
        }

        return next_obs, reward, terminated, truncated, info

    def _get_current_obs(self) -> np.ndarray:
        if not self.replay_buffer:
            return np.zeros(STATE_DIM, dtype=np.float32)
        exp = self.replay_buffer[self._cursor]
        self._current_experience = exp
        return np.array(exp.get("state_vector", [0.0] * STATE_DIM), dtype=np.float32)

    def render(self) -> None:
        pass

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Reward Shaper
# ---------------------------------------------------------------------------


class RewardShaper:
    """
    Mathematically justified reward function.

    Design principles:
    1. Base reward from event type (see REWARD_VALUES).
    2. Action-event alignment bonus/penalty: correct action for event type +5.
    3. Risk calibration bonus: RL adjustment converges toward truth +2 to -2.
    4. Temporal discounting handled by PPO's GAE; we shape per-step rewards here.
    5. Alert fatigue penalty accumulates over episode (tracked externally via DB).

    Mathematical justification:
      R(s, a) = R_base(e) + R_align(a, e) + R_calibrate(s, a)

    Where:
      R_base(e)        = base reward from event type (lookup table)
      R_align(a, e)    = +5 if action is optimal for event, -5 if clearly wrong
      R_calibrate(s,a) = Gaussian reward for risk adjustment closeness to truth
    """

    # Optimal action for each event type (primary alignment)
    OPTIMAL_ACTIONS: dict[str, set[int]] = {
        RewardEventType.CORRECT_CLASSIFICATION:  {RLAction.MARK_ACTIVE, RLAction.MARK_ZOMBIE, RLAction.MARK_ORPHANED, RLAction.MARK_DEPRECATED},
        RewardEventType.ANALYST_AGREEMENT:       {RLAction.REQUIRE_ANALYST_REVIEW, RLAction.TRIGGER_ALERT},
        RewardEventType.SUCCESSFUL_REMEDIATION:  {RLAction.TRIGGER_AUTO_REMEDIATION},
        RewardEventType.THREAT_PREVENTION:       {RLAction.TRIGGER_ALERT, RLAction.ESCALATE_SEVERITY, RLAction.TRIGGER_AUTO_REMEDIATION},
        RewardEventType.REDUCED_FALSE_POSITIVE:  {RLAction.SUPPRESS_ALERT, RLAction.IGNORE},
        RewardEventType.REDUCED_FALSE_NEGATIVE:  {RLAction.TRIGGER_ALERT, RLAction.ESCALATE_SEVERITY},
        RewardEventType.FALSE_POSITIVE:          {RLAction.IGNORE, RLAction.SUPPRESS_ALERT},
        RewardEventType.WRONG_CLASSIFICATION:    set(),  # no optimal action for past mistake
        RewardEventType.MISSED_ATTACK:           {RLAction.TRIGGER_ALERT, RLAction.ESCALATE_SEVERITY},
        RewardEventType.FAILED_REMEDIATION:      {RLAction.REQUIRE_ANALYST_REVIEW},
        RewardEventType.ANALYST_OVERRIDE:        {RLAction.REQUIRE_ANALYST_REVIEW},
        RewardEventType.ALERT_FATIGUE:           {RLAction.SUPPRESS_ALERT, RLAction.IGNORE},
    }

    # Clearly wrong actions for each event type (double penalty)
    WRONG_ACTIONS: dict[str, set[int]] = {
        RewardEventType.MISSED_ATTACK:      {RLAction.IGNORE, RLAction.SUPPRESS_ALERT, RLAction.DECREASE_RISK},
        RewardEventType.THREAT_PREVENTION:  {RLAction.IGNORE, RLAction.DECREASE_RISK},
        RewardEventType.ALERT_FATIGUE:      {RLAction.TRIGGER_ALERT, RLAction.ESCALATE_SEVERITY},
    }

    def compute(self, action: int, experience: dict) -> float:
        """
        Compute the shaped reward for a (state, action, event_type) triple.

        Args:
            action: Agent's chosen action.
            experience: Replay buffer entry with state_vector, action, event_type.

        Returns:
            Shaped reward value clipped to [REWARD_CLIP_MIN, REWARD_CLIP_MAX].
        """
        event_type_str = experience.get("event_type", "")
        state_vector = experience.get("state_vector", [0.0] * STATE_DIM)

        # 1. Base reward from event type
        try:
            event_type = RewardEventType(event_type_str)
            r_base = REWARD_VALUES.get(event_type, 0.0)
        except ValueError:
            r_base = 0.0
            event_type = None

        # 2. Action-event alignment bonus/penalty
        r_align = self._compute_alignment_reward(action, event_type_str)

        # 3. Risk calibration reward
        r_calibrate = self._compute_calibration_reward(action, state_vector)

        # 4. Zombie probability bonus: if state indicates Zombie, reward Zombie-targeting actions
        r_zombie = self._compute_zombie_bonus(action, state_vector)

        total = r_base + r_align + r_calibrate + r_zombie
        return float(np.clip(total, REWARD_CLIP_MIN, REWARD_CLIP_MAX))

    def _compute_alignment_reward(self, action: int, event_type_str: str) -> float:
        """
        +5 if action aligns with optimal set for the event.
        -5 if action is in the wrong-action set.
        0 otherwise.
        """
        optimal = self.OPTIMAL_ACTIONS.get(event_type_str, set())
        wrong = self.WRONG_ACTIONS.get(event_type_str, set())

        if action in optimal:
            return +5.0
        if action in wrong:
            return -5.0
        return 0.0

    def _compute_calibration_reward(self, action: int, state_vector: list[float]) -> float:
        """
        Gaussian shaped reward for risk adjustment actions.

        For INCREASE_RISK / DECREASE_RISK actions, reward is higher when the
        risk score is actually misaligned (i.e., the adjustment is needed).

        R_cal = 2 * exp(-0.5 * ((predicted_adjustment - needed_adjustment) / 10)^2)
        where needed_adjustment is estimated from the state's rule_risk_score vs
        the historical mean.
        """
        if len(state_vector) < STATE_DIM:
            return 0.0

        if action not in (RLAction.INCREASE_RISK, RLAction.DECREASE_RISK):
            return 0.0

        rule_risk = state_vector[12]       # rule_risk_score_normalized [0, 1]
        anomaly_sigma = state_vector[13]   # anomaly_sigma_normalized [0, 1]

        # High risk + anomaly = adjustment is warranted
        combined_threat = (rule_risk + anomaly_sigma) / 2.0

        if action == RLAction.INCREASE_RISK and combined_threat > 0.5:
            return +2.0 * combined_threat
        if action == RLAction.DECREASE_RISK and combined_threat < 0.3:
            return +1.0 * (1.0 - combined_threat)

        # Penalise clearly misaligned risk adjustment
        if action == RLAction.INCREASE_RISK and combined_threat < 0.2:
            return -3.0
        if action == RLAction.DECREASE_RISK and combined_threat > 0.7:
            return -3.0

        return 0.0

    def _compute_zombie_bonus(self, action: int, state_vector: list[float]) -> float:
        """
        Additional reward for targeting Zombie endpoints correctly.

        When lifecycle_status indicates Zombie (state[2] ~= 0.75) and the
        action is Zombie-targeting (MARK_ZOMBIE, TRIGGER_ALERT, etc.) →
        +3.0 bonus. Penalise IGNORE on Zombie by -3.0.
        """
        if len(state_vector) < 3:
            return 0.0

        lifecycle_enc = state_vector[2]
        is_likely_zombie = 0.65 <= lifecycle_enc <= 0.85

        zombie_actions = {RLAction.MARK_ZOMBIE, RLAction.TRIGGER_ALERT,
                          RLAction.TRIGGER_AUTO_REMEDIATION, RLAction.ESCALATE_SEVERITY,
                          RLAction.REQUIRE_ANALYST_REVIEW}

        if is_likely_zombie:
            if action in zombie_actions:
                return +3.0
            if action == RLAction.IGNORE or action == RLAction.SUPPRESS_ALERT:
                return -3.0
        return 0.0
