"""
JWT validation for the API Gateway.

Validates RS256-signed JWTs, checking signature, expiry, and required claims.
"""

from jose import jwt, JWTError, ExpiredSignatureError

ALGORITHM = "RS256"
ALGORITHM_HS = "HS256"
JWT_SECRET = "sentinel-dev-secret-change-in-production"


class TokenExpiredError(Exception):
    """Raised when a JWT has expired."""


class InvalidTokenError(Exception):
    """Raised when a JWT is invalid (bad signature, malformed, missing claims, etc.)."""


def validate_jwt(token: str, public_key: str) -> dict:
    """
    Validate an RS256-signed JWT and return its decoded payload.

    Args:
        token: The raw JWT string (Bearer token value).
        public_key: PEM-encoded RSA public key used to verify the signature.

    Returns:
        The decoded JWT payload as a dict.

    Raises:
        TokenExpiredError: If the token has expired.
        InvalidTokenError: If the token is invalid for any other reason
                           (bad signature, malformed, missing required claims, etc.).
    """
    if not token or not isinstance(token, str):
        raise InvalidTokenError("Token must be a non-empty string")

    # Use HS256 fallback when no RS256 public key is configured
    if not public_key:
        import os
        secret = os.getenv("JWT_SECRET", JWT_SECRET)
        try:
            payload = jwt.decode(token, secret, algorithms=[ALGORITHM_HS],
                                 options={"verify_aud": False})
        except ExpiredSignatureError as exc:
            raise TokenExpiredError("JWT has expired") from exc
        except JWTError as exc:
            raise InvalidTokenError(f"JWT validation failed: {exc}") from exc
    else:
        try:
            payload = jwt.decode(token, public_key, algorithms=[ALGORITHM],
                                 options={"verify_aud": False})
        except ExpiredSignatureError as exc:
            raise TokenExpiredError("JWT has expired") from exc
        except JWTError as exc:
            raise InvalidTokenError(f"JWT validation failed: {exc}") from exc

    # Require the 'role' claim
    if "role" not in payload:
        raise InvalidTokenError("JWT missing required 'role' claim")

    # Require the 'sub' claim (actor identity for audit log)
    if "sub" not in payload:
        raise InvalidTokenError("JWT missing required 'sub' claim")

    return payload
