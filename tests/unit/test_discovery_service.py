# Feature: sentinel-api, Task 3: Discovery Service unit tests
"""
Unit tests for the Discovery Service parsers, PII anonymization, and upsert logic.

Covers:
- OpenAPI 3.x and Swagger 2.x parser (valid, malformed, auth extraction)
- Gateway config parsers (Kong, Apigee, AWS, unknown format)
- Gateway access log parser (JSON, CLF, deduplication, last_access_at)
- PII anonymization
- InMemoryStore upsert / deduplication
"""

import asyncio
import hashlib
import json
import sys
import os
from datetime import datetime, timezone

import pytest

# ---------------------------------------------------------------------------
# Path setup — allow imports from discovery-service and sentinel_shared
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, _REPO_ROOT)
from conftest import activate_service
activate_service("discovery-service")
sys.path.insert(0, os.path.join(_REPO_ROOT, "sentinel_shared"))

from parsers.openapi_parser import parse_openapi_spec, OpenAPIParseError
from parsers.gateway_parser import parse_gateway_config, GatewayParseError
from parsers.log_parser import parse_gateway_logs
from parsers.pii import anonymize_pii_fields
from db import InMemoryStore
from sentinel_shared.models import AuthScheme, EndpointRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MINIMAL_OPENAPI3 = {
    "openapi": "3.0.0",
    "info": {"title": "Test API", "version": "1.0.0"},
    "paths": {
        "/users": {
            "get": {"responses": {"200": {"description": "ok"}}},
            "post": {"responses": {"201": {"description": "created"}}},
        },
        "/items/{item_id}": {
            "parameters": [
                {"name": "item_id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "get": {"responses": {"200": {"description": "ok"}}},
            "delete": {"responses": {"204": {"description": "deleted"}}},
        },
    },
}

MINIMAL_SWAGGER2 = {
    "swagger": "2.0",
    "info": {"title": "Test API", "version": "1.0.0"},
    "host": "api.example.com",
    "basePath": "/v1",
    "paths": {
        "/pets": {
            "get": {"responses": {"200": {"description": "ok"}}},
        },
        "/pets/{pet_id}": {
            "parameters": [
                {"name": "pet_id", "in": "path", "required": True, "type": "string"}
            ],
            "get": {"responses": {"200": {"description": "ok"}}},
            "delete": {"responses": {"204": {"description": "deleted"}}},
        },
    },
}

OPENAPI3_WITH_OAUTH2 = {
    "openapi": "3.0.0",
    "info": {"title": "Secure API", "version": "1.0.0"},
    "components": {
        "securitySchemes": {
            "oauth2Scheme": {
                "type": "oauth2",
                "flows": {
                    "authorizationCode": {
                        "authorizationUrl": "https://example.com/oauth/authorize",
                        "tokenUrl": "https://example.com/oauth/token",
                        "scopes": {"read": "Read access"},
                    }
                },
            }
        }
    },
    "security": [{"oauth2Scheme": ["read"]}],
    "paths": {
        "/secure": {
            "get": {"responses": {"200": {"description": "ok"}}},
        }
    },
}

OPENAPI3_WITH_NO_AUTH = {
    "openapi": "3.0.0",
    "info": {"title": "Public API", "version": "1.0.0"},
    "paths": {
        "/public": {
            "get": {
                "security": [],
                "responses": {"200": {"description": "ok"}},
            }
        }
    },
}


# ---------------------------------------------------------------------------
# OpenAPI Parser tests
# ---------------------------------------------------------------------------


def test_parse_valid_openapi3_spec():
    """Parse a minimal valid OpenAPI 3.0 spec with 4 path-method combos."""
    content = json.dumps(MINIMAL_OPENAPI3)
    records = parse_openapi_spec(content, file_name="test.json")
    assert len(records) == 4
    methods = {r.http_method for r in records}
    assert methods == {"GET", "POST", "DELETE"}


def test_parse_valid_swagger2_spec():
    """Parse a minimal valid Swagger 2.0 spec."""
    content = json.dumps(MINIMAL_SWAGGER2)
    records = parse_openapi_spec(content, file_name="swagger.json")
    assert len(records) == 3
    assert all(r.host == "api.example.com" for r in records)


def test_parse_malformed_json_raises():
    """Invalid JSON content must raise OpenAPIParseError."""
    with pytest.raises(OpenAPIParseError) as exc_info:
        parse_openapi_spec("{not valid json", file_name="bad.json")
    assert exc_info.value.file_name == "bad.json"


def test_parse_malformed_yaml_raises():
    """Invalid YAML content must raise OpenAPIParseError."""
    bad_yaml = "key: [\nunclosed bracket"
    with pytest.raises(OpenAPIParseError) as exc_info:
        parse_openapi_spec(bad_yaml, file_name="bad.yaml")
    assert exc_info.value.file_name == "bad.yaml"


def test_parse_missing_required_fields_raises():
    """A dict with openapi version but missing info/paths must raise OpenAPIParseError."""
    incomplete = {"openapi": "3.0.0"}
    with pytest.raises(OpenAPIParseError) as exc_info:
        parse_openapi_spec(json.dumps(incomplete), file_name="incomplete.json")
    assert exc_info.value.validation_error  # must have a non-empty validation error


def test_parse_extracts_auth_scheme_oauth2():
    """Spec with global OAuth2 security must produce records with AuthScheme.OAUTH2."""
    content = json.dumps(OPENAPI3_WITH_OAUTH2)
    records = parse_openapi_spec(content, file_name="oauth.json")
    assert len(records) == 1
    assert records[0].auth_scheme == AuthScheme.OAUTH2


def test_parse_extracts_auth_scheme_none():
    """Operation with security: [] must produce a record with AuthScheme.NONE."""
    content = json.dumps(OPENAPI3_WITH_NO_AUTH)
    records = parse_openapi_spec(content, file_name="public.json")
    assert len(records) == 1
    assert records[0].auth_scheme == AuthScheme.NONE


def test_parse_sets_source_file_id():
    """All records must carry the provided file_name as source_file_id."""
    content = json.dumps(MINIMAL_OPENAPI3)
    records = parse_openapi_spec(content, file_name="myspec.yaml")
    assert all(r.source_file_id == "myspec.yaml" for r in records)


# ---------------------------------------------------------------------------
# Gateway Parser tests
# ---------------------------------------------------------------------------

KONG_CONFIG_VALID = {
    "services": [
        {
            "name": "user-service",
            "host": "users.internal",
            "routes": [
                {
                    "paths": ["/users"],
                    "methods": ["GET", "POST"],
                }
            ],
        }
    ]
}

KONG_CONFIG_UNSUPPORTED_AUTH = {
    "services": [
        {
            "name": "secure-service",
            "host": "secure.internal",
            "plugins": [
                {"name": "custom-ldap-auth"}
            ],
            "routes": [
                {
                    "paths": ["/secure"],
                    "methods": ["GET"],
                }
            ],
        }
    ]
}

APIGEE_CONFIG_VALID = {
    "proxies": [
        {
            "name": "my-proxy",
            "basePath": "/v1",
            "proxyEndpoints": [
                {
                    "basePath": "/v1",
                    "flows": [
                        {
                            "condition": 'request.verb = "GET" and proxy.pathsuffix MatchesPath("/orders")',
                            "policies": [],
                        }
                    ],
                }
            ],
        }
    ]
}

AWS_GATEWAY_CONFIG = {
    "openapi": "3.0.0",
    "info": {"title": "AWS API", "version": "1.0.0"},
    "servers": [{"url": "https://api.example.com"}],
    "paths": {
        "/orders": {
            "get": {
                "x-amazon-apigateway-integration": {
                    "type": "aws_proxy",
                    "uri": "arn:aws:lambda:...",
                },
                "responses": {"200": {"description": "ok"}},
            }
        }
    },
}


def test_parse_kong_config_valid():
    """Minimal Kong config with 1 service, 1 route, 2 methods → 2 records."""
    content = json.dumps(KONG_CONFIG_VALID)
    records = parse_gateway_config(content, source_file_id="kong.json")
    assert len(records) == 2
    methods = {r.http_method for r in records}
    assert methods == {"GET", "POST"}
    assert all(r.host == "users.internal" for r in records)


def test_parse_kong_unsupported_auth_plugin():
    """Kong config with unknown plugin must set auth_scheme=UNKNOWN and raw_auth_plugin."""
    content = json.dumps(KONG_CONFIG_UNSUPPORTED_AUTH)
    records = parse_gateway_config(content, source_file_id="kong_auth.json")
    assert len(records) == 1
    record = records[0]
    assert record.auth_scheme == AuthScheme.UNKNOWN
    assert record.metadata.get("raw_auth_plugin") == "custom-ldap-auth"


def test_parse_apigee_config_valid():
    """Minimal Apigee config with 1 proxy, 1 flow → at least 1 record."""
    content = json.dumps(APIGEE_CONFIG_VALID)
    records = parse_gateway_config(content, source_file_id="apigee.json")
    assert len(records) >= 1


def test_parse_aws_gateway_config_valid():
    """AWS API Gateway export (OpenAPI + x-amazon-apigateway-integration) → records."""
    content = json.dumps(AWS_GATEWAY_CONFIG)
    records = parse_gateway_config(content, source_file_id="aws.json")
    assert len(records) >= 1
    assert any(r.http_method == "GET" for r in records)


def test_parse_unknown_format_raises():
    """Unrecognized gateway config format must raise GatewayParseError."""
    content = json.dumps({"random": "data", "not_a_gateway": True})
    with pytest.raises(GatewayParseError):
        parse_gateway_config(content, source_file_id="unknown.json")


# ---------------------------------------------------------------------------
# Log Parser tests
# ---------------------------------------------------------------------------

def _json_log_line(method: str, host: str, path: str, status: int, timestamp: str) -> str:
    return json.dumps({
        "method": method,
        "host": host,
        "path": path,
        "status": status,
        "timestamp": timestamp,
    })


def test_parse_json_logs_extracts_endpoints():
    """3 JSON log lines for 2 unique endpoints → 2 records."""
    lines = [
        _json_log_line("GET", "api.example.com", "/users", 200, "2024-01-15T10:00:00Z"),
        _json_log_line("GET", "api.example.com", "/users", 200, "2024-01-15T11:00:00Z"),
        _json_log_line("POST", "api.example.com", "/orders", 201, "2024-01-15T10:30:00Z"),
    ]
    content = "\n".join(lines)
    records = parse_gateway_logs(content, source_file_id="access.log", default_host="api.example.com")
    assert len(records) == 2
    methods = {r.http_method for r in records}
    assert "GET" in methods
    assert "POST" in methods


def test_parse_combined_log_format():
    """Combined Log Format lines → records extracted."""
    clf_lines = (
        '127.0.0.1 - frank [10/Oct/2000:13:55:36 -0700] "GET /apache_pb.gif HTTP/1.0" 200 2326\n'
        '127.0.0.1 - - [10/Oct/2000:14:00:00 -0700] "POST /submit HTTP/1.1" 201 512\n'
    )
    records = parse_gateway_logs(clf_lines, default_host="localhost")
    assert len(records) == 2
    methods = {r.http_method for r in records}
    assert "GET" in methods
    assert "POST" in methods


def test_parse_logs_last_access_at_is_max_timestamp():
    """3 log entries for same endpoint → last_access_at equals the latest timestamp."""
    ts1 = "2024-01-15T08:00:00Z"
    ts2 = "2024-01-15T12:00:00Z"  # latest
    ts3 = "2024-01-15T10:00:00Z"
    lines = [
        _json_log_line("GET", "api.example.com", "/users", 200, ts1),
        _json_log_line("GET", "api.example.com", "/users", 200, ts2),
        _json_log_line("GET", "api.example.com", "/users", 200, ts3),
    ]
    content = "\n".join(lines)
    records = parse_gateway_logs(content, default_host="api.example.com")
    assert len(records) == 1
    record = records[0]
    assert record.last_access_at is not None
    expected = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    # Normalize to UTC for comparison
    actual = record.last_access_at
    if actual.tzinfo is None:
        actual = actual.replace(tzinfo=timezone.utc)
    assert actual == expected


def test_parse_logs_deduplicates_by_method_host_path():
    """5 log entries for 2 unique (method, host, path) combos → 2 records."""
    lines = [
        _json_log_line("GET", "api.example.com", "/users", 200, "2024-01-15T10:00:00Z"),
        _json_log_line("GET", "api.example.com", "/users", 200, "2024-01-15T11:00:00Z"),
        _json_log_line("GET", "api.example.com", "/users", 200, "2024-01-15T12:00:00Z"),
        _json_log_line("DELETE", "api.example.com", "/users/42", 204, "2024-01-15T09:00:00Z"),
        _json_log_line("DELETE", "api.example.com", "/users/99", 204, "2024-01-15T09:30:00Z"),
    ]
    content = "\n".join(lines)
    records = parse_gateway_logs(content, default_host="api.example.com")
    # /users/42 and /users/99 both normalize to /users/{n}
    assert len(records) == 2


# ---------------------------------------------------------------------------
# PII Anonymization tests
# ---------------------------------------------------------------------------


def test_anonymize_pii_replaces_with_sha256():
    """PII field value must be replaced with its SHA-256 hex digest."""
    data = {"email": "alice@example.com", "name": "Alice"}
    result = anonymize_pii_fields(data, ["email"])
    expected_hash = hashlib.sha256("alice@example.com".encode()).hexdigest()
    assert result["email"] == expected_hash
    assert result["name"] == "Alice"


def test_anonymize_pii_does_not_mutate_original():
    """The original dict must not be mutated by anonymize_pii_fields."""
    data = {"email": "bob@example.com", "age": 30}
    original_email = data["email"]
    anonymize_pii_fields(data, ["email"])
    assert data["email"] == original_email


# ---------------------------------------------------------------------------
# InMemoryStore / Upsert tests
# ---------------------------------------------------------------------------


def _make_record(method: str = "GET", host: str = "api.example.com", path: str = "/users") -> EndpointRecord:
    return EndpointRecord(http_method=method, host=host, normalized_path=path)


@pytest.mark.asyncio
async def test_upsert_new_endpoint_returns_inserted_true():
    """Upserting a new record must return was_inserted=True."""
    store = InMemoryStore()
    record = _make_record()
    _, was_inserted = await store.upsert_endpoint(record)
    assert was_inserted is True


@pytest.mark.asyncio
async def test_upsert_duplicate_returns_inserted_false():
    """Upserting the same record twice must return was_inserted=False on second call."""
    store = InMemoryStore()
    record = _make_record()
    await store.upsert_endpoint(record)
    _, was_inserted = await store.upsert_endpoint(record)
    assert was_inserted is False


@pytest.mark.asyncio
async def test_upsert_deduplication_key():
    """Two records with same (method, host, path) but different IDs → only 1 entry in store."""
    store = InMemoryStore()
    r1 = _make_record()
    r2 = EndpointRecord(http_method="GET", host="api.example.com", normalized_path="/users")
    assert r1.id != r2.id  # different UUIDs
    await store.upsert_endpoint(r1)
    await store.upsert_endpoint(r2)
    results = await store.list_endpoints()
    assert len(results) == 1


@pytest.mark.asyncio
async def test_upsert_updates_metadata_on_conflict():
    """Re-upserting with new metadata must merge/update the stored metadata."""
    store = InMemoryStore()
    r1 = EndpointRecord(
        http_method="GET",
        host="api.example.com",
        normalized_path="/users",
        metadata={"version": "v1"},
    )
    await store.upsert_endpoint(r1)

    r2 = EndpointRecord(
        http_method="GET",
        host="api.example.com",
        normalized_path="/users",
        metadata={"version": "v2", "owner": "team-a"},
    )
    await store.upsert_endpoint(r2)

    results = await store.list_endpoints()
    assert len(results) == 1
    stored_meta = results[0]["metadata"]
    # Metadata should reflect the latest values
    assert stored_meta.get("version") == "v2"
    assert stored_meta.get("owner") == "team-a"
