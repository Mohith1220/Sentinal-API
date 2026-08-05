"""
Database layer for the Risk Scorer Service.

Provides:
- InMemoryRiskScorerStore: in-memory store for unit tests (no live DB).
- RiskScorerDatabaseManager: async PostgreSQL store for production.

Both implement the same interface so the service layer can swap them.
"""

import os
import uuid
from datetime import datetime, timezone
from typing import Optional, Any

import structlog

from sentinel_shared.models import RiskScoreResult

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# In-memory store (for unit tests)
# ---------------------------------------------------------------------------


class InMemoryRiskScorerStore:
    """
    In-memory store for risk scoring data.

    Stores endpoint records and risk score history in plain dicts —
    no live database required.
    """

    def __init__(self) -> None:
        # endpoint_id -> dict with endpoint fields
        self._endpoints: dict[str, dict] = {}
        # list of risk score history dicts
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
            "auth_scheme": "unknown",
            "data_sensitivity": "internal",
            "lifecycle_status": "Active",
            "risk_score": 0,
            "is_traffic_abnormal": None,
            "traffic_current": None,
            "traffic_mean": None,
            "traffic_stddev": None,
            **kwargs,
        }

    async def get_endpoint(self, endpoint_id: str) -> Optional[dict]:
        """Return the endpoint dict or None."""
        entry = self._endpoints.get(endpoint_id)
        return dict(entry) if entry else None

    async def update_risk_score(self, endpoint_id: str, score: int) -> bool:
        """
        Update the risk_score of an endpoint.

        Returns True if the endpoint was found and updated, False otherwise.
        """
        entry = self._endpoints.get(endpoint_id)
        if entry is None:
            return False
        entry["risk_score"] = score
        return True

    async def list_all_endpoint_ids(self) -> list[str]:
        """Return all endpoint IDs."""
        return list(self._endpoints.keys())

    # ------------------------------------------------------------------
    # Risk score history
    # ------------------------------------------------------------------

    async def insert_risk_score_history(self, result: RiskScoreResult) -> str:
        """
        Insert a risk score history record.

        Returns the new record's ID.
        """
        record_id = str(uuid.uuid4())
        self._history.append(
            {
                "id": record_id,
                "endpoint_id": result.endpoint_id,
                "score": result.score,
                "factors": [f.model_dump() for f in result.factors],
                "computed_at": result.computed_at.isoformat(),
            }
        )
        return record_id

    async def get_risk_score_history(
        self, endpoint_id: str, limit: int = 50
    ) -> list[dict]:
        """Return risk score history for an endpoint, newest first."""
        records = [r for r in self._history if r["endpoint_id"] == endpoint_id]
        records.sort(key=lambda r: r["computed_at"], reverse=True)
        return records[:limit]


# ---------------------------------------------------------------------------
# PostgreSQL store (for production)
# ---------------------------------------------------------------------------


class RiskScorerDatabaseManager:
    """Manages async PostgreSQL connections for the risk scorer service."""

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
            SELECT id, auth_scheme, data_sensitivity, lifecycle_status,
                   risk_score, metadata
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
                "auth_scheme": row[1],
                "data_sensitivity": row[2],
                "lifecycle_status": row[3],
                "risk_score": row[4],
                "metadata": row[5] or {},
            }

    async def update_risk_score(self, endpoint_id: str, score: int) -> bool:
        """Atomically update api_endpoints.risk_score."""
        if not self._engine:
            raise RuntimeError("Database not connected")
        from sqlalchemy import text

        query = text("""
            UPDATE api_endpoints
            SET risk_score = :score, updated_at = NOW()
            WHERE id = :endpoint_id
        """)
        async with self._engine.begin() as conn:
            result = await conn.execute(
                query,
                {"endpoint_id": endpoint_id, "score": score},
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

    async def insert_risk_score_history(self, result: RiskScoreResult) -> str:
        """
        Persist a risk score computation to risk_score_history and
        atomically update api_endpoints.risk_score.
        """
        if not self._engine:
            raise RuntimeError("Database not connected")
        import json
        from sqlalchemy import text

        record_id = str(uuid.uuid4())
        factors_json = json.dumps([f.model_dump() for f in result.factors])

        async with self._engine.begin() as conn:
            # Insert history record
            insert_query = text("""
                INSERT INTO risk_score_history
                    (id, endpoint_id, score, factors, computed_at)
                VALUES
                    (:id, :endpoint_id, :score, :factors::jsonb, :computed_at)
            """)
            await conn.execute(
                insert_query,
                {
                    "id": record_id,
                    "endpoint_id": result.endpoint_id,
                    "score": result.score,
                    "factors": factors_json,
                    "computed_at": result.computed_at,
                },
            )

            # Atomically update the endpoint's risk_score
            update_query = text("""
                UPDATE api_endpoints
                SET risk_score = :score, updated_at = NOW()
                WHERE id = :endpoint_id
            """)
            await conn.execute(
                update_query,
                {"endpoint_id": result.endpoint_id, "score": result.score},
            )

        return record_id

    async def get_risk_score_history(
        self, endpoint_id: str, limit: int = 50
    ) -> list[dict]:
        if not self._engine:
            raise RuntimeError("Database not connected")
        from sqlalchemy import text

        query = text("""
            SELECT id, endpoint_id, score, factors, computed_at
            FROM risk_score_history
            WHERE endpoint_id = :endpoint_id
            ORDER BY computed_at DESC
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
                    "score": row[2],
                    "factors": row[3],
                    "computed_at": row[4].isoformat() if row[4] else None,
                }
                for row in result.fetchall()
            ]
