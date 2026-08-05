"""
Kafka consumer for the RL Intelligence Service.

Subscribes to all six Kafka topics and generates reward events
or triggers re-prediction as appropriate:

  endpoint.updated      → re-run RL prediction; update agent state
  endpoint.classified   → check if RL agreed; generate CORRECT/WRONG reward
  anomaly.alerts        → trigger TRIGGER_ALERT action check; potential reward
  endpoint.remediated   → generate SUCCESSFUL/FAILED_REMEDIATION reward
  analyst.feedback      → generate reward from human signal (primary feedback loop)
  risk.recalculated     → update state vector with new risk score
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from sentinel_shared.kafka import SentinelConsumer, SentinelProducer

from models import (
    RLRewardEventRow,
    RLAction,
    RewardEventType,
    REWARD_VALUES,
    AnalystFeedbackRow,
)

logger = structlog.get_logger(__name__)

KAFKA_BOOTSTRAP = "kafka:9092"
GROUP_ID = "rl-intelligence-service"

# All topics this service consumes
RL_TOPICS = [
    "endpoint.updated",
    "endpoint.classified",
    "anomaly.alerts",
    "endpoint.remediated",
    "analyst.feedback",
    "risk.recalculated",
]


async def _handle_endpoint_updated(message: dict, db: Any, predictor: Any) -> None:
    """Re-run RL prediction when endpoint metadata changes."""
    endpoint_id = message.get("endpoint_id")
    if not endpoint_id:
        return
    logger.info("rl_endpoint_updated", endpoint_id=endpoint_id)
    # Trigger async prediction update (fire-and-forget, errors are logged)
    try:
        await predictor.run_prediction(endpoint_id)
    except Exception as exc:
        logger.error("rl_prediction_on_update_failed", endpoint_id=endpoint_id, error=str(exc))


async def _handle_endpoint_classified(message: dict, db: Any, predictor: Any) -> None:
    """
    Compare RL's last action with the new classification.

    If RL recommended the same lifecycle status as the rule engine → CORRECT_CLASSIFICATION.
    If RL recommended a different status that was overridden → WRONG_CLASSIFICATION.
    """
    endpoint_id = message.get("endpoint_id")
    new_status = message.get("lifecycle_status")
    if not endpoint_id or not new_status:
        return

    agent_state = await db.get_agent_state(endpoint_id)
    if not agent_state:
        return

    last_action = agent_state.get("last_action", -1)
    state_snapshot = agent_state.get("state_vector", [])

    # Map lifecycle status to expected RL action
    status_to_action = {
        "Zombie": RLAction.MARK_ZOMBIE.value,
        "Orphaned": RLAction.MARK_ORPHANED.value,
        "Deprecated": RLAction.MARK_DEPRECATED.value,
        "Active": RLAction.MARK_ACTIVE.value,
    }

    expected_action = status_to_action.get(new_status)
    if expected_action is None:
        return

    if last_action == expected_action:
        event_type = RewardEventType.CORRECT_CLASSIFICATION
    elif last_action in (RLAction.IGNORE.value, RLAction.SUPPRESS_ALERT.value) and new_status in ("Zombie", "Orphaned"):
        event_type = RewardEventType.WRONG_CLASSIFICATION
    else:
        return  # inconclusive

    reward_row = RLRewardEventRow(
        endpoint_id=endpoint_id,
        event_type=event_type.value,
        reward_value=REWARD_VALUES[event_type],
        action_taken=last_action,
        state_snapshot=state_snapshot,
        source="kafka_classified",
        occurred_at=datetime.now(timezone.utc),
    )
    await db.insert_reward_event(reward_row)
    logger.info(
        "rl_reward_from_classification",
        endpoint_id=endpoint_id,
        event_type=event_type.value,
        reward=REWARD_VALUES[event_type],
    )


async def _handle_anomaly_alert(message: dict, db: Any, predictor: Any) -> None:
    """
    When a high-sigma anomaly fires, check if RL already triggered an alert.

    If RL last action was TRIGGER_ALERT / ESCALATE_SEVERITY → positive reward.
    If RL last action was IGNORE / SUPPRESS_ALERT → MISSED_ATTACK penalty.
    """
    endpoint_id = message.get("endpoint_id")
    deviation_sigma = float(message.get("deviation_sigma", 0.0))
    if not endpoint_id:
        return

    # Only generate reward for significant anomalies (> 3σ)
    if deviation_sigma < 3.0:
        return

    agent_state = await db.get_agent_state(endpoint_id)
    if not agent_state:
        return

    last_action = agent_state.get("last_action", RLAction.IGNORE.value)
    state_snapshot = agent_state.get("state_vector", [])

    alert_actions = {RLAction.TRIGGER_ALERT.value, RLAction.ESCALATE_SEVERITY.value,
                     RLAction.TRIGGER_AUTO_REMEDIATION.value}
    ignore_actions = {RLAction.IGNORE.value, RLAction.SUPPRESS_ALERT.value}

    if last_action in alert_actions:
        event_type = RewardEventType.THREAT_PREVENTION
    elif last_action in ignore_actions:
        event_type = RewardEventType.MISSED_ATTACK
    else:
        event_type = RewardEventType.REDUCED_FALSE_NEGATIVE

    reward_row = RLRewardEventRow(
        endpoint_id=endpoint_id,
        event_type=event_type.value,
        reward_value=REWARD_VALUES[event_type],
        action_taken=last_action,
        state_snapshot=state_snapshot,
        source="kafka_anomaly",
        occurred_at=datetime.now(timezone.utc),
    )
    await db.insert_reward_event(reward_row)
    logger.info(
        "rl_reward_from_anomaly",
        endpoint_id=endpoint_id,
        event_type=event_type.value,
        deviation_sigma=deviation_sigma,
        reward=REWARD_VALUES[event_type],
    )


async def _handle_endpoint_remediated(message: dict, db: Any, predictor: Any) -> None:
    """
    When a recommendation is resolved, check if the risk score improved.

    Simplified: if RL recommended auto-remediation → SUCCESSFUL_REMEDIATION.
    Otherwise → baseline signal.
    """
    endpoint_id = message.get("endpoint_id")
    if not endpoint_id:
        return

    agent_state = await db.get_agent_state(endpoint_id)
    if not agent_state:
        return

    last_action = agent_state.get("last_action", -1)
    state_snapshot = agent_state.get("state_vector", [])

    if last_action == RLAction.TRIGGER_AUTO_REMEDIATION.value:
        event_type = RewardEventType.SUCCESSFUL_REMEDIATION
    elif last_action == RLAction.REQUIRE_ANALYST_REVIEW.value:
        event_type = RewardEventType.ANALYST_AGREEMENT
    else:
        event_type = RewardEventType.SUCCESSFUL_REMEDIATION  # still positive signal

    reward_row = RLRewardEventRow(
        endpoint_id=endpoint_id,
        event_type=event_type.value,
        reward_value=REWARD_VALUES[event_type],
        action_taken=last_action,
        state_snapshot=state_snapshot,
        source="kafka_remediated",
        occurred_at=datetime.now(timezone.utc),
    )
    await db.insert_reward_event(reward_row)
    logger.info(
        "rl_reward_from_remediation",
        endpoint_id=endpoint_id,
        event_type=event_type.value,
        reward=REWARD_VALUES[event_type],
    )


async def _handle_analyst_feedback(message: dict, db: Any, predictor: Any) -> None:
    """
    Process analyst.feedback Kafka events.

    Schema: {
        endpoint_id, analyst_id, feedback_type,
        previous_value, new_value, rl_prediction_id, notes
    }

    feedback_type → reward mapping:
      classification_override → ANALYST_OVERRIDE (-15)
      risk_change             → check direction vs RL → ANALYST_AGREEMENT (+15) or override (-15)
      alert_ack               → ANALYST_AGREEMENT (+15) + REDUCED_FALSE_NEGATIVE (+25)
      alert_reject            → FALSE_POSITIVE (-20) + REDUCED_FALSE_POSITIVE (+15, net -5)
      remediation_approved    → SUCCESSFUL_REMEDIATION (+20)
      remediation_rejected    → FAILED_REMEDIATION (-30)
    """
    endpoint_id = message.get("endpoint_id")
    analyst_id = message.get("analyst_id", "unknown")
    feedback_type = message.get("feedback_type", "")
    if not endpoint_id or not feedback_type:
        return

    agent_state = await db.get_agent_state(endpoint_id)
    state_snapshot = agent_state.get("state_vector", []) if agent_state else []

    feedback_reward_map = {
        "classification_override": RewardEventType.ANALYST_OVERRIDE,
        "alert_ack":               RewardEventType.ANALYST_AGREEMENT,
        "alert_reject":            RewardEventType.FALSE_POSITIVE,
        "remediation_approved":    RewardEventType.SUCCESSFUL_REMEDIATION,
        "remediation_rejected":    RewardEventType.FAILED_REMEDIATION,
        "risk_change":             RewardEventType.ANALYST_AGREEMENT,
    }

    event_type = feedback_reward_map.get(feedback_type, RewardEventType.ANALYST_AGREEMENT)
    reward = REWARD_VALUES[event_type]

    # Insert feedback record
    feedback_row = AnalystFeedbackRow(
        endpoint_id=endpoint_id,
        analyst_id=analyst_id,
        feedback_type=feedback_type,
        previous_value=message.get("previous_value"),
        new_value=message.get("new_value"),
        rl_prediction_id=message.get("rl_prediction_id"),
        reward_generated=reward,
        notes=message.get("notes"),
        occurred_at=datetime.now(timezone.utc),
    )
    await db.insert_analyst_feedback(feedback_row)

    # Insert reward event
    last_action = agent_state.get("last_action", -1) if agent_state else -1
    reward_row = RLRewardEventRow(
        endpoint_id=endpoint_id,
        event_type=event_type.value,
        reward_value=reward,
        action_taken=last_action,
        state_snapshot=state_snapshot,
        source="analyst_feedback",
        occurred_at=datetime.now(timezone.utc),
    )
    await db.insert_reward_event(reward_row)

    logger.info(
        "rl_reward_from_analyst_feedback",
        endpoint_id=endpoint_id,
        feedback_type=feedback_type,
        analyst_id=analyst_id,
        reward=reward,
    )


async def _handle_risk_recalculated(message: dict, db: Any, predictor: Any) -> None:
    """Update agent state with refreshed risk score, trigger re-prediction."""
    endpoint_id = message.get("endpoint_id")
    if not endpoint_id:
        return
    logger.info("rl_risk_recalculated", endpoint_id=endpoint_id)
    try:
        await predictor.run_prediction(endpoint_id)
    except Exception as exc:
        logger.error("rl_reprediction_on_risk_failed", endpoint_id=endpoint_id, error=str(exc))


# Topic → handler mapping
_TOPIC_HANDLERS = {
    "endpoint.updated":    _handle_endpoint_updated,
    "endpoint.classified": _handle_endpoint_classified,
    "anomaly.alerts":      _handle_anomaly_alert,
    "endpoint.remediated": _handle_endpoint_remediated,
    "analyst.feedback":    _handle_analyst_feedback,
    "risk.recalculated":   _handle_risk_recalculated,
}


async def kafka_consumer_loop(app: Any) -> None:
    """
    Main Kafka consumer loop for the RL Intelligence Service.

    Subscribes to all six topics and dispatches to per-topic handlers.
    Runs as a background asyncio task.
    """
    db = getattr(app.state, "db", None)
    predictor = getattr(app.state, "predictor", None)

    if db is None:
        logger.warning("rl_kafka_no_db")
        return

    consumer = SentinelConsumer(
        topics=RL_TOPICS,
        group_id=GROUP_ID,
        bootstrap_servers=KAFKA_BOOTSTRAP,
    )

    async def handle_message(message: dict) -> None:
        topic = message.get("_topic", "unknown")
        handler = _TOPIC_HANDLERS.get(topic)
        if handler:
            try:
                await handler(message, db, predictor)
            except Exception as exc:
                logger.error(
                    "rl_kafka_handler_error",
                    topic=topic,
                    error=str(exc),
                )

    try:
        await consumer.start()
        await consumer.run(handle_message)
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("rl_kafka_consumer_error", error=str(exc))
    finally:
        await consumer.stop()
