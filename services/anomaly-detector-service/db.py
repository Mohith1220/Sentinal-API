"""
Database layer for the Anomaly Detector Service.

Provides:
- InMemoryAnomalyStore: in-memory store for unit tests (no live DB).
- AnomalyDatabaseManager: async PostgreSQL store for production.

Both implement the same interface so the service layer can swap them.
"""

import os
import uuid
from datetime import datetime, timezone
from typing import Optional, Any

import structlog

from sentinel_shared.models import AnomalyAlert

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# In-memory store (for unit tests)
# ---------------------------------------------------------------------------


class InMemoryAnomalyStore:
    """
    In-memory store for anomaly detection data.

    Stores endpoint records, baselines, and anomaly alerts in plain dicts —
    no live database required.
    """

    def __init__(self) -> None:
        # endpoint_id -> dict with endpoint fields
        self._endpoints: dict[str, dict] = {}
        # baseline_id -> dict with baseline fields
        self._baselines: list[dict] = []
        # list of anomaly alert dicts
        self._alerts: list[dict] = []

    def clear(self) -> None:
        """Reset all state (useful between tests)."""
        self._endpoints.clear()
        self._baselines.clear()
        self._alerts.clear()

    async def connect(self) -> None:
        """No-op."""

    async def disconnect(self) -> None:
        """No-op."""

    # ------------------------------------------------------------------
    # Endpoint helpers
    # ------------------------------------------------------------------

    def seed_endpoint(self, endpoint_id: str, **kwargs: Any) -> None:
        """Seed an endpoint record for testing."""
        self._endpoints[endpoint_id] = {
            "id": endpoint_id,
            "lifecycle_status": "Active",
            "data_sensitivity": "internal",
            "last_access_at": None,
            "metadata": {},
            **kwargs,
        }

    async def get_endpoint(self, endpoint_id: str) -> Optional[dict]:
        """Return the endpoint dict or None."""
        entry = self._endpoints.get(endpoint_id)
        return dict(entry) if entry else None

    # ------------------------------------------------------------------
    # Baseline helpers
    # ------------------------------------------------------------------

    def seed_baseline(
        self,
        endpoint_id: Optional[str],
        cluster_key: Optional[str],
        model_artifact: bytes,
        training_days: int,
        **kwargs: Any,
    ) -> str:
        """Seed a baseline record for testing. Returns the baseline ID."""
        baseline_id = str(uuid.uuid4())
        self._baselines.append(
            {
                "id": baseline_id,
                "endpoint_id": endpoint_id,
                "cluster_key": cluster_key,
                "model_artifact": model_artifact,
                "training_days": training_days,
                "trained_at": datetime.now(timezone.utc).isoformat(),
                **kwargs,
            }
        )
        return baseline_id

    async def get_baseline(self, endpoint_id: str) -> Optional[dict]:
        """
        Return the most recent individual baseline for an endpoint, or None.
        """
        candidates = [
            b for b in self._baselines if b.get("endpoint_id") == endpoint_id
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda b: b["trained_at"])

    async def get_cluster_baseline(self, cluster_key: str) -> Optional[dict]:
        """
        Return the most recent cluster baseline for a given cluster key, or None.
        """
        candidates = [
            b
            for b in self._baselines
            if b.get("cluster_key") == cluster_key and b.get("endpoint_id") is None
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda b: b["trained_at"])

    async def upsert_baseline(
        self,
        endpoint_id: Optional[str],
        cluster_key: Optional[str],
        model_artifact: bytes,
        training_days: int,
    ) -> str:
        """Insert or update a baseline record. Returns the baseline ID."""
        # Remove existing baseline for this endpoint/cluster
        self._baselines = [
            b
            for b in self._baselines
            if not (
                b.get("endpoint_id") == endpoint_id
                and b.get("cluster_key") == cluster_key
            )
        ]
        return self.seed_baseline(
            endpoint_id=endpoint_id,
            cluster_key=cluster_key,
            model_artifact=model_artifact,
            training_days=training_days,
        )

    # ------------------------------------------------------------------
    # Alert helpers
    # ------------------------------------------------------------------

    async def insert_alert(self, alert: AnomalyAlert) -> str:
        """Persist an anomaly alert. Returns the alert ID."""
        self._alerts.append(
            {
                "id": alert.id,
                "endpoint_id": alert.endpoint_id,
                "anomaly_type": alert.anomaly_type,
                "observed_value": alert.observed_value,
                "baseline_value": alert.baseline_value,
                "deviation_sigma": alert.deviation_sigma,
                "feature_importance": list(alert.feature_importance),
                "emitted_at": alert.emitted_at.isoformat(),
                "resolved_at": None,
            }
        )
        return alert.id

    async def list_alerts(
        self,
        endpoint_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Return alerts, optionally filtered by endpoint_id, newest first."""
        records = self._alerts
        if endpoint_id:
            records = [r for r in records if r["endpoint_id"] == endpoint_id]
        records = sorted(records, key=lambda r: r["emitted_at"], reverse=True)
        return records[:limit]


# ---------------------------------------------------------------------------
# PostgreSQL store (for production)
# ---------------------------------------------------------------------------


class AnomalyDatabaseManager:
    """Manages async PostgreSQL connections for the anomaly detector service."""

    def __init__(self, database_url: Optional[str] = None) -> None:
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://sentinel:sentinel@localhost:5432/sentinel",
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
            logger.info("db_connected", url=self.database_url.split("@")[-1])
        except Exception as exc:
            logger.warning("db_connection_failed", error=str(exc))
            self._engine = None

    async def disconnect(self) -> None:
        if self._engine:
            await self._engine.dispose()
            logger.info("db_disconnected")

    async def get_endpoint(self, endpoint_id: str) -> Optional[dict]:
        if not self._engine:
            raise RuntimeError("Database not connected")
        from sqlalchemy import text

        query = text("""
            SELECT id, lifecycle_status, data_sensitivity, last_access_at, metadata
            FROM api_endpoints
            WHERE id = :endpoint_id
        """)
        async with self._engine.connect() as conn:
            result = await conn.execute(query, {"endpoint_id": endpoint_id})
            row = result.fetchone()
            if not row:
                return None
            return {
                "id": str(row[0]),
                "lifecycle_status": row[1],
                "data_sensitivity": row[2],
                "last_access_at": row[3].isoformat() if row[3] else None,
                "metadata": row[4] or {},
            }

    async def get_baseline(self, endpoint_id: str) -> Optional[dict]:
        if not self._engine:
            raise RuntimeError("Database not connected")
        from sqlalchemy import text

        query = text("""
            SELECT id, endpoint_id, cluster_key, model_artifact, trained_at, training_days
            FROM anomaly_baselines
            WHERE endpoint_id = :endpoint_id
            ORDER BY trained_at DESC
            LIMIT 1
        """)
        async with self._engine.connect() as conn:
            result = await conn.execute(query, {"endpoint_id": endpoint_id})
            row = result.fetchone()
            if not row:
                return None
            return {
                "id": str(row[0]),
                "endpoint_id": str(row[1]) if row[1] else None,
                "cluster_key": row[2],
                "model_artifact": bytes(row[3]) if row[3] else b"",
                "trained_at": row[4].isoformat() if row[4] else None,
                "training_days": row[5],
            }

    async def get_cluster_baseline(self, cluster_key: str) -> Optional[dict]:
        if not self._engine:
            raise RuntimeError("Database not connected")
        from sqlalchemy import text

        query = text("""
            SELECT id, endpoint_id, cluster_key, model_artifact, trained_at, training_days
            FROM anomaly_baselines
            WHERE cluster_key = :cluster_key AND endpoint_id IS NULL
            ORDER BY trained_at DESC
            LIMIT 1
        """)
        async with self._engine.connect() as conn:
            result = await conn.execute(query, {"cluster_key": cluster_key})
            row = result.fetchone()
            if not row:
                return None
            return {
                "id": str(row[0]),
                "endpoint_id": None,
                "cluster_key": row[2],
                "model_artifact": bytes(row[3]) if row[3] else b"",
                "trained_at": row[4].isoformat() if row[4] else None,
                "training_days": row[5],
            }

    async def upsert_baseline(
        self,
        endpoint_id: Optional[str],
        cluster_key: Optional[str],
        model_artifact: bytes,
        training_days: int,
    ) -> str:
        if not self._engine:
            raise RuntimeError("Database not connected")
        import json
        from sqlalchemy import text

        record_id = str(uuid.uuid4())
        query = text("""
            INSERT INTO anomaly_baselines
                (id, endpoint_id, cluster_key, model_artifact, trained_at, training_days)
            VALUES
                (:id, :endpoint_id, :cluster_key, :model_artifact, NOW(), :training_days)
            ON CONFLICT (endpoint_id, cluster_key)
            DO UPDATE SET
                model_artifact = EXCLUDED.model_artifact,
                trained_at = NOW(),
                training_days = EXCLUDED.training_days
        """)
        async with self._engine.begin() as conn:
            await conn.execute(
                query,
                {
                    "id": record_id,
                    "endpoint_id": endpoint_id,
                    "cluster_key": cluster_key,
                    "model_artifact": model_artifact,
                    "training_days": training_days,
                },
            )
        return record_id

    async def insert_alert(self, alert: AnomalyAlert) -> str:
        if not self._engine:
            raise RuntimeError("Database not connected")
        import json
        from sqlalchemy import text

        feature_importance_json = json.dumps(list(alert.feature_importance))
        query = text("""
            INSERT INTO anomaly_alerts
                (id, endpoint_id, anomaly_type, observed_value, baseline_value,
                 deviation_sigma, feature_importance, emitted_at)
            VALUES
                (:id, :endpoint_id, :anomaly_type, :observed_value, :baseline_value,
                 :deviation_sigma, :feature_importance::jsonb, :emitted_at)
        """)
        async with self._engine.begin() as conn:
            await conn.execute(
                query,
                {
                    "id": alert.id,
                    "endpoint_id": alert.endpoint_id,
                    "anomaly_type": alert.anomaly_type,
                    "observed_value": alert.observed_value,
                    "baseline_value": alert.baseline_value,
                    "deviation_sigma": alert.deviation_sigma,
                    "feature_importance": feature_importance_json,
                    "emitted_at": alert.emitted_at,
                },
            )
        return alert.id

    async def list_alerts(
        self,
        endpoint_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        if not self._engine:
            raise RuntimeError("Database not connected")
        from sqlalchemy import text

        if endpoint_id:
            query = text("""
                SELECT id, endpoint_id, anomaly_type, observed_value, baseline_value,
                       deviation_sigma, feature_importance, emitted_at, resolved_at
                FROM anomaly_alerts
                WHERE endpoint_id = :endpoint_id
                ORDER BY emitted_at DESC
                LIMIT :limit
            """)
            params = {"endpoint_id": endpoint_id, "limit": limit}
        else:
            query = text("""
                SELECT id, endpoint_id, anomaly_type, observed_value, baseline_value,
                       deviation_sigma, feature_importance, emitted_at, resolved_at
                FROM anomaly_alerts
                ORDER BY emitted_at DESC
                LIMIT :limit
            """)
            params = {"limit": limit}

        async with self._engine.connect() as conn:
            result = await conn.execute(query, params)
            return [
                {
                    "id": str(row[0]),
                    "endpoint_id": str(row[1]),
                    "anomaly_type": row[2],
                    "observed_value": row[3],
                    "baseline_value": row[4],
                    "deviation_sigma": row[5],
                    "feature_importance": row[6],
                    "emitted_at": row[7].isoformat() if row[7] else None,
                    "resolved_at": row[8].isoformat() if row[8] else None,
                }
                for row in result.fetchall()
            ]
