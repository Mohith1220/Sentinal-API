"""
Discovery route handlers.

Implements POST /discover/openapi, POST /discover/github,
POST /discover/gateway, POST /discover/gateway-logs endpoints.
"""

from typing import Optional, Annotated

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form, Body
from pydantic import BaseModel, Field
import structlog

from sentinel_shared.models import EndpointRecord
from parsers.openapi_parser import parse_openapi_spec, OpenAPIParseError
from parsers.github_scanner import scan_github_repo, GitHubScanError
from parsers.gateway_parser import parse_gateway_config, GatewayParseError
from parsers.log_parser import parse_gateway_logs

logger = structlog.get_logger(__name__)

discover_router = APIRouter(prefix="/discover", tags=["discovery"])


class DiscoveryResult(BaseModel):
    """Response model for discovery endpoints."""
    endpoints_discovered: int
    endpoints_upserted: int
    endpoints_updated: int
    source: str
    errors: list[str] = Field(default_factory=list)


class OpenAPIDiscoverRequest(BaseModel):
    """Request body for OpenAPI spec discovery."""
    content: str = Field(..., description="OpenAPI spec content (JSON or YAML)")
    file_name: str = Field(default="", description="Optional file name for error messages")
    host: str = Field(default="unknown", description="Default host if not in spec")


class GitHubDiscoverRequest(BaseModel):
    """Request body for GitHub repo discovery."""
    repo_url: str = Field(..., description="GitHub repository URL")
    token: Optional[str] = Field(default=None, description="GitHub personal access token")
    host: str = Field(default="unknown", description="Default host for discovered endpoints")


class GatewayDiscoverRequest(BaseModel):
    """Request body for gateway config discovery."""
    content: str = Field(..., description="Gateway config content (JSON or YAML)")
    file_name: str = Field(default="", description="Optional file name")
    host: str = Field(default="unknown", description="Default host if not in config")


class GatewayLogsDiscoverRequest(BaseModel):
    """Request body for gateway log discovery."""
    content: str = Field(..., description="Gateway access log content")
    file_name: str = Field(default="", description="Optional file name")
    host: str = Field(default="unknown", description="Default host if not in logs")


async def _upsert_records(
    request: Request,
    records: list[EndpointRecord],
    source: str,
) -> DiscoveryResult:
    """
    Upsert a list of endpoint records into the database and publish Kafka events.

    Args:
        request: FastAPI request (used to access app state for db/kafka).
        records: List of endpoint records to upsert.
        source: Source identifier for logging.

    Returns:
        DiscoveryResult with counts of upserted/updated records.
    """
    db = getattr(request.app.state, "db", None)
    kafka = getattr(request.app.state, "kafka", None)

    upserted = 0
    updated = 0
    errors: list[str] = []

    for record in records:
        try:
            if db:
                endpoint_id, was_inserted = await db.upsert_endpoint(record)
                if was_inserted:
                    upserted += 1
                    change_type = "created"
                else:
                    updated += 1
                    change_type = "updated"

                if kafka:
                    await kafka.publish_endpoint_updated(
                        endpoint_id=endpoint_id,
                        change_type=change_type,
                        changed_fields=["auth_scheme", "metadata"],
                    )
            else:
                # No DB — count as upserted for response
                upserted += 1
        except Exception as exc:
            logger.error(
                "endpoint_upsert_failed",
                method=record.http_method,
                host=record.host,
                path=record.normalized_path,
                error=str(exc),
            )
            errors.append(f"{record.http_method} {record.host}{record.normalized_path}: {exc}")

    return DiscoveryResult(
        endpoints_discovered=len(records),
        endpoints_upserted=upserted,
        endpoints_updated=updated,
        source=source,
        errors=errors,
    )


@discover_router.post("/openapi", response_model=DiscoveryResult, summary="Discover endpoints from OpenAPI spec")
async def discover_openapi(
    request: Request,
    body: OpenAPIDiscoverRequest,
) -> DiscoveryResult:
    """
    Parse an OpenAPI 3.x or Swagger 2.x specification and discover endpoint records.

    Validates the spec schema and raises HTTP 400 on malformed input.
    """
    try:
        records = parse_openapi_spec(
            content=body.content,
            file_name=body.file_name,
            default_host=body.host,
        )
    except OpenAPIParseError as exc:
        logger.warning(
            "openapi_parse_failed",
            file_name=body.file_name,
            error=str(exc),
            validation_error=exc.validation_error,
        )
        raise HTTPException(
            status_code=400,
            detail={
                "error": "malformed_spec",
                "file_name": exc.file_name or body.file_name,
                "validation_error": exc.validation_error,
                "message": str(exc),
            },
        )

    logger.info(
        "openapi_discovered",
        file_name=body.file_name,
        endpoints_found=len(records),
    )

    return await _upsert_records(request, records, source=body.file_name or "openapi")


@discover_router.post("/github", response_model=DiscoveryResult, summary="Discover endpoints from GitHub repo")
async def discover_github(
    request: Request,
    body: GitHubDiscoverRequest,
) -> DiscoveryResult:
    """
    Scan a GitHub repository for OpenAPI spec files and discover endpoint records.

    Completes within 60 seconds or returns HTTP 504.
    """
    try:
        records = await scan_github_repo(
            repo_url=body.repo_url,
            token=body.token,
            default_host=body.host,
        )
    except GitHubScanError as exc:
        if "timed out" in str(exc).lower():
            raise HTTPException(
                status_code=504,
                detail={
                    "error": "scan_timeout",
                    "repo_url": body.repo_url,
                    "message": str(exc),
                },
            )
        raise HTTPException(
            status_code=400,
            detail={
                "error": "github_scan_failed",
                "repo_url": body.repo_url,
                "message": str(exc),
            },
        )

    logger.info(
        "github_discovered",
        repo_url=body.repo_url,
        endpoints_found=len(records),
    )

    return await _upsert_records(request, records, source=body.repo_url)


@discover_router.post("/gateway", response_model=DiscoveryResult, summary="Discover endpoints from gateway config")
async def discover_gateway(
    request: Request,
    body: GatewayDiscoverRequest,
) -> DiscoveryResult:
    """
    Parse an API gateway configuration export (AWS API Gateway, Kong, or Apigee)
    and discover endpoint records.
    """
    try:
        records = parse_gateway_config(
            content=body.content,
            source_file_id=body.file_name,
            default_host=body.host,
        )
    except GatewayParseError as exc:
        logger.warning(
            "gateway_parse_failed",
            file_name=body.file_name,
            error=str(exc),
        )
        raise HTTPException(
            status_code=400,
            detail={
                "error": "malformed_gateway_config",
                "file_name": body.file_name,
                "format": exc.format_name,
                "message": str(exc),
            },
        )

    logger.info(
        "gateway_discovered",
        file_name=body.file_name,
        endpoints_found=len(records),
    )

    return await _upsert_records(request, records, source=body.file_name or "gateway")


@discover_router.post("/gateway-logs", response_model=DiscoveryResult, summary="Discover endpoints from gateway logs")
async def discover_gateway_logs(
    request: Request,
    body: GatewayLogsDiscoverRequest,
) -> DiscoveryResult:
    """
    Parse gateway access log files and discover endpoint records.

    Computes last_access_at as MAX(timestamp) per endpoint.
    Applies PII anonymization to log payload fields before persisting.
    """
    records = parse_gateway_logs(
        content=body.content,
        source_file_id=body.file_name,
        default_host=body.host,
    )

    logger.info(
        "gateway_logs_discovered",
        file_name=body.file_name,
        endpoints_found=len(records),
    )

    return await _upsert_records(request, records, source=body.file_name or "gateway-logs")
