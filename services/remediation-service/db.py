"""
Database layer for the Remediation Service.

Provides:
- InMemoryRemediationStore: in-memory store for unit tests (no live DB).
- RemediationDatabaseManager: async PostgreSQL store for production.

Both implement the same interface so the service layer can swap them.
"""

import os
import uuid
from datetime import datetime, timezone
from typing import Optional, Any

import structlog

from sentinel_shared.models import RemediationRecommendation

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# In-memory store (for unit tests)
# ---------------------------------------------------------------------------


class InMemoryRemediationStore:
    """
    In-memory store for remediation data.

    Stores endpoint records and remediation recommendations in plain dicts —
    no live database required.
    """

    def __init__(self) -> None:
        # endpoint_id -> dict with endpoint fields
        self._endpoints: dict[str, dict] = {}
        # rec_id -> dict with recommendation fields
        self._recommendations: dict[str, dict] = {}

    def clear(self) -> None:
        """Reset all state (useful between tests)."""
        self._endpoints.clear()
        self._recommendations.clear()

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
            "has_traffic_anomaly": False,
            "tls_enabled": True,
            "p95_hourly_rate": None,
            "regulatory_standard": "PCI-DSS",
            **kwargs,
        }

    async def get_endpoint(self, endpoint_id: str) -> Optional[dict]:
        """Return the endpoint dict or None."""
        entry = self._endpoints.get(endpoint_id)
        return dict(entry) if entry else None

    async def list_all_endpoint_ids(self) -> list[str]:
        """Return all endpoint IDs."""
        return list(self._endpoints.keys())

    # ------------------------------------------------------------------
    # Recommendations
    # ------------------------------------------------------------------

    async def insert_recommendation(self, rec: RemediationRecommendation) -> str:
        """
        Insert a remediation recommendation.

        Returns the new record's ID.
        """
        rec_id = rec.id
        self._recommendations[rec_id] = {
            "id": rec_id,
            "endpoint_id": rec.endpoint_id,
            "priority": rec.priority,
            "trigger_rule": rec.trigger_rule,
            "summary_text": rec.summary_text,
            "detail_json": rec.detail_json,
            "resolved_by": None,
            "resolved_at": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        return rec_id

    async def get_recommendations(self, endpoint_id: str) -> list[dict]:
        """Return all recommendations for an endpoint."""
        return [
            dict(r)
            for r in self._recommendations.values()
            if r["endpoint_id"] == endpoint_id
        ]

    async def list_recommendations(
        self, cursor: Optional[str] = None, limit: int = 50
    ) -> dict:
        """
        Return a paginated list of all recommendations.

        Args:
            cursor: Opaque cursor from a previous response (recommendation ID).
            limit: Maximum number of items to return.

        Returns:
            A dict with ``items`` (list of recommendation dicts) and
            ``next_cursor`` (str or None).
        """
        # Sort by created_at for stable pagination
        all_recs = sorted(
            self._recommendations.values(),
            key=lambda r: r["created_at"],
        )

        # Apply cursor (skip items up to and including the cursor ID)
        if cursor:
            start_idx = 0
            for i, rec in enumerate(all_recs):
                if rec["id"] == cursor:
                    start_idx = i + 1
                    break
            all_recs = all_recs[start_idx:]

        page = all_recs[:limit]
        next_cursor = page[-1]["id"] if len(all_recs) > limit else None

        return {
            "items": [dict(r) for r in page],
            "next_cursor": next_cursor,
        }

    async def resolve_recommendation(
        self, rec_id: str, resolved_by: str
    ) -> Optional[dict]:
        """
        Mark a recommendation as resolved.

        Sets resolved_by and resolved_at on the record.

        Returns:
            The updated record dict, or None if not found.
        """
        rec = self._recommendations.get(rec_id)
        if rec is None:
            return None

        now = datetime.now(timezone.utc).isoformat()
        rec["resolved_by"] = resolved_by
        rec["resolved_at"] = now
        rec["updated_at"] = now
        return dict(rec)


# ---------------------------------------------------------------------------
# PostgreSQL store (for production)
# ---------------------------------------------------------------------------


class RemediationDatabaseManager:
    """Manages async PostgreSQL connections for the remediation service."""

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
            metadata = row[5] or {}
            return {
                "id": str(row[0]),
                "auth_scheme": row[1],
                "data_sensitivity": row[2],
                "lifecycle_status": row[3],
                "risk_score": row[4],
                "has_traffic_anomaly": metadata.get("has_traffic_anomaly", False),
                "tls_enabled": metadata.get("tls_enabled", True),
                "p95_hourly_rate": metadata.get("p95_hourly_rate"),
                "regulatory_standard": metadata.get("regulatory_standard", "PCI-DSS"),
                "metadata": metadata,
            }

    async def list_all_endpoint_ids(self) -> list[str]:
        if not self._engine:
            raise RuntimeError("Database not connected")
        from sqlalchemy import text

        query = text("SELECT id FROM api_endpoints ORDER BY id")
        async with self._engine.connect() as conn:
            result = await conn.execute(query)
            return [str(row[0]) for row in result.fetchall()]

    async def insert_recommendation(self, rec: RemediationRecommendation) -> str:
        """
        Persist a remediation recommendation to remediation_recommendations.

        Returns the new record's ID.
        """
        if not self._engine:
            raise RuntimeError("Database not connected")
        import json
        from sqlalchemy import text

        rec_id = rec.id
        detail_json_str = json.dumps(rec.detail_json)

        async with self._engine.begin() as conn:
            insert_query = text("""
                INSERT INTO remediation_recommendations
                    (id, endpoint_id, priority, trigger_rule, summary_text, detail_json)
                VALUES
                    (:id, :endpoint_id, :priority, :trigger_rule,
                     :summary_text, :detail_json::jsonb)
            """)
            await conn.execute(
                insert_query,
                {
                    "id": rec_id,
                    "endpoint_id": rec.endpoint_id,
                    "priority": rec.priority,
                    "trigger_rule": rec.trigger_rule,
                    "summary_text": rec.summary_text,
                    "detail_json": detail_json_str,
                },
            )

        return rec_id

    async def get_recommendations(self, endpoint_id: str) -> list[dict]:
        if not self._engine:
            raise RuntimeError("Database not connected")
        from sqlalchemy import text

        query = text("""
            SELECT id, endpoint_id, priority, trigger_rule, summary_text,
                   detail_json, resolved_by, resolved_at, created_at, updated_at
            FROM remediation_recommendations
            WHERE endpoint_id = :endpoint_id
            ORDER BY created_at DESC
        """)
        async with self._engine.connect() as conn:
            result = await conn.execute(query, {"endpoint_id": endpoint_id})
            return [
                {
                    "id": str(row[0]),
                    "endpoint_id": str(row[1]),
                    "priority": row[2],
                    "trigger_rule": row[3],
                    "summary_text": row[4],
                    "detail_json": row[5],
                    "resolved_by": row[6],
                    "resolved_at": row[7].isoformat() if row[7] else None,
                    "created_at": row[8].isoformat() if row[8] else None,
                    "updated_at": row[9].isoformat() if row[9] else None,
                }
                for row in result.fetchall()
            ]

    async def list_recommendations(
        self, cursor: Optional[str] = None, limit: int = 50
    ) -> dict:
        if not self._engine:
            raise RuntimeError("Database not connected")
        from sqlalchemy import text

        if cursor:
            query = text("""
                SELECT id, endpoint_id, priority, trigger_rule, summary_text,
                       detail_json, resolved_by, resolved_at, created_at, updated_at
                FROM remediation_recommendations
                WHERE created_at > (
                    SELECT created_at FROM remediation_recommendations WHERE id = :cursor
                )
                ORDER BY created_at ASC
                LIMIT :limit
            """)
            params: dict = {"cursor": cursor, "limit": limit + 1}
        else:
            query = text("""
                SELECT id, endpoint_id, priority, trigger_rule, summary_text,
                       detail_json, resolved_by, resolved_at, created_at, updated_at
                FROM remediation_recommendations
                ORDER BY created_at ASC
                LIMIT :limit
            """)
            params = {"limit": limit + 1}

        async with self._engine.connect() as conn:
            result = await conn.execute(query, params)
            rows = result.fetchall()

        items = [
            {
                "id": str(row[0]),
                "endpoint_id": str(row[1]),
                "priority": row[2],
                "trigger_rule": row[3],
                "summary_text": row[4],
                "detail_json": row[5],
                "resolved_by": row[6],
                "resolved_at": row[7].isoformat() if row[7] else None,
                "created_at": row[8].isoformat() if row[8] else None,
                "updated_at": row[9].isoformat() if row[9] else None,
            }
            for row in rows[: limit]
        ]
        next_cursor = items[-1]["id"] if len(rows) > limit else None

        return {"items": items, "next_cursor": next_cursor}

    async def resolve_recommendation(
        self, rec_id: str, resolved_by: str
    ) -> Optional[dict]:
        if not self._engine:
            raise RuntimeError("Database not connected")
        from sqlalchemy import text

        query = text("""
            UPDATE remediation_recommendations
            SET resolved_by = :resolved_by,
                resolved_at = NOW(),
                updated_at  = NOW()
            WHERE id = :rec_id
            RETURNING id, endpoint_id, priority, trigger_rule, summary_text,
                      detail_json, resolved_by, resolved_at, created_at, updated_at
        """)
        async with self._engine.begin() as conn:
            result = await conn.execute(
                query, {"rec_id": rec_id, "resolved_by": resolved_by}
            )
            row = result.fetchone()
            if not row:
                return None
            return {
                "id": str(row[0]),
                "endpoint_id": str(row[1]),
                "priority": row[2],
                "trigger_rule": row[3],
                "summary_text": row[4],
                "detail_json": row[5],
                "resolved_by": row[6],
                "resolved_at": row[7].isoformat() if row[7] else None,
                "created_at": row[8].isoformat() if row[8] else None,
                "updated_at": row[9].isoformat() if row[9] else None,
            }
