"""
Risk Scorer — core scoring logic for SentinelAPI.

Pure functions with no I/O. Implements the four additive scoring rules:
  - No authentication:              +40 pts  (auth_scheme == "none")
  - Sensitive data + weak auth:     +30 pts  (PII/financial AND auth none/unknown)
  - Zombie or Orphaned lifecycle:   +20 pts  (lifecycle_status in Zombie, Orphaned)
  - Abnormal traffic:               +10 pts  (traffic volume > 3σ above 30-day mean)

Score is capped at 100. Missing inputs use conservative defaults:
  - missing auth_scheme       → treated as "none"
  - missing data_sensitivity  → treated as "PII"
  - missing traffic stats     → treated as abnormal

Each substitution is recorded as a named factor entry in the result.
"""

from datetime import datetime, timezone
from typing import Optional, Union
from sentinel_shared.models import (
    EndpointRecord,
    RiskScoreResult,
    RiskFactor,
    AuthScheme,
    DataSensitivity,
    LifecycleStatus,
)

# ---------------------------------------------------------------------------
# Rule constants
# ---------------------------------------------------------------------------

RULE_NO_AUTH = "no_auth"
RULE_SENSITIVE_DATA_WEAK_AUTH = "sensitive_data_weak_auth"
RULE_ZOMBIE_ORPHANED = "zombie_orphaned"
RULE_ABNORMAL_TRAFFIC = "abnormal_traffic"

# Default substitution rule names (recorded in factors when a default is applied)
RULE_DEFAULT_AUTH_SCHEME = "default_auth_scheme"
RULE_DEFAULT_DATA_SENSITIVITY = "default_data_sensitivity"
RULE_DEFAULT_TRAFFIC_STATS = "default_traffic_stats"

POINTS_NO_AUTH = 40
POINTS_SENSITIVE_DATA_WEAK_AUTH = 30
POINTS_ZOMBIE_ORPHANED = 20
POINTS_ABNORMAL_TRAFFIC = 10

MAX_SCORE = 100

# Auth schemes considered "weak" for the sensitive-data rule
_WEAK_AUTH_SCHEMES = {AuthScheme.NONE, AuthScheme.UNKNOWN}

# Data sensitivity values that trigger the sensitive-data rule
_SENSITIVE_DATA_VALUES = {DataSensitivity.PII, DataSensitivity.FINANCIAL}

# Lifecycle statuses that trigger the zombie/orphaned rule
_RISKY_LIFECYCLE_STATUSES = {LifecycleStatus.ZOMBIE, LifecycleStatus.ORPHANED}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_risk_score(endpoint_data: Union[dict, EndpointRecord]) -> RiskScoreResult:
    """
    Compute the risk score for an endpoint from its data dict or EndpointRecord.

    Applies all four additive rules, caps the total at 100, and returns a
    ``RiskScoreResult`` whose ``factors`` list contains exactly one entry per
    contributing rule (including any conservative-default substitutions).

    Args:
        endpoint_data: A dict or EndpointRecord with endpoint fields. Recognised keys:
            - ``id`` (str): endpoint UUID
            - ``auth_scheme`` (str | AuthScheme | None)
            - ``data_sensitivity`` (str | DataSensitivity | None)
            - ``lifecycle_status`` (str | LifecycleStatus | None)
            - ``is_traffic_abnormal`` (bool | None): explicit flag; if None,
              ``traffic_mean`` and ``traffic_stddev`` and ``traffic_current``
              are used to derive abnormality (current > mean + 3*stddev).
              If all traffic stats are missing, treated as abnormal.

    Returns:
        A ``RiskScoreResult`` with the computed score and contributing factors.
    """
    # Convert EndpointRecord to dict if needed
    if isinstance(endpoint_data, EndpointRecord):
        endpoint_data = endpoint_data.model_dump()
    
    endpoint_id: str = str(endpoint_data.get("id", ""))
    factors: list[RiskFactor] = []
    total_points = 0

    # ------------------------------------------------------------------
    # Resolve auth_scheme (with conservative default)
    # ------------------------------------------------------------------
    auth_scheme, auth_defaulted = _resolve_auth_scheme(endpoint_data)
    if auth_defaulted:
        factors.append(
            RiskFactor(
                rule=RULE_DEFAULT_AUTH_SCHEME,
                points=0,
                description=(
                    "auth_scheme was missing or null; defaulted to 'none' "
                    "(conservative assumption: no authentication)"
                ),
            )
        )

    # ------------------------------------------------------------------
    # Resolve data_sensitivity (with conservative default)
    # ------------------------------------------------------------------
    data_sensitivity, sensitivity_defaulted = _resolve_data_sensitivity(endpoint_data)
    if sensitivity_defaulted:
        factors.append(
            RiskFactor(
                rule=RULE_DEFAULT_DATA_SENSITIVITY,
                points=0,
                description=(
                    "data_sensitivity was missing or null; defaulted to 'PII' "
                    "(conservative assumption: sensitive data)"
                ),
            )
        )

    # ------------------------------------------------------------------
    # Resolve traffic abnormality (with conservative default)
    # ------------------------------------------------------------------
    is_abnormal, traffic_defaulted = _resolve_traffic_abnormality(endpoint_data)
    if traffic_defaulted:
        factors.append(
            RiskFactor(
                rule=RULE_DEFAULT_TRAFFIC_STATS,
                points=0,
                description=(
                    "traffic statistics were missing or null; defaulted to abnormal "
                    "(conservative assumption: abnormal traffic)"
                ),
            )
        )

    # ------------------------------------------------------------------
    # Rule 1: No authentication (+40)
    # ------------------------------------------------------------------
    if auth_scheme == AuthScheme.NONE:
        factors.append(
            RiskFactor(
                rule=RULE_NO_AUTH,
                points=POINTS_NO_AUTH,
                description=(
                    f"Endpoint has no authentication scheme "
                    f"(auth_scheme='{auth_scheme.value}')"
                ),
            )
        )
        total_points += POINTS_NO_AUTH

    # ------------------------------------------------------------------
    # Rule 2: Sensitive data + weak auth (+30)
    # ------------------------------------------------------------------
    if data_sensitivity in _SENSITIVE_DATA_VALUES and auth_scheme in _WEAK_AUTH_SCHEMES:
        factors.append(
            RiskFactor(
                rule=RULE_SENSITIVE_DATA_WEAK_AUTH,
                points=POINTS_SENSITIVE_DATA_WEAK_AUTH,
                description=(
                    f"Endpoint transmits sensitive data "
                    f"(data_sensitivity='{data_sensitivity.value}') "
                    f"with weak authentication "
                    f"(auth_scheme='{auth_scheme.value}')"
                ),
            )
        )
        total_points += POINTS_SENSITIVE_DATA_WEAK_AUTH

    # ------------------------------------------------------------------
    # Rule 3: Zombie or Orphaned lifecycle (+20)
    # ------------------------------------------------------------------
    lifecycle_status = _resolve_lifecycle_status(endpoint_data)
    if lifecycle_status in _RISKY_LIFECYCLE_STATUSES:
        factors.append(
            RiskFactor(
                rule=RULE_ZOMBIE_ORPHANED,
                points=POINTS_ZOMBIE_ORPHANED,
                description=(
                    f"Endpoint has risky lifecycle status "
                    f"(lifecycle_status='{lifecycle_status.value}')"
                ),
            )
        )
        total_points += POINTS_ZOMBIE_ORPHANED

    # ------------------------------------------------------------------
    # Rule 4: Abnormal traffic (+10)
    # ------------------------------------------------------------------
    if is_abnormal:
        factors.append(
            RiskFactor(
                rule=RULE_ABNORMAL_TRAFFIC,
                points=POINTS_ABNORMAL_TRAFFIC,
                description=(
                    "Endpoint traffic volume exceeds 3 standard deviations "
                    "above its 30-day hourly mean (abnormal traffic)"
                ),
            )
        )
        total_points += POINTS_ABNORMAL_TRAFFIC

    # ------------------------------------------------------------------
    # Cap score at 100
    # ------------------------------------------------------------------
    final_score = min(total_points, MAX_SCORE)

    return RiskScoreResult(
        endpoint_id=endpoint_id,
        score=final_score,
        factors=factors,
        computed_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_auth_scheme(endpoint_data: dict) -> tuple[AuthScheme, bool]:
    """
    Resolve the auth_scheme from endpoint_data.

    Returns (AuthScheme, defaulted: bool).
    If the value is missing or None, returns (AuthScheme.NONE, True).
    """
    raw = endpoint_data.get("auth_scheme")
    if raw is None:
        return AuthScheme.NONE, True
    if isinstance(raw, AuthScheme):
        return raw, False
    try:
        return AuthScheme(raw), False
    except ValueError:
        # Unknown string value — treat as none (conservative)
        return AuthScheme.NONE, True


def _resolve_data_sensitivity(endpoint_data: dict) -> tuple[DataSensitivity, bool]:
    """
    Resolve the data_sensitivity from endpoint_data.

    Returns (DataSensitivity, defaulted: bool).
    If the value is missing or None, returns (DataSensitivity.PII, True).
    """
    raw = endpoint_data.get("data_sensitivity")
    if raw is None:
        return DataSensitivity.PII, True
    if isinstance(raw, DataSensitivity):
        return raw, False
    try:
        return DataSensitivity(raw), False
    except ValueError:
        # Unknown string value — treat as PII (conservative)
        return DataSensitivity.PII, True


def _resolve_lifecycle_status(endpoint_data: dict) -> LifecycleStatus:
    """
    Resolve the lifecycle_status from endpoint_data.

    Defaults to ACTIVE if missing or unrecognised (non-risky default).
    """
    raw = endpoint_data.get("lifecycle_status")
    if raw is None:
        return LifecycleStatus.ACTIVE
    if isinstance(raw, LifecycleStatus):
        return raw
    try:
        return LifecycleStatus(raw)
    except ValueError:
        return LifecycleStatus.ACTIVE


def _resolve_traffic_abnormality(endpoint_data: dict) -> tuple[bool, bool]:
    """
    Determine whether traffic is abnormal.

    Checks in order:
    1. ``is_traffic_abnormal`` (bool) — explicit flag if present.
    2. Derived from ``traffic_current``, ``traffic_mean``, ``traffic_stddev``:
       abnormal if current > mean + 3 * stddev.
    3. If all traffic stats are missing/None → treat as abnormal (conservative).

    Returns (is_abnormal: bool, defaulted: bool).
    ``defaulted`` is True only when all traffic stats were missing.
    """
    explicit = endpoint_data.get("is_traffic_abnormal")
    if explicit is not None:
        return bool(explicit), False

    current = endpoint_data.get("traffic_current")
    mean = endpoint_data.get("traffic_mean")
    stddev = endpoint_data.get("traffic_stddev")

    if current is None and mean is None and stddev is None:
        # All stats missing — conservative default: treat as abnormal
        return True, True

    # Partial stats: if any required value is missing, treat as abnormal
    if current is None or mean is None or stddev is None:
        return True, True

    try:
        threshold = float(mean) + 3.0 * float(stddev)
        return float(current) > threshold, False
    except (TypeError, ValueError):
        return True, True
