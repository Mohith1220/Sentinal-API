"""
Database layer for Discovery Service.

Provides async PostgreSQL connection management and upsert logic for endpoint records.
Also provides an InMemoryStore for use in unit tests (no live DB required).
"""

import os
from typing import Optional, Any
from datetime import datetime, timezone

from sqlalchemy import create_engine, text, MetaData, Table, Column, String, Integer, Boolean, DateTime, JSON
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine, AsyncConnection
from sqlalchemy.dialects.postgresql import UUID, SMALLINT, BIGINT
import structlog

from sentinel_shared.models import EndpointRecord, AuthScheme, DataSensitivity, LifecycleStatus

logger = structlog.get_logger(__name__)


class InMemoryStore:
    """
    In-memory endpoint store for unit tests.

    Implements the same interface as DatabaseManager but uses a plain dict
    keyed on (http_method, host, normalized_path) — no live database required.
    """

    def __init__(self) -> None:
        # Maps dedup key -> endpoint dict
        self._store: dict[tuple[str, str, str], dict] = {}

    async def connect(self) -> None:
        """No-op — no connection needed."""

    async def disconnect(self) -> None:
        """No-op."""

    def clear(self) -> None:
        """Reset the store (useful between tests)."""
        self._store.clear()

    async def upsert_endpoint(self, record: EndpointRecord) -> tuple[str, bool]:
        """
        Upsert an endpoint record using the deduplication key
        (http_method, host, normalized_path).

        Returns:
            Tuple of (endpoint_id, was_inserted).
        """
        key = (record.http_method, record.host, record.normalized_path)
        existing = self._store.get(key)

        auth_value = record.auth_scheme.value if isinstance(record.auth_scheme, AuthScheme) else record.auth_scheme
        sensitivity_value = record.data_sensitivity.value if isinstance(record.data_sensitivity, DataSensitivity) else record.data_sensitivity
        lifecycle_value = record.lifecycle_status.value if isinstance(record.lifecycle_status, LifecycleStatus) else record.lifecycle_status

        if existing is None:
            # Insert
            entry = {
                "id": record.id,
                "http_method": record.http_method,
                "host": record.host,
                "path": record.normalized_path,
                "normalized_path": record.normalized_path,
                "auth_scheme": auth_value,
                "data_sensitivity": sensitivity_value,
                "lifecycle_status": lifecycle_value,
                "risk_score": record.risk_score,
                "request_count_24h": record.request_count_24h,
                "last_access_at": record.last_access_at.isoformat() if record.last_access_at else None,
                "first_seen_at": datetime.utcnow().isoformat(),
                "is_stale": False,
                "owning_team": record.owning_team,
                "source_file_id": record.source_file_id,
                "metadata": dict(record.metadata),
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }
            self._store[key] = entry
            return entry["id"], True
        else:
            # Update — merge metadata, prefer new non-null values
            existing["auth_scheme"] = auth_value
            existing["data_sensitivity"] = sensitivity_value
            existing["lifecycle_status"] = lifecycle_value
            if record.last_access_at is not None:
                existing["last_access_at"] = record.last_access_at.isoformat()
            if record.owning_team is not None:
                existing["owning_team"] = record.owning_team
            if record.source_file_id is not None:
                existing["source_file_id"] = record.source_file_id
            # Merge metadata (new values override old)
            existing["metadata"] = {**existing["metadata"], **record.metadata}
            existing["updated_at"] = datetime.utcnow().isoformat()
            return existing["id"], False

    async def get_endpoint(self, endpoint_id: str) -> Optional[dict]:
        """Retrieve a single endpoint by ID."""
        for entry in self._store.values():
            if entry["id"] == endpoint_id:
                return dict(entry)
        return None

    async def list_endpoints(
        self,
        limit: int = 100,
        offset: int = 0,
        lifecycle_status: Optional[str] = None,
        auth_scheme: Optional[str] = None,
        data_sensitivity: Optional[str] = None,
        risk_score_min: Optional[int] = None,
        risk_score_max: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> list[dict]:
        """
        List endpoints with optional filters and cursor-based pagination.

        Cursor is the ``id`` of the last record seen; results with id > cursor
        are returned (lexicographic UUID ordering).
        """
        results = list(self._store.values())

        if lifecycle_status:
            results = [r for r in results if r["lifecycle_status"] == lifecycle_status]
        if auth_scheme:
            results = [r for r in results if r["auth_scheme"] == auth_scheme]
        if data_sensitivity:
            results = [r for r in results if r["data_sensitivity"] == data_sensitivity]
        if risk_score_min is not None:
            results = [r for r in results if r["risk_score"] >= risk_score_min]
        if risk_score_max is not None:
            results = [r for r in results if r["risk_score"] <= risk_score_max]

        # Sort by id for stable cursor-based pagination
        results.sort(key=lambda r: r["id"])

        if cursor:
            results = [r for r in results if r["id"] > cursor]

        return [dict(r) for r in results[:limit]]

    async def increment_traffic_counters(
        self,
        endpoint_id: str,
        access_time: Optional[datetime] = None,
    ) -> Optional[dict]:
        """
        Atomically increment request_count_24h and update last_access_at.

        In the in-memory store this is a simple dict mutation.

        Args:
            endpoint_id: UUID of the endpoint to update.
            access_time: Timestamp of the traffic event; defaults to now.

        Returns:
            Updated endpoint dict, or None if not found.
        """
        if access_time is None:
            access_time = datetime.now(timezone.utc)

        for entry in self._store.values():
            if entry["id"] == endpoint_id:
                entry["request_count_24h"] = entry.get("request_count_24h", 0) + 1
                entry["last_access_at"] = access_time.isoformat()
                entry["updated_at"] = datetime.now(timezone.utc).isoformat()
                return dict(entry)
        return None

    async def mark_stale_endpoints(self, cutoff: Optional[datetime] = None) -> int:
        """
        Set is_stale=True for all endpoints where last_access_at < cutoff.

        Only updates entries that are not already stale (idempotent).
        Cutoff defaults to 90 days ago.

        Returns:
            Number of endpoints newly marked stale.
        """
        from datetime import timedelta

        if cutoff is None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=90)

        count = 0
        for entry in self._store.values():
            # Skip entries already marked stale
            if entry.get("is_stale"):
                continue

            last_access = entry.get("last_access_at")
            if last_access is None:
                # No traffic ever — use first_seen_at
                first_seen = entry.get("first_seen_at")
                if first_seen:
                    if isinstance(first_seen, str):
                        try:
                            ts = datetime.fromisoformat(first_seen.replace("Z", "+00:00"))
                        except ValueError:
                            continue
                    else:
                        ts = first_seen
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts < cutoff:
                        entry["is_stale"] = True
                        count += 1
            else:
                if isinstance(last_access, str):
                    try:
                        ts = datetime.fromisoformat(last_access.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                else:
                    ts = last_access
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts < cutoff:
                    entry["is_stale"] = True
                    count += 1
        return count


class DatabaseManager:
    """Manages async PostgreSQL connections and endpoint upserts."""

    def __init__(self, database_url: Optional[str] = None):
        """
        Initialize the database manager.

        Args:
            database_url: PostgreSQL connection string. If None, reads from DATABASE_URL env var.
        """
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://sentinel:sentinel@localhost:5432/sentinel"
        )
        self._engine: Optional[AsyncEngine] = None

    async def connect(self) -> None:
        """Establish async database connection."""
        try:
            self._engine = create_async_engine(
                self.database_url,
                echo=False,
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=20,
            )
            logger.info("database_connected", url=self.database_url.split("@")[-1])
        except Exception as exc:
            logger.warning("database_connection_failed", error=str(exc))
            # Continue without DB - graceful degradation
            self._engine = None

    async def disconnect(self) -> None:
        """Close database connection."""
        if self._engine:
            await self._engine.dispose()
            logger.info("database_disconnected")

    async def upsert_endpoint(self, record: EndpointRecord) -> tuple[str, bool]:
        """
        Upsert an endpoint record into the database.

        Uses INSERT ... ON CONFLICT DO UPDATE to implement deduplication.
        The deduplication key is (http_method, host, normalized_path).

        Args:
            record: The endpoint record to upsert.

        Returns:
            Tuple of (endpoint_id, was_inserted) where was_inserted is True if a new
            record was created, False if an existing record was updated.

        Raises:
            RuntimeError: If database is not connected.
        """
        if not self._engine:
            raise RuntimeError("Database not connected")

        query = text("""
            INSERT INTO api_endpoints (
                id, http_method, host, path, normalized_path, auth_scheme,
                data_sensitivity, lifecycle_status, risk_score, request_count_24h,
                last_access_at, owning_team, source_file_id, metadata, created_at, updated_at
            )
            VALUES (
                :id, :http_method, :host, :path, :normalized_path, :auth_scheme,
                :data_sensitivity, :lifecycle_status, :risk_score, :request_count_24h,
                :last_access_at, :owning_team, :source_file_id, :metadata, NOW(), NOW()
            )
            ON CONFLICT (http_method, host, normalized_path)
            DO UPDATE SET
                auth_scheme = EXCLUDED.auth_scheme,
                data_sensitivity = EXCLUDED.data_sensitivity,
                lifecycle_status = EXCLUDED.lifecycle_status,
                last_access_at = COALESCE(EXCLUDED.last_access_at, api_endpoints.last_access_at),
                owning_team = COALESCE(EXCLUDED.owning_team, api_endpoints.owning_team),
                source_file_id = COALESCE(EXCLUDED.source_file_id, api_endpoints.source_file_id),
                metadata = api_endpoints.metadata || EXCLUDED.metadata,
                updated_at = NOW()
            RETURNING id, (xmax = 0) AS inserted
        """)

        params = {
            "id": record.id,
            "http_method": record.http_method,
            "host": record.host,
            "path": record.normalized_path,  # Store normalized path in both path and normalized_path
            "normalized_path": record.normalized_path,
            "auth_scheme": record.auth_scheme.value if isinstance(record.auth_scheme, AuthScheme) else record.auth_scheme,
            "data_sensitivity": record.data_sensitivity.value if isinstance(record.data_sensitivity, DataSensitivity) else record.data_sensitivity,
            "lifecycle_status": record.lifecycle_status.value if isinstance(record.lifecycle_status, LifecycleStatus) else record.lifecycle_status,
            "risk_score": record.risk_score,
            "request_count_24h": record.request_count_24h,
            "last_access_at": record.last_access_at,
            "owning_team": record.owning_team,
            "source_file_id": record.source_file_id,
            "metadata": record.metadata,
        }

        async with self._engine.begin() as conn:
            result = await conn.execute(query, params)
            row = result.fetchone()
            endpoint_id = str(row[0])
            was_inserted = row[1]

            logger.info(
                "endpoint_upserted",
                endpoint_id=endpoint_id,
                method=record.http_method,
                host=record.host,
                path=record.normalized_path,
                inserted=was_inserted,
            )

            return endpoint_id, was_inserted

    async def get_endpoint(self, endpoint_id: str) -> Optional[dict]:
        """
        Retrieve a single endpoint by ID.

        Args:
            endpoint_id: The UUID of the endpoint.

        Returns:
            Dictionary of endpoint fields, or None if not found.
        """
        if not self._engine:
            raise RuntimeError("Database not connected")

        query = text("""
            SELECT id, http_method, host, path, normalized_path, auth_scheme,
                   data_sensitivity, lifecycle_status, risk_score, request_count_24h,
                   last_access_at, first_seen_at, is_stale, owning_team, source_file_id,
                   metadata, created_at, updated_at
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
                "http_method": row[1],
                "host": row[2],
                "path": row[3],
                "normalized_path": row[4],
                "auth_scheme": row[5],
                "data_sensitivity": row[6],
                "lifecycle_status": row[7],
                "risk_score": row[8],
                "request_count_24h": row[9],
                "last_access_at": row[10].isoformat() if row[10] else None,
                "first_seen_at": row[11].isoformat() if row[11] else None,
                "is_stale": row[12],
                "owning_team": row[13],
                "source_file_id": row[14],
                "metadata": row[15],
                "created_at": row[16].isoformat() if row[16] else None,
                "updated_at": row[17].isoformat() if row[17] else None,
            }

    async def list_endpoints(
        self,
        limit: int = 100,
        offset: int = 0,
        lifecycle_status: Optional[str] = None,
        auth_scheme: Optional[str] = None,
        data_sensitivity: Optional[str] = None,
        risk_score_min: Optional[int] = None,
        risk_score_max: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> list[dict]:
        """
        List endpoints with optional filters and cursor-based pagination.

        Cursor is the ``id`` (UUID) of the last record seen; results with
        ``id > cursor`` are returned (lexicographic UUID ordering).  When
        ``cursor`` is supplied, ``offset`` is ignored.

        Args:
            limit: Maximum number of results to return.
            offset: Number of results to skip (ignored when cursor is set).
            lifecycle_status: Filter by lifecycle status.
            auth_scheme: Filter by authentication scheme.
            data_sensitivity: Filter by data sensitivity.
            risk_score_min: Minimum risk score (inclusive).
            risk_score_max: Maximum risk score (inclusive).
            cursor: Opaque pagination cursor (last seen endpoint id).

        Returns:
            List of endpoint dictionaries.
        """
        if not self._engine:
            raise RuntimeError("Database not connected")

        # Build dynamic WHERE clause
        where_clauses = []
        params: dict[str, Any] = {"limit": limit}

        if lifecycle_status:
            where_clauses.append("lifecycle_status = :lifecycle_status")
            params["lifecycle_status"] = lifecycle_status

        if auth_scheme:
            where_clauses.append("auth_scheme = :auth_scheme")
            params["auth_scheme"] = auth_scheme

        if data_sensitivity:
            where_clauses.append("data_sensitivity = :data_sensitivity")
            params["data_sensitivity"] = data_sensitivity

        if risk_score_min is not None:
            where_clauses.append("risk_score >= :risk_score_min")
            params["risk_score_min"] = risk_score_min

        if risk_score_max is not None:
            where_clauses.append("risk_score <= :risk_score_max")
            params["risk_score_max"] = risk_score_max

        if cursor:
            where_clauses.append("id > :cursor")
            params["cursor"] = cursor
            offset_sql = ""
        else:
            params["offset"] = offset
            offset_sql = "OFFSET :offset"

        where_sql = " AND ".join(where_clauses) if where_clauses else "TRUE"

        query = text(f"""
            SELECT id, http_method, host, path, normalized_path, auth_scheme,
                   data_sensitivity, lifecycle_status, risk_score, request_count_24h,
                   last_access_at, first_seen_at, is_stale, owning_team, source_file_id,
                   metadata, created_at, updated_at
            FROM api_endpoints
            WHERE {where_sql}
            ORDER BY id
            LIMIT :limit {offset_sql}
        """)

        async with self._engine.connect() as conn:
            result = await conn.execute(query, params)
            rows = result.fetchall()

            return [
                {
                    "id": str(row[0]),
                    "http_method": row[1],
                    "host": row[2],
                    "path": row[3],
                    "normalized_path": row[4],
                    "auth_scheme": row[5],
                    "data_sensitivity": row[6],
                    "lifecycle_status": row[7],
                    "risk_score": row[8],
                    "request_count_24h": row[9],
                    "last_access_at": row[10].isoformat() if row[10] else None,
                    "first_seen_at": row[11].isoformat() if row[11] else None,
                    "is_stale": row[12],
                    "owning_team": row[13],
                    "source_file_id": row[14],
                    "metadata": row[15],
                    "created_at": row[16].isoformat() if row[16] else None,
                    "updated_at": row[17].isoformat() if row[17] else None,
                }
                for row in rows
            ]

    async def increment_traffic_counters(
        self,
        endpoint_id: str,
        access_time: Optional[datetime] = None,
    ) -> Optional[dict]:
        """
        Atomically increment request_count_24h and update last_access_at.

        Uses a single ``UPDATE … RETURNING`` statement so the counter
        increment and timestamp update are atomic.

        Args:
            endpoint_id: UUID of the endpoint to update.
            access_time: Timestamp of the traffic event; defaults to NOW().

        Returns:
            Updated endpoint dict, or None if not found.
        """
        if not self._engine:
            raise RuntimeError("Database not connected")

        query = text("""
            UPDATE api_endpoints
            SET
                request_count_24h = request_count_24h + 1,
                last_access_at    = COALESCE(:access_time, NOW()),
                updated_at        = NOW()
            WHERE id = :endpoint_id
            RETURNING id, request_count_24h, last_access_at, updated_at
        """)

        async with self._engine.begin() as conn:
            result = await conn.execute(
                query,
                {"endpoint_id": endpoint_id, "access_time": access_time},
            )
            row = result.fetchone()
            if not row:
                return None
            return {
                "id": str(row[0]),
                "request_count_24h": row[1],
                "last_access_at": row[2].isoformat() if row[2] else None,
                "updated_at": row[3].isoformat() if row[3] else None,
            }

    async def mark_stale_endpoints(self, cutoff: Optional[datetime] = None) -> int:
        """
        Set ``is_stale = TRUE`` for all endpoints where
        ``last_access_at < cutoff`` (or last_access_at IS NULL and
        first_seen_at < cutoff).

        Cutoff defaults to 90 days ago.

        Returns:
            Number of rows updated.
        """
        from datetime import timedelta

        if not self._engine:
            raise RuntimeError("Database not connected")

        if cutoff is None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=90)

        query = text("""
            UPDATE api_endpoints
            SET is_stale = TRUE, updated_at = NOW()
            WHERE is_stale = FALSE
              AND (
                    (last_access_at IS NOT NULL AND last_access_at < :cutoff)
                 OR (last_access_at IS NULL     AND first_seen_at  < :cutoff)
              )
        """)

        async with self._engine.begin() as conn:
            result = await conn.execute(query, {"cutoff": cutoff})
            return result.rowcount
