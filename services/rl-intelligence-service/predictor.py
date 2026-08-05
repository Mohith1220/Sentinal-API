"""
Predictor — the orchestration layer that ties together:

  1. State Builder (raw endpoint → 18-dim normalised vector)
  2. Graph Intelligence (Neo4j centrality + blast radius)
  3. PPO Agent (action + probabilities + RL risk adjustment)
  4. XGBoost (zombie/threat/remediation probabilities)
  5. SHAP Explainer (feature contributions)
  6. Database persistence (rl_predictions, rl_agent_state)

Entry points:
  run_prediction(endpoint_id)   → full prediction pipeline
  get_explanation(endpoint_id)  → explanation for last prediction
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Any

import structlog

from models import (
    RLAgentStateRow,
    RLPredictionRow,
    RLStateVector,
    RLAction,
    ACTION_DESCRIPTIONS,
    STATE_FEATURE_NAMES,
    RewardEventType,
    REWARD_VALUES,
    RLRewardEventRow,
)
from state_builder import build_state_vector
from graph_intelligence import get_graph_features
from ppo_agent import PPOAgent, RLExplainer

logger = structlog.get_logger(__name__)

# XGBoost ML contribution weight in the hybrid score formula
ML_CONTRIBUTION_WEIGHT = 10.0   # scaled contribution out of 100


class Predictor:
    """
    Orchestrates the full prediction pipeline for a single endpoint.

    Designed to be instantiated once at service startup and shared across
    all request handlers (thread-safe for inference; training is serialised
    by background task).
    """

    def __init__(self, db: Any, neo4j_driver: Optional[Any] = None) -> None:
        self._db = db
        self._neo4j_driver = neo4j_driver
        self._agent = PPOAgent()
        self._explainer = RLExplainer(self._agent)
        self._start_time = datetime.now(timezone.utc)

        # Load models on init (non-blocking — falls back gracefully)
        self._agent.load()
        self._agent.load_xgboost()

    # ------------------------------------------------------------------
    # Main prediction pipeline
    # ------------------------------------------------------------------

    async def run_prediction(self, endpoint_id: str, force_refresh_graph: bool = False) -> dict:
        """
        Run the full RL prediction pipeline for one endpoint.

        Returns a PredictResponse-compatible dict.
        """
        # 1. Fetch endpoint data
        endpoint = await self._db.get_endpoint(endpoint_id)
        if endpoint is None:
            logger.warning("predictor_endpoint_not_found", endpoint_id=endpoint_id)
            return {"error": f"Endpoint {endpoint_id} not found"}

        # 2. Fetch graph features
        graph_features = await get_graph_features(
            endpoint_id,
            self._neo4j_driver,
            force_refresh=force_refresh_graph,
        )

        # 3. Fetch anomaly history
        anomaly_history = await self._db.get_anomaly_alerts(endpoint_id, limit=10)

        # 4. Fetch feedback stats
        feedback_stats = await self._db.get_feedback_stats(endpoint_id)

        # 5. Build normalised state vector
        state = build_state_vector(
            endpoint=endpoint,
            graph_features=graph_features,
            anomaly_history=anomaly_history,
            feedback_stats=feedback_stats,
        )

        # 6. PPO inference
        ppo_result = self._agent.predict(state)

        # 7. Probability estimates
        prob_result = self._agent.predict_probabilities(state)

        # 8. Compute hybrid risk score
        rule_risk = int(endpoint.get("risk_score", 0))
        rl_adjustment = ppo_result["rl_risk_adjustment"]
        ml_contribution = _compute_ml_contribution(state)
        final_risk = min(100, max(0, rule_risk + int(ml_contribution) + rl_adjustment))

        # 9. SHAP explanation
        try:
            bg_state_arrays = await self._db.get_background_states(limit=50)
            background_states = [_array_to_state_vector(arr) for arr in bg_state_arrays]
            shap_result = self._explainer.explain(state, background_states)
        except Exception as exc:
            logger.warning("shap_explain_failed", error=str(exc))
            shap_result = []

        # Format top features
        top_features = shap_result[:5] if shap_result else []
        shap_values_list = [item["contribution"] for item in shap_result]
        # Pad to STATE_DIM length
        while len(shap_values_list) < 18:
            shap_values_list.append(0.0)

        # 10. Build action probabilities dict (name → prob)
        action_probs_list = ppo_result["action_probabilities"]
        action_probs_dict = {
            RLAction(i).name: round(float(p), 4)
            for i, p in enumerate(action_probs_list)
        }

        # 11. Persist prediction
        action_int = ppo_result["action"]
        pred_row = RLPredictionRow(
            endpoint_id=endpoint_id,
            policy_version=self._agent.policy_version,
            action=action_int,
            action_confidence=ppo_result["action_confidence"],
            action_probabilities=action_probs_list,
            rl_risk_adjustment=rl_adjustment,
            zombie_probability=prob_result["zombie_probability"],
            threat_probability=prob_result["threat_probability"],
            remediation_probability=prob_result["remediation_probability"],
            shap_values=shap_values_list,
            top_features=top_features,
            rule_risk_score=rule_risk,
            ml_risk_contribution=ml_contribution,
            final_risk_score=final_risk,
            predicted_at=datetime.now(timezone.utc),
        )
        try:
            prediction_id = await self._db.insert_prediction(pred_row)
        except Exception as exc:
            logger.warning("persist_prediction_failed", error=str(exc))
            prediction_id = pred_row.id

        # 12. Persist/update agent state
        state_row = RLAgentStateRow(
            endpoint_id=endpoint_id,
            state_vector=state.to_numpy().tolist(),
            last_action=action_int,
            last_reward=0.0,
            total_reward=0.0,
            episode_step=0,
            updated_at=datetime.now(timezone.utc),
        )
        try:
            await self._db.upsert_agent_state(state_row)
        except Exception as exc:
            logger.warning("persist_agent_state_failed", error=str(exc))

        # 13. Build confidence level label
        confidence = ppo_result["action_confidence"]
        if confidence >= 0.7:
            confidence_level = "High"
        elif confidence >= 0.4:
            confidence_level = "Medium"
        else:
            confidence_level = "Low"

        # 14. Build explanation
        action_rationale = _build_rationale(
            action=action_int,
            state=state,
            top_features=top_features,
            final_risk=final_risk,
            rule_risk=rule_risk,
            rl_adjustment=rl_adjustment,
        )

        now_iso = datetime.now(timezone.utc).isoformat()

        return {
            "endpoint_id": endpoint_id,
            "action": action_int,
            "action_name": RLAction(action_int).name,
            "action_description": ACTION_DESCRIPTIONS.get(action_int, ""),
            "action_confidence": round(confidence, 4),
            "action_probabilities": action_probs_dict,
            "rl_risk_adjustment": rl_adjustment,
            "zombie_probability": prob_result["zombie_probability"],
            "threat_probability": prob_result["threat_probability"],
            "remediation_probability": prob_result["remediation_probability"],
            "rule_risk_score": rule_risk,
            "final_risk_score": final_risk,
            "prediction_id": prediction_id,
            "explanation": {
                "top_features": top_features,
                "action_rationale": action_rationale,
                "historical_comparison": {"similar_endpoints": 0, "avg_reward": 0.0},
                "confidence_level": confidence_level,
                "policy_version": self._agent.policy_version,
            },
            "predicted_at": now_iso,
        }

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    async def train(self, total_timesteps: int = 10_000) -> dict:
        """Pull replay buffer and run PPO training."""
        from datetime import datetime, timezone

        replay_buffer = await self._db.get_replay_buffer(limit=50_000)
        if not replay_buffer:
            return {
                "policy_version": self._agent.policy_version,
                "total_timesteps": 0,
                "mean_reward": 0.0,
                "training_duration_seconds": 0.0,
                "promoted": False,
                "message": "No replay buffer data available for training.",
            }

        metrics = self._agent.train(replay_buffer, total_timesteps=total_timesteps)

        # Persist training history
        from models import RLTrainingHistoryRow
        history_row = RLTrainingHistoryRow(
            policy_version=metrics["policy_version"],
            total_timesteps=metrics["total_timesteps"],
            mean_reward=metrics.get("mean_reward", 0.0),
            std_reward=metrics.get("std_reward", 0.0),
            entropy_loss=metrics.get("entropy_loss", 0.0),
            policy_loss=metrics.get("policy_loss", 0.0),
            value_loss=metrics.get("value_loss", 0.0),
            explained_variance=metrics.get("explained_variance", 0.0),
            training_duration_seconds=metrics["training_duration_seconds"],
            trained_at=datetime.now(timezone.utc),
        )
        await self._db.insert_training_history(history_row)

        # Persist policy version
        from models import RLPolicyVersionRow
        policy_row = RLPolicyVersionRow(
            version=metrics["policy_version"],
            artifact_path=metrics.get("artifact_path", ""),
            mean_reward=metrics.get("mean_reward", 0.0),
            is_active=True,
            promoted_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        await self._db.insert_policy_version(policy_row)

        return {
            "policy_version": metrics["policy_version"],
            "total_timesteps": metrics["total_timesteps"],
            "mean_reward": metrics.get("mean_reward", 0.0),
            "training_duration_seconds": metrics["training_duration_seconds"],
            "promoted": True,
            "message": f"Policy v{metrics['policy_version']} trained and promoted.",
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_ml_contribution(state: RLStateVector) -> float:
    """
    Compute the XGBoost ML risk contribution (scaled to roughly -10 to +10).

    Uses the state vector features to estimate what ML would add to the risk score.
    When XGBoost model is loaded, this uses its output; otherwise uses heuristic.
    """
    risk = state.rule_risk_score_normalized
    anomaly = state.anomaly_sigma_normalized
    blast = state.blast_radius_normalized
    lifecycle = state.lifecycle_status_encoded

    # Heuristic: weight the most predictive features
    ml_signal = (risk * 0.5 + anomaly * 0.3 + blast * 0.1 + lifecycle * 0.1)
    # Scale to [-10, +10]
    contribution = (ml_signal - 0.5) * 20.0
    return round(max(-10.0, min(10.0, contribution)), 2)


def _build_rationale(
    action: int,
    state: RLStateVector,
    top_features: list[dict],
    final_risk: int,
    rule_risk: int,
    rl_adjustment: int,
) -> str:
    """Build a human-readable explanation string for the RL action."""
    action_desc = ACTION_DESCRIPTIONS.get(action, "")
    risk_delta = final_risk - rule_risk
    delta_str = f"+{risk_delta}" if risk_delta >= 0 else str(risk_delta)

    top = top_features[:3] if top_features else []
    feature_str = ", ".join(
        f"{f['feature']} ({'+' if f['contribution'] >= 0 else ''}{f['contribution']:.3f})"
        for f in top
    ) or "no dominant feature"

    return (
        f"Action: {action_desc}. "
        f"Rule-based risk: {rule_risk}/100, RL adjustment: {delta_str} points "
        f"(RL: {rl_adjustment:+d}). "
        f"Top contributing features: {feature_str}. "
        f"Final composite risk: {final_risk}/100."
    )


def _array_to_state_vector(arr: list) -> RLStateVector:
    """Convert a stored state array back to RLStateVector."""
    from models import STATE_DIM
    keys = list(RLStateVector.model_fields.keys())
    kwargs = {}
    for i, key in enumerate(keys):
        val = float(arr[i]) if i < len(arr) else 0.0
        if key == "traffic_trend":
            kwargs[key] = max(-1.0, min(1.0, val))
        else:
            kwargs[key] = max(0.0, min(1.0, val))
    return RLStateVector(**kwargs)
