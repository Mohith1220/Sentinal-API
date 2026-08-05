"""
Path normalization utilities for SentinelAPI.

Replaces concrete parameter values (UUIDs, numeric IDs, dates) in URL paths
with parameterized template equivalents using a configurable regex table.
"""

import re
from typing import List, Tuple

# Default normalization rules: (pattern, replacement)
# Evaluated in order; first match wins for each path segment.
DEFAULT_NORMALIZATION_RULES: List[Tuple[re.Pattern, str]] = [
    # UUID (e.g. 550e8400-e29b-41d4-a716-446655440000)
    (
        re.compile(
            r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
        ),
        "{id}",
    ),
    # ISO date (e.g. 2024-01-15)
    (
        re.compile(r"^\d{4}-\d{2}-\d{2}$"),
        "{date}",
    ),
    # Pure numeric ID (e.g. 12345)
    (
        re.compile(r"^\d+$"),
        "{n}",
    ),
]

# Module-level mutable rules list — callers may replace this to customise behaviour.
_normalization_rules: List[Tuple[re.Pattern, str]] = list(DEFAULT_NORMALIZATION_RULES)


def set_normalization_rules(rules: List[Tuple[re.Pattern, str]]) -> None:
    """Replace the active normalization rule table."""
    global _normalization_rules
    _normalization_rules = list(rules)


def get_normalization_rules() -> List[Tuple[re.Pattern, str]]:
    """Return a copy of the active normalization rule table."""
    return list(_normalization_rules)


def normalize_path(raw_path: str) -> str:
    """
    Normalize a URL path by replacing concrete parameter values with
    parameterized template equivalents.

    Examples:
        /accounts/12345          -> /accounts/{n}
        /users/550e8400-...      -> /users/{id}
        /reports/2024-01-15      -> /reports/{date}
        /v1/items/42/details     -> /v1/items/{n}/details
        /health                  -> /health  (unchanged)

    Args:
        raw_path: The raw URL path string (may include leading slash).

    Returns:
        The normalized path string with concrete values replaced.
    """
    if not raw_path:
        return raw_path

    # Preserve leading and trailing slashes independently
    leading_slash = raw_path.startswith("/")
    trailing_slash = raw_path.endswith("/") and len(raw_path) > 1

    # Strip only leading slash before splitting; preserve trailing slash info
    stripped = raw_path.lstrip("/")
    if trailing_slash:
        stripped = stripped.rstrip("/")
    parts = stripped.split("/")

    normalized_parts: List[str] = []
    for segment in parts:
        replaced = False
        for pattern, replacement in _normalization_rules:
            if pattern.match(segment):
                normalized_parts.append(replacement)
                replaced = True
                break
        if not replaced:
            normalized_parts.append(segment)

    result = "/".join(normalized_parts)
    if leading_slash:
        result = "/" + result
    if trailing_slash:
        result = result + "/"
    return result
