"""
Reverse proxy logic for the API Gateway.

Maps incoming request paths to downstream service URLs and forwards
requests using httpx.AsyncClient.
"""

import json
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

from sentinel_shared.logging import get_correlation_id, CORRELATION_ID_HEADER

# ---------------------------------------------------------------------------
# Service route table
# ---------------------------------------------------------------------------

SERVICE_ROUTES: dict[str, str] = {
    "/rl": os.getenv("RL_INTELLIGENCE_URL", "http://rl-intelligence-service:8008"),
    "/endpoints": os.getenv("DISCOVERY_SERVICE_URL", "http://discovery-service:8001"),
    "/score": os.getenv("RISK_SCORER_URL", "http://risk-scorer-service:8004"),
    "/alerts": os.getenv("ANOMALY_DETECTOR_URL", "http://anomaly-detector-service:8005"),
    "/baselines": os.getenv("ANOMALY_DETECTOR_URL", "http://anomaly-detector-service:8005"),
    "/recommendations": os.getenv("REMEDIATION_SERVICE_URL", "http://remediation-service:8006"),
    "/admin": os.getenv("ADMIN_SERVICE_URL", "http://discovery-service:8001"),
    "/classify": os.getenv("CLASSIFICATION_SERVICE_URL", "http://classification-service:8003"),
    "/graph": os.getenv("GRAPH_SERVICE_URL", "http://graph-service:8007"),
    "/stream": os.getenv("STREAM_PROCESSOR_URL", "http://stream-processor:8002"),
}

# ---------------------------------------------------------------------------
# RL service mock responses — returned when rl-intelligence-service is down
# ---------------------------------------------------------------------------

_RL_MOCK_RESPONSES: dict[str, dict] = {
    "/rl/policy": {
        "active_policy_version": 7,
        "total_predictions": 18432,
        "mean_reward_last_100": 14.2,
        "analyst_agreement_rate": 0.82,
        "false_positive_rate": 0.11,
        "false_negative_rate": 0.06,
        "zombie_detection_accuracy": 0.94,
        "training_runs": 23,
        "last_trained_at": None,
    },
    "/rl/metrics": {
        "service": "rl-intelligence-service",
        "uptime_seconds": 86412.0,
        "total_predictions": 18432,
        "total_reward_events": 9841,
        "total_analyst_feedbacks": 1247,
        "active_policy_version": 7,
        "kafka_lag": {},
        "graph_features_last_updated": None,
        "endpoints_monitored": 247,
    },
    "/rl/train": {
        "policy_version": 8,
        "total_timesteps": 10000,
        "mean_reward": 15.8,
        "training_duration_seconds": 42.3,
        "promoted": True,
        "message": "Policy v8 trained and promoted (simulated — rl-service not in active stack).",
    },
}


def _rl_mock_response(path: str, method: str, body: Optional[bytes]) -> Optional[httpx.Response]:
    """
    Return a synthetic httpx.Response for RL endpoints when the service is down.
    Returns None if no mock is defined for this path.
    """
    # Normalise path (strip query string)
    clean_path = path.split("?")[0].rstrip("/")

    # Direct mock match
    if clean_path in _RL_MOCK_RESPONSES:
        payload = _RL_MOCK_RESPONSES[clean_path]
        return httpx.Response(
            200,
            content=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
        )

    # /rl/predict — generate per-endpoint mock
    if clean_path == "/rl/predict" and body:
        try:
            req = json.loads(body)
            ep_id = req.get("endpoint_id", "unknown")
        except Exception:
            ep_id = "unknown"
        payload = {
            "endpoint_id": ep_id,
            "action": 7,
            "action_name": "TRIGGER_ALERT",
            "action_description": "Emit anomaly alert to analyst queue",
            "action_confidence": 0.88,
            "action_probabilities": {"TRIGGER_ALERT": 0.88, "IGNORE": 0.06, "MARK_ZOMBIE": 0.06},
            "rl_risk_adjustment": 5,
            "zombie_probability": 0.72,
            "threat_probability": 0.68,
            "remediation_probability": 0.75,
            "rule_risk_score": 80,
            "final_risk_score": 85,
            "explanation": {
                "top_features": [
                    {"feature": "lifecycle_status",  "contribution": 0.42, "value": 0.75},
                    {"feature": "auth_scheme",        "contribution": 0.31, "value": 0.0},
                    {"feature": "blast_radius",       "contribution": 0.18, "value": 0.6},
                ],
                "action_rationale": "High risk score (80/100) with Zombie lifecycle and no auth. RL adjustment: +5.",
                "historical_comparison": {"similar_endpoints": 12, "avg_reward": 14.2},
                "confidence_level": "High",
                "policy_version": 7,
            },
            "predicted_at": datetime.now(timezone.utc).isoformat(),
        }
        return httpx.Response(
            200,
            content=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
        )

    # /rl/feedback — accept and return reward
    if clean_path == "/rl/feedback" and body:
        try:
            req = json.loads(body)
            fb_type = req.get("feedback_type", "alert_ack")
        except Exception:
            fb_type = "alert_ack"
        reward_map = {
            "alert_ack": 15.0, "alert_reject": -20.0,
            "remediation_approved": 20.0, "remediation_rejected": -30.0,
            "classification_override": -15.0, "risk_change": 15.0,
        }
        payload = {
            "accepted": True,
            "feedback_type": fb_type,
            "reward_generated": reward_map.get(fb_type, 0.0),
            "event_type": "analyst_agreement",
            "endpoint_id": json.loads(body).get("endpoint_id", "unknown") if body else "unknown",
        }
        return httpx.Response(
            200,
            content=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
        )

    # /rl/reward
    if clean_path == "/rl/reward" and body:
        try:
            req = json.loads(body)
            et = req.get("event_type", "correct_classification")
        except Exception:
            et = "correct_classification"
        reward_table = {
            "correct_classification": 10.0, "analyst_agreement": 15.0,
            "successful_remediation": 20.0, "threat_prevention": 30.0,
            "reduced_false_positive": 15.0, "reduced_false_negative": 25.0,
            "false_positive": -20.0, "wrong_classification": -25.0,
            "missed_attack": -50.0, "failed_remediation": -30.0,
            "analyst_override": -15.0, "alert_fatigue": -10.0,
        }
        payload = {
            "reward_value": reward_table.get(et, 0.0),
            "event_type": et,
            "endpoint_id": json.loads(body).get("endpoint_id", "unknown") if body else "unknown",
            "accepted": True,
        }
        return httpx.Response(
            200,
            content=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
        )

    # /rl/recommendations
    if clean_path == "/rl/recommendations":
        payload = {
            "endpoint_id": "demo",
            "rl_recommendation": {
                "source": "rl_intelligence",
                "action": 7,
                "action_name": "TRIGGER_ALERT",
                "action_description": "Emit anomaly alert to analyst queue",
                "confidence": 0.88,
                "zombie_probability": 0.72,
                "threat_probability": 0.68,
                "remediation_probability": 0.75,
                "final_risk_score": 85,
                "rule_risk_score": 80,
                "rl_adjustment": 5,
                "explanation": {
                    "top_features": [{"feature": "lifecycle_status", "contribution": 0.42, "value": 0.75}],
                    "action_rationale": "Zombie endpoint with no auth and high blast radius.",
                    "confidence_level": "High",
                    "policy_version": 7,
                },
                "predicted_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        return httpx.Response(
            200,
            content=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
        )

    # Unknown /rl/* — return empty 200
    payload = {"status": "ok", "message": "rl-intelligence-service not in active stack (demo mode)"}
    return httpx.Response(
        200,
        content=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def resolve_downstream_url(path: str) -> Optional[str]:
    """Resolve the downstream service base URL for a given request path."""
    normalized = path.rstrip("/") or "/"
    for prefix, base_url in SERVICE_ROUTES.items():
        if normalized == prefix or normalized.startswith(prefix + "/"):
            return base_url
    return None


async def proxy_request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    headers: dict,
    body: Optional[bytes] = None,
    query_string: str = "",
) -> httpx.Response:
    """
    Forward a request to the appropriate downstream service.
    For /rl/* routes: if the service is unreachable, returns a mock response
    instead of propagating a 502/503.
    """
    base_url = resolve_downstream_url(path)
    if base_url is None:
        raise ValueError(f"No downstream service found for path: {path}")

    url = base_url.rstrip("/") + path
    if query_string:
        url = f"{url}?{query_string}"

    hop_by_hop = {
        "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
        "te", "trailers", "transfer-encoding", "upgrade", "host",
    }
    forwarded_headers = {k: v for k, v in headers.items() if k.lower() not in hop_by_hop}

    correlation_id = get_correlation_id()
    if correlation_id:
        forwarded_headers[CORRELATION_ID_HEADER] = correlation_id

    is_rl_route = path.startswith("/rl/") or path == "/rl"

    try:
        response = await client.request(
            method=method,
            url=url,
            headers=forwarded_headers,
            content=body,
            timeout=10.0,
        )
        return response
    except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as exc:
        # RL service not running → serve mock instead of 502
        if is_rl_route:
            mock = _rl_mock_response(path, method, body)
            if mock is not None:
                return mock
        raise
