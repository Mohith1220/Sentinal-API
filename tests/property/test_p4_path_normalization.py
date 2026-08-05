# Feature: sentinel-api, Property 4: Path Parameter Normalization
"""
Property-based tests for Property 4: Path Parameter Normalization.

For any URL path containing concrete parameter values (UUIDs, numeric IDs,
dates, or other values matching the configured normalization patterns), the
normalized form SHALL replace those values with their parameterized template
equivalents, and two paths that differ only in their concrete parameter values
SHALL normalize to the same template string.

**Validates: Requirements 2.5, 3.4**
"""

import re
import string

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from sentinel_shared.normalization import normalize_path

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Hex characters for UUID generation
_hex = "0123456789abcdef"

def uuid_strategy() -> st.SearchStrategy[str]:
    """Generate valid UUID strings matching the normalization UUID pattern."""
    def make_uuid(parts):
        p1, p2, p3, p4, p5 = parts
        return f"{p1}-{p2}-{p3}-{p4}-{p5}"

    return st.builds(
        make_uuid,
        st.tuples(
            st.text(alphabet=_hex, min_size=8, max_size=8),
            st.text(alphabet=_hex, min_size=4, max_size=4),
            st.text(alphabet=_hex, min_size=4, max_size=4),
            st.text(alphabet=_hex, min_size=4, max_size=4),
            st.text(alphabet=_hex, min_size=12, max_size=12),
        ),
    )


def numeric_id_strategy() -> st.SearchStrategy[str]:
    """Generate purely numeric ID strings (one or more digits)."""
    return st.from_regex(r"[0-9]+", fullmatch=True)


def date_strategy() -> st.SearchStrategy[str]:
    """Generate ISO date strings in YYYY-MM-DD format."""
    return st.builds(
        lambda y, m, d: f"{y:04d}-{m:02d}-{d:02d}",
        st.integers(min_value=1000, max_value=9999),
        st.integers(min_value=1, max_value=12),
        st.integers(min_value=1, max_value=28),  # safe range for all months
    )


def static_segment_strategy() -> st.SearchStrategy[str]:
    """Generate path segments that should NOT be normalized (plain words)."""
    # Must not be purely numeric, UUID-shaped, or YYYY-MM-DD
    return st.from_regex(r"[a-zA-Z][a-zA-Z0-9_-]{0,19}", fullmatch=True).filter(
        lambda s: not re.fullmatch(r"\d+", s)
        and not re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
            s,
        )
        and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s)
    )


def path_prefix_strategy() -> st.SearchStrategy[list]:
    """Generate a list of 0–3 static path segments to use as a prefix."""
    return st.lists(static_segment_strategy(), min_size=0, max_size=3)


# ---------------------------------------------------------------------------
# Property 4a: UUID segments normalize to {id}
# ---------------------------------------------------------------------------

@settings(max_examples=10)
@given(
    prefix=path_prefix_strategy(),
    uuid_val=uuid_strategy(),
    suffix=path_prefix_strategy(),
)
def test_uuid_segments_normalize_to_id(prefix, uuid_val, suffix):
    """
    **Validates: Requirements 2.5, 3.4**

    For any path containing a UUID segment, normalize_path SHALL replace
    that segment with {id}.
    """
    segments = prefix + [uuid_val] + suffix
    raw_path = "/" + "/".join(segments)
    result = normalize_path(raw_path)

    # The UUID segment must be replaced with {id}
    result_segments = result.lstrip("/").split("/")
    input_segments = raw_path.lstrip("/").split("/")

    uuid_pattern = re.compile(
        r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    )

    for i, (inp, out) in enumerate(zip(input_segments, result_segments)):
        if uuid_pattern.match(inp):
            assert out == "{id}", (
                f"UUID segment '{inp}' at position {i} was not replaced with {{id}}; "
                f"got '{out}' in path '{raw_path}' -> '{result}'"
            )
        else:
            # Static segments must be preserved unchanged
            assert out == inp, (
                f"Static segment '{inp}' at position {i} was unexpectedly changed to '{out}' "
                f"in path '{raw_path}' -> '{result}'"
            )


# ---------------------------------------------------------------------------
# Property 4b: Numeric segments normalize to {n}
# ---------------------------------------------------------------------------

@settings(max_examples=10)
@given(
    prefix=path_prefix_strategy(),
    numeric_val=numeric_id_strategy(),
    suffix=path_prefix_strategy(),
)
def test_numeric_segments_normalize_to_n(prefix, numeric_val, suffix):
    """
    **Validates: Requirements 2.5, 3.4**

    For any path containing a purely numeric segment, normalize_path SHALL
    replace that segment with {n}.
    """
    segments = prefix + [numeric_val] + suffix
    raw_path = "/" + "/".join(segments)
    result = normalize_path(raw_path)

    result_segments = result.lstrip("/").split("/")
    input_segments = raw_path.lstrip("/").split("/")

    numeric_pattern = re.compile(r"^\d+$")
    uuid_pattern = re.compile(
        r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    )
    date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    for i, (inp, out) in enumerate(zip(input_segments, result_segments)):
        if numeric_pattern.match(inp) and not uuid_pattern.match(inp) and not date_pattern.match(inp):
            assert out == "{n}", (
                f"Numeric segment '{inp}' at position {i} was not replaced with {{n}}; "
                f"got '{out}' in path '{raw_path}' -> '{result}'"
            )
        elif inp in prefix + suffix:
            # Static segments must be preserved
            assert out == inp, (
                f"Static segment '{inp}' at position {i} was unexpectedly changed to '{out}' "
                f"in path '{raw_path}' -> '{result}'"
            )


# ---------------------------------------------------------------------------
# Property 4c: Date segments normalize to {date}
# ---------------------------------------------------------------------------

@settings(max_examples=10)
@given(
    prefix=path_prefix_strategy(),
    date_val=date_strategy(),
    suffix=path_prefix_strategy(),
)
def test_date_segments_normalize_to_date(prefix, date_val, suffix):
    """
    **Validates: Requirements 2.5, 3.4**

    For any path containing an ISO date segment (YYYY-MM-DD), normalize_path
    SHALL replace that segment with {date}.
    """
    segments = prefix + [date_val] + suffix
    raw_path = "/" + "/".join(segments)
    result = normalize_path(raw_path)

    result_segments = result.lstrip("/").split("/")
    input_segments = raw_path.lstrip("/").split("/")

    date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    for i, (inp, out) in enumerate(zip(input_segments, result_segments)):
        if date_pattern.match(inp):
            assert out == "{date}", (
                f"Date segment '{inp}' at position {i} was not replaced with {{date}}; "
                f"got '{out}' in path '{raw_path}' -> '{result}'"
            )
        else:
            assert out == inp, (
                f"Static segment '{inp}' at position {i} was unexpectedly changed to '{out}' "
                f"in path '{raw_path}' -> '{result}'"
            )


# ---------------------------------------------------------------------------
# Property 4d: Two paths differing only in concrete parameter values
#              normalize to the same template string
# ---------------------------------------------------------------------------

@settings(max_examples=10)
@given(
    prefix=path_prefix_strategy(),
    uuid_a=uuid_strategy(),
    uuid_b=uuid_strategy(),
    suffix=path_prefix_strategy(),
)
def test_two_uuid_paths_same_template(prefix, uuid_a, uuid_b, suffix):
    """
    **Validates: Requirements 2.5, 3.4**

    Two paths that differ only in their UUID parameter values SHALL normalize
    to the same template string.
    """
    path_a = "/" + "/".join(prefix + [uuid_a] + suffix)
    path_b = "/" + "/".join(prefix + [uuid_b] + suffix)

    assert normalize_path(path_a) == normalize_path(path_b), (
        f"Paths differing only in UUID values produced different templates:\n"
        f"  '{path_a}' -> '{normalize_path(path_a)}'\n"
        f"  '{path_b}' -> '{normalize_path(path_b)}'"
    )


@settings(max_examples=10)
@given(
    prefix=path_prefix_strategy(),
    num_a=numeric_id_strategy(),
    num_b=numeric_id_strategy(),
    suffix=path_prefix_strategy(),
)
def test_two_numeric_paths_same_template(prefix, num_a, num_b, suffix):
    """
    **Validates: Requirements 2.5, 3.4**

    Two paths that differ only in their numeric parameter values SHALL normalize
    to the same template string.
    """
    path_a = "/" + "/".join(prefix + [num_a] + suffix)
    path_b = "/" + "/".join(prefix + [num_b] + suffix)

    assert normalize_path(path_a) == normalize_path(path_b), (
        f"Paths differing only in numeric values produced different templates:\n"
        f"  '{path_a}' -> '{normalize_path(path_a)}'\n"
        f"  '{path_b}' -> '{normalize_path(path_b)}'"
    )


@settings(max_examples=10)
@given(
    prefix=path_prefix_strategy(),
    date_a=date_strategy(),
    date_b=date_strategy(),
    suffix=path_prefix_strategy(),
)
def test_two_date_paths_same_template(prefix, date_a, date_b, suffix):
    """
    **Validates: Requirements 2.5, 3.4**

    Two paths that differ only in their date parameter values SHALL normalize
    to the same template string.
    """
    path_a = "/" + "/".join(prefix + [date_a] + suffix)
    path_b = "/" + "/".join(prefix + [date_b] + suffix)

    assert normalize_path(path_a) == normalize_path(path_b), (
        f"Paths differing only in date values produced different templates:\n"
        f"  '{path_a}' -> '{normalize_path(path_a)}'\n"
        f"  '{path_b}' -> '{normalize_path(path_b)}'"
    )


@settings(max_examples=10)
@given(
    prefix=path_prefix_strategy(),
    uuid_a=uuid_strategy(),
    uuid_b=uuid_strategy(),
    num_a=numeric_id_strategy(),
    num_b=numeric_id_strategy(),
    date_a=date_strategy(),
    date_b=date_strategy(),
    suffix=path_prefix_strategy(),
)
def test_mixed_parameter_paths_same_template(
    prefix, uuid_a, uuid_b, num_a, num_b, date_a, date_b, suffix
):
    """
    **Validates: Requirements 2.5, 3.4**

    Two paths with the same structure but different concrete values for all
    parameter types (UUID, numeric, date) SHALL normalize to the same template.
    """
    path_a = "/" + "/".join(prefix + [uuid_a, num_a, date_a] + suffix)
    path_b = "/" + "/".join(prefix + [uuid_b, num_b, date_b] + suffix)

    assert normalize_path(path_a) == normalize_path(path_b), (
        f"Paths differing only in mixed parameter values produced different templates:\n"
        f"  '{path_a}' -> '{normalize_path(path_a)}'\n"
        f"  '{path_b}' -> '{normalize_path(path_b)}'"
    )

