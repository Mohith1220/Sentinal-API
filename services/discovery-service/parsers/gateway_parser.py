"""
Gateway configuration parsers for AWS API Gateway, Kong, and Apigee export formats.

Detects the gateway format from the JSON structure and extracts endpoint records.
For unsupported auth plugin types, records auth_scheme = "unknown" and stores
the raw plugin name in metadata["raw_auth_plugin"].
"""

import json
from typing import Any, Optional

import yaml
import structlog

from sentinel_shared.models import EndpointRecord, AuthScheme
from sentinel_shared.normalization import normalize_path
from .openapi_parser import parse_openapi_spec, OpenAPIParseError

logger = structlog.get_logger(__name__)

# HTTP methods recognized in gateway configs
GATEWAY_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "ANY"}

# Known Kong auth plugin names and their AuthScheme mappings
KONG_AUTH_PLUGIN_MAP: dict[str, AuthScheme] = {
    "jwt": AuthScheme.JWT,
    "oauth2": AuthScheme.OAUTH2,
    "key-auth": AuthScheme.API_KEY,
    "key_auth": AuthScheme.API_KEY,
    "basic-auth": AuthScheme.API_KEY,
    "basic_auth": AuthScheme.API_KEY,
    "hmac-auth": AuthScheme.API_KEY,
    "hmac_auth": AuthScheme.API_KEY,
    "ldap-auth": AuthScheme.UNKNOWN,
    "openid-connect": AuthScheme.OAUTH2,
}

# Known Apigee policy names and their AuthScheme mappings
APIGEE_AUTH_POLICY_MAP: dict[str, AuthScheme] = {
    "OAuthV2": AuthScheme.OAUTH2,
    "VerifyAPIKey": AuthScheme.API_KEY,
    "BasicAuthentication": AuthScheme.API_KEY,
    "JWT": AuthScheme.JWT,
    "SAML": AuthScheme.UNKNOWN,
}


class GatewayParseError(Exception):
    """Raised when a gateway config cannot be parsed."""

    def __init__(self, message: str, format_name: str = ""):
        super().__init__(message)
        self.format_name = format_name


def _load_config_content(content: str | bytes) -> dict | list:
    """Parse raw config content (JSON or YAML) into a Python object."""
    if isinstance(content, bytes):
        content = content.decode("utf-8")

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    try:
        return yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise GatewayParseError(f"Failed to parse config as JSON or YAML: {exc}")


def _detect_gateway_format(config: dict) -> str:
    """
    Detect the gateway format from the config structure.

    Returns one of: "aws", "kong", "apigee", "openapi", "unknown"
    """
    if not isinstance(config, dict):
        return "unknown"

    # AWS API Gateway: has openapi/swagger field at root with x-amazon-apigateway-integration
    # OR has paths with x-amazon-apigateway-integration
    if "openapi" in config or "swagger" in config:
        paths = config.get("paths", {})
        for path_item in paths.values():
            if isinstance(path_item, dict):
                for method_item in path_item.values():
                    if isinstance(method_item, dict) and "x-amazon-apigateway-integration" in method_item:
                        return "aws"
        # Plain OpenAPI spec (not AWS)
        return "openapi"

    # Kong: has services array at root
    if "services" in config and isinstance(config.get("services"), list):
        return "kong"

    # Apigee: has proxies or apiProducts array at root
    if "proxies" in config or "apiProducts" in config:
        return "apigee"

    return "unknown"


def _parse_aws_gateway(config: dict, source_file_id: str = "") -> list[EndpointRecord]:
    """
    Parse an AWS API Gateway export (OpenAPI with x-amazon-apigateway-integration extensions).

    AWS exports are OpenAPI specs with additional x-amazon-apigateway-* extensions.
    We use the standard OpenAPI parser but also extract AWS-specific auth info.
    """
    # Extract host from servers or info
    servers = config.get("servers", [])
    host = "unknown"
    if servers:
        url = servers[0].get("url", "")
        if "://" in url:
            url = url.split("://", 1)[1]
        host = url.split("/")[0] or "unknown"

    paths = config.get("paths", {})
    records: list[EndpointRecord] = []

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue

        normalized = normalize_path(path)

        for method, operation in path_item.items():
            if method.lower() not in {m.lower() for m in GATEWAY_HTTP_METHODS}:
                continue
            if not isinstance(operation, dict):
                continue

            # Extract AWS auth from x-amazon-apigateway-auth or security
            auth_scheme = AuthScheme.UNKNOWN
            metadata: dict[str, Any] = {}

            # Check x-amazon-apigateway-auth
            aws_auth = operation.get("x-amazon-apigateway-auth", {})
            if aws_auth:
                auth_type = aws_auth.get("type", "").lower()
                if auth_type == "aws_iam":
                    auth_scheme = AuthScheme.API_KEY
                    metadata["raw_auth_plugin"] = "aws_iam"
                elif auth_type == "cognito_user_pools":
                    auth_scheme = AuthScheme.OAUTH2
                    metadata["raw_auth_plugin"] = "cognito_user_pools"
                elif auth_type == "custom":
                    auth_scheme = AuthScheme.UNKNOWN
                    metadata["raw_auth_plugin"] = aws_auth.get("authorizerId", "custom")
                elif auth_type == "none":
                    auth_scheme = AuthScheme.NONE
                else:
                    auth_scheme = AuthScheme.UNKNOWN
                    metadata["raw_auth_plugin"] = auth_type

            # Check security requirements if no AWS-specific auth found
            if auth_scheme == AuthScheme.UNKNOWN and not metadata.get("raw_auth_plugin"):
                security_reqs = operation.get("security", config.get("security", []))
                if security_reqs == []:
                    auth_scheme = AuthScheme.NONE
                elif security_reqs:
                    scheme_defs = config.get("components", {}).get("securitySchemes", {})
                    for req in security_reqs:
                        for scheme_name in req:
                            scheme_def = scheme_defs.get(scheme_name, {})
                            scheme_type = scheme_def.get("type", "").lower()
                            if scheme_type == "oauth2":
                                auth_scheme = AuthScheme.OAUTH2
                            elif scheme_type == "http":
                                auth_scheme = AuthScheme.JWT
                            elif scheme_type == "apikey":
                                auth_scheme = AuthScheme.API_KEY
                            else:
                                auth_scheme = AuthScheme.UNKNOWN
                                metadata["raw_auth_plugin"] = scheme_name
                            break
                        if auth_scheme != AuthScheme.UNKNOWN:
                            break

            # Handle ANY method
            actual_method = method.upper()
            if actual_method == "ANY":
                # Expand ANY to common methods
                for expanded_method in ["GET", "POST", "PUT", "DELETE"]:
                    record = EndpointRecord(
                        http_method=expanded_method,
                        host=host,
                        normalized_path=normalized,
                        auth_scheme=auth_scheme,
                        source_file_id=source_file_id or None,
                        metadata=dict(metadata),
                    )
                    records.append(record)
            else:
                record = EndpointRecord(
                    http_method=actual_method,
                    host=host,
                    normalized_path=normalized,
                    auth_scheme=auth_scheme,
                    source_file_id=source_file_id or None,
                    metadata=metadata,
                )
                records.append(record)

    return records


def _parse_kong_config(config: dict, source_file_id: str = "") -> list[EndpointRecord]:
    """
    Parse a Kong gateway configuration export.

    Kong config has a 'services' array, each with 'routes' and optional 'plugins'.
    """
    records: list[EndpointRecord] = []
    services = config.get("services", [])

    for service in services:
        if not isinstance(service, dict):
            continue

        # Extract host from service
        host = service.get("host", service.get("name", "unknown"))

        # Extract auth from service-level plugins
        service_auth = AuthScheme.UNKNOWN
        service_auth_metadata: dict[str, Any] = {}
        service_plugins = service.get("plugins", [])
        for plugin in service_plugins:
            if not isinstance(plugin, dict):
                continue
            plugin_name = plugin.get("name", "").lower()
            if plugin_name in KONG_AUTH_PLUGIN_MAP:
                service_auth = KONG_AUTH_PLUGIN_MAP[plugin_name]
                if service_auth == AuthScheme.UNKNOWN:
                    service_auth_metadata["raw_auth_plugin"] = plugin_name
            elif plugin_name:
                service_auth = AuthScheme.UNKNOWN
                service_auth_metadata["raw_auth_plugin"] = plugin_name

        routes = service.get("routes", [])
        for route in routes:
            if not isinstance(route, dict):
                continue

            # Extract paths from route
            route_paths = route.get("paths", ["/"])
            route_methods = route.get("methods", list(GATEWAY_HTTP_METHODS - {"ANY"}))

            # Extract auth from route-level plugins (overrides service-level)
            route_auth = service_auth
            route_auth_metadata = dict(service_auth_metadata)
            route_plugins = route.get("plugins", [])
            for plugin in route_plugins:
                if not isinstance(plugin, dict):
                    continue
                plugin_name = plugin.get("name", "").lower()
                if plugin_name in KONG_AUTH_PLUGIN_MAP:
                    route_auth = KONG_AUTH_PLUGIN_MAP[plugin_name]
                    if route_auth == AuthScheme.UNKNOWN:
                        route_auth_metadata["raw_auth_plugin"] = plugin_name
                    else:
                        route_auth_metadata.pop("raw_auth_plugin", None)
                elif plugin_name:
                    route_auth = AuthScheme.UNKNOWN
                    route_auth_metadata["raw_auth_plugin"] = plugin_name

            for path in route_paths:
                normalized = normalize_path(path)
                for method in route_methods:
                    method_upper = method.upper()
                    if method_upper not in GATEWAY_HTTP_METHODS:
                        continue

                    record = EndpointRecord(
                        http_method=method_upper,
                        host=host,
                        normalized_path=normalized,
                        auth_scheme=route_auth,
                        source_file_id=source_file_id or None,
                        metadata=dict(route_auth_metadata),
                    )
                    records.append(record)

    return records


def _parse_apigee_config(config: dict, source_file_id: str = "") -> list[EndpointRecord]:
    """
    Parse an Apigee gateway configuration export.

    Apigee config has a 'proxies' array, each with proxy endpoints and flows.
    """
    records: list[EndpointRecord] = []
    proxies = config.get("proxies", [])

    for proxy in proxies:
        if not isinstance(proxy, dict):
            continue

        proxy_name = proxy.get("name", "unknown")
        host = proxy.get("basePath", proxy_name)
        if host.startswith("/"):
            host = proxy_name  # Use proxy name as host if basePath is just a path

        # Extract auth from proxy-level policies
        proxy_auth = AuthScheme.UNKNOWN
        proxy_auth_metadata: dict[str, Any] = {}

        policies = proxy.get("policies", [])
        for policy in policies:
            if not isinstance(policy, dict):
                continue
            policy_type = policy.get("type", policy.get("name", ""))
            # Check known Apigee auth policy types
            for known_type, scheme in APIGEE_AUTH_POLICY_MAP.items():
                if known_type.lower() in policy_type.lower():
                    proxy_auth = scheme
                    if scheme == AuthScheme.UNKNOWN:
                        proxy_auth_metadata["raw_auth_plugin"] = policy_type
                    break
            else:
                if policy_type:
                    proxy_auth = AuthScheme.UNKNOWN
                    proxy_auth_metadata["raw_auth_plugin"] = policy_type

        # Extract endpoints from proxy
        endpoints = proxy.get("proxyEndpoints", proxy.get("endpoints", []))
        if not endpoints:
            # If no explicit endpoints, create a catch-all
            endpoints = [{"basePath": "/", "flows": []}]

        for endpoint in endpoints:
            if not isinstance(endpoint, dict):
                continue

            base_path = endpoint.get("basePath", "/")
            flows = endpoint.get("flows", [])

            if not flows:
                # No flows defined — create a generic endpoint
                normalized = normalize_path(base_path)
                record = EndpointRecord(
                    http_method="GET",
                    host=host,
                    normalized_path=normalized,
                    auth_scheme=proxy_auth,
                    source_file_id=source_file_id or None,
                    metadata=dict(proxy_auth_metadata),
                )
                records.append(record)
                continue

            for flow in flows:
                if not isinstance(flow, dict):
                    continue

                # Extract method and path from flow condition
                condition = flow.get("condition", "")
                methods = _extract_apigee_methods(condition)
                path = _extract_apigee_path(condition) or base_path

                normalized = normalize_path(path)

                # Extract flow-level auth policies
                flow_auth = proxy_auth
                flow_auth_metadata = dict(proxy_auth_metadata)
                flow_policies = flow.get("policies", [])
                for policy in flow_policies:
                    if not isinstance(policy, dict):
                        continue
                    policy_type = policy.get("type", policy.get("name", ""))
                    for known_type, scheme in APIGEE_AUTH_POLICY_MAP.items():
                        if known_type.lower() in policy_type.lower():
                            flow_auth = scheme
                            if scheme == AuthScheme.UNKNOWN:
                                flow_auth_metadata["raw_auth_plugin"] = policy_type
                            else:
                                flow_auth_metadata.pop("raw_auth_plugin", None)
                            break
                    else:
                        if policy_type:
                            flow_auth = AuthScheme.UNKNOWN
                            flow_auth_metadata["raw_auth_plugin"] = policy_type

                for method in (methods or ["GET"]):
                    record = EndpointRecord(
                        http_method=method.upper(),
                        host=host,
                        normalized_path=normalized,
                        auth_scheme=flow_auth,
                        source_file_id=source_file_id or None,
                        metadata=dict(flow_auth_metadata),
                    )
                    records.append(record)

    return records


def _extract_apigee_methods(condition: str) -> list[str]:
    """Extract HTTP methods from an Apigee flow condition string."""
    methods = []
    for method in ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]:
        if method in condition.upper():
            methods.append(method)
    return methods or ["GET"]


def _extract_apigee_path(condition: str) -> Optional[str]:
    """Extract path from an Apigee flow condition string."""
    # Look for proxy.pathsuffix patterns like MatchesPath("/some/path")
    import re
    match = re.search(r'proxy\.pathsuffix\s+MatchesPath\s*\(\s*["\']([^"\']+)["\']', condition)
    if match:
        return match.group(1)
    # Look for quoted paths
    match = re.search(r'["\'](/[^"\']*)["\']', condition)
    if match:
        return match.group(1)
    return None


def parse_gateway_config(
    content: str | bytes,
    source_file_id: str = "",
    default_host: str = "unknown",
) -> list[EndpointRecord]:
    """
    Parse a gateway configuration export and extract endpoint records.

    Automatically detects the gateway format (AWS API Gateway, Kong, or Apigee).

    Args:
        content: Raw config content (JSON or YAML string or bytes).
        source_file_id: Optional identifier for the source file.
        default_host: Default host to use if not specified in the config.

    Returns:
        List of EndpointRecord instances.

    Raises:
        GatewayParseError: If the config cannot be parsed or format is unrecognized.
    """
    config = _load_config_content(content)

    if not isinstance(config, dict):
        raise GatewayParseError("Gateway config must be a JSON/YAML object")

    gateway_format = _detect_gateway_format(config)

    logger.info("gateway_format_detected", format=gateway_format, source=source_file_id)

    if gateway_format == "aws":
        return _parse_aws_gateway(config, source_file_id)
    elif gateway_format == "openapi":
        # Plain OpenAPI spec — use the OpenAPI parser
        try:
            return parse_openapi_spec(content, file_name=source_file_id, default_host=default_host)
        except OpenAPIParseError as exc:
            raise GatewayParseError(f"Failed to parse OpenAPI spec: {exc}") from exc
    elif gateway_format == "kong":
        return _parse_kong_config(config, source_file_id)
    elif gateway_format == "apigee":
        return _parse_apigee_config(config, source_file_id)
    else:
        raise GatewayParseError(
            f"Unrecognized gateway config format. Expected AWS API Gateway, Kong, or Apigee format.",
            format_name="unknown",
        )
