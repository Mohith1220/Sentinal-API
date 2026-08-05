"""
Integration tests for the RL Intelligence Service.

Uses FastAPI's test client and InMemoryRLStore — no live database,
Kafka, or Neo4j required.
"""
import sys
import os
import pytest
from datetime import datetime, timezone

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_RL_DIR = os.path.join(_REPO_ROOT, "services", "rl-intelligence-service")
_SHARED = os.path.join(_REPO_ROOT, "sentinel_shared")

for p in [_SHARED, _RL_DIR]:
    if p in sys.path:
        sys.path.remove(p)
sys.path.insert(0, _SHARED)
sys.path.insert(0, _RL_DIR)

import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from db import InMemoryRLStore
from predictor import Predictor
from models import RLAgentStateRow, RLRewardEventRow, RewardEventType


# ---------------------------------------------------------------------------
# App factory — overrides DB and Predictor with in-memory versions
# ---------------------------------------------------------------------------

def build_test_app(store: InMemoryRLStore):
    """Create the FastAPI app with injected in-memory store."""
    import main as rl_main
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from sentinel_shared.logging import CorrelationIDMiddleware

    app = FastAPI(title="RL Test App")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.add_middleware(CorrelationIDMiddleware)

    # Mount only the routers we need (skip Kafka/Neo4j lifespan)
    from sentinel_shared.health import health_router
    app.include_router(health_router)

    # Inject store and predictor into app state
    predictor = Predictor(db=store, neo4j_driver=None)
    app.state.db = store
    app.state.predictor = predictor
    app.state.producer = None
    app.state.neo4j_driver = None

    # Import routes from main and register them directly
    from fastapi.routing import APIRoute
    for route in rl_main.app.routes:
        if isinstance(route, APIRoute) and route.path not in ("/health", "/metrics"):
            app.add_api_route(
                route.path,
                route.endpoint,
                methods=list(route.methods or ["GET"]),
                summary=route.summary,
            )

    return app


@pytest.fixture
def store():
    s = InMemoryRLStore()
    s.seed_endpoint(
        "aaaaaaaa-0000-0000-0000-000000000001",
        lifecycle_status="Zombie",
        risk_score=80,
        auth_scheme="none",
        data_sensitivity="PII",
        request_count_24h=5000,
        owning_team=None,
        source_file_id=None,
    )
    s.seed_endpoint(
        "bbbbbbbb-0000-0000-0000-000000000002",
        lifecycle_status="Active",
        risk_score=20,
        auth_scheme="OAuth2",
        data_sensitivity="internal",
        request_count_24h=100,
        owning_team="platform-team",
        source_file_id="openapi.yaml",
    )
    return s


@pytest.fixture
def app(store):
    return build_test_app(store)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_endpoint(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"


# ---------------------------------------------------------------------------
# POST /rl/predict
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_predict_zombie_endpoint(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/rl/predict", json={
            "endpoint_id": "aaaaaaaa-0000-0000-0000-000000000001",
            "force_refresh_graph": False,
        })
    assert resp.status_code == 200
    data = resp.json()

    assert "action" in data
    assert "action_name" in data
    assert "zombie_probability" in data
    assert "threat_probability" in data
    assert "final_risk_score" in data
    assert "rule_risk_score" in data
    assert "rl_risk_adjustment" in data
    assert "explanation" in data

    # Zombie endpoint should have non-zero zombie probability
    assert data["zombie_probability"] >= 0.0
    assert 0 <= data["final_risk_score"] <= 100
    assert -20 <= data["rl_risk_adjustment"] <= 20


@pytest.mark.asyncio
async def test_predict_healthy_endpoint(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/rl/predict", json={
            "endpoint_id": "bbbbbbbb-0000-0000-0000-000000000002",
            "force_refresh_graph": False,
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["rule_risk_score"] == 20


@pytest.mark.asyncio
async def test_predict_unknown_endpoint_returns_404(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/rl/predict", json={
            "endpoint_id": "00000000-dead-beef-0000-000000000000",
            "force_refresh_graph": False,
        })
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /rl/reward
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_inject_valid_reward(app, store):
    # Seed an agent state so the endpoint has history
    await store.upsert_agent_state(RLAgentStateRow(
        endpoint_id="aaaaaaaa-0000-0000-0000-000000000001",
        state_vector=[0.5] * 18,
        last_action=7,
        last_reward=0.0,
        total_reward=0.0,
        episode_step=0,
        updated_at=datetime.now(timezone.utc),
    ))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/rl/reward", json={
            "endpoint_id": "aaaaaaaa-0000-0000-0000-000000000001",
            "event_type": "threat_prevention",
            "source": "test",
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] is True
    assert data["reward_value"] == 30.0  # THREAT_PREVENTION = +30
    assert data["event_type"] == "threat_prevention"


@pytest.mark.asyncio
async def test_inject_invalid_event_type_returns_422(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/rl/reward", json={
            "endpoint_id": "aaaaaaaa-0000-0000-0000-000000000001",
            "event_type": "definitely_not_a_real_event",
            "source": "test",
        })
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /rl/feedback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("feedback_type,expected_reward", [
    ("alert_ack",            15.0),
    ("alert_reject",        -20.0),
    ("remediation_approved", 20.0),
    ("remediation_rejected",-30.0),
    ("classification_override", -15.0),
    ("risk_change",          15.0),
])
async def test_feedback_reward_mapping(app, feedback_type, expected_reward):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/rl/feedback", json={
            "endpoint_id": "aaaaaaaa-0000-0000-0000-000000000001",
            "analyst_id": "test-analyst",
            "feedback_type": feedback_type,
            "notes": "integration test",
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] is True
    assert data["reward_generated"] == expected_reward


@pytest.mark.asyncio
async def test_feedback_invalid_type_returns_422(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/rl/feedback", json={
            "endpoint_id": "aaaaaaaa-0000-0000-0000-000000000001",
            "analyst_id": "analyst",
            "feedback_type": "not_a_valid_type",
        })
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /rl/policy
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_policy_metrics_structure(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/rl/policy")
    assert resp.status_code == 200
    data = resp.json()

    required_keys = [
        "active_policy_version", "total_predictions", "mean_reward_last_100",
        "analyst_agreement_rate", "false_positive_rate", "training_runs",
    ]
    for key in required_keys:
        assert key in data, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# GET /rl/metrics
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_service_metrics_structure(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/rl/metrics")
    assert resp.status_code == 200
    data = resp.json()

    assert data["service"] == "rl-intelligence-service"
    assert "uptime_seconds" in data
    assert "active_policy_version" in data
    assert "endpoints_monitored" in data


# ---------------------------------------------------------------------------
# GET /rl/recommendations
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recommendations_structure(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/rl/recommendations", params={
            "endpoint_id": "aaaaaaaa-0000-0000-0000-000000000001",
        })
    assert resp.status_code == 200
    data = resp.json()

    assert "endpoint_id" in data
    assert "rl_recommendation" in data
    rec = data["rl_recommendation"]
    assert "action_name" in rec
    assert "zombie_probability" in rec
    assert "final_risk_score" in rec
    assert "explanation" in rec


# ---------------------------------------------------------------------------
# POST /rl/predict/bulk
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bulk_predict(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/rl/predict/bulk", json=[
            "aaaaaaaa-0000-0000-0000-000000000001",
            "bbbbbbbb-0000-0000-0000-000000000002",
        ])
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    assert len(data["results"]) == 2


@pytest.mark.asyncio
async def test_bulk_predict_too_many_returns_422(app):
    ids = [f"ep-{i:03d}" for i in range(51)]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/rl/predict/bulk", json=ids)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /rl/explain
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_explain_after_predict(app):
    endpoint_id = "aaaaaaaa-0000-0000-0000-000000000001"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # First predict so there's state to explain
        await client.post("/rl/predict", json={
            "endpoint_id": endpoint_id,
            "force_refresh_graph": False,
        })
        resp = await client.get("/rl/explain", params={"endpoint_id": endpoint_id})

    assert resp.status_code == 200
    data = resp.json()
    assert "explanation" in data
    assert "action_name" in data
    assert "final_risk_score" in data


@pytest.mark.asyncio
async def test_explain_unknown_endpoint_returns_404(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/rl/explain", params={
            "endpoint_id": "00000000-dead-0000-0000-000000000000",
        })
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Reward value invariants
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_positive_rewards_accepted(app):
    """All positive reward event types return positive reward values."""
    positive_events = [
        "correct_classification", "analyst_agreement", "successful_remediation",
        "threat_prevention", "reduced_false_positive", "reduced_false_negative",
    ]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for event_type in positive_events:
            resp = await client.post("/rl/reward", json={
                "endpoint_id": "aaaaaaaa-0000-0000-0000-000000000001",
                "event_type": event_type,
                "source": "test",
            })
            assert resp.status_code == 200, f"Failed for {event_type}"
            data = resp.json()
            assert data["reward_value"] > 0, f"{event_type} should give positive reward"


@pytest.mark.asyncio
async def test_negative_rewards_accepted(app):
    """All negative reward event types return negative reward values."""
    negative_events = [
        "false_positive", "wrong_classification", "missed_attack",
        "failed_remediation", "analyst_override", "alert_fatigue",
    ]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for event_type in negative_events:
            resp = await client.post("/rl/reward", json={
                "endpoint_id": "aaaaaaaa-0000-0000-0000-000000000001",
                "event_type": event_type,
                "source": "test",
            })
            assert resp.status_code == 200, f"Failed for {event_type}"
            data = resp.json()
            assert data["reward_value"] < 0, f"{event_type} should give negative reward"
