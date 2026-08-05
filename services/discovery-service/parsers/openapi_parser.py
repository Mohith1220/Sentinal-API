"""
OpenAPI 3.x and Swagger 2.x specification parser.

Validates specs using openapi-spec-validator and extracts all path-method
combinations, mapping them to EndpointRecord instances.
"""

import json
from typing import Any

import yaml
from openapi_spec_validator import OpenAPIV30SpecValidator, OpenAPIV31SpecValidator
from openapi_spec_validator.validation.exceptions import OpenAPISpecValidatorError, OpenAPIValidationError

from sentinel_shared.models import EndpointRecord, AuthScheme
from sentinel_shared.normalization import normalize_path

# HTTP methods recognized in OpenAPI specs
OPENAPI_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}

# Mapping from OpenAPI securityScheme type to AuthScheme enum
SECURITY_SCHEME_TYPE_MAP: dict[str, AuthScheme] = {
    "oauth2": AuthScheme.OAUTH2,
    "openIdConnect": AuthScheme.OAUTH2,
    "http": AuthScheme.JWT,  # Will be refined by scheme field
    "apiKey": AuthScheme.API_KEY,
}


class OpenAPIParseError(Exception):
    """Raised when an OpenAPI spec cannot be parsed or validated."""

    def __init__(self, message: str, file_name: str = "", validation_error: str = ""):
        super().__init__(message)
        self.file_name = file_name
        self.validation_error = validation_error


def _load_spec_content(content: str | bytes, file_name: str = "") -> dict:
    """
    Parse raw spec content (JSON or YAML) into a Python dict.

    Args:
        content: Raw spec content as string or bytes.
        file_name: Optional file name for error messages.

    Returns:
        Parsed spec as a dictionary.

    Raises:
        OpenAPIParseError: If content cannot be parsed as JSON or YAML.
    """
    if isinstance(content, bytes):
        try:
            content = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise OpenAPIParseError(
                "Spec content is not valid UTF-8",
                file_name=file_name,
                validation_error=str(exc),
            ) from exc

    # Try JSON first
    try:
        result = json.loads(content)
        if not isinstance(result, dict):
            raise OpenAPIParseError(
                "Spec content is not a mapping object",
                file_name=file_name,
                validation_error=f"Root element must be a mapping, got {type(result).__name__}",
            )
        return result
    except json.JSONDecodeError:
        pass

    # Try YAML
    try:
        result = yaml.safe_load(content)
        if not isinstance(result, dict):
            raise OpenAPIParseError(
                f"Spec content is not a mapping object",
                file_name=file_name,
                validation_error="Root element must be a mapping",
            )
        return result
    except yaml.YAMLError as exc:
        raise OpenAPIParseError(
            f"Failed to parse spec as JSON or YAML",
            file_name=file_name,
            validation_error=str(exc),
        ) from exc


def _validate_spec(spec_dict: dict, file_name: str = "") -> None:
    """
    Validate an OpenAPI spec dict against the OpenAPI 3.x or Swagger 2.x schema.

    Args:
        spec_dict: Parsed spec dictionary.
        file_name: Optional file name for error messages.

    Raises:
        OpenAPIParseError: If the spec fails validation.
    """
    # Detect spec version
    openapi_version = spec_dict.get("openapi", "") if isinstance(spec_dict, dict) else ""
    swagger_version = spec_dict.get("swagger", "") if isinstance(spec_dict, dict) else ""

    if not isinstance(spec_dict, dict):
        raise OpenAPIParseError(
            "Spec must be a JSON/YAML object",
            file_name=file_name,
            validation_error=f"Root element must be a mapping, got {type(spec_dict).__name__}",
        )

    if openapi_version.startswith("3.1"):
        validator = OpenAPIV31SpecValidator
    elif openapi_version.startswith("3.0") or openapi_version.startswith("3"):
        validator = OpenAPIV30SpecValidator
    elif swagger_version.startswith("2"):
        # Use OpenAPI 3.0 validator for Swagger 2.x — openapi-spec-validator handles both
        from openapi_spec_validator import OpenAPIV2SpecValidator
        validator = OpenAPIV2SpecValidator
    else:
        raise OpenAPIParseError(
            f"Unrecognized spec version: openapi='{openapi_version}', swagger='{swagger_version}'",
            file_name=file_name,
            validation_error="Missing or unrecognized 'openapi' or 'swagger' version field",
        )

    try:
        validator(spec_dict).validate()
    except (OpenAPISpecValidatorError, OpenAPIValidationError) as exc:
        # Extract the first validation error message
        first_error = str(exc).split("\n")[0] if str(exc) else str(exc)
        raise OpenAPIParseError(
            f"Spec validation failed",
            file_name=file_name,
            validation_error=first_error,
        ) from exc


def _extract_auth_scheme(spec_dict: dict, operation: dict) -> AuthScheme:
    """
    Extract the authentication scheme for an operation.

    Checks operation-level security first, then global security.
    Maps OpenAPI securityScheme types to AuthScheme enum values.

    Args:
        spec_dict: The full spec dictionary.
        operation: The operation object for a specific path-method.

    Returns:
        The AuthScheme for this operation.
    """
    # Get security requirements (operation-level overrides global)
    security_reqs = operation.get("security", spec_dict.get("security", []))

    # Empty security array means explicitly no auth
    if security_reqs == []:
        return AuthScheme.NONE

    if not security_reqs:
        return AuthScheme.UNKNOWN

    # Get security scheme definitions
    # OpenAPI 3.x: components.securitySchemes
    # Swagger 2.x: securityDefinitions
    scheme_defs = (
        spec_dict.get("components", {}).get("securitySchemes", {})
        or spec_dict.get("securityDefinitions", {})
    )

    # Check the first security requirement
    for req in security_reqs:
        for scheme_name in req:
            scheme_def = scheme_defs.get(scheme_name, {})
            scheme_type = scheme_def.get("type", "").lower()

            if scheme_type == "oauth2" or scheme_type == "openidconnect":
                return AuthScheme.OAUTH2
            elif scheme_type == "http":
                http_scheme = scheme_def.get("scheme", "").lower()
                if http_scheme == "bearer":
                    return AuthScheme.JWT
                elif http_scheme == "basic":
                    return AuthScheme.API_KEY  # Basic auth treated as API key
                return AuthScheme.JWT
            elif scheme_type == "apikey":
                return AuthScheme.API_KEY
            elif scheme_type:
                return AuthScheme.UNKNOWN

    return AuthScheme.UNKNOWN


def _extract_host_openapi3(spec_dict: dict) -> str:
    """Extract host from OpenAPI 3.x servers array."""
    servers = spec_dict.get("servers", [])
    if servers:
        url = servers[0].get("url", "")
        # Extract host from URL (strip scheme and path)
        if "://" in url:
            url = url.split("://", 1)[1]
        # Strip path component
        host = url.split("/")[0]
        if host:
            return host
    return "unknown"


def _extract_host_swagger2(spec_dict: dict) -> str:
    """Extract host from Swagger 2.x host field."""
    host = spec_dict.get("host", "")
    if host:
        return host
    return "unknown"


def parse_openapi_spec(
    content: str | bytes,
    file_name: str = "",
    default_host: str = "unknown",
) -> list[EndpointRecord]:
    """
    Parse an OpenAPI 3.x or Swagger 2.x specification and extract endpoint records.

    Args:
        content: Raw spec content (JSON or YAML string or bytes).
        file_name: Optional file name for error messages and source_file_id.
        default_host: Default host to use if not specified in the spec.

    Returns:
        List of EndpointRecord instances, one per path-method combination.

    Raises:
        OpenAPIParseError: If the spec is malformed or fails validation.
    """
    # Parse content
    spec_dict = _load_spec_content(content, file_name)

    # Validate spec
    _validate_spec(spec_dict, file_name)

    # Determine spec version and host
    openapi_version = spec_dict.get("openapi", "")
    swagger_version = spec_dict.get("swagger", "")

    if openapi_version:
        host = _extract_host_openapi3(spec_dict)
    else:
        host = _extract_host_swagger2(spec_dict)

    if host == "unknown" and default_host != "unknown":
        host = default_host

    # Extract paths
    paths = spec_dict.get("paths", {})
    records: list[EndpointRecord] = []

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue

        # Normalize the path (replace concrete values with templates)
        normalized = normalize_path(path)

        for method, operation in path_item.items():
            if method.lower() not in OPENAPI_HTTP_METHODS:
                continue
            if not isinstance(operation, dict):
                continue

            # Extract auth scheme
            auth_scheme = _extract_auth_scheme(spec_dict, operation)

            record = EndpointRecord(
                http_method=method.upper(),
                host=host,
                normalized_path=normalized,
                auth_scheme=auth_scheme,
                source_file_id=file_name or None,
            )
            records.append(record)

    return records
