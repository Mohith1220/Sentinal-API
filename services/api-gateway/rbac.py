"""
RBAC enforcement for the API Gateway.

Implements the permission matrix from design §2.8:

  Role     | Inventory | Risk/Alerts | Remediation | Admin Config
  ---------|-----------|-------------|-------------|-------------
  admin    | R/W       | R/W         | R/W         | R/W
  analyst  | R         | R           | R/W         | —
  viewer   | R         | R           | R           | —

Path prefix → category mapping:
  /endpoints              → inventory
  /score, /alerts, /baselines → risk_alerts
  /recommendations        → remediation
  /admin                  → admin
"""

from typing import Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
READ_METHODS = {"GET", "HEAD", "OPTIONS"}

# Categories
CATEGORY_INVENTORY = "inventory"
CATEGORY_RISK_ALERTS = "risk_alerts"
CATEGORY_REMEDIATION = "remediation"
CATEGORY_ADMIN = "admin"
CATEGORY_RL = "rl_intelligence"
CATEGORY_UNKNOWN = "unknown"

# Path prefix → category
PATH_CATEGORY_MAP = {
    "/endpoints": CATEGORY_INVENTORY,
    "/score": CATEGORY_RISK_ALERTS,
    "/alerts": CATEGORY_RISK_ALERTS,
    "/baselines": CATEGORY_RISK_ALERTS,
    "/recommendations": CATEGORY_REMEDIATION,
    "/admin": CATEGORY_ADMIN,
    "/rl": CATEGORY_RL,
}

# ---------------------------------------------------------------------------
# Permission matrix: (role, category, access_type) -> bool
# access_type is "read" or "write"
# ---------------------------------------------------------------------------

PERMISSION_MATRIX: dict[tuple[str, str, str], bool] = {
    # admin: full access everywhere
    ("admin", CATEGORY_INVENTORY, "read"): True,
    ("admin", CATEGORY_INVENTORY, "write"): True,
    ("admin", CATEGORY_RISK_ALERTS, "read"): True,
    ("admin", CATEGORY_RISK_ALERTS, "write"): True,
    ("admin", CATEGORY_REMEDIATION, "read"): True,
    ("admin", CATEGORY_REMEDIATION, "write"): True,
    ("admin", CATEGORY_ADMIN, "read"): True,
    ("admin", CATEGORY_ADMIN, "write"): True,
    ("admin", CATEGORY_RL, "read"): True,
    ("admin", CATEGORY_RL, "write"): True,
    # analyst: read inventory/risk_alerts, read+write remediation and RL, no admin
    ("analyst", CATEGORY_INVENTORY, "read"): True,
    ("analyst", CATEGORY_INVENTORY, "write"): False,
    ("analyst", CATEGORY_RISK_ALERTS, "read"): True,
    ("analyst", CATEGORY_RISK_ALERTS, "write"): False,
    ("analyst", CATEGORY_REMEDIATION, "read"): True,
    ("analyst", CATEGORY_REMEDIATION, "write"): True,
    ("analyst", CATEGORY_ADMIN, "read"): False,
    ("analyst", CATEGORY_ADMIN, "write"): False,
    ("analyst", CATEGORY_RL, "read"): True,
    ("analyst", CATEGORY_RL, "write"): True,   # analysts can submit feedback + trigger predict
    # viewer: read-only everywhere except admin (no access)
    ("viewer", CATEGORY_INVENTORY, "read"): True,
    ("viewer", CATEGORY_INVENTORY, "write"): False,
    ("viewer", CATEGORY_RISK_ALERTS, "read"): True,
    ("viewer", CATEGORY_RISK_ALERTS, "write"): False,
    ("viewer", CATEGORY_REMEDIATION, "read"): True,
    ("viewer", CATEGORY_REMEDIATION, "write"): False,
    ("viewer", CATEGORY_ADMIN, "read"): False,
    ("viewer", CATEGORY_ADMIN, "write"): False,
    ("viewer", CATEGORY_RL, "read"): True,
    ("viewer", CATEGORY_RL, "write"): False,
}

# Minimum role required for each (category, access_type) — used for error hints
REQUIRED_ROLE_HINTS: dict[tuple[str, str], str] = {
    (CATEGORY_INVENTORY, "read"): "viewer",
    (CATEGORY_INVENTORY, "write"): "admin",
    (CATEGORY_RISK_ALERTS, "read"): "viewer",
    (CATEGORY_RISK_ALERTS, "write"): "admin",
    (CATEGORY_REMEDIATION, "read"): "viewer",
    (CATEGORY_REMEDIATION, "write"): "analyst",
    (CATEGORY_ADMIN, "read"): "admin",
    (CATEGORY_ADMIN, "write"): "admin",
    (CATEGORY_RL, "read"): "viewer",
    (CATEGORY_RL, "write"): "analyst",
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def is_write_method(method: str) -> bool:
    """Return True for HTTP methods that mutate state (POST, PUT, PATCH, DELETE)."""
    return method.upper() in WRITE_METHODS


def get_path_category(path: str) -> str:
    """
    Map a request path to its resource category.

    Returns one of: 'inventory', 'risk_alerts', 'remediation', 'admin', 'unknown'.
    """
    normalized = path.rstrip("/")
    for prefix, category in PATH_CATEGORY_MAP.items():
        if normalized == prefix or normalized.startswith(prefix + "/"):
            return category
    return CATEGORY_UNKNOWN


def check_permission(role: str, method: str, path: str) -> Tuple[bool, str]:
    """
    Check whether a role is permitted to perform a given HTTP method on a path.

    Args:
        role: The JWT role claim value (e.g. 'admin', 'analyst', 'viewer').
        method: The HTTP method (e.g. 'GET', 'POST').
        path: The request path (e.g. '/endpoints/abc123').

    Returns:
        A tuple (allowed: bool, required_role_hint: str).
        - allowed is True if the role has permission.
        - required_role_hint is the minimum role needed (empty string if allowed).
    """
    # Normalize subroles to standard permission buckets
    norm_role = (role or "").lower()
    if norm_role in ("admin", "security_admin", "super_admin"):
        norm_role = "admin"
    elif norm_role in ("analyst", "security_analyst", "api_governance_manager", "governance"):
        norm_role = "analyst"
    elif norm_role in ("viewer", "compliance_officer", "compliance"):
        norm_role = "viewer"

    category = get_path_category(path)

    # Unknown paths are allowed through (no RBAC restriction on unrecognised paths)
    if category == CATEGORY_UNKNOWN:
        return True, ""

    access_type = "write" if is_write_method(method) else "read"
    key = (norm_role, category, access_type)

    # Unknown roles are denied
    allowed = PERMISSION_MATRIX.get(key, False)

    if allowed:
        return True, ""

    hint = REQUIRED_ROLE_HINTS.get((category, access_type), "admin")
    return False, hint
