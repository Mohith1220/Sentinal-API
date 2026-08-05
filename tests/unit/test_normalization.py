"""
Unit tests for sentinel_shared.normalization.normalize_path.

Covers:
- Path with no parameters (unchanged)
- Path with multiple parameters (all replaced)
- Path with trailing slash
- Empty path
- UUID replacement
- Numeric ID replacement
- Date segment replacement
"""

import pytest
from sentinel_shared.normalization import normalize_path, set_normalization_rules, get_normalization_rules, DEFAULT_NORMALIZATION_RULES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def reset_rules():
    """Restore the default normalization rules after a test that mutates them."""
    set_normalization_rules(list(DEFAULT_NORMALIZATION_RULES))


# ---------------------------------------------------------------------------
# No-parameter paths — must be returned unchanged
# ---------------------------------------------------------------------------

class TestNoParameters:
    def test_simple_path_unchanged(self):
        assert normalize_path("/health") == "/health"

    def test_multi_segment_path_unchanged(self):
        assert normalize_path("/api/v1/users") == "/api/v1/users"

    def test_root_path_unchanged(self):
        assert normalize_path("/") == "/"

    def test_version_segment_unchanged(self):
        # "v1" is not purely numeric, so it must not be replaced
        assert normalize_path("/v1/items") == "/v1/items"

    def test_word_segment_unchanged(self):
        assert normalize_path("/accounts/summary") == "/accounts/summary"


# ---------------------------------------------------------------------------
# Empty path
# ---------------------------------------------------------------------------

class TestEmptyPath:
    def test_empty_string_returns_empty(self):
        assert normalize_path("") == ""

    def test_none_like_falsy_empty(self):
        # The function guards on `if not raw_path: return raw_path`
        assert normalize_path("") == ""


# ---------------------------------------------------------------------------
# UUID replacement
# ---------------------------------------------------------------------------

class TestUUIDReplacement:
    def test_uuid_v4_replaced(self):
        path = "/users/550e8400-e29b-41d4-a716-446655440000"
        assert normalize_path(path) == "/users/{id}"

    def test_uuid_uppercase_replaced(self):
        path = "/users/550E8400-E29B-41D4-A716-446655440000"
        assert normalize_path(path) == "/users/{id}"

    def test_uuid_mixed_case_replaced(self):
        path = "/users/550e8400-E29B-41d4-A716-446655440000"
        assert normalize_path(path) == "/users/{id}"

    def test_uuid_in_middle_of_path(self):
        path = "/api/v1/550e8400-e29b-41d4-a716-446655440000/details"
        assert normalize_path(path) == "/api/v1/{id}/details"

    def test_multiple_uuids_replaced(self):
        path = "/orgs/550e8400-e29b-41d4-a716-446655440000/users/6ba7b810-9dad-11d1-80b4-00c04fd430c8"
        assert normalize_path(path) == "/orgs/{id}/users/{id}"


# ---------------------------------------------------------------------------
# Numeric ID replacement
# ---------------------------------------------------------------------------

class TestNumericIDReplacement:
    def test_simple_numeric_id_replaced(self):
        assert normalize_path("/accounts/12345") == "/accounts/{n}"

    def test_single_digit_replaced(self):
        assert normalize_path("/items/0") == "/items/{n}"

    def test_large_number_replaced(self):
        assert normalize_path("/records/9999999999") == "/records/{n}"

    def test_numeric_id_in_middle(self):
        assert normalize_path("/v1/items/42/details") == "/v1/items/{n}/details"

    def test_multiple_numeric_ids_replaced(self):
        assert normalize_path("/users/1/orders/99") == "/users/{n}/orders/{n}"

    def test_alphanumeric_not_replaced(self):
        # "abc123" is not purely numeric
        assert normalize_path("/items/abc123") == "/items/abc123"


# ---------------------------------------------------------------------------
# Date segment replacement
# ---------------------------------------------------------------------------

class TestDateSegmentReplacement:
    def test_iso_date_replaced(self):
        assert normalize_path("/reports/2024-01-15") == "/reports/{date}"

    def test_date_at_start_of_path(self):
        assert normalize_path("/2023-12-31/events") == "/{date}/events"

    def test_date_in_middle_of_path(self):
        assert normalize_path("/api/v1/2024-06-01/summary") == "/api/v1/{date}/summary"

    def test_multiple_dates_replaced(self):
        assert normalize_path("/range/2024-01-01/2024-12-31") == "/range/{date}/{date}"

    def test_partial_date_not_replaced(self):
        # "2024-01" is not a full YYYY-MM-DD date
        assert normalize_path("/archive/2024-01") == "/archive/2024-01"


# ---------------------------------------------------------------------------
# Multiple parameter types in one path
# ---------------------------------------------------------------------------

class TestMultipleParameters:
    def test_uuid_and_numeric_in_same_path(self):
        path = "/orgs/550e8400-e29b-41d4-a716-446655440000/items/42"
        assert normalize_path(path) == "/orgs/{id}/items/{n}"

    def test_uuid_numeric_and_date_in_same_path(self):
        path = "/users/550e8400-e29b-41d4-a716-446655440000/reports/2024-01-15/page/3"
        assert normalize_path(path) == "/users/{id}/reports/{date}/page/{n}"

    def test_all_segments_replaced(self):
        path = "/550e8400-e29b-41d4-a716-446655440000/2024-01-15/99"
        assert normalize_path(path) == "/{id}/{date}/{n}"


# ---------------------------------------------------------------------------
# Trailing slash handling
# ---------------------------------------------------------------------------

class TestTrailingSlash:
    def test_trailing_slash_preserved_on_plain_path(self):
        # strip("/").split("/") on "/health/" gives ["health", ""]
        # The empty segment at the end is preserved as-is
        result = normalize_path("/health/")
        assert result == "/health/"

    def test_trailing_slash_with_numeric_id(self):
        result = normalize_path("/accounts/123/")
        assert result == "/accounts/{n}/"

    def test_trailing_slash_with_uuid(self):
        result = normalize_path("/users/550e8400-e29b-41d4-a716-446655440000/")
        assert result == "/users/{id}/"

    def test_trailing_slash_only(self):
        # "/" stripped → "" → split → [""] → join → "" → prepend "/" → "/"
        assert normalize_path("/") == "/"


# ---------------------------------------------------------------------------
# No leading slash (relative paths)
# ---------------------------------------------------------------------------

class TestNoLeadingSlash:
    def test_relative_path_no_leading_slash(self):
        assert normalize_path("accounts/12345") == "accounts/{n}"

    def test_relative_path_uuid(self):
        assert normalize_path("users/550e8400-e29b-41d4-a716-446655440000") == "users/{id}"


# ---------------------------------------------------------------------------
# Rule priority: UUID before date before numeric
# ---------------------------------------------------------------------------

class TestRulePriority:
    def test_uuid_takes_priority_over_numeric(self):
        # A UUID contains hyphens so it won't match the numeric rule,
        # but this test confirms the UUID rule fires first.
        path = "/items/550e8400-e29b-41d4-a716-446655440000"
        assert normalize_path(path) == "/items/{id}"

    def test_date_takes_priority_over_numeric(self):
        # "2024-01-15" matches the date pattern before the numeric pattern
        # (the numeric pattern only matches purely numeric strings anyway)
        path = "/reports/2024-01-15"
        assert normalize_path(path) == "/reports/{date}"


# ---------------------------------------------------------------------------
# Configurable rules
# ---------------------------------------------------------------------------

class TestConfigurableRules:
    def teardown_method(self, _method):
        reset_rules()

    def test_custom_rule_replaces_segment(self):
        import re
        custom_rules = [(re.compile(r"^v\d+$"), "{version}")]
        set_normalization_rules(custom_rules)
        assert normalize_path("/v1/items") == "/{version}/items"

    def test_empty_rules_leaves_path_unchanged(self):
        set_normalization_rules([])
        assert normalize_path("/users/12345") == "/users/12345"

    def test_get_normalization_rules_returns_copy(self):
        rules = get_normalization_rules()
        rules.clear()
        # Original rules should be unaffected
        assert len(get_normalization_rules()) > 0
