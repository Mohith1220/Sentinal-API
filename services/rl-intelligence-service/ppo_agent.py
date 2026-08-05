"""
PPO Agent — wraps Stable-Baselines3 PPO for the SentinelAPI RL service.

Responsibilities:
  - Load/save policy artifacts from disk
  - Run inference (predict) for a given state vector
  - Train/fine-tune the policy against the offline replay buffer
  - Track policy versions
  - Compute XGBoost-based zombie/threat/remediation probabilities
  - Expose per-decision SHAP explanations

Architecture:
  Rule Engine score (deterministic, authoritative)
      +
  XGBoost ML score (feature-based, advisory)
      +
  PPO RL adjustment (learned from feedback, -20 to +20)
      =
  Final Risk Score (capped at 100)

The PPO policy is an MLP with 2×256 hidden layers, trained with:
  - Clipping: ε = 0.2
  - Entropy coefficient: 0.01 (encourages exploration)
  - GAE λ = 0.95
  - Batch size: 64
  - n_steps: 2048
"""

from __future__ import annotations

import io
import logging
import os
import pickle
import time
from pathlib import Path
from typing import Optional

import numpy as np
import structlog

from models import (
    RLAction,
    RLStateVector,
    STATE_DIM,
    ACTION_DIM,
    ACTION_DESCRIPTIONS,
    STATE_FEATURE_NAMES,
)

logger = structlog.get_logger(__name__)

# Default artifact paths
POLICY_DIR = Path(os.environ.get("RL_POLICY_DIR", "/models/rl_policies"))
XGBOOST_MODEL_PATH = Path(os.environ.get("XGBOOST_MODEL_PATH", "/models/xgb_risk.pkl"))


class PPOAgent:
    """
    Manages the PPO policy lifecycle: load, infer, train, version.

    Thread-safety: inference is read-only and safe to call concurrently.
    Training must be called from a single background task.
    """

    def __init__(self, policy_dir: Path = POLICY_DIR) -> None:
        self._policy_dir = policy_dir
        self._policy_dir.mkdir(parents=True, exist_ok=True)

        self._model = None        # SB3 PPO model
        self._xgb_model = None    # XGBoost risk classifier
        self._policy_version = 0
        self._load_attempted = False

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------

    def load(self) -> bool:
        """
        Attempt to load the latest PPO policy artifact.

        Returns True if loaded successfully, False otherwise (caller falls
        back to uniform random action).
        """
        if self._load_attempted:
            return self._model is not None
        self._load_attempted = True

        # Find latest policy artifact
        artifacts = sorted(self._policy_dir.glob("policy_v*.zip"))
        if not artifacts:
            logger.warning(f"ppo_no_policy_artifact dir={str(self._policy_dir)}")
            self._model = self._create_untrained_model()
            return True

        latest = artifacts[-1]
        try:
            from stable_baselines3 import PPO
            import gymnasium as gym
            from environment import SentinelAPIEnvironment

            # Create a dummy env just for loading
            dummy_env = _DummyEnv()
            self._model = PPO.load(str(latest), env=dummy_env)
            # Parse version from filename
            stem = latest.stem  # e.g. "policy_v3"
            self._policy_version = int(stem.split("_v")[-1])
            logger.info(
                "ppo_policy_loaded",
                path=str(latest),
                version=self._policy_version,
            )
            return True
        except Exception as exc:
            logger.error("ppo_load_failed", path=str(latest), error=str(exc))
            self._model = self._create_untrained_model()
            return True

    def load_xgboost(self) -> bool:
        """Load the XGBoost risk classifier artifact."""
        if not XGBOOST_MODEL_PATH.exists():
            logger.warning("xgboost_model_not_found", path=str(XGBOOST_MODEL_PATH))
            self._xgb_model = None
            return False
        try:
            with open(XGBOOST_MODEL_PATH, "rb") as f:
                self._xgb_model = pickle.load(f)  # noqa: S301
            logger.info("xgboost_model_loaded", path=str(XGBOOST_MODEL_PATH))
            return True
        except Exception as exc:
            logger.error("xgboost_load_failed", error=str(exc))
            return False

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def predict(self, state: RLStateVector) -> dict:
        """
        Run PPO inference for a single state vector.

        Returns:
            dict with keys:
              action (int), action_name (str),
              action_confidence (float), action_probabilities (list[float]),
              rl_risk_adjustment (int)
        """
        if not self._load_attempted:
            self.load()

        obs = state.to_numpy().reshape(1, -1)

        if self._model is not None:
            try:
                action, _states = self._model.predict(obs, deterministic=True)
                action_int = int(action)

                # Get action probabilities from policy distribution
                probs = self._get_action_probabilities(obs)
                confidence = float(probs[action_int]) if probs is not None else 0.0

            except Exception as exc:
                logger.warning("ppo_inference_failed", error=str(exc))
                action_int, probs, confidence = self._fallback_predict(state)
        else:
            action_int, probs, confidence = self._fallback_predict(state)

        # Compute RL risk adjustment (-20 to +20)
        rl_adjustment = self._compute_rl_adjustment(action_int, state)

        return {
            "action": action_int,
            "action_name": RLAction(action_int).name,
            "action_confidence": confidence,
            "action_probabilities": probs if probs is not None else [1.0 / ACTION_DIM] * ACTION_DIM,
            "rl_risk_adjustment": rl_adjustment,
        }

    def predict_probabilities(self, state: RLStateVector) -> dict:
        """
        Compute zombie/threat/remediation probabilities from the state and XGBoost.

        Returns dict with: zombie_probability, threat_probability, remediation_probability
        """
        obs = state.to_numpy()

        if self._xgb_model is not None:
            try:
                probs = self._xgb_model.predict_proba(obs.reshape(1, -1))[0]
                # Assume 4-class: [active, deprecated, zombie, threat]
                zombie_prob = float(probs[2]) if len(probs) > 2 else 0.0
                threat_prob = float(probs[3]) if len(probs) > 3 else 0.0
                remediation_prob = float(probs[2] + probs[3]) if len(probs) > 3 else 0.0
            except Exception:
                zombie_prob, threat_prob, remediation_prob = self._heuristic_probabilities(state)
        else:
            zombie_prob, threat_prob, remediation_prob = self._heuristic_probabilities(state)

        return {
            "zombie_probability": round(zombie_prob, 4),
            "threat_probability": round(threat_prob, 4),
            "remediation_probability": round(min(remediation_prob, 1.0), 4),
        }

    def _heuristic_probabilities(
        self, state: RLStateVector
    ) -> tuple[float, float, float]:
        """
        Rule-based heuristic probability estimates when XGBoost is absent.

        Uses features directly to estimate probabilities:
          - zombie = high traffic + no spec + no owner
          - threat = high risk + high anomaly
          - remediation = zombie + threat combined
        """
        lifecycle_enc = state.lifecycle_status_encoded
        spec = state.spec_presence
        owner = state.owner_present
        traffic_freq = state.traffic_frequency_normalized
        risk = state.rule_risk_score_normalized
        anomaly = state.anomaly_sigma_normalized
        blast = state.blast_radius_normalized

        zombie_prob = min(1.0, max(0.0,
            (0.75 if 0.65 <= lifecycle_enc <= 0.85 else 0.0)
            + (0.15 if spec < 0.5 else 0.0)
            + (0.10 if owner < 0.5 else 0.0)
        ))

        threat_prob = min(1.0, max(0.0,
            (risk * 0.5)
            + (anomaly * 0.3)
            + (blast * 0.2)
        ))

        remediation_prob = min(1.0, (zombie_prob * 0.6 + threat_prob * 0.4))

        return zombie_prob, threat_prob, remediation_prob

    def _get_action_probabilities(self, obs: np.ndarray) -> Optional[list[float]]:
        """Extract action probability distribution from PPO policy."""
        try:
            import torch
            obs_tensor = torch.FloatTensor(obs)
            with torch.no_grad():
                dist = self._model.policy.get_distribution(obs_tensor)
                probs = dist.distribution.probs.squeeze().numpy().tolist()
            return probs
        except Exception:
            return None

    def _fallback_predict(
        self, state: RLStateVector
    ) -> tuple[int, list[float], float]:
        """
        Rule-based fallback prediction when PPO model is unavailable.

        Implements a deterministic policy based on known risk signals:
        high risk + zombie → TRIGGER_AUTO_REMEDIATION
        high risk → TRIGGER_ALERT
        zombie → MARK_ZOMBIE
        orphaned → MARK_ORPHANED
        default → IGNORE
        """
        lifecycle_enc = state.lifecycle_status_encoded
        risk = state.rule_risk_score_normalized
        anomaly = state.anomaly_sigma_normalized
        spec = state.spec_presence
        owner = state.owner_present

        if risk > 0.7 and anomaly > 0.5:
            action = RLAction.TRIGGER_AUTO_REMEDIATION
        elif risk > 0.6:
            action = RLAction.TRIGGER_ALERT
        elif 0.65 <= lifecycle_enc <= 0.85:
            action = RLAction.MARK_ZOMBIE
        elif 0.4 <= lifecycle_enc <= 0.6 and not owner:
            action = RLAction.MARK_ORPHANED
        elif spec < 0.5 and owner < 0.5:
            action = RLAction.REQUIRE_ANALYST_REVIEW
        else:
            action = RLAction.IGNORE

        probs = [1.0 / ACTION_DIM] * ACTION_DIM
        probs[action.value] = 0.7
        total = sum(probs)
        probs = [p / total for p in probs]
        return action.value, probs, 0.7

    def _compute_rl_adjustment(self, action: int, state: RLStateVector) -> int:
        """
        Compute the RL risk score adjustment in range [-20, +20].

        Adjustment logic:
          INCREASE_RISK → +abs(adjustment), scaled by threat indicators
          DECREASE_RISK → -abs(adjustment), scaled by safety indicators
          Risk-neutral actions → 0
        """
        risk = state.rule_risk_score_normalized
        anomaly = state.anomaly_sigma_normalized
        blast = state.blast_radius_normalized
        zombie = 1.0 if 0.65 <= state.lifecycle_status_encoded <= 0.85 else 0.0

        combined_threat = (risk * 0.4 + anomaly * 0.3 + blast * 0.2 + zombie * 0.1)

        if action in (RLAction.INCREASE_RISK, RLAction.ESCALATE_SEVERITY,
                      RLAction.TRIGGER_ALERT, RLAction.TRIGGER_AUTO_REMEDIATION):
            raw = int(round(combined_threat * 20))
            return min(20, max(1, raw))

        if action in (RLAction.DECREASE_RISK, RLAction.SUPPRESS_ALERT, RLAction.IGNORE):
            safety = 1.0 - combined_threat
            raw = int(round(safety * 20))
            return -min(20, max(1, raw))

        return 0

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(
        self,
        replay_buffer: list[dict],
        total_timesteps: int = 10_000,
    ) -> dict:
        """
        Train (or fine-tune) the PPO policy on the offline replay buffer.

        Args:
            replay_buffer: List of experience dicts from the DB.
            total_timesteps: Number of environment steps.

        Returns:
            Training metrics dict.
        """
        from stable_baselines3 import PPO
        from stable_baselines3.common.callbacks import EvalCallback
        from environment import SentinelAPIEnvironment

        start_time = time.monotonic()

        # Wrap the replay buffer in the Gymnasium environment
        env = SentinelAPIEnvironment(replay_buffer=replay_buffer)

        if self._model is None:
            self._model = self._create_model(env)
        else:
            # Re-set the environment (fine-tuning case)
            self._model.set_env(env)

        logger.info(
            "ppo_training_start",
            timesteps=total_timesteps,
            buffer_size=len(replay_buffer),
        )

        self._model.learn(
            total_timesteps=total_timesteps,
            reset_num_timesteps=False,
            progress_bar=False,
        )

        duration = time.monotonic() - start_time

        # Bump version and save artifact
        self._policy_version += 1
        artifact_path = self._policy_dir / f"policy_v{self._policy_version}.zip"
        self._model.save(str(artifact_path))

        # Extract training metrics
        metrics = self._extract_training_metrics()
        metrics["policy_version"] = self._policy_version
        metrics["total_timesteps"] = total_timesteps
        metrics["training_duration_seconds"] = round(duration, 2)
        metrics["artifact_path"] = str(artifact_path)

        logger.info(
            "ppo_training_complete",
            version=self._policy_version,
            duration_s=duration,
        )
        return metrics

    def _create_model(self, env) -> "PPO":
        from stable_baselines3 import PPO
        return PPO(
            policy="MlpPolicy",
            env=env,
            n_steps=2048,
            batch_size=64,
            n_epochs=10,
            gamma=0.99,
            gae_lambda=0.95,
            clip_range=0.2,
            ent_coef=0.01,
            vf_coef=0.5,
            max_grad_norm=0.5,
            learning_rate=3e-4,
            policy_kwargs={"net_arch": [256, 256]},
            verbose=0,
        )

    def _create_untrained_model(self):
        """Create an untrained PPO model with the correct env."""
        try:
            env = _DummyEnv()
            return self._create_model(env)
        except Exception as exc:
            logger.warning(f"create_untrained_model_failed error={exc}")
            return None

    def _extract_training_metrics(self) -> dict:
        """Pull the latest training metrics from SB3 logger."""
        metrics = {
            "mean_reward": 0.0,
            "std_reward": 0.0,
            "entropy_loss": 0.0,
            "policy_loss": 0.0,
            "value_loss": 0.0,
            "explained_variance": 0.0,
        }
        try:
            if hasattr(self._model, "logger") and self._model.logger is not None:
                log_data = self._model.logger.name_to_value
                metrics["policy_loss"] = float(log_data.get("train/policy_gradient_loss", 0.0))
                metrics["value_loss"] = float(log_data.get("train/value_loss", 0.0))
                metrics["entropy_loss"] = float(log_data.get("train/entropy_loss", 0.0))
                metrics["explained_variance"] = float(log_data.get("train/explained_variance", 0.0))
                metrics["mean_reward"] = float(log_data.get("rollout/ep_rew_mean", 0.0))
        except Exception:
            pass
        return metrics

    @property
    def policy_version(self) -> int:
        return self._policy_version


# ---------------------------------------------------------------------------
# SHAP Explainer for RL decisions
# ---------------------------------------------------------------------------


class RLExplainer:
    """
    SHAP-based explainability for PPO decisions.

    Uses KernelExplainer (model-agnostic) since PPO's neural network
    is not directly supported by TreeExplainer or LinearExplainer.
    Falls back to permutation-based importance on failure.
    """

    def __init__(self, agent: PPOAgent) -> None:
        self._agent = agent
        self._explainer = None

    def explain(
        self,
        state: RLStateVector,
        background_states: Optional[list[RLStateVector]] = None,
    ) -> list[dict]:
        """
        Compute feature contributions for a single prediction.

        Returns a list of dicts: [{"feature": str, "contribution": float, "value": float}]
        sorted descending by abs(contribution).
        """
        try:
            return self._shap_explain(state, background_states)
        except Exception as exc:
            logger.warning("shap_explain_failed", error=str(exc))
            return self._permutation_explain(state)

    def _shap_explain(
        self,
        state: RLStateVector,
        background_states: Optional[list[RLStateVector]],
    ) -> list[dict]:
        import shap

        obs = state.to_numpy()
        state_values = obs.tolist()

        # Build background dataset
        if background_states and len(background_states) >= 5:
            bg = np.array([s.to_numpy() for s in background_states[:50]])
        else:
            bg = np.zeros((10, STATE_DIM), dtype=np.float32)
            bg[:, 12] = 0.5   # default risk = 0.5

        def _predict_fn(X: np.ndarray) -> np.ndarray:
            """Wrapper: maps state batch → max action probability."""
            results = []
            for row in X:
                try:
                    import torch
                    obs_t = torch.FloatTensor(row.reshape(1, -1))
                    with torch.no_grad():
                        dist = self._agent._model.policy.get_distribution(obs_t)
                        max_prob = dist.distribution.probs.max().item()
                    results.append(max_prob)
                except Exception:
                    results.append(0.5)
            return np.array(results)

        explainer = shap.KernelExplainer(_predict_fn, bg)
        shap_values = explainer.shap_values(
            obs.reshape(1, -1), nsamples=100, silent=True
        )
        sv = shap_values[0] if isinstance(shap_values, list) else shap_values.flatten()

        contributions = [
            {
                "feature": STATE_FEATURE_NAMES[i],
                "contribution": float(sv[i]),
                "value": float(state_values[i]),
            }
            for i in range(len(STATE_FEATURE_NAMES))
        ]
        contributions.sort(key=lambda x: abs(x["contribution"]), reverse=True)
        return contributions

    def _permutation_explain(self, state: RLStateVector) -> list[dict]:
        """
        Permutation-based importance fallback.

        Measures change in action confidence when each feature is zeroed.
        """
        obs = state.to_numpy()
        state_values = obs.tolist()

        # Baseline prediction
        result = self._agent.predict(state)
        baseline_conf = result["action_confidence"]

        contributions = []
        for i, feature_name in enumerate(STATE_FEATURE_NAMES):
            perturbed = obs.copy()
            perturbed[i] = 0.0

            # Build a temporary state from perturbed array
            perturbed_state = _array_to_state(perturbed)
            perturbed_result = self._agent.predict(perturbed_state)
            delta = baseline_conf - perturbed_result["action_confidence"]

            contributions.append({
                "feature": feature_name,
                "contribution": round(float(delta), 6),
                "value": round(float(state_values[i]), 6),
            })

        contributions.sort(key=lambda x: abs(x["contribution"]), reverse=True)
        return contributions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _DummyEnv:
    """Minimal stub to satisfy SB3 env requirements during model loading."""

    def __init__(self):
        try:
            from gymnasium import spaces
            self.observation_space = spaces.Box(
                low=-1.0, high=1.0, shape=(STATE_DIM,), dtype=np.float32
            )
            self.action_space = spaces.Discrete(ACTION_DIM)
        except ImportError:
            # gymnasium not installed — create minimal duck-typed stubs
            self.observation_space = _BoxStub(STATE_DIM)
            self.action_space = _DiscreteStub(ACTION_DIM)

    def reset(self, **kwargs):
        return np.zeros(STATE_DIM, dtype=np.float32), {}

    def step(self, action):
        return np.zeros(STATE_DIM, dtype=np.float32), 0.0, False, False, {}


class _BoxStub:
    """Minimal observation space stub when gymnasium is not installed."""
    def __init__(self, dim: int):
        self.shape = (dim,)
        self.low = np.full(dim, -1.0, dtype=np.float32)
        self.high = np.full(dim, 1.0, dtype=np.float32)
        self.dtype = np.float32


class _DiscreteStub:
    """Minimal action space stub when gymnasium is not installed."""
    def __init__(self, n: int):
        self.n = n


def _array_to_state(arr: np.ndarray) -> RLStateVector:
    """Convert a raw numpy array back to RLStateVector."""
    keys = [field for field in RLStateVector.model_fields]
    kwargs = {}
    for i, key in enumerate(keys):
        val = float(arr[i]) if i < len(arr) else 0.0
        # Clamp to valid range
        if key == "traffic_trend":
            kwargs[key] = max(-1.0, min(1.0, val))
        else:
            kwargs[key] = max(0.0, min(1.0, val))
    return RLStateVector(**kwargs)
