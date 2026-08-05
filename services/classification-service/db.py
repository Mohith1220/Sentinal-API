"""
Database layer for the Classification Service.

Provides:
- InMemoryClassificationStore: in-memory store for unit tests (no live DB).
- ClassificationDatabaseManager: async PostgreSQL store for production.

Both implement the same interface so the service layer can swap them.
"""

import os
import uuid
from datetime import datetime, timezone
from typing import Optional, Any

import structlog

from sentinel_shared.models import LifecycleStatus

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# In-memory store (for unit tests)
# ---------------------------------------------------------------------------


class InMemoryClassificationStore:
    """
    In-memory store for classification data.

    Stores endpoint lifecycle statuses and classification history records
    in plain dicts — no live database required.
    """

    def __init__(self) -> None:
        # endpoint_id -> dict with at least "lifecycle_status", "owning_team", etc.
        self._endpoints: dict[str, dict] = {}
        # list of classification history dicts
        self._history: list[dict] = []

    def clear(self) -> None:
        """Reset all state (useful between tests)."""
        self._endpoints.clear()
        self._history.clear()

    async def connect(self) -> None:
        """No-op."""

    async def disconnect(self) -> None:
        """No-op."""

    # ------------------------------------------------------------------
    # Endpoint helpers
    # ------------------------------------------------------------------

    def seed_endpoint(self, endpoint_id: str, **kwargs: Any) -> None:
        """
        Seed an endpoint record for testing.

        Accepts any keyword arguments that map to endpoint fields.
        """
        self._endpoints[endpoint_id] = {
            "id": endpoint_id,
            "lifecycle_status": LifecycleStatus.ACTIVE.value,
            "owning_team": None,
            "last_access_at": None,
            "spec_presence": True,
            "deprecated_flag": False,
            "traffic_recency_days": None,
            "traffic_trend": 0.0,
            **kwargs,
        }

    async def get_endpoint(self, endpoint_id: str) -> Optional[dict]:
        """Return the endpoint dict or None."""
        entry = self._endpoints.get(endpoint_id)
        return dict(entry) if entry else None

    async def update_lifecycle_status(
        self, endpoint_id: str, status: LifecycleStatus
    ) -> bool:
        """
        Update the lifecycle_status of an endpoint.

        Returns True if the endpoint was found and updated, False otherwise.
        """
        entry = self._endpoints.get(endpoint_id)
        if entry is None:
            return False
        entry["lifecycle_status"] = status.value
        return True

    async def list_all_endpoint_ids(self) -> list[str]:
        """Return all endpoint IDs (for batch re-classification)."""
        return list(self._endpoints.keys())

    # ------------------------------------------------------------------
    # Classification history
    # ------------------------------------------------------------------

    async def insert_classification_history(
        self,
        endpoint_id: str,
        rule_status: LifecycleStatus,
        ml_status: Optional[LifecycleStatus] = None,
        ml_confidence: Optional[float] = None,
        override_by: Optional[str] = None,
        override_reason: Optional[str] = None,
    ) -> str:
        """
        Insert a classification history record.

        Returns the new record's ID.
        """
        record_id = str(uuid.uuid4())
        self._history.append(
            {
                "id": record_id,
                "endpoint_id": endpoint_id,
                "rule_status": rule_status.value,
                "ml_status": ml_status.value if ml_status else None,
                "ml_confidence": ml_confidence,
                "override_by": override_by,
                "override_reason": override_reason,
                "classified_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return record_id

    async def get_classification_history(
        self, endpoint_id: str, limit: int = 50
    ) -> list[dict]:
        """Return classification history for an endpoint, newest first."""
        records = [r for r in self._history if r["endpoint_id"] == endpoint_id]
        records.sort(key=lambda r: r["classified_at"], reverse=True)
        return records[:limit]


# ---------------------------------------------------------------------------
# PostgreSQL store (for production)
# ---------------------------------------------------------------------------


class ClassificationDatabaseManager:
    """Manages async PostgreSQL connections for the classification service."""

    def __init__(self, database_url: Optional[str] = None) -> None:
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine

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
            SELECT id, lifecycle_status, owning_team, last_access_at,
                   metadata, source_file_id
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
                "owning_team": row[2],
                "last_access_at": row[3].isoformat() if row[3] else None,
                "metadata": row[4] or {},
                "source_file_id": row[5],
            }

    async def update_lifecycle_status(
        self, endpoint_id: str, status: LifecycleStatus
    ) -> bool:
        if not self._engine:
            raise RuntimeError("Database not connected")
        from sqlalchemy import text

        query = text("""
            UPDATE api_endpoints
            SET lifecycle_status = :status, updated_at = NOW()
            WHERE id = :endpoint_id
        """)
        async with self._engine.begin() as conn:
            result = await conn.execute(
                query,
                {"endpoint_id": endpoint_id, "status": status.value},
            )
            return result.rowcount > 0

    async def list_all_endpoint_ids(self) -> list[str]:
        if not self._engine:
            raise RuntimeError("Database not connected")
        from sqlalchemy import text

        query = text("SELECT id FROM api_endpoints ORDER BY id")
        async with self._engine.connect() as conn:
            result = await conn.execute(query)
            return [str(row[0]) for row in result.fetchall()]

    async def insert_classification_history(
        self,
        endpoint_id: str,
        rule_status: LifecycleStatus,
        ml_status: Optional[LifecycleStatus] = None,
        ml_confidence: Optional[float] = None,
        override_by: Optional[str] = None,
        override_reason: Optional[str] = None,
    ) -> str:
        if not self._engine:
            raise RuntimeError("Database not connected")
        from sqlalchemy import text

        record_id = str(uuid.uuid4())
        query = text("""
            INSERT INTO classification_history
                (id, endpoint_id, rule_status, ml_status, ml_confidence,
                 override_by, override_reason, classified_at)
            VALUES
                (:id, :endpoint_id, :rule_status, :ml_status, :ml_confidence,
                 :override_by, :override_reason, NOW())
        """)
        async with self._engine.begin() as conn:
            await conn.execute(
                query,
                {
                    "id": record_id,
                    "endpoint_id": endpoint_id,
                    "rule_status": rule_status.value,
                    "ml_status": ml_status.value if ml_status else None,
                    "ml_confidence": ml_confidence,
                    "override_by": override_by,
                    "override_reason": override_reason,
                },
            )
        return record_id

    async def get_classification_history(
        self, endpoint_id: str, limit: int = 50
    ) -> list[dict]:
        if not self._engine:
            raise RuntimeError("Database not connected")
        from sqlalchemy import text

        query = text("""
            SELECT id, endpoint_id, rule_status, ml_status, ml_confidence,
                   override_by, override_reason, classified_at
            FROM classification_history
            WHERE endpoint_id = :endpoint_id
            ORDER BY classified_at DESC
            LIMIT :limit
        """)
        async with self._engine.connect() as conn:
            result = await conn.execute(
                query, {"endpoint_id": endpoint_id, "limit": limit}
            )
            return [
                {
                    "id": str(row[0]),
                    "endpoint_id": str(row[1]),
                    "rule_status": row[2],
                    "ml_status": row[3],
                    "ml_confidence": row[4],
                    "override_by": row[5],
                    "override_reason": row[6],
                    "classified_at": row[7].isoformat() if row[7] else None,
                }
                for row in result.fetchall()
            ]
