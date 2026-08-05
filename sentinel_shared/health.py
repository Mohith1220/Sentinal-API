"""
Shared FastAPI router providing the /health endpoint.

Each microservice mounts this router so that container orchestration
liveness probes always have a consistent target.

Returns HTTP 200 {"status": "ok"} when the service is operational.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

health_router = APIRouter(tags=["health"])


@health_router.get("/health", summary="Liveness health check")
async def health_check() -> JSONResponse:
    """
    Return HTTP 200 when the service is operational.

    Container orchestration (Docker Compose, Kubernetes) uses this endpoint
    as a liveness probe. Returns HTTP 503 if the service is not ready
    (override this handler in individual services if needed).
    """
    return JSONResponse(content={"status": "ok"}, status_code=200)
