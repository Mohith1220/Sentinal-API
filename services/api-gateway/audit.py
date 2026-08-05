"""
Audit log writer for the API Gateway.

Writes an entry to the audit_log table for every state-mutating request
that passes authentication and authorisation.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Tuple


@dataclass
class AuditLogEntry:
    """
    Represents a single audit log entry.

    Fields match the audit_log table schema from design §4.1.
    """

    actor_identity: str          # JWT 'sub' claim
    action_type: str             # e.g. "POST /endpoints"
    resource_type: str           # e.g. "endpoint", "recommendation"
    occurred_at: datetime        # UTC timestamp
    resource_id: Optional[str] = None   # extracted from path, may be None
    payload: dict = field(default_factory=dict)  # request metadata


# ---------------------------------------------------------------------------
# Resource extraction
# ---------------------------------------------------------------------------

# Maps path prefixes to resource type names
_RESOURCE_TYPE_MAP = {
    "/endpoints": "endpoint",
    "/score": "risk_score",
    "/alerts": "alert",
    "/baselines": "baseline",
    "/recommendations": "recommendation",
    "/admin": "admin_config",
}


def extract_resource_info(path: str, method: str) -> Tuple[str, Optional[str]]:
    """
    Extract (resource_type, resource_id) from a request path and method.

    The resource_id is the path segment immediately following the resource
    prefix (if present), e.g. '/endpoints/abc-123' → resource_id='abc-123'.

    Args:
        path: The request path (e.g. '/endpoints/abc-123').
        method: The HTTP method (unused currently, reserved for future use).

    Returns:
        A tuple (resource_type, resource_id).
        resource_type is a non-empty string; resource_id may be None.
    """
    normalized = path.rstrip("/")

    for prefix, resource_type in _RESOURCE_TYPE_MAP.items():
        if normalized == prefix or normalized.startswith(prefix + "/"):
            # Extract the ID segment if present
            remainder = normalized[len(prefix):]
            if remainder.startswith("/"):
                remainder = remainder[1:]
            # Take only the first path segment as the resource ID
            segments = remainder.split("/") if remainder else []
            resource_id = segments[0] if segments else None
            return resource_type, resource_id or None

    # Fallback: use the first non-empty path segment as the resource type
    parts = [p for p in normalized.split("/") if p]
    resource_type = parts[0] if parts else "unknown"
    return resource_type, None


# ---------------------------------------------------------------------------
# Database writer
# ---------------------------------------------------------------------------


async def write_audit_log(db, entry: AuditLogEntry) -> None:
    """
    Persist an audit log entry to the database.

    Args:
        db: A database manager instance with a write_audit_log method,
            or None (in which case the write is silently skipped).
        entry: The AuditLogEntry to persist.
    """
    if db is None:
        return
    try:
        await db.write_audit_log(entry)
    except Exception:
        # Audit log failures must never block the proxied request
        import structlog
        logger = structlog.get_logger(__name__)
        logger.error(
            "audit_log_write_failed",
            actor=entry.actor_identity,
            action=entry.action_type,
        )
