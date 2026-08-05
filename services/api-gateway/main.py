"""
API Gateway — SentinelAPI

Single entry point for the React dashboard.
Enforces JWT authentication and RBAC, then proxies requests to downstream services.

Routes:
  ALL /*          — JWT-authenticated, RBAC-enforced reverse proxy
  GET /ws/alerts  — WebSocket relay for anomaly.alerts Kafka topic
  GET /health     — Liveness probe (unauthenticated)
"""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from sentinel_shared.health import health_router
from sentinel_shared.kafka import SentinelConsumer
from sentinel_shared.logging import CorrelationIDMiddleware, configure_logging, make_global_exception_handler
from sentinel_shared.metrics import setup_metrics

from auth import InvalidTokenError, TokenExpiredError, validate_jwt
from audit import AuditLogEntry, extract_resource_info, write_audit_log
from db import GatewayDatabaseManager
from proxy import proxy_request
from rbac import check_permission, is_write_method

SERVICE_NAME = "api-gateway"
logger = structlog.get_logger(__name__)

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
JWT_PUBLIC_KEY = os.getenv("JWT_PUBLIC_KEY", "")

# Paths that bypass JWT authentication
_UNAUTHENTICATED_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/auth/register", "/auth/token"}

# Bearer token extractor (auto_error=False so we can return custom JSON errors)
_bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# JWT dependency
# ---------------------------------------------------------------------------


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """
    FastAPI dependency that validates the Bearer JWT on every protected request.

    Returns the decoded JWT payload (including 'sub' and 'role' claims).
    Raises HTTP 401 with a JSON body on authentication failure.
    """
    if request.method == "OPTIONS":
        return {"sub": "options-bypass", "role": "admin"}

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail={"error": "invalid_token"},
        )

    public_key = getattr(request.app.state, "jwt_public_key", JWT_PUBLIC_KEY)

    try:
        payload = validate_jwt(credentials.credentials, public_key)
    except TokenExpiredError:
        raise HTTPException(
            status_code=401,
            detail={"error": "token_expired"},
        )
    except InvalidTokenError:
        raise HTTPException(
            status_code=401,
            detail={"error": "invalid_token"},
        )

    return payload


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN001
    configure_logging(SERVICE_NAME)

    # Store JWT public key
    app.state.jwt_public_key = JWT_PUBLIC_KEY

    # Initialize database
    db = GatewayDatabaseManager()
    try:
        await db.connect()
        app.state.db = db
    except Exception as exc:
        logger.warning("db_init_failed", error=str(exc))
        app.state.db = None

    # Initialize httpx client for reverse proxy
    app.state.http_client = httpx.AsyncClient(timeout=30.0)

    yield

    # Cleanup
    await app.state.http_client.aclose()

    if app.state.db:
        await app.state.db.disconnect()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SentinelAPI — API Gateway",
    version="0.1.0",
    lifespan=lifespan,
)

# Configure CORS to allow frontend requests (must be first!)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server
        "http://localhost:5174",
        "http://localhost:5175",
        "http://localhost:3000",  # Alternative React dev server
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:5175",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all headers
    expose_headers=["*"],  # Expose all headers
)

app.add_middleware(CorrelationIDMiddleware)
setup_metrics(app, SERVICE_NAME)
app.include_router(health_router)


# ---------------------------------------------------------------------------
# Auth routes (unauthenticated)
# ---------------------------------------------------------------------------


from pydantic import BaseModel as _BaseModel

class _RegisterRequest(_BaseModel):
    username: str
    email: str
    password: str
    role: str = "viewer"

class _LoginRequest(_BaseModel):
    username: str
    password: str

# Add OPTIONS handlers for CORS preflight requests
@app.options("/auth/register")
@app.options("/auth/token")
@app.options("/auth/logout")
async def handle_auth_options():
    return {"message": "CORS preflight"}


@app.post("/auth/logout")
async def logout(request: Request):
    """Logout endpoint — invalidates the session (client discards token)."""
    return {"message": "logged_out", "status": "ok"}


@app.post("/auth/register", status_code=201)
async def register(request: Request, body: _RegisterRequest):
    """Register a new user account."""
    import hashlib, os, json
    db: GatewayDatabaseManager = getattr(request.app.state, "db", None)
    if not db or not db._engine:
        raise HTTPException(status_code=503, detail={"error": "database_unavailable"})

    valid_roles = {"admin", "analyst", "viewer"}
    if body.role not in valid_roles:
        raise HTTPException(status_code=400, detail={"error": "invalid_role", "valid_roles": list(valid_roles)})

    # Hash password using simple SHA256 for now to avoid bcrypt issues
    import hashlib
    import base64
    
    # Simple password hashing for development
    password_bytes = body.password.encode('utf-8')
    password_hash = base64.b64encode(hashlib.sha256(password_bytes).digest()).decode('utf-8')

    from sqlalchemy import text
    async with db._engine.begin() as conn:
        # Check for existing username/email
        existing = await conn.execute(
            text("SELECT id FROM users WHERE username = :u OR email = :e"),
            {"u": body.username, "e": body.email}
        )
        if existing.fetchone():
            raise HTTPException(status_code=409, detail={"error": "user_already_exists"})

        result = await conn.execute(
            text("""
                INSERT INTO users (username, email, password_hash, role)
                VALUES (:username, :email, :password_hash, :role)
                RETURNING id, username, email, role, created_at
            """),
            {"username": body.username, "email": body.email,
             "password_hash": password_hash, "role": body.role}
        )
        row = result.fetchone()

    return {"id": str(row.id), "username": row.username, "email": row.email,
            "role": row.role, "created_at": str(row.created_at)}


@app.post("/auth/token")
async def login(request: Request, body: _LoginRequest):
    """Authenticate and return a JWT access token."""
    import os, datetime
    from jose import jwt as _jwt
    from sqlalchemy import text

    db: GatewayDatabaseManager = getattr(request.app.state, "db", None)
    if not db or not db._engine:
        raise HTTPException(status_code=503, detail={"error": "database_unavailable"})

    async with db._engine.connect() as conn:
        result = await conn.execute(
            text("SELECT id, username, password_hash, role FROM users WHERE username = :u"),
            {"u": body.username}
        )
        row = result.fetchone()

    if not row:
        raise HTTPException(status_code=401, detail={"error": "invalid_credentials"})

    # Verify password using SHA256 (same as registration)
    import hashlib
    import base64
    
    password_bytes = body.password.encode('utf-8')
    password_hash = base64.b64encode(hashlib.sha256(password_bytes).digest()).decode('utf-8')
    
    if password_hash != row.password_hash:
        raise HTTPException(status_code=401, detail={"error": "invalid_credentials"})

    # Build JWT — use HS256 with a secret if no RS256 key is configured
    secret = os.getenv("JWT_SECRET", "sentinel-dev-secret-change-in-production")
    public_key = getattr(request.app.state, "jwt_public_key", "")

    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": row.username,
        "role": row.role,
        "iat": now,
        "exp": now + datetime.timedelta(hours=8),
    }

    if public_key:
        private_key = os.getenv("JWT_PRIVATE_KEY", "")
        token = _jwt.encode(payload, private_key, algorithm="RS256")
    else:
        token = _jwt.encode(payload, secret, algorithm="HS256")

    return {"access_token": token, "token_type": "bearer", "role": row.role}


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Return HTTPException details as JSON."""
    detail = exc.detail
    if isinstance(detail, dict):
        return JSONResponse(status_code=exc.status_code, content=detail)
    return JSONResponse(status_code=exc.status_code, content={"error": detail})


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler: log the error and return a generic 500."""
    from sentinel_shared.logging import get_correlation_id
    import traceback
    correlation_id = get_correlation_id()
    logger.error(
        "unhandled_exception",
        service=SERVICE_NAME,
        operation=f"{request.method} {request.url.path}",
        input_summary={
            "method": request.method,
            "path": str(request.url.path),
            "query": str(request.url.query),
        },
        stack_trace=traceback.format_exc(),
        error=str(exc),
        correlation_id=correlation_id,
    )
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "correlation_id": correlation_id},
    )


# ---------------------------------------------------------------------------
# WebSocket relay — /ws/alerts
# ---------------------------------------------------------------------------


@app.websocket("/ws/alerts")
async def ws_alerts(websocket: WebSocket) -> None:
    """
    WebSocket endpoint that subscribes to the anomaly.alerts Kafka topic
    and streams events to connected dashboard clients.
    """
    await websocket.accept()
    logger.info("ws_alerts_client_connected")

    consumer = SentinelConsumer(
        topics=["anomaly.alerts"],
        group_id=f"api-gateway-ws-{id(websocket)}",
        bootstrap_servers=KAFKA_BOOTSTRAP,
    )

    try:
        await consumer.start()

        async def forward_to_ws(message: dict) -> None:
            import json
            try:
                await websocket.send_text(json.dumps(message, default=str))
            except Exception as exc:
                logger.error("ws_send_error", error=str(exc))
                raise

        # Run consumer in a background task
        consumer_task = asyncio.create_task(consumer.run(forward_to_ws))

        # Create a task that waits for client disconnect
        async def wait_for_disconnect() -> None:
            try:
                while True:
                    # This will raise WebSocketDisconnect when client disconnects
                    await websocket.receive_text()
            except WebSocketDisconnect:
                raise
            except Exception:
                pass

        disconnect_task = asyncio.create_task(wait_for_disconnect())

        # Wait for either the consumer to finish or the client to disconnect
        done, pending = await asyncio.wait(
            [consumer_task, disconnect_task],
            return_when=asyncio.FIRST_COMPLETED
        )

        # Cancel the pending task
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    except WebSocketDisconnect:
        logger.info("ws_alerts_client_disconnected")
    except Exception as exc:
        logger.error("ws_alerts_error", error=str(exc))
    finally:
        await consumer.stop()
        try:
            await websocket.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Reverse proxy catch-all route
# ---------------------------------------------------------------------------


@app.api_route(
    "/{full_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"],
)
async def reverse_proxy(
    request: Request,
    full_path: str,
    current_user: dict = Depends(get_current_user),
) -> Response:
    """
    JWT-authenticated, RBAC-enforced reverse proxy to downstream services.

    1. JWT is validated by the get_current_user dependency.
    2. RBAC is checked against the permission matrix.
    3. Request is forwarded to the appropriate downstream service.
    4. Audit log entry is written for state-mutating requests.
    """
    path = "/" + full_path if not full_path.startswith("/") else full_path
    method = request.method
    role = current_user.get("role", "")
    actor = current_user.get("sub", "unknown")

    # RBAC check
    allowed, required_role = check_permission(role, method, path)
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail={"error": "forbidden", "required_role": required_role},
        )

    # Forward request to downstream service
    client: httpx.AsyncClient = request.app.state.http_client
    body = await request.body()
    query_string = request.url.query

    try:
        downstream_response = await proxy_request(
            client=client,
            method=method,
            path=path,
            headers=dict(request.headers),
            body=body or None,
            query_string=query_string,
        )
    except ValueError as exc:
        # No downstream service found for this path
        raise HTTPException(status_code=404, detail={"error": "not_found"}) from exc
    except httpx.TimeoutException as exc:
        logger.error("proxy_timeout", path=path, error=str(exc))
        raise HTTPException(status_code=504, detail={"error": "gateway_timeout"}) from exc
    except httpx.HTTPError as exc:
        logger.error("proxy_error", path=path, error=str(exc))
        raise HTTPException(status_code=502, detail={"error": "bad_gateway"}) from exc

    # Write audit log for state-mutating requests
    if is_write_method(method):
        resource_type, resource_id = extract_resource_info(path, method)
        entry = AuditLogEntry(
            actor_identity=actor,
            action_type=f"{method} {path}",
            resource_type=resource_type,
            resource_id=resource_id,
            occurred_at=datetime.now(timezone.utc),
            payload={
                "status_code": downstream_response.status_code,
                "role": role,
            },
        )
        db = getattr(request.app.state, "db", None)
        await write_audit_log(db, entry)

    # Return the downstream response
    return Response(
        content=downstream_response.content,
        status_code=downstream_response.status_code,
        headers=dict(downstream_response.headers),
        media_type=downstream_response.headers.get("content-type"),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
