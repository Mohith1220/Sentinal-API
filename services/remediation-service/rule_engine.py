"""
Remediation Rule Engine — core recommendation logic for SentinelAPI.

Pure functions with no I/O. Implements four trigger rules:
  - No authentication:              Add authentication (OAuth2/JWT/API key)
  - Zombie/Orphaned lifecycle:      Disable endpoint at gateway
  - Traffic anomaly confirmed:      Apply rate limiting (derived threshold)
  - PII/financial + no TLS:         Enforce TLS; cite PCI-DSS or GDPR

Only generates recommendations when risk_score >= 40.
Returns empty list if risk_score < 40.
"""

from typing import Optional

from sentinel_shared.models import (
    AuthScheme,
    DataSensitivity,
    LifecycleStatus,
    RemediationRecommendation,
)

# ---------------------------------------------------------------------------
# Rule constants
# ---------------------------------------------------------------------------

RULE_NO_AUTH = "no_auth"
RULE_ZOMBIE_ORPHANED = "zombie_orphaned"
RULE_TRAFFIC_ANOMALY = "traffic_anomaly"
RULE_TLS_MISSING = "tls_missing"

# Minimum risk score threshold to generate any recommendations
MIN_RISK_SCORE = 40

# Priority thresholds
CRITICAL_SCORE_THRESHOLD = 70

# Default rate limit when p95_hourly_rate is missing (requests per minute)
DEFAULT_RATE_LIMIT_RPM = 60

# Auth mechanism recommendations by data sensitivity
_AUTH_RECOMMENDATIONS = {
    DataSensitivity.PII: "OAuth2",
    DataSensitivity.FINANCIAL: "OAuth2",
    DataSensitivity.INTERNAL: "JWT",
    DataSensitivity.PUBLIC: "API key",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


from typing import Union

def generate_recommendations(
    endpoint_data: Union[dict, "EndpointRecord"],
    risk_result: Union["RiskScoreResult", None] = None
) -> list[RemediationRecommendation]:
    """
    Generate prioritized remediation recommendations for an endpoint.

    Only generates recommendations when risk_score >= 40.
    Returns an empty list if risk_score < 40.

    Args:
        endpoint_data: A dict or EndpointRecord with endpoint fields. Recognised keys:
            - ``id`` (str): endpoint UUID
            - ``risk_score`` (int): current risk score [0, 100]
            - ``auth_scheme`` (str | AuthScheme | None)
            - ``data_sensitivity`` (str | DataSensitivity | None)
            - ``lifecycle_status`` (str | LifecycleStatus | None)
            - ``has_traffic_anomaly`` (bool | None)
            - ``tls_enabled`` (bool | None)
            - ``p95_hourly_rate`` (float | None): 30-day p95 hourly request rate
            - ``regulatory_standard`` (str | None): "PCI-DSS" or "GDPR"
        risk_result: Optional RiskScoreResult to use for risk_score (overrides endpoint_data)

    Returns:
        A list of ``RemediationRecommendation`` objects, one per triggered rule.
    """
    # Convert EndpointRecord to dict if needed
    if hasattr(endpoint_data, 'model_dump'):
        endpoint_data = endpoint_data.model_dump()
    
    # If risk_result provided, use its score
    if risk_result is not None:
        endpoint_data = dict(endpoint_data)  # Make a copy
        endpoint_data['risk_score'] = risk_result.score
    
    endpoint_id: str = str(endpoint_data.get("id", ""))
    risk_score: int = int(endpoint_data.get("risk_score", 0))

    # Gate: only generate recommendations for endpoints with risk_score >= 40
    if risk_score < MIN_RISK_SCORE:
        return []

    recommendations: list[RemediationRecommendation] = []

    # Resolve field values
    auth_scheme = _resolve_auth_scheme(endpoint_data)
    data_sensitivity = _resolve_data_sensitivity(endpoint_data)
    lifecycle_status = _resolve_lifecycle_status(endpoint_data)
    has_traffic_anomaly = bool(endpoint_data.get("has_traffic_anomaly", False))
    tls_enabled = endpoint_data.get("tls_enabled")
    p95_hourly_rate = endpoint_data.get("p95_hourly_rate")
    regulatory_standard = endpoint_data.get("regulatory_standard") or "PCI-DSS"

    # ------------------------------------------------------------------
    # Rule 1: No Auth → Add Authentication
    # ------------------------------------------------------------------
    if auth_scheme == AuthScheme.NONE:
        rec = _build_no_auth_recommendation(
            endpoint_id, risk_score, data_sensitivity
        )
        recommendations.append(rec)

    # ------------------------------------------------------------------
    # Rule 2: Zombie/Orphaned → Disable at Gateway
    # ------------------------------------------------------------------
    if lifecycle_status in (LifecycleStatus.ZOMBIE, LifecycleStatus.ORPHANED):
        rec = _build_zombie_orphaned_recommendation(
            endpoint_id, risk_score, lifecycle_status
        )
        recommendations.append(rec)

    # ------------------------------------------------------------------
    # Rule 3: Traffic Anomaly → Rate Limit
    # ------------------------------------------------------------------
    if has_traffic_anomaly:
        rec = _build_traffic_anomaly_recommendation(
            endpoint_id, p95_hourly_rate
        )
        recommendations.append(rec)

    # ------------------------------------------------------------------
    # Rule 4: PII/Financial + No TLS → Enforce TLS
    # ------------------------------------------------------------------
    if data_sensitivity in (DataSensitivity.PII, DataSensitivity.FINANCIAL):
        # tls_enabled missing or False triggers the rule
        if not tls_enabled:
            rec = _build_tls_missing_recommendation(
                endpoint_id, data_sensitivity, regulatory_standard
            )
            recommendations.append(rec)

    return recommendations


# ---------------------------------------------------------------------------
# Rule builders
# ---------------------------------------------------------------------------


def _build_no_auth_recommendation(
    endpoint_id: str,
    risk_score: int,
    data_sensitivity: DataSensitivity,
) -> RemediationRecommendation:
    """Build a recommendation for the no-auth rule."""
    priority = "Critical" if risk_score >= CRITICAL_SCORE_THRESHOLD else "High"
    auth_mechanism = _AUTH_RECOMMENDATIONS.get(data_sensitivity, "JWT")

    summary_text = (
        f"Endpoint has no authentication. "
        f"Add {auth_mechanism} authentication to protect this endpoint."
    )
    detail_json = {
        "rule": RULE_NO_AUTH,
        "auth_scheme_detected": "none",
        "recommended_mechanism": auth_mechanism,
        "data_sensitivity": data_sensitivity.value,
        "risk_score": risk_score,
        "action": "Add authentication to the endpoint",
    }

    return RemediationRecommendation(
        endpoint_id=endpoint_id,
        priority=priority,
        trigger_rule=RULE_NO_AUTH,
        summary_text=summary_text,
        detail_json=detail_json,
    )


def _build_zombie_orphaned_recommendation(
    endpoint_id: str,
    risk_score: int,
    lifecycle_status: LifecycleStatus,
) -> RemediationRecommendation:
    """Build a recommendation for the zombie/orphaned rule."""
    priority = "Critical" if risk_score >= CRITICAL_SCORE_THRESHOLD else "High"
    status_label = lifecycle_status.value

    summary_text = (
        f"Endpoint has lifecycle status '{status_label}'. "
        f"Disable this endpoint at the gateway to prevent unauthorized access."
    )
    detail_json = {
        "rule": RULE_ZOMBIE_ORPHANED,
        "lifecycle_status": status_label,
        "risk_score": risk_score,
        "action": "Disable endpoint at the API gateway",
        "steps": [
            "Identify the gateway route configuration for this endpoint",
            "Set the route status to disabled or remove the route",
            "Verify no active consumers depend on this endpoint",
            "Archive or decommission the underlying service if applicable",
        ],
    }

    return RemediationRecommendation(
        endpoint_id=endpoint_id,
        priority=priority,
        trigger_rule=RULE_ZOMBIE_ORPHANED,
        summary_text=summary_text,
        detail_json=detail_json,
    )


def _build_traffic_anomaly_recommendation(
    endpoint_id: str,
    p95_hourly_rate: Optional[float],
) -> RemediationRecommendation:
    """Build a recommendation for the traffic anomaly rule."""
    # Derive rate limit threshold from p95_hourly_rate
    if p95_hourly_rate is not None:
        # Convert p95 hourly rate to requests per minute
        rate_limit_rpm = max(1, int(p95_hourly_rate / 60))
        threshold_source = "derived from 30-day p95 hourly baseline"
    else:
        rate_limit_rpm = DEFAULT_RATE_LIMIT_RPM
        threshold_source = "conservative default (p95 hourly rate unavailable)"

    summary_text = (
        f"Traffic anomaly detected on this endpoint. "
        f"Apply rate limiting at {rate_limit_rpm} requests/minute to mitigate abuse."
    )
    detail_json = {
        "rule": RULE_TRAFFIC_ANOMALY,
        "recommended_rate_limit_rpm": rate_limit_rpm,
        "threshold_source": threshold_source,
        "p95_hourly_rate": p95_hourly_rate,
        "action": "Apply rate limiting at the API gateway",
        "steps": [
            f"Configure rate limit of {rate_limit_rpm} requests/minute for this endpoint",
            "Enable burst allowance of 2x the rate limit for short spikes",
            "Set up alerting when rate limit is exceeded",
        ],
    }

    return RemediationRecommendation(
        endpoint_id=endpoint_id,
        priority="High",
        trigger_rule=RULE_TRAFFIC_ANOMALY,
        summary_text=summary_text,
        detail_json=detail_json,
    )


def _build_tls_missing_recommendation(
    endpoint_id: str,
    data_sensitivity: DataSensitivity,
    regulatory_standard: str,
) -> RemediationRecommendation:
    """Build a recommendation for the TLS missing rule."""
    sensitivity_label = data_sensitivity.value

    summary_text = (
        f"Endpoint exposes {sensitivity_label} data without TLS encryption. "
        f"Enforce TLS to comply with {regulatory_standard}."
    )
    detail_json = {
        "rule": RULE_TLS_MISSING,
        "data_sensitivity": sensitivity_label,
        "tls_enabled": False,
        "regulatory_standard": regulatory_standard,
        "action": "Enforce TLS 1.2 or higher on this endpoint",
        "compliance_reference": regulatory_standard,
        "steps": [
            "Obtain a valid TLS certificate from a trusted CA",
            "Configure the API gateway to require HTTPS for this endpoint",
            "Redirect HTTP traffic to HTTPS",
            f"Verify compliance with {regulatory_standard} requirements",
        ],
    }

    return RemediationRecommendation(
        endpoint_id=endpoint_id,
        priority="Critical",
        trigger_rule=RULE_TLS_MISSING,
        summary_text=summary_text,
        detail_json=detail_json,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_auth_scheme(endpoint_data: dict) -> AuthScheme:
    """Resolve auth_scheme from endpoint_data. Defaults to UNKNOWN if missing."""
    raw = endpoint_data.get("auth_scheme")
    if raw is None:
        return AuthScheme.UNKNOWN
    if isinstance(raw, AuthScheme):
        return raw
    try:
        return AuthScheme(raw)
    except ValueError:
        return AuthScheme.UNKNOWN


def _resolve_data_sensitivity(endpoint_data: dict) -> DataSensitivity:
    """Resolve data_sensitivity from endpoint_data. Defaults to INTERNAL if missing."""
    raw = endpoint_data.get("data_sensitivity")
    if raw is None:
        return DataSensitivity.INTERNAL
    if isinstance(raw, DataSensitivity):
        return raw
    try:
        return DataSensitivity(raw)
    except ValueError:
        return DataSensitivity.INTERNAL


def _resolve_lifecycle_status(endpoint_data: dict) -> LifecycleStatus:
    """Resolve lifecycle_status from endpoint_data. Defaults to ACTIVE if missing."""
    raw = endpoint_data.get("lifecycle_status")
    if raw is None:
        return LifecycleStatus.ACTIVE
    if isinstance(raw, LifecycleStatus):
        return raw
    try:
        return LifecycleStatus(raw)
    except ValueError:
        return LifecycleStatus.ACTIVE
