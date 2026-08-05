"""
Endpoint inventory route handlers.

Implements GET /endpoints (paginated list) and GET /endpoints/{id} (single record).
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Query
import structlog

logger = structlog.get_logger(__name__)

endpoints_router = APIRouter(prefix="/endpoints", tags=["endpoints"])


@endpoints_router.get("", summary="List discovered endpoints")
async def list_endpoints(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum number of results"),
    cursor: Optional[str] = Query(default=None, description="Pagination cursor (last seen endpoint id)"),
    lifecycle_status: Optional[str] = Query(default=None, description="Filter by lifecycle status"),
    auth_scheme: Optional[str] = Query(default=None, description="Filter by auth scheme"),
    data_sensitivity: Optional[str] = Query(default=None, description="Filter by data sensitivity"),
    risk_score_min: Optional[int] = Query(default=None, ge=0, le=100, description="Minimum risk score"),
    risk_score_max: Optional[int] = Query(default=None, ge=0, le=100, description="Maximum risk score"),
) -> dict:
    """
    Return a paginated, filtered list of discovered API endpoints.

    Uses cursor-based pagination: pass the ``next_cursor`` from a previous
    response as the ``cursor`` query parameter to retrieve the next page.
    Results are ordered by ``id`` (UUID lexicographic order).

    Supports filtering by lifecycle status, auth scheme, data sensitivity,
    and risk score range.
    """
    db = getattr(request.app.state, "db", None)

    if not db:
        raise HTTPException(
            status_code=503,
            detail={"error": "database_unavailable", "message": "Database connection not available"},
        )

    try:
        records = await db.list_endpoints(
            limit=limit,
            cursor=cursor,
            lifecycle_status=lifecycle_status,
            auth_scheme=auth_scheme,
            data_sensitivity=data_sensitivity,
            risk_score_min=risk_score_min,
            risk_score_max=risk_score_max,
        )
    except Exception as exc:
        logger.error("list_endpoints_failed", error=str(exc))
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": str(exc)},
        )

    # Derive next_cursor from the last record's id
    next_cursor = records[-1]["id"] if len(records) == limit else None

    return {
        "items": records,
        "limit": limit,
        "count": len(records),
        "cursor": cursor,
        "next_cursor": next_cursor,
    }


@endpoints_router.get("/{endpoint_id}", summary="Get a single endpoint by ID")
async def get_endpoint(
    endpoint_id: str,
    request: Request,
) -> dict:
    """
    Return a single endpoint record by its UUID.

    Returns HTTP 404 if the endpoint is not found.
    """
    db = getattr(request.app.state, "db", None)

    if not db:
        raise HTTPException(
            status_code=503,
            detail={"error": "database_unavailable", "message": "Database connection not available"},
        )

    try:
        record = await db.get_endpoint(endpoint_id)
    except Exception as exc:
        logger.error("get_endpoint_failed", endpoint_id=endpoint_id, error=str(exc))
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": str(exc)},
        )

    if not record:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "endpoint_id": endpoint_id},
        )

    return record
