"""
State Builder — converts raw endpoint data into the 18-dimensional RL state vector.

Pulls data from:
  - PostgreSQL (endpoint metadata, risk scores, anomaly history)
  - Neo4j (graph centrality metrics, blast radius)
  - In-memory feedback cache (analyst agreement rates, remediation outcomes)

All values are normalised to [0, 1] or [-1, 1] before being packed into
RLStateVector.
"""

from __future__ import annotations

import math
import logging
from typing import Optional, Any

from models import RLStateVector
from sentinel_shared.models import AuthScheme, DataSensitivity, LifecycleStatus

logger = logging.getLogger(__name__)

# Sentinel values used when graph data is unavailable
_DEFAULT_GRAPH_FEATURES = {
    "pagerank": 0.01,
    "betweenness": 0.0,
    "blast_radius": 0,
    "attack_path_length": 5,
}

# Normalisation constants
MAX_TRAFFIC_RECENCY_DAYS = 90.0
MAX_REQUEST_COUNT_24H_LOG = math.log1p(100_000)    # log(100k + 1)
MAX_ANOMALY_SIGMA = 10.0
MAX_BLAST_RADIUS = 50.0
MAX_ATTACK_PATH = 10.0
MAX_INCIDENT_RATE = 20.0   # incidents per 30 days


# ---------------------------------------------------------------------------
# Auth / Sensitivity / Lifecycle encodings
# ---------------------------------------------------------------------------

_AUTH_ENCODING: dict[str, float] = {
    AuthScheme.NONE.value:    0.00,
    AuthScheme.API_KEY.value: 0.25,
    AuthScheme.JWT.value:     0.50,
    AuthScheme.OAUTH2.value:  0.75,
    AuthScheme.UNKNOWN.value: 1.00,  # unknown = maximally uncertain
}

_SENSITIVITY_ENCODING: dict[str, float] = {
    DataSensitivity.PUBLIC.value:    0.00,
    DataSensitivity.INTERNAL.value:  0.33,
    DataSensitivity.FINANCIAL.value: 0.67,
    DataSensitivity.PII.value:       1.00,
}

_LIFECYCLE_ENCODING: dict[str, float] = {
    LifecycleStatus.ACTIVE.value:     0.00,
    LifecycleStatus.DEPRECATED.value: 0.25,
    LifecycleStatus.ORPHANED.value:   0.50,
    LifecycleStatus.ZOMBIE.value:     0.75,
    LifecycleStatus.SHADOW.value:     1.00,
}


def build_state_vector(
    endpoint: dict,
    graph_features: Optional[dict] = None,
    anomaly_history: Optional[list[dict]] = None,
    feedback_stats: Optional[dict] = None,
) -> RLStateVector:
    """
    Build the normalised 18-dimensional state vector for an endpoint.

    Args:
        endpoint: Row dict from api_endpoints (with risk_score, lifecycle_status, etc.)
        graph_features: Dict with keys: pagerank, betweenness, blast_radius, attack_path_length
        anomaly_history: List of recent anomaly alert dicts for this endpoint
        feedback_stats: Dict with keys: analyst_agreement_rate, remediation_success_rate,
                        false_positive_rate, historical_incident_rate

    Returns:
        Normalised RLStateVector ready for PPO inference.
    """
    gf = graph_features or _DEFAULT_GRAPH_FEATURES
    ah = anomaly_history or []
    fs = feedback_stats or {}

    # ---------------------------------------------------------------
    # API Metadata features
    # ---------------------------------------------------------------
    auth_enc = _AUTH_ENCODING.get(
        str(endpoint.get("auth_scheme", "unknown")), 1.0
    )
    sens_enc = _SENSITIVITY_ENCODING.get(
        str(endpoint.get("data_sensitivity", "internal")), 0.33
    )
    lifecycle_enc = _LIFECYCLE_ENCODING.get(
        str(endpoint.get("lifecycle_status", "Active")), 0.0
    )
    owner_present = 1.0 if endpoint.get("owning_team") else 0.0
    spec_presence = 1.0 if endpoint.get("source_file_id") else 0.0

    # ---------------------------------------------------------------
    # Traffic features
    # ---------------------------------------------------------------
    traffic_recency_days: Optional[float] = endpoint.get("traffic_recency_days")
    if traffic_recency_days is None:
        # Compute from last_access_at if available
        last_access = endpoint.get("last_access_at")
        if last_access:
            from datetime import datetime, timezone
            if isinstance(last_access, str):
                try:
                    ts = datetime.fromisoformat(last_access.replace("Z", "+00:00"))
                    delta = datetime.now(timezone.utc) - ts
                    traffic_recency_days = delta.total_seconds() / 86400.0
                except ValueError:
                    traffic_recency_days = MAX_TRAFFIC_RECENCY_DAYS
            else:
                traffic_recency_days = MAX_TRAFFIC_RECENCY_DAYS
        else:
            traffic_recency_days = MAX_TRAFFIC_RECENCY_DAYS  # treat as stale

    traffic_recency_norm = min(
        traffic_recency_days / MAX_TRAFFIC_RECENCY_DAYS, 1.0
    )

    request_count_24h = float(endpoint.get("request_count_24h", 0))
    traffic_freq_norm = min(
        math.log1p(request_count_24h) / MAX_REQUEST_COUNT_24H_LOG, 1.0
    )

    traffic_trend = float(endpoint.get("traffic_trend", 0.0))
    traffic_trend_norm = float(max(-1.0, min(1.0, traffic_trend)))

    # ---------------------------------------------------------------
    # Graph Intelligence features
    # ---------------------------------------------------------------
    pagerank = float(gf.get("pagerank", 0.01))
    betweenness = float(gf.get("betweenness", 0.0))
    blast_radius = float(gf.get("blast_radius", 0))
    attack_path = float(gf.get("attack_path_length", MAX_ATTACK_PATH))

    pagerank_norm = min(pagerank * 100.0, 1.0)        # PageRank usually tiny
    betweenness_norm = min(betweenness, 1.0)
    blast_radius_norm = min(blast_radius / MAX_BLAST_RADIUS, 1.0)
    attack_path_norm = min(attack_path / MAX_ATTACK_PATH, 1.0)

    # ---------------------------------------------------------------
    # Risk and Anomaly scores
    # ---------------------------------------------------------------
    rule_risk = int(endpoint.get("risk_score", 0))
    rule_risk_norm = min(rule_risk / 100.0, 1.0)

    max_sigma = 0.0
    for alert in ah:
        sigma = float(alert.get("deviation_sigma", 0.0))
        if sigma > max_sigma:
            max_sigma = sigma
    anomaly_sigma_norm = min(max_sigma / MAX_ANOMALY_SIGMA, 1.0)

    # ---------------------------------------------------------------
    # Historical context features
    # ---------------------------------------------------------------
    incident_rate = float(fs.get("historical_incident_rate", 0.0))
    incident_rate_norm = min(
        math.log1p(incident_rate) / math.log1p(MAX_INCIDENT_RATE), 1.0
    )

    analyst_agreement = float(fs.get("analyst_agreement_rate", 0.5))
    analyst_agreement = max(0.0, min(1.0, analyst_agreement))

    remediation_success = float(fs.get("remediation_success_rate", 0.5))
    remediation_success = max(0.0, min(1.0, remediation_success))

    false_positive_rate = float(fs.get("false_positive_rate", 0.1))
    false_positive_rate = max(0.0, min(1.0, false_positive_rate))

    return RLStateVector(
        auth_scheme_encoded=auth_enc,
        data_sensitivity_encoded=sens_enc,
        lifecycle_status_encoded=lifecycle_enc,
        owner_present=owner_present,
        spec_presence=spec_presence,
        traffic_recency_normalized=traffic_recency_norm,
        traffic_frequency_normalized=traffic_freq_norm,
        traffic_trend=traffic_trend_norm,
        pagerank_score=pagerank_norm,
        betweenness_centrality=betweenness_norm,
        blast_radius_normalized=blast_radius_norm,
        attack_path_length_normalized=attack_path_norm,
        rule_risk_score_normalized=rule_risk_norm,
        anomaly_sigma_normalized=anomaly_sigma_norm,
        historical_incident_rate=incident_rate_norm,
        analyst_agreement_rate=analyst_agreement,
        remediation_success_rate=remediation_success,
        false_positive_rate=false_positive_rate,
    )
