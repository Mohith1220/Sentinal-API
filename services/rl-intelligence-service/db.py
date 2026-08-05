"""
Database layer for the RL Intelligence Service.

Provides:
  - InMemoryRLStore: in-memory store for unit tests
  - RLDatabaseManager: async PostgreSQL store for production

Tables owned by this service:
  rl_agent_state, rl_training_history, rl_reward_events,
  rl_predictions, rl_policy_versions, analyst_feedback
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional, Any

import structlog

from models import (
    RLAgentStateRow,
    RLTrainingHistoryRow,
    RLRewardEventRow,
    RLPredictionRow,
    RLPolicyVersionRow,
    AnalystFeedbackRow,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# In-memory store (unit tests)
# ---------------------------------------------------------------------------


class InMemoryRLStore:
    """In-memory RL data store — no live database required."""

    def __init__(self) -> None:
        self._endpoints: dict[str, dict] = {}
        self._agent_states: dict[str, dict] = {}
        self._training_history: list[dict] = []
        self._reward_events: list[dict] = []
        self._predictions: list[dict] = []
        self._policy_versions: list[dict] = []
        self._analyst_feedbacks: list[dict] = []
        self._anomaly_alerts: dict[str, list[dict]] = {}

    def clear(self) -> None:
        self._endpoints.clear()
        self._agent_states.clear()
        self._training_history.clear()
        self._reward_events.clear()
        self._predictions.clear()
        self._policy_versions.clear()
        self._analyst_feedbacks.clear()
        self._anomaly_alerts.clear()

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    def seed_endpoint(self, endpoint_id: str, **kwargs: Any) -> None:
        self._endpoints[endpoint_id] = {
            "id": endpoint_id,
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
            **kwargs,
        }

    async def get_endpoint(self, endpoint_id: str) -> Optional[dict]:
        e = self._endpoints.get(endpoint_id)
        return dict(e) if e else None

    async def get_anomaly_alerts(self, endpoint_id: str, limit: int = 10) -> list[dict]:
        return self._anomaly_alerts.get(endpoint_id, [])[:limit]

    async def get_feedback_stats(self, endpoint_id: str) -> dict:
        feedbacks = [f for f in self._analyst_feedbacks if f["endpoint_id"] == endpoint_id]
        if not feedbacks:
            return {
                "analyst_agreement_rate": 0.5,
                "remediation_success_rate": 0.5,
                "false_positive_rate": 0.1,
                "historical_incident_rate": 0.0,
            }
        total = len(feedbacks)
        agreements = sum(1 for f in feedbacks if f["feedback_type"] in ("alert_ack", "remediation_approved"))
        fps = sum(1 for f in feedbacks if f["feedback_type"] in ("alert_reject", "classification_override"))
        return {
            "analyst_agreement_rate": agreements / total,
            "remediation_success_rate": 0.5,
            "false_positive_rate": fps / total,
            "historical_incident_rate": total / 30.0,
        }

    async def upsert_agent_state(self, row: RLAgentStateRow) -> None:
        self._agent_states[row.endpoint_id] = row.model_dump()

    async def get_agent_state(self, endpoint_id: str) -> Optional[dict]:
        return self._agent_states.get(endpoint_id)

    async def insert_training_history(self, row: RLTrainingHistoryRow) -> str:
        self._training_history.append(row.model_dump())
        return row.id

    async def insert_reward_event(self, row: RLRewardEventRow) -> str:
        self._reward_events.append(row.model_dump())
        return row.id

    async def insert_prediction(self, row: RLPredictionRow) -> str:
        self._predictions.append(row.model_dump())
        return row.id

    async def insert_policy_version(self, row: RLPolicyVersionRow) -> str:
        # Deactivate all others
        for pv in self._policy_versions:
            pv["is_active"] = False
        self._policy_versions.append(row.model_dump())
        return row.id

    async def get_active_policy_version(self) -> int:
        actives = [pv for pv in self._policy_versions if pv.get("is_active")]
        if actives:
            return max(actives, key=lambda x: x["version"])["version"]
        return 0

    async def insert_analyst_feedback(self, row: AnalystFeedbackRow) -> str:
        self._analyst_feedbacks.append(row.model_dump())
        return row.id

    async def get_replay_buffer(self, limit: int = 50_000) -> list[dict]:
        """Build offline replay buffer from reward events + agent states."""
        events = self._reward_events[-limit:]
        return [
            {
                "endpoint_id": e["endpoint_id"],
                "state_vector": e["state_snapshot"],
                "action": e["action_taken"],
                "event_type": e["event_type"],
                "next_state_vector": e["state_snapshot"],  # simplified for in-memory
            }
            for e in events
        ]

    async def get_policy_metrics(self) -> dict:
        total = len(self._predictions)
        rewards = [e["reward_value"] for e in self._reward_events[-100:]]
        mean_reward = sum(rewards) / max(len(rewards), 1)
        feedbacks = self._analyst_feedbacks
        agreements = sum(1 for f in feedbacks if f["feedback_type"] in ("alert_ack", "remediation_approved"))
        fps = sum(1 for f in feedbacks if f["feedback_type"] == "alert_reject")
        return {
            "active_policy_version": await self.get_active_policy_version(),
            "total_predictions": total,
            "mean_reward_last_100": mean_reward,
            "analyst_agreement_rate": agreements / max(len(feedbacks), 1),
            "false_positive_rate": fps / max(len(feedbacks), 1),
            "false_negative_rate": 0.0,
            "zombie_detection_accuracy": 0.0,
            "training_runs": len(self._training_history),
            "last_trained_at": (
                self._training_history[-1]["trained_at"].isoformat()
                if self._training_history
                else None
            ),
        }

    async def list_all_endpoint_ids(self) -> list[str]:
        return list(self._endpoints.keys())

    async def get_background_states(self, limit: int = 50) -> list[dict]:
        states = list(self._agent_states.values())
        return [s["state_vector"] for s in states[:limit]]


# ---------------------------------------------------------------------------
# PostgreSQL store
# ---------------------------------------------------------------------------


class RLDatabaseManager:
    """Async PostgreSQL store for the RL Intelligence Service."""

    def __init__(self, database_url: Optional[str] = None) -> None:
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://sentinel:sentinel_secret@postgres:5432/sentinelapi",
        )
        self._engine: Optional[Any] = None

    async def connect(self) -> None:
        from sqlalchemy.ext.asyncio import create_async_engine
        try:
            self._engine = create_async_engine(
                self.database_url,
                echo=False,
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=20,
            )
            logger.info("rl_db_connected", url=self.database_url.split("@")[-1])
        except Exception as exc:
            logger.warning("rl_db_connection_failed", error=str(exc))
            self._engine = None

    async def disconnect(self) -> None:
        if self._engine:
            await self._engine.dispose()

    def _require_engine(self) -> Any:
        if not self._engine:
            raise RuntimeError("RL database not connected")
        return self._engine

    # ------------------------------------------------------------------
    # Endpoint reads (read from api_endpoints table)
    # ------------------------------------------------------------------

    async def get_endpoint(self, endpoint_id: str) -> Optional[dict]:
        from sqlalchemy import text
        engine = self._require_engine()
        q = text("""
            SELECT id, auth_scheme, data_sensitivity, lifecycle_status,
                   risk_score, request_count_24h, owning_team, source_file_id,
                   last_access_at, metadata
            FROM api_endpoints
            WHERE id = :id
        """)
        async with engine.connect() as conn:
            r = await conn.execute(q, {"id": endpoint_id})
            row = r.fetchone()
            if not row:
                return None
            return {
                "id": str(row[0]),
                "auth_scheme": row[1],
                "data_sensitivity": row[2],
                "lifecycle_status": row[3],
                "risk_score": row[4],
                "request_count_24h": row[5],
                "owning_team": row[6],
                "source_file_id": row[7],
                "last_access_at": row[8].isoformat() if row[8] else None,
                "metadata": row[9] or {},
            }

    async def list_all_endpoint_ids(self) -> list[str]:
        from sqlalchemy import text
        engine = self._require_engine()
        q = text("SELECT id FROM api_endpoints ORDER BY id")
        async with engine.connect() as conn:
            r = await conn.execute(q)
            return [str(row[0]) for row in r.fetchall()]

    async def get_anomaly_alerts(self, endpoint_id: str, limit: int = 10) -> list[dict]:
        from sqlalchemy import text
        engine = self._require_engine()
        q = text("""
            SELECT id, anomaly_type, deviation_sigma, emitted_at
            FROM anomaly_alerts
            WHERE endpoint_id = :id
            ORDER BY emitted_at DESC
            LIMIT :limit
        """)
        async with engine.connect() as conn:
            r = await conn.execute(q, {"id": endpoint_id, "limit": limit})
            return [
                {"id": str(row[0]), "anomaly_type": row[1],
                 "deviation_sigma": row[2], "emitted_at": row[3].isoformat() if row[3] else None}
                for row in r.fetchall()
            ]

    async def get_feedback_stats(self, endpoint_id: str) -> dict:
        from sqlalchemy import text
        engine = self._require_engine()
        q = text("""
            SELECT feedback_type, COUNT(*) as cnt
            FROM analyst_feedback
            WHERE endpoint_id = :id
            GROUP BY feedback_type
        """)
        async with engine.connect() as conn:
            r = await conn.execute(q, {"id": endpoint_id})
            rows = r.fetchall()

        counts: dict[str, int] = {}
        for row in rows:
            counts[row[0]] = int(row[1])

        total = sum(counts.values())
        if total == 0:
            return {
                "analyst_agreement_rate": 0.5,
                "remediation_success_rate": 0.5,
                "false_positive_rate": 0.1,
                "historical_incident_rate": 0.0,
            }

        agreements = counts.get("alert_ack", 0) + counts.get("remediation_approved", 0)
        fps = counts.get("alert_reject", 0)
        overrides = counts.get("classification_override", 0)

        return {
            "analyst_agreement_rate": agreements / total,
            "remediation_success_rate": counts.get("remediation_approved", 0) / max(
                counts.get("remediation_approved", 0) + counts.get("remediation_rejected", 0), 1
            ),
            "false_positive_rate": fps / total,
            "historical_incident_rate": total / 30.0,
        }

    # ------------------------------------------------------------------
    # RL State
    # ------------------------------------------------------------------

    async def upsert_agent_state(self, row: RLAgentStateRow) -> None:
        from sqlalchemy import text
        engine = self._require_engine()
        q = text("""
            INSERT INTO rl_agent_state
                (id, endpoint_id, state_vector, last_action, last_reward,
                 total_reward, episode_step, updated_at)
            VALUES
                (:id, :endpoint_id, :state_vector::jsonb, :last_action, :last_reward,
                 :total_reward, :episode_step, :updated_at)
            ON CONFLICT (endpoint_id) DO UPDATE SET
                state_vector = EXCLUDED.state_vector,
                last_action  = EXCLUDED.last_action,
                last_reward  = EXCLUDED.last_reward,
                total_reward = EXCLUDED.total_reward,
                episode_step = EXCLUDED.episode_step,
                updated_at   = EXCLUDED.updated_at
        """)
        async with engine.begin() as conn:
            await conn.execute(q, {
                "id": row.id,
                "endpoint_id": row.endpoint_id,
                "state_vector": json.dumps(row.state_vector),
                "last_action": row.last_action,
                "last_reward": row.last_reward,
                "total_reward": row.total_reward,
                "episode_step": row.episode_step,
                "updated_at": row.updated_at,
            })

    async def get_agent_state(self, endpoint_id: str) -> Optional[dict]:
        from sqlalchemy import text
        engine = self._require_engine()
        q = text("SELECT * FROM rl_agent_state WHERE endpoint_id = :id")
        async with engine.connect() as conn:
            r = await conn.execute(q, {"id": endpoint_id})
            row = r.fetchone()
            return dict(row._mapping) if row else None

    # ------------------------------------------------------------------
    # Training history
    # ------------------------------------------------------------------

    async def insert_training_history(self, row: RLTrainingHistoryRow) -> str:
        from sqlalchemy import text
        engine = self._require_engine()
        q = text("""
            INSERT INTO rl_training_history
                (id, policy_version, total_timesteps, mean_reward, std_reward,
                 entropy_loss, policy_loss, value_loss, explained_variance,
                 training_duration_seconds, trained_at)
            VALUES
                (:id, :policy_version, :total_timesteps, :mean_reward, :std_reward,
                 :entropy_loss, :policy_loss, :value_loss, :explained_variance,
                 :training_duration_seconds, :trained_at)
        """)
        async with engine.begin() as conn:
            await conn.execute(q, row.model_dump())
        return row.id

    # ------------------------------------------------------------------
    # Reward events
    # ------------------------------------------------------------------

    async def insert_reward_event(self, row: RLRewardEventRow) -> str:
        from sqlalchemy import text
        engine = self._require_engine()
        q = text("""
            INSERT INTO rl_reward_events
                (id, endpoint_id, event_type, reward_value, action_taken,
                 state_snapshot, source, occurred_at)
            VALUES
                (:id, :endpoint_id, :event_type, :reward_value, :action_taken,
                 :state_snapshot::jsonb, :source, :occurred_at)
        """)
        async with engine.begin() as conn:
            await conn.execute(q, {
                **row.model_dump(),
                "state_snapshot": json.dumps(row.state_snapshot),
            })
        return row.id

    # ------------------------------------------------------------------
    # Predictions
    # ------------------------------------------------------------------

    async def insert_prediction(self, row: RLPredictionRow) -> str:
        from sqlalchemy import text
        engine = self._require_engine()
        q = text("""
            INSERT INTO rl_predictions
                (id, endpoint_id, policy_version, action, action_confidence,
                 action_probabilities, rl_risk_adjustment, zombie_probability,
                 threat_probability, remediation_probability, shap_values,
                 top_features, rule_risk_score, ml_risk_contribution,
                 final_risk_score, predicted_at)
            VALUES
                (:id, :endpoint_id, :policy_version, :action, :action_confidence,
                 :action_probabilities::jsonb, :rl_risk_adjustment, :zombie_probability,
                 :threat_probability, :remediation_probability, :shap_values::jsonb,
                 :top_features::jsonb, :rule_risk_score, :ml_risk_contribution,
                 :final_risk_score, :predicted_at)
        """)
        async with engine.begin() as conn:
            await conn.execute(q, {
                **row.model_dump(),
                "action_probabilities": json.dumps(row.action_probabilities),
                "shap_values": json.dumps(row.shap_values),
                "top_features": json.dumps(row.top_features),
            })
        return row.id

    # ------------------------------------------------------------------
    # Policy versions
    # ------------------------------------------------------------------

    async def insert_policy_version(self, row: RLPolicyVersionRow) -> str:
        from sqlalchemy import text
        engine = self._require_engine()
        async with engine.begin() as conn:
            # Deactivate existing active versions
            await conn.execute(
                text("UPDATE rl_policy_versions SET is_active = FALSE WHERE is_active = TRUE")
            )
            q = text("""
                INSERT INTO rl_policy_versions
                    (id, version, artifact_path, mean_reward, is_active, promoted_at, created_at)
                VALUES
                    (:id, :version, :artifact_path, :mean_reward, :is_active, :promoted_at, :created_at)
            """)
            await conn.execute(q, row.model_dump())
        return row.id

    async def get_active_policy_version(self) -> int:
        from sqlalchemy import text
        engine = self._require_engine()
        q = text("SELECT version FROM rl_policy_versions WHERE is_active = TRUE ORDER BY version DESC LIMIT 1")
        async with engine.connect() as conn:
            r = await conn.execute(q)
            row = r.fetchone()
            return int(row[0]) if row else 0

    # ------------------------------------------------------------------
    # Analyst feedback
    # ------------------------------------------------------------------

    async def insert_analyst_feedback(self, row: AnalystFeedbackRow) -> str:
        from sqlalchemy import text
        engine = self._require_engine()
        q = text("""
            INSERT INTO analyst_feedback
                (id, endpoint_id, analyst_id, feedback_type, previous_value,
                 new_value, rl_prediction_id, reward_generated, notes, occurred_at)
            VALUES
                (:id, :endpoint_id, :analyst_id, :feedback_type, :previous_value,
                 :new_value, :rl_prediction_id, :reward_generated, :notes, :occurred_at)
        """)
        async with engine.begin() as conn:
            await conn.execute(q, row.model_dump())
        return row.id

    # ------------------------------------------------------------------
    # Replay buffer
    # ------------------------------------------------------------------

    async def get_replay_buffer(self, limit: int = 50_000) -> list[dict]:
        from sqlalchemy import text
        engine = self._require_engine()
        q = text("""
            SELECT endpoint_id, event_type, action_taken, state_snapshot, reward_value
            FROM rl_reward_events
            ORDER BY occurred_at DESC
            LIMIT :limit
        """)
        async with engine.connect() as conn:
            r = await conn.execute(q, {"limit": limit})
            return [
                {
                    "endpoint_id": str(row[0]),
                    "event_type": row[1],
                    "action": int(row[2]),
                    "state_vector": row[3] if isinstance(row[3], list) else json.loads(row[3]),
                    "reward_value": float(row[4]),
                    "next_state_vector": row[3] if isinstance(row[3], list) else json.loads(row[3]),
                }
                for row in r.fetchall()
            ]

    # ------------------------------------------------------------------
    # Policy metrics
    # ------------------------------------------------------------------

    async def get_policy_metrics(self) -> dict:
        from sqlalchemy import text
        engine = self._require_engine()
        async with engine.connect() as conn:
            # Total predictions
            r = await conn.execute(text("SELECT COUNT(*) FROM rl_predictions"))
            total_preds = int(r.scalar() or 0)

            # Mean reward last 100
            r = await conn.execute(text(
                "SELECT AVG(reward_value) FROM (SELECT reward_value FROM rl_reward_events "
                "ORDER BY occurred_at DESC LIMIT 100) t"
            ))
            mean_reward = float(r.scalar() or 0.0)

            # Analyst feedback counts
            r = await conn.execute(text("""
                SELECT feedback_type, COUNT(*) FROM analyst_feedback
                GROUP BY feedback_type
            """))
            fcounts: dict[str, int] = {row[0]: int(row[1]) for row in r.fetchall()}
            total_fb = sum(fcounts.values())

            agreements = fcounts.get("alert_ack", 0) + fcounts.get("remediation_approved", 0)
            fps = fcounts.get("alert_reject", 0)

            # Training runs
            r = await conn.execute(text("SELECT COUNT(*), MAX(trained_at) FROM rl_training_history"))
            row = r.fetchone()
            training_runs = int(row[0] or 0)
            last_trained = row[1].isoformat() if row[1] else None

        active_version = await self.get_active_policy_version()

        return {
            "active_policy_version": active_version,
            "total_predictions": total_preds,
            "mean_reward_last_100": mean_reward,
            "analyst_agreement_rate": agreements / max(total_fb, 1),
            "false_positive_rate": fps / max(total_fb, 1),
            "false_negative_rate": 0.0,
            "zombie_detection_accuracy": 0.0,
            "training_runs": training_runs,
            "last_trained_at": last_trained,
        }

    async def get_background_states(self, limit: int = 50) -> list[dict]:
        from sqlalchemy import text
        engine = self._require_engine()
        q = text("""
            SELECT state_vector FROM rl_agent_state
            ORDER BY updated_at DESC
            LIMIT :limit
        """)
        async with engine.connect() as conn:
            r = await conn.execute(q, {"limit": limit})
            result = []
            for row in r.fetchall():
                sv = row[0]
                if isinstance(sv, list):
                    result.append(sv)
                else:
                    try:
                        result.append(json.loads(sv))
                    except Exception:
                        pass
            return result
