# Feature: sentinel-api, Property 19: JWT Rejection
"""
Property 19: JWT Rejection

For any JWT that is expired, has an invalid signature, or is structurally
malformed, the API Gateway SHALL return HTTP 401 and SHALL not grant access
to any protected resource.

Validates: Requirements 12.3
"""

import sys
import os
from datetime import datetime, timezone, timedelta

from hypothesis import given, settings, assume
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
SERVICE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "services", "api-gateway"
)
if SERVICE_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(SERVICE_DIR))

from auth import validate_jwt, TokenExpiredError, InvalidTokenError, ALGORITHM

# ---------------------------------------------------------------------------
# RSA key pair generation (done once at module level)
# ---------------------------------------------------------------------------

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from jose import jwt as jose_jwt


def _gen_rsa_pair():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return priv_pem, pub_pem


# Generate two key pairs: one for signing, one as the "wrong" key
_PRIVATE_KEY, _PUBLIC_KEY = _gen_rsa_pair()
_OTHER_PRIVATE_KEY, _OTHER_PUBLIC_KEY = _gen_rsa_pair()


def _make_token(payload: dict, private_key: str = _PRIVATE_KEY) -> str:
    return jose_jwt.encode(payload, private_key, algorithm=ALGORITHM)


def _future_exp() -> int:
    return int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())


def _past_exp() -> int:
    return int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp())


# ---------------------------------------------------------------------------
# Strategies for malformed JWT strings
# ---------------------------------------------------------------------------

# Strings that are clearly not valid JWTs
malformed_jwt_st = st.one_of(
    st.just(""),
    st.just("not-a-jwt"),
    st.just("header.payload"),                    # missing signature segment
    st.just("a.b.c.d"),                           # too many segments
    st.just("eyJhbGciOiJSUzI1NiJ9.bad.sig"),      # bad base64 payload
    st.text(min_size=1, max_size=50).filter(
        lambda s: s.count(".") != 2               # not a 3-part JWT
    ),
)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


@given(malformed=malformed_jwt_st)
@settings(max_examples=10)
def test_p19_malformed_jwt_always_rejected(malformed: str):
    """
    **Validates: Requirements 12.3**

    Any structurally malformed JWT string SHALL raise InvalidTokenError
    and SHALL NOT grant access.
    """
    with pytest.raises((InvalidTokenError, TokenExpiredError)):
        validate_jwt(malformed, _PUBLIC_KEY)


def test_p19_expired_jwt_raises_token_expired():
    """
    **Validates: Requirements 12.3**

    An expired JWT SHALL raise TokenExpiredError.
    """
    payload = {"sub": "user-1", "role": "admin", "exp": _past_exp()}
    token = _make_token(payload)

    with pytest.raises(TokenExpiredError):
        validate_jwt(token, _PUBLIC_KEY)


def test_p19_wrong_signature_raises_invalid_token():
    """
    **Validates: Requirements 12.3**

    A JWT signed with a different private key SHALL raise InvalidTokenError.
    """
    payload = {"sub": "user-1", "role": "admin", "exp": _future_exp()}
    token = _make_token(payload, private_key=_OTHER_PRIVATE_KEY)

    with pytest.raises(InvalidTokenError):
        validate_jwt(token, _PUBLIC_KEY)


def test_p19_tampered_payload_raises_invalid_token():
    """
    **Validates: Requirements 12.3**

    A JWT with a tampered payload (but original signature) SHALL raise
    InvalidTokenError because the signature no longer matches.
    """
    import base64
    import json

    payload = {"sub": "user-1", "role": "viewer", "exp": _future_exp()}
    token = _make_token(payload)

    # Split and tamper with the payload segment
    header, _, signature = token.split(".")

    # Encode a different payload
    tampered_payload = {"sub": "admin-user", "role": "admin", "exp": _future_exp()}
    tampered_b64 = base64.urlsafe_b64encode(
        json.dumps(tampered_payload).encode()
    ).rstrip(b"=").decode()

    tampered_token = f"{header}.{tampered_b64}.{signature}"

    with pytest.raises(InvalidTokenError):
        validate_jwt(tampered_token, _PUBLIC_KEY)


def test_p19_wrong_algorithm_jwt_rejected():
    """
    **Validates: Requirements 12.3**

    A JWT signed with HS256 (symmetric) instead of RS256 SHALL be rejected.
    """
    import hmac
    import hashlib
    import base64
    import json

    # Manually craft an HS256 JWT
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    payload_data = {"sub": "user-1", "role": "admin", "exp": _future_exp()}
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload_data).encode()
    ).rstrip(b"=").decode()
    signing_input = f"{header}.{payload_b64}"
    sig = base64.urlsafe_b64encode(
        hmac.new(b"secret", signing_input.encode(), hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    hs256_token = f"{signing_input}.{sig}"

    with pytest.raises(InvalidTokenError):
        validate_jwt(hs256_token, _PUBLIC_KEY)


def test_p19_valid_jwt_not_rejected():
    """
    **Validates: Requirements 12.3**

    A valid, unexpired JWT with correct signature SHALL NOT raise any error.
    """
    payload = {"sub": "user-1", "role": "analyst", "exp": _future_exp()}
    token = _make_token(payload)

    result = validate_jwt(token, _PUBLIC_KEY)
    assert result["sub"] == "user-1"
    assert result["role"] == "analyst"


@given(
    role=st.sampled_from(["admin", "analyst", "viewer"]),
    sub=st.text(min_size=1, max_size=50),
)
@settings(max_examples=15)
def test_p19_valid_jwt_with_any_role_passes(role: str, sub: str):
    """
    **Validates: Requirements 12.3**

    A valid JWT with any recognised role and any non-empty sub claim
    SHALL pass validation.
    """
    payload = {"sub": sub, "role": role, "exp": _future_exp()}
    token = _make_token(payload)

    result = validate_jwt(token, _PUBLIC_KEY)
    assert result["role"] == role
    assert result["sub"] == sub


# ---------------------------------------------------------------------------
# Import pytest at the top (needed for pytest.raises in property tests)
# ---------------------------------------------------------------------------
import pytest



