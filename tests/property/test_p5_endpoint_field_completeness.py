# Feature: sentinel-api, Property 5: Endpoint Record Field Completeness
"""
Property-based tests for Property 5: Endpoint Record Field Completeness.

For any valid OpenAPI spec or gateway configuration, every endpoint record
extracted by the Discovery Engine SHALL contain non-null values for all
required fields: HTTP method, path, host, authentication scheme, and source
file identifier (when provided).

**Validates: Requirements 1.6**
"""

import json
import sys
import os

from hypothesis import given, settings
from hypothesis import strategies as st

_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(_REPO_ROOT, "services", "discovery-service"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "sentinel_shared"))

from parsers.openapi_parser import parse_openapi_spec
from parsers.gateway_parser import parse_gateway_config
from sentinel_shared.models import AuthScheme

# ---------------------------------------------------------------------------
# Strategies (reuse the same spec generation as P1)
# ---------------------------------------------------------------------------

HTTP_METHODS = ["get", "post", "put", "delete", "patch"]
VALID_HTTP_METHODS_UPPER = {m.upper() for m in HTTP_METHODS}

_segment = st.from_regex(r"[a-zA-Z][a-zA-Z0-9_]{0,15}", fullmatch=True)
_path = st.lists(_segment, min_size=1, max_size=3).map(lambda s: "/" + "/".join(s))
_host_url = st.from_regex(r"[a-zA-Z][a-zA-Z0-9\-]{0,15}\.example\.com", fullmatch=True)


def openapi3_spec_strategy(host: str = "api.example.com") -> st.SearchStrategy[dict]:
    """Generate a minimal valid OpenAPI 3.0 spec dict."""
    paths_strategy = st.dictionaries(
        _path,
        st.lists(st.sampled_from(HTTP_METHODS), min_size=1, max_size=4, unique=True),
        min_size=1,
        max_size=5,
    )

    def build_spec(paths_dict: dict) -> dict:
        paths = {}
        for path, methods in paths_dict.items():
            path_item = {}
            for method in methods:
                path_item[method] = {"responses": {"200": {"description": "ok"}}}
            paths[path] = path_item

        return {
            "openapi": "3.0.0",
            "info": {"title": "Generated API", "version": "1.0.0"},
            "servers": [{"url": f"https://{host}"}],
            "paths": paths,
        }

    return paths_strategy.map(build_spec)


def kong_config_strategy() -> st.SearchStrategy[dict]:
    """Generate a minimal valid Kong gateway config."""
    _host = st.from_regex(r"[a-zA-Z][a-zA-Z0-9\-]{0,15}\.internal", fullmatch=True)
    _route_path = st.lists(_segment, min_size=1, max_size=2).map(lambda s: "/" + "/".join(s))
    _methods = st.lists(
        st.sampled_from(["GET", "POST", "PUT", "DELETE"]),
        min_size=1,
        max_size=3,
        unique=True,
    )

    return st.builds(
        lambda host, path, methods: {
            "services": [
                {
                    "name": "test-service",
                    "host": host,
                    "routes": [{"paths": [path], "methods": methods}],
                }
            ]
        },
        host=_host,
        path=_route_path,
        methods=_methods,
    )


# ---------------------------------------------------------------------------
# Property 5a: All required fields are non-null in OpenAPI-parsed records
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(spec=openapi3_spec_strategy(), file_name=st.from_regex(r"[a-zA-Z0-9_\-]{1,20}\.json", fullmatch=True))
def test_openapi_records_have_all_required_fields(spec: dict, file_name: str):
    """
    **Validates: Requirements 1.6**

    Every record from parse_openapi_spec SHALL have non-null/non-empty values
    for http_method, normalized_path, host, auth_scheme, and source_file_id.
    """
    content = json.dumps(spec)
    records = parse_openapi_spec(content, file_name=file_name, default_host="api.example.com")

    for record in records:
        # http_method: non-empty string, valid HTTP method
        assert record.http_method, f"http_method is empty for record {record}"
        assert record.http_method in VALID_HTTP_METHODS_UPPER, (
            f"http_method '{record.http_method}' is not a valid HTTP method"
        )

        # normalized_path: non-empty, starts with "/"
        assert record.normalized_path, f"normalized_path is empty for record {record}"
        assert record.normalized_path.startswith("/"), (
            f"normalized_path '{record.normalized_path}' does not start with '/'"
        )

        # host: non-empty
        assert record.host, f"host is empty for record {record}"
        assert record.host.strip(), f"host is whitespace-only for record {record}"

        # auth_scheme: not None (may be UNKNOWN)
        assert record.auth_scheme is not None, (
            f"auth_scheme is None for record {record}"
        )
        assert isinstance(record.auth_scheme, AuthScheme), (
            f"auth_scheme '{record.auth_scheme}' is not an AuthScheme instance"
        )

        # source_file_id: must equal the provided file_name
        assert record.source_file_id == file_name, (
            f"source_file_id '{record.source_file_id}' != provided file_name '{file_name}'"
        )


# ---------------------------------------------------------------------------
# Property 5b: All required fields are non-null in Kong-parsed records
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(config=kong_config_strategy(), file_name=st.from_regex(r"[a-zA-Z0-9_\-]{1,20}\.json", fullmatch=True))
def test_kong_records_have_all_required_fields(config: dict, file_name: str):
    """
    **Validates: Requirements 1.6**

    Every record from parse_gateway_config (Kong format) SHALL have non-null/non-empty
    values for http_method, normalized_path, host, and auth_scheme.
    """
    content = json.dumps(config)
    records = parse_gateway_config(content, source_file_id=file_name)

    for record in records:
        assert record.http_method, f"http_method is empty for record {record}"
        assert record.http_method in VALID_HTTP_METHODS_UPPER, (
            f"http_method '{record.http_method}' is not a valid HTTP method"
        )
        assert record.normalized_path, f"normalized_path is empty for record {record}"
        assert record.normalized_path.startswith("/"), (
            f"normalized_path '{record.normalized_path}' does not start with '/'"
        )
        assert record.host, f"host is empty for record {record}"
        assert record.auth_scheme is not None, f"auth_scheme is None for record {record}"
        assert isinstance(record.auth_scheme, AuthScheme), (
            f"auth_scheme '{record.auth_scheme}' is not an AuthScheme instance"
        )


# ---------------------------------------------------------------------------
# Property 5c: source_file_id is None when no file_name is provided
# ---------------------------------------------------------------------------


@settings(max_examples=15)
@given(spec=openapi3_spec_strategy())
def test_source_file_id_is_none_when_no_file_name(spec: dict):
    """
    **Validates: Requirements 1.6**

    When no file_name is provided to parse_openapi_spec, source_file_id
    SHALL be None for all records.
    """
    content = json.dumps(spec)
    records = parse_openapi_spec(content, file_name="", default_host="api.example.com")

    for record in records:
        assert record.source_file_id is None, (
            f"Expected source_file_id=None when no file_name provided, "
            f"got '{record.source_file_id}'"
        )


# ---------------------------------------------------------------------------
# Property 5d: auth_scheme is always a valid AuthScheme enum value
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(spec=openapi3_spec_strategy())
def test_auth_scheme_is_always_valid_enum_value(spec: dict):
    """
    **Validates: Requirements 1.6**

    The auth_scheme field of every record SHALL be a valid AuthScheme enum value
    (OAuth2, JWT, api_key, none, or unknown).
    """
    valid_schemes = set(AuthScheme)
    content = json.dumps(spec)
    records = parse_openapi_spec(content, file_name="spec.json", default_host="api.example.com")

    for record in records:
        assert record.auth_scheme in valid_schemes, (
            f"auth_scheme '{record.auth_scheme}' is not in valid AuthScheme values {valid_schemes}"
        )


