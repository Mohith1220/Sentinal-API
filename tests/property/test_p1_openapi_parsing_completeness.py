# Feature: sentinel-api, Property 1: OpenAPI Spec Parsing Completeness
"""
Property-based tests for Property 1: OpenAPI Spec Parsing Completeness.

For any valid OpenAPI 3.x or Swagger 2.x specification, the number of endpoint
records produced by the Discovery Engine SHALL equal the number of unique
path-method combinations declared in the specification.

**Validates: Requirements 1.1**
"""

import json
import sys
import os

from hypothesis import given, settings, assume
from hypothesis import strategies as st

_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(_REPO_ROOT, "services", "discovery-service"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "sentinel_shared"))

from parsers.openapi_parser import parse_openapi_spec

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

HTTP_METHODS = ["get", "post", "put", "delete", "patch"]

_path_segment = st.from_regex(r"[a-zA-Z][a-zA-Z0-9_]{0,15}", fullmatch=True)
_path_segments = st.lists(_path_segment, min_size=1, max_size=3)


def path_strategy() -> st.SearchStrategy[str]:
    """Generate valid OpenAPI path strings like /users or /items/{id}."""
    return _path_segments.map(lambda segs: "/" + "/".join(segs))


def methods_for_path_strategy() -> st.SearchStrategy[list[str]]:
    """Generate 1–4 distinct HTTP methods for a path."""
    return st.lists(
        st.sampled_from(HTTP_METHODS),
        min_size=1,
        max_size=4,
        unique=True,
    )


def openapi3_spec_strategy() -> st.SearchStrategy[dict]:
    """
    Generate a minimal valid OpenAPI 3.0 spec dict with 1–5 paths,
    each having 1–4 HTTP methods.
    """
    paths_strategy = st.dictionaries(
        path_strategy(),
        methods_for_path_strategy(),
        min_size=1,
        max_size=5,
    )

    def build_spec(paths_dict: dict) -> dict:
        paths = {}
        for path, methods in paths_dict.items():
            path_item = {}
            for method in methods:
                path_item[method] = {
                    "responses": {"200": {"description": "ok"}}
                }
            paths[path] = path_item

        return {
            "openapi": "3.0.0",
            "info": {"title": "Generated API", "version": "1.0.0"},
            "paths": paths,
        }

    return paths_strategy.map(build_spec)


# ---------------------------------------------------------------------------
# Property 1a: Record count equals path-method combination count
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(spec=openapi3_spec_strategy())
def test_record_count_equals_path_method_combinations(spec: dict):
    """
    **Validates: Requirements 1.1**

    For any valid OpenAPI 3.0 spec, the number of endpoint records produced
    SHALL equal the number of unique path-method combinations in the spec.
    """
    # Count expected path-method combinations
    expected_count = sum(
        len([m for m in path_item.keys() if m in HTTP_METHODS])
        for path_item in spec["paths"].values()
    )

    content = json.dumps(spec)
    records = parse_openapi_spec(content, file_name="generated.json", default_host="api.example.com")

    assert len(records) == expected_count, (
        f"Expected {expected_count} records for spec with paths "
        f"{list(spec['paths'].keys())}, got {len(records)}.\n"
        f"Spec: {json.dumps(spec, indent=2)}"
    )


# ---------------------------------------------------------------------------
# Property 1b: Each record's HTTP method matches a declared method in the spec
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(spec=openapi3_spec_strategy())
def test_each_record_method_is_declared_in_spec(spec: dict):
    """
    **Validates: Requirements 1.1**

    Every endpoint record produced by the parser SHALL have an HTTP method
    that was declared in the specification.
    """
    # Collect all declared (path, method) pairs
    declared_methods: set[str] = set()
    for path_item in spec["paths"].values():
        for method in path_item.keys():
            if method in HTTP_METHODS:
                declared_methods.add(method.upper())

    content = json.dumps(spec)
    records = parse_openapi_spec(content, file_name="generated.json", default_host="api.example.com")

    for record in records:
        assert record.http_method in declared_methods, (
            f"Record has method '{record.http_method}' which is not in declared methods "
            f"{declared_methods} for spec paths {list(spec['paths'].keys())}"
        )


# ---------------------------------------------------------------------------
# Property 1c: No duplicate (method, normalized_path) pairs in output
# ---------------------------------------------------------------------------


@settings(max_examples=10)
@given(spec=openapi3_spec_strategy())
def test_no_duplicate_method_path_pairs(spec: dict):
    """
    **Validates: Requirements 1.1**

    The parser SHALL NOT produce duplicate (http_method, normalized_path) pairs
    for a single spec (each path-method combination appears exactly once).
    """
    content = json.dumps(spec)
    records = parse_openapi_spec(content, file_name="generated.json", default_host="api.example.com")

    seen: set[tuple[str, str]] = set()
    for record in records:
        key = (record.http_method, record.normalized_path)
        assert key not in seen, (
            f"Duplicate (method, path) pair found: {key}. "
            f"Records: {[(r.http_method, r.normalized_path) for r in records]}"
        )
        seen.add(key)


# ---------------------------------------------------------------------------
# Property 1d: Empty paths dict produces zero records
# ---------------------------------------------------------------------------


def test_empty_paths_produces_zero_records():
    """
    **Validates: Requirements 1.1**

    A spec with an empty paths object SHALL produce zero endpoint records.
    """
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Empty API", "version": "1.0.0"},
        "paths": {},
    }
    content = json.dumps(spec)
    records = parse_openapi_spec(content, file_name="empty.json", default_host="api.example.com")
    assert records == [], f"Expected no records for empty paths, got {records}"

