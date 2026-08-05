"""
Database manager for the API Gateway.

Handles audit log persistence to PostgreSQL.
"""

import os
import uuid
import json
from typing import Optional, Any

import structlog

from audit import AuditLogEntry

logger = structlog.get_logger(__name__)


class GatewayDatabaseManager:
    """
    Manages async PostgreSQL connections for the API Gateway service.

    Provides audit log write operations.
    """

    def __init__(self, database_url: Optional[str] = None) -> None:
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://sentinel:sentinel@localhost:5432/sentinel",
        )
        self._engine: Optional[Any] = None

    async def connect(self) -> None:
        """Establish the async database connection pool."""
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
        """Close the database connection pool."""
        if self._engine:
            await self._engine.dispose()
            logger.info("db_disconnected")

    async def write_audit_log(self, entry: AuditLogEntry) -> str:
        """
        Insert an audit log entry into the audit_log table.

        Args:
            entry: The AuditLogEntry to persist.

        Returns:
            The generated UUID for the new audit log row.

        Raises:
            RuntimeError: If the database is not connected.
        """
        if not self._engine:
            raise RuntimeError("Database not connected")

        from sqlalchemy import text

        record_id = str(uuid.uuid4())
        payload_json = json.dumps(entry.payload)

        query = text("""
            INSERT INTO audit_log
                (id, actor_identity, action_type, resource_type, resource_id,
                 payload, occurred_at)
            VALUES
                (:id, :actor_identity, :action_type, :resource_type, :resource_id,
                 :payload::jsonb, :occurred_at)
        """)

        async with self._engine.begin() as conn:
            await conn.execute(
                query,
                {
                    "id": record_id,
                    "actor_identity": entry.actor_identity,
                    "action_type": entry.action_type,
                    "resource_type": entry.resource_type,
                    "resource_id": entry.resource_id,
                    "payload": payload_json,
                    "occurred_at": entry.occurred_at,
                },
            )

        return record_id
