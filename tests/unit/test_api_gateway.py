"""
Unit tests for the API Gateway service.

Tests cover:
  - Valid JWT passes authentication
  - Expired JWT returns HTTP 401 {"error": "token_expired"}
  - Invalid signature returns HTTP 401 {"error": "invalid_token"}
  - Viewer role blocked from write endpoints (POST /endpoints) → HTTP 403
  - Analyst role blocked from admin config (GET /admin/...) → HTTP 403
  - Admin role permitted everywhere
  - RBAC permission matrix correctness
  - Audit log entry extraction
"""

import sys
import os
from datetime import datetime, timezone, timedelta

import pytest

# ---------------------------------------------------------------------------
# Path setup — add api-gateway to sys.path
# ---------------------------------------------------------------------------
SERVICE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "services", "api-gateway"
)
if SERVICE_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(SERVICE_DIR))

from auth import validate_jwt, TokenExpiredError, InvalidTokenError, ALGORITHM
from rbac import (
    check_permission,
    get_path_category,
    is_write_method,
    CATEGORY_INVENTORY,
    CATEGORY_RISK_ALERTS,
    CATEGORY_REMEDIATION,
    CATEGORY_ADMIN,
)
from audit import AuditLogEntry, extract_resource_info


# ---------------------------------------------------------------------------
# RSA key pair generation helper
# ---------------------------------------------------------------------------


def _generate_rsa_key_pair():
    """Generate a fresh RSA-2048 key pair for testing."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    public_pem = private_key.public_key().private_bytes if False else (
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
    )

    return private_pem, public_pem


def _make_jwt(private_key_pem: str, payload: dict) -> str:
    """Sign a JWT with the given RSA private key."""
    from jose import jwt as jose_jwt
    return jose_jwt.encode(payload, private_key_pem, algorithm=ALGORITHM)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rsa_keys():
    """Generate a single RSA key pair for the entire test module."""
    return _generate_rsa_key_pair()


@pytest.fixture(scope="module")
def private_key(rsa_keys):
    return rsa_keys[0]


@pytest.fixture(scope="module")
def public_key(rsa_keys):
    return rsa_keys[1]


# ---------------------------------------------------------------------------
# JWT validation tests
# ---------------------------------------------------------------------------


class TestJWTValidation:
    """Tests for auth.validate_jwt()."""

    def test_valid_jwt_passes(self, private_key, public_key):
        """A well-formed, unexpired JWT with required claims should pass."""
        payload = {
            "sub": "user-123",
            "role": "admin",
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        }
        token = _make_jwt(private_key, payload)
        result = validate_jwt(token, public_key)

        assert result["sub"] == "user-123"
        assert result["role"] == "admin"

    def test_expired_jwt_raises_token_expired_error(self, private_key, public_key):
        """An expired JWT should raise TokenExpiredError."""
        payload = {
            "sub": "user-123",
            "role": "viewer",
            "exp": int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp()),
        }
        token = _make_jwt(private_key, payload)

        with pytest.raises(TokenExpiredError):
            validate_jwt(token, public_key)

    def test_invalid_signature_raises_invalid_token_error(self, public_key):
        """A JWT signed with a different key should raise InvalidTokenError."""
        # Generate a different key pair
        other_private, _ = _generate_rsa_key_pair()
        payload = {
            "sub": "user-123",
            "role": "admin",
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        }
        token = _make_jwt(other_private, payload)

        with pytest.raises(InvalidTokenError):
            validate_jwt(token, public_key)

    def test_malformed_token_raises_invalid_token_error(self, public_key):
        """A completely malformed token string should raise InvalidTokenError."""
        with pytest.raises(InvalidTokenError):
            validate_jwt("not.a.valid.jwt.token", public_key)

    def test_empty_token_raises_invalid_token_error(self, public_key):
        """An empty token should raise InvalidTokenError."""
        with pytest.raises(InvalidTokenError):
            validate_jwt("", public_key)

    def test_missing_role_claim_raises_invalid_token_error(self, private_key, public_key):
        """A JWT without the 'role' claim should raise InvalidTokenError."""
        payload = {
            "sub": "user-123",
            # 'role' is intentionally missing
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        }
        token = _make_jwt(private_key, payload)

        with pytest.raises(InvalidTokenError):
            validate_jwt(token, public_key)

    def test_missing_sub_claim_raises_invalid_token_error(self, private_key, public_key):
        """A JWT without the 'sub' claim should raise InvalidTokenError."""
        payload = {
            # 'sub' is intentionally missing
            "role": "admin",
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        }
        token = _make_jwt(private_key, payload)

        with pytest.raises(InvalidTokenError):
            validate_jwt(token, public_key)

    def test_all_roles_accepted(self, private_key, public_key):
        """Valid JWTs with any of the three roles should pass."""
        for role in ["admin", "analyst", "viewer"]:
            payload = {
                "sub": f"user-{role}",
                "role": role,
                "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
            }
            token = _make_jwt(private_key, payload)
            result = validate_jwt(token, public_key)
            assert result["role"] == role


# ---------------------------------------------------------------------------
# RBAC tests
# ---------------------------------------------------------------------------


class TestRBAC:
    """Tests for rbac.check_permission()."""

    # --- Admin role ---

    def test_admin_can_read_inventory(self):
        allowed, _ = check_permission("admin", "GET", "/endpoints")
        assert allowed is True

    def test_admin_can_write_inventory(self):
        allowed, _ = check_permission("admin", "POST", "/endpoints")
        assert allowed is True

    def test_admin_can_read_admin_config(self):
        allowed, _ = check_permission("admin", "GET", "/admin/settings")
        assert allowed is True

    def test_admin_can_write_admin_config(self):
        allowed, _ = check_permission("admin", "DELETE", "/admin/settings")
        assert allowed is True

    def test_admin_can_read_risk_alerts(self):
        allowed, _ = check_permission("admin", "GET", "/alerts")
        assert allowed is True

    def test_admin_can_write_remediation(self):
        allowed, _ = check_permission("admin", "POST", "/recommendations")
        assert allowed is True

    # --- Analyst role ---

    def test_analyst_can_read_inventory(self):
        allowed, _ = check_permission("analyst", "GET", "/endpoints")
        assert allowed is True

    def test_analyst_cannot_write_inventory(self):
        allowed, required = check_permission("analyst", "POST", "/endpoints")
        assert allowed is False
        assert required  # should have a hint

    def test_analyst_can_read_risk_alerts(self):
        allowed, _ = check_permission("analyst", "GET", "/score/ep-123")
        assert allowed is True

    def test_analyst_cannot_write_risk_alerts(self):
        allowed, required = check_permission("analyst", "POST", "/score/ep-123")
        assert allowed is False

    def test_analyst_can_write_remediation(self):
        allowed, _ = check_permission("analyst", "POST", "/recommendations")
        assert allowed is True

    def test_analyst_cannot_read_admin_config(self):
        """Analyst role should be blocked from admin config (GET /admin/...)."""
        allowed, required = check_permission("analyst", "GET", "/admin/settings")
        assert allowed is False
        assert required == "admin"

    def test_analyst_cannot_write_admin_config(self):
        allowed, required = check_permission("analyst", "DELETE", "/admin/settings")
        assert allowed is False
        assert required == "admin"

    # --- Viewer role ---

    def test_viewer_can_read_inventory(self):
        allowed, _ = check_permission("viewer", "GET", "/endpoints")
        assert allowed is True

    def test_viewer_cannot_write_inventory(self):
        """Viewer role should be blocked from write endpoints (POST /endpoints)."""
        allowed, required = check_permission("viewer", "POST", "/endpoints")
        assert allowed is False
        assert required  # should have a hint

    def test_viewer_can_read_risk_alerts(self):
        allowed, _ = check_permission("viewer", "GET", "/alerts")
        assert allowed is True

    def test_viewer_cannot_write_risk_alerts(self):
        allowed, _ = check_permission("viewer", "POST", "/alerts")
        assert allowed is False

    def test_viewer_can_read_remediation(self):
        allowed, _ = check_permission("viewer", "GET", "/recommendations")
        assert allowed is True

    def test_viewer_cannot_write_remediation(self):
        allowed, _ = check_permission("viewer", "PUT", "/recommendations/rec-123")
        assert allowed is False

    def test_viewer_cannot_read_admin_config(self):
        allowed, required = check_permission("viewer", "GET", "/admin/settings")
        assert allowed is False
        assert required == "admin"

    def test_viewer_cannot_write_admin_config(self):
        allowed, required = check_permission("viewer", "POST", "/admin/settings")
        assert allowed is False
        assert required == "admin"

    # --- Unknown role ---

    def test_unknown_role_denied(self):
        allowed, _ = check_permission("superuser", "GET", "/endpoints")
        assert allowed is False

    # --- Path category mapping ---

    def test_path_category_endpoints(self):
        assert get_path_category("/endpoints") == CATEGORY_INVENTORY
        assert get_path_category("/endpoints/abc-123") == CATEGORY_INVENTORY

    def test_path_category_score(self):
        assert get_path_category("/score/ep-1") == CATEGORY_RISK_ALERTS

    def test_path_category_alerts(self):
        assert get_path_category("/alerts") == CATEGORY_RISK_ALERTS

    def test_path_category_baselines(self):
        assert get_path_category("/baselines/ep-1") == CATEGORY_RISK_ALERTS

    def test_path_category_recommendations(self):
        assert get_path_category("/recommendations") == CATEGORY_REMEDIATION

    def test_path_category_admin(self):
        assert get_path_category("/admin/settings") == CATEGORY_ADMIN

    # --- Write method detection ---

    def test_is_write_method_post(self):
        assert is_write_method("POST") is True

    def test_is_write_method_put(self):
        assert is_write_method("PUT") is True

    def test_is_write_method_patch(self):
        assert is_write_method("PATCH") is True

    def test_is_write_method_delete(self):
        assert is_write_method("DELETE") is True

    def test_is_write_method_get(self):
        assert is_write_method("GET") is False

    def test_is_write_method_head(self):
        assert is_write_method("HEAD") is False


# ---------------------------------------------------------------------------
# Audit log tests
# ---------------------------------------------------------------------------


class TestAuditLog:
    """Tests for audit.extract_resource_info() and AuditLogEntry."""

    def test_extract_resource_info_endpoints_with_id(self):
        resource_type, resource_id = extract_resource_info("/endpoints/abc-123", "GET")
        assert resource_type == "endpoint"
        assert resource_id == "abc-123"

    def test_extract_resource_info_endpoints_no_id(self):
        resource_type, resource_id = extract_resource_info("/endpoints", "GET")
        assert resource_type == "endpoint"
        assert resource_id is None

    def test_extract_resource_info_recommendations(self):
        resource_type, resource_id = extract_resource_info(
            "/recommendations/rec-456/resolve", "POST"
        )
        assert resource_type == "recommendation"
        assert resource_id == "rec-456"

    def test_extract_resource_info_admin(self):
        resource_type, resource_id = extract_resource_info("/admin/settings", "GET")
        assert resource_type == "admin_config"
        assert resource_id == "settings"

    def test_extract_resource_info_score(self):
        resource_type, resource_id = extract_resource_info("/score/ep-789", "GET")
        assert resource_type == "risk_score"
        assert resource_id == "ep-789"

    def test_audit_log_entry_fields(self):
        """AuditLogEntry should have all required fields."""
        now = datetime.now(timezone.utc)
        entry = AuditLogEntry(
            actor_identity="user-123",
            action_type="POST /endpoints",
            resource_type="endpoint",
            resource_id="ep-abc",
            occurred_at=now,
        )
        assert entry.actor_identity == "user-123"
        assert entry.action_type == "POST /endpoints"
        assert entry.resource_type == "endpoint"
        assert entry.resource_id == "ep-abc"
        assert entry.occurred_at == now

    def test_audit_log_entry_occurred_at_is_utc(self):
        """AuditLogEntry.occurred_at should be a UTC datetime."""
        now = datetime.now(timezone.utc)
        entry = AuditLogEntry(
            actor_identity="user-123",
            action_type="DELETE /endpoints/ep-1",
            resource_type="endpoint",
            occurred_at=now,
        )
        assert entry.occurred_at.tzinfo is not None
        assert entry.occurred_at.tzinfo == timezone.utc
