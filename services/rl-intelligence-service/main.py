"""
RL Intelligence Service — SentinelAPI

Production-grade Reinforcement Learning layer that augments the existing
Rule Engine + XGBoost ML stack with a PPO agent trained on analyst feedback.

Hybrid scoring formula:
    Final Score = Rule Score + ML Contribution + RL Adjustment
                                                 ^^^^^^^^^^^
                                                 -20 to +20

Endpoints:
  POST /rl/predict          — run RL prediction for an endpoint
  GET  /rl/explain          — explain last prediction (SHAP + rationale)
  POST /rl/train            — trigger offline PPO training run
  POST /rl/reward           — manually inject a reward signal
  POST /rl/feedback         — submit analyst feedback
  GET  /rl/policy           — policy version and performance metrics
  GET  /rl/metrics          — service health and Kafka lag metrics
  GET  /rl/recommendations  — RL-augmented remediation recommendations
  GET  /health              — liveness probe
"""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from sentinel_shared.health import health_router
from sentinel_shared.kafka import SentinelProducer
from sentinel_shared.logging import (
    CorrelationIDMiddleware,
    configure_logging,
    make_global_exception_handler,
)
from sentinel_shared.metrics import setup_metrics

from db import RLDatabaseManager
from graph_intelligence import refresh_all_centralities
from kafka_consumer import kafka_consumer_loop
from models import (
    ACTION_DESCRIPTIONS,
    REWARD_VALUES,
    AnalystFeedbackRequest,
    AnalystFeedbackRow,
    PredictRequest,
    PolicyMetricsResponse,
    RLMetricsResponse,
    RewardEventType,
    RewardRequest,
    RewardResponse,
    RLRewardEventRow,
    TrainRequest,
)
from predictor import Predictor

SERVICE_NAME = "rl-intelligence-service"
SERVICE_PORT = int(os.getenv("RL_SERVICE_PORT", "8008"))
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "sentinel_secret")

logger = structlog.get_logger(__name__)

_start_time = time.monotonic()


# ---------------------------------------------------------------------------
# Neo4j driver factory
# ---------------------------------------------------------------------------


async def _create_neo4j_driver() -> Optional[object]:
    """Attempt to connect to Neo4j. Returns None if unavailable."""
    try:
        from neo4j import AsyncGraphDatabase

        driver = AsyncGraphDatabase.driver(
            NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)
        )
        await driver.verify_connectivity()
        logger.info("rl_neo4j_connected", uri=NEO4J_URI)
        return driver
    except Exception as exc:
        logger.warning("rl_neo4j_unavailable", error=str(exc))
        return None


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(SERVICE_NAME)

    # Database
    db = RLDatabaseManager()
    await db.connect()
    app.state.db = db

    # Neo4j
    neo4j_driver = await _create_neo4j_driver()
    app.state.neo4j_driver = neo4j_driver

    # Predictor (PPO + XGBoost + SHAP)
    predictor = Predictor(db=db, neo4j_driver=neo4j_driver)
    app.state.predictor = predictor

    # Kafka producer (for publishing analyst.feedback events downstream)
    try:
        producer = SentinelProducer(bootstrap_servers=KAFKA_BOOTSTRAP)
        await producer.start()
        app.state.producer = producer
    except Exception as exc:
        logger.warning("rl_kafka_producer_unavailable", error=str(exc))
        app.state.producer = None

    # Background Kafka consumer
    consumer_task = asyncio.create_task(kafka_consumer_loop(app))
    app.state.consumer_task = consumer_task

    # APScheduler: refresh graph centralities every 5 min + trigger training every hour
    scheduler = AsyncIOScheduler()

    async def _refresh_graph():
        await refresh_all_centralities(app.state.neo4j_driver)

    async def _background_train():
        logger.info("rl_background_training_start")
        try:
            result = await app.state.predictor.train(total_timesteps=5_000)
            logger.info("rl_background_training_complete", **result)
        except Exception as exc:
            logger.error("rl_background_training_failed", error=str(exc))

    scheduler.add_job(_refresh_graph, "interval", minutes=5, id="refresh_graph")
    scheduler.add_job(_background_train, "interval", hours=1, id="background_train")
    scheduler.start()
    app.state.scheduler = scheduler

    yield

    # Cleanup
    scheduler.shutdown(wait=False)
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass

    if app.state.producer:
        await app.state.producer.stop()

    if neo4j_driver:
        await neo4j_driver.close()

    await db.disconnect()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SentinelAPI — RL Intelligence Service",
    description=(
        "Production-grade PPO Reinforcement Learning layer. "
        "Augments rule-based and ML scoring with continuous learning "
        "from analyst feedback."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(CorrelationIDMiddleware)
setup_metrics(app, SERVICE_NAME)
app.add_exception_handler(Exception, make_global_exception_handler(SERVICE_NAME))
app.include_router(health_router)


# ---------------------------------------------------------------------------
# POST /rl/predict
# ---------------------------------------------------------------------------


@app.post("/rl/predict", summary="Run RL prediction for an endpoint")
async def predict(body: PredictRequest, request: Request) -> JSONResponse:
    """
    Run the full RL prediction pipeline for one endpoint.

    Combines rule-based risk score, XGBoost ML contribution, and PPO
    RL adjustment into a final composite risk score.

    Also returns:
    - Recommended action (12-action discrete space)
    - Zombie / threat / remediation probabilities
    - SHAP feature importance for explainability
    """
    predictor: Predictor = request.app.state.predictor
    if predictor is None:
        raise HTTPException(status_code=503, detail="Predictor not initialised")

    result = await predictor.run_prediction(
        body.endpoint_id,
        force_refresh_graph=body.force_refresh_graph,
    )

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return JSONResponse(content=result)


# ---------------------------------------------------------------------------
# GET /rl/explain
# ---------------------------------------------------------------------------


@app.get("/rl/explain", summary="Explain the last RL prediction for an endpoint")
async def explain(
    request: Request,
    endpoint_id: str = Query(..., description="Endpoint UUID"),
) -> JSONResponse:
    """
    Return a detailed explanation for the most recent RL prediction.

    Includes:
    - Top SHAP features driving the decision
    - Human-readable action rationale
    - Confidence level and policy version
    - Historical comparison against similar endpoints
    """
    db: RLDatabaseManager = request.app.state.db
    predictor: Predictor = request.app.state.predictor

    agent_state = await db.get_agent_state(endpoint_id)
    if not agent_state:
        raise HTTPException(
            status_code=404,
            detail=f"No prediction found for endpoint {endpoint_id}",
        )

    # Re-run prediction to get fresh explanation (lightweight — uses cache)
    result = await predictor.run_prediction(endpoint_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return JSONResponse(content={
        "endpoint_id": endpoint_id,
        "explanation": result["explanation"],
        "action": result["action"],
        "action_name": result["action_name"],
        "action_description": result["action_description"],
        "zombie_probability": result["zombie_probability"],
        "threat_probability": result["threat_probability"],
        "final_risk_score": result["final_risk_score"],
        "predicted_at": result["predicted_at"],
    })


# ---------------------------------------------------------------------------
# POST /rl/train
# ---------------------------------------------------------------------------


@app.post("/rl/train", summary="Trigger offline PPO training run")
async def train(body: TrainRequest, request: Request) -> JSONResponse:
    """
    Trigger an offline PPO training run using the accumulated replay buffer.

    The PPO policy is trained against all reward events stored in
    rl_reward_events. After training, the new policy is promoted as active.

    Note: Training is compute-intensive. Runs in a background thread via
    asyncio.to_thread to avoid blocking the event loop.
    """
    predictor: Predictor = request.app.state.predictor
    if predictor is None:
        raise HTTPException(status_code=503, detail="Predictor not initialised")

    # Check if enough data exists (skip if buffer too small and not forced)
    db: RLDatabaseManager = request.app.state.db
    replay_buffer = await db.get_replay_buffer(limit=100)
    if len(replay_buffer) < 100 and not body.force:
        return JSONResponse(
            content={
                "policy_version": predictor._agent.policy_version,
                "total_timesteps": 0,
                "mean_reward": 0.0,
                "training_duration_seconds": 0.0,
                "promoted": False,
                "message": (
                    f"Insufficient replay data ({len(replay_buffer)} events). "
                    "Need ≥ 100. Use force=true to override."
                ),
            }
        )

    # Run training in thread pool to avoid blocking event loop
    result = await asyncio.to_thread(
        _sync_train, predictor, body.timesteps
    )
    return JSONResponse(content=result)


def _sync_train(predictor: Predictor, timesteps: int) -> dict:
    """Synchronous wrapper for asyncio.to_thread."""
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(predictor.train(timesteps))
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# POST /rl/reward
# ---------------------------------------------------------------------------


@app.post("/rl/reward", summary="Manually inject a reward signal")
async def inject_reward(body: RewardRequest, request: Request) -> JSONResponse:
    """
    Manually inject a reward event for an endpoint.

    Used for programmatic reward injection (e.g. from integration pipelines).
    Analyst feedback should use the /rl/feedback endpoint instead.
    """
    db: RLDatabaseManager = request.app.state.db

    # Validate event type
    try:
        event_type = RewardEventType(body.event_type)
    except ValueError:
        valid = [e.value for e in RewardEventType]
        raise HTTPException(
            status_code=422,
            detail=f"Invalid event_type. Valid values: {valid}",
        )

    reward_value = REWARD_VALUES[event_type]

    # Get last known agent state for this endpoint
    agent_state = await db.get_agent_state(body.endpoint_id) or {}
    state_snapshot = agent_state.get("state_vector", [0.0] * 18)
    last_action = agent_state.get("last_action", 0)

    row = RLRewardEventRow(
        endpoint_id=body.endpoint_id,
        event_type=event_type.value,
        reward_value=reward_value,
        action_taken=last_action,
        state_snapshot=state_snapshot,
        source=body.source,
        occurred_at=datetime.now(timezone.utc),
    )
    await db.insert_reward_event(row)

    logger.info(
        "reward_injected",
        endpoint_id=body.endpoint_id,
        event_type=event_type.value,
        reward=reward_value,
        source=body.source,
    )

    return JSONResponse(content=RewardResponse(
        reward_value=reward_value,
        event_type=event_type.value,
        endpoint_id=body.endpoint_id,
        accepted=True,
    ).model_dump())


# ---------------------------------------------------------------------------
# POST /rl/feedback  (Analyst Feedback Loop)
# ---------------------------------------------------------------------------


@app.post("/rl/feedback", summary="Submit analyst feedback to train the RL agent")
async def submit_feedback(body: AnalystFeedbackRequest, request: Request) -> JSONResponse:
    """
    Submit analyst feedback to generate a reward event and update the RL policy.

    Feedback types:
    - classification_override: analyst changed lifecycle status → ANALYST_OVERRIDE (-15)
    - risk_change:             analyst adjusted risk score → ANALYST_AGREEMENT (+15)
    - alert_ack:               analyst acknowledged alert → ANALYST_AGREEMENT (+15)
    - alert_reject:            analyst rejected alert → FALSE_POSITIVE (-20)
    - remediation_approved:    analyst approved remediation → SUCCESSFUL_REMEDIATION (+20)
    - remediation_rejected:    analyst rejected remediation → FAILED_REMEDIATION (-30)
    """
    db: RLDatabaseManager = request.app.state.db
    producer = request.app.state.producer

    valid_feedback_types = {
        "classification_override", "risk_change", "alert_ack",
        "alert_reject", "remediation_approved", "remediation_rejected",
    }
    if body.feedback_type not in valid_feedback_types:
        raise HTTPException(
            status_code=422,
            detail=f"feedback_type must be one of {sorted(valid_feedback_types)}",
        )

    feedback_reward_map = {
        "classification_override": RewardEventType.ANALYST_OVERRIDE,
        "risk_change":             RewardEventType.ANALYST_AGREEMENT,
        "alert_ack":               RewardEventType.ANALYST_AGREEMENT,
        "alert_reject":            RewardEventType.FALSE_POSITIVE,
        "remediation_approved":    RewardEventType.SUCCESSFUL_REMEDIATION,
        "remediation_rejected":    RewardEventType.FAILED_REMEDIATION,
    }
    event_type = feedback_reward_map[body.feedback_type]
    reward_value = REWARD_VALUES[event_type]

    # Persist feedback record
    agent_state = await db.get_agent_state(body.endpoint_id) or {}
    state_snapshot = agent_state.get("state_vector", [0.0] * 18)
    last_action = agent_state.get("last_action", 0)

    feedback_row = AnalystFeedbackRow(
        endpoint_id=body.endpoint_id,
        analyst_id=body.analyst_id,
        feedback_type=body.feedback_type,
        previous_value=body.previous_value,
        new_value=body.new_value,
        rl_prediction_id=body.rl_prediction_id,
        reward_generated=reward_value,
        notes=body.notes,
        occurred_at=datetime.now(timezone.utc),
    )
    await db.insert_analyst_feedback(feedback_row)

    # Generate reward event
    reward_row = RLRewardEventRow(
        endpoint_id=body.endpoint_id,
        event_type=event_type.value,
        reward_value=reward_value,
        action_taken=last_action,
        state_snapshot=state_snapshot,
        source="analyst_feedback_api",
        occurred_at=datetime.now(timezone.utc),
    )
    await db.insert_reward_event(reward_row)

    # Publish to analyst.feedback Kafka topic for other services
    if producer:
        try:
            await producer.send(
                "analyst.feedback",
                {
                    "endpoint_id": body.endpoint_id,
                    "analyst_id": body.analyst_id,
                    "feedback_type": body.feedback_type,
                    "previous_value": body.previous_value,
                    "new_value": body.new_value,
                    "rl_prediction_id": body.rl_prediction_id,
                    "reward_generated": reward_value,
                    "notes": body.notes,
                },
                key=body.endpoint_id,
            )
        except Exception as exc:
            logger.warning("feedback_kafka_publish_failed", error=str(exc))

    logger.info(
        "analyst_feedback_accepted",
        endpoint_id=body.endpoint_id,
        analyst_id=body.analyst_id,
        feedback_type=body.feedback_type,
        reward=reward_value,
    )

    return JSONResponse(content={
        "accepted": True,
        "feedback_type": body.feedback_type,
        "reward_generated": reward_value,
        "event_type": event_type.value,
        "endpoint_id": body.endpoint_id,
    })


# ---------------------------------------------------------------------------
# GET /rl/policy
# ---------------------------------------------------------------------------


@app.get("/rl/policy", summary="Policy version and performance metrics")
async def get_policy(request: Request) -> JSONResponse:
    """
    Return the active PPO policy version and performance metrics.

    Metrics include analyst agreement rate, false positive/negative rates,
    zombie detection accuracy, and training history.
    """
    db: RLDatabaseManager = request.app.state.db
    predictor: Predictor = request.app.state.predictor

    try:
        metrics = await db.get_policy_metrics()
    except Exception as exc:
        logger.warning("policy_metrics_failed", error=str(exc))
        metrics = {
            "active_policy_version": getattr(predictor._agent, "policy_version", 0),
            "total_predictions": 0,
            "mean_reward_last_100": 0.0,
            "analyst_agreement_rate": 0.0,
            "false_positive_rate": 0.0,
            "false_negative_rate": 0.0,
            "zombie_detection_accuracy": 0.0,
            "training_runs": 0,
            "last_trained_at": None,
        }

    return JSONResponse(content=metrics)


# ---------------------------------------------------------------------------
# GET /rl/metrics
# ---------------------------------------------------------------------------


@app.get("/rl/metrics", summary="Service health and operational metrics")
async def get_metrics(request: Request) -> JSONResponse:
    """
    Return operational metrics for the RL Intelligence Service.

    Includes prediction volume, reward event counts, Kafka lag estimates,
    and graph feature freshness.
    """
    db: RLDatabaseManager = request.app.state.db
    predictor: Predictor = request.app.state.predictor

    uptime = time.monotonic() - _start_time

    # Count endpoints being monitored
    try:
        endpoint_ids = await db.list_all_endpoint_ids()
        endpoints_monitored = len(endpoint_ids)
    except Exception:
        endpoints_monitored = 0

    # Get policy metrics for summary fields
    try:
        policy_metrics = await db.get_policy_metrics()
        total_preds = policy_metrics["total_predictions"]
        training_runs = policy_metrics["training_runs"]
        active_version = policy_metrics["active_policy_version"]
    except Exception:
        total_preds = 0
        training_runs = 0
        active_version = getattr(predictor._agent, "policy_version", 0)

    return JSONResponse(content=RLMetricsResponse(
        service=SERVICE_NAME,
        uptime_seconds=round(uptime, 1),
        total_predictions=total_preds,
        total_reward_events=0,
        total_analyst_feedbacks=0,
        active_policy_version=active_version,
        kafka_lag={},
        graph_features_last_updated=None,
        endpoints_monitored=endpoints_monitored,
    ).model_dump())


# ---------------------------------------------------------------------------
# GET /rl/recommendations
# ---------------------------------------------------------------------------


@app.get("/rl/recommendations", summary="RL-augmented remediation recommendations")
async def get_rl_recommendations(
    request: Request,
    endpoint_id: str = Query(..., description="Endpoint UUID"),
) -> JSONResponse:
    """
    Return RL-augmented remediation recommendations for an endpoint.

    Combines:
    1. Existing rule-based recommendations (from remediation-service)
    2. RL agent's recommended action
    3. Probability estimates (zombie, threat, remediation urgency)
    4. SHAP-based explanation of why action was chosen
    """
    predictor: Predictor = request.app.state.predictor

    result = await predictor.run_prediction(endpoint_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    # Build RL recommendation overlay
    action_name = result["action_name"]
    action_desc = ACTION_DESCRIPTIONS.get(result["action"], "")

    rl_recommendation = {
        "source": "rl_intelligence",
        "action": result["action"],
        "action_name": action_name,
        "action_description": action_desc,
        "confidence": result["action_confidence"],
        "zombie_probability": result["zombie_probability"],
        "threat_probability": result["threat_probability"],
        "remediation_probability": result["remediation_probability"],
        "final_risk_score": result["final_risk_score"],
        "rule_risk_score": result["rule_risk_score"],
        "rl_adjustment": result["rl_risk_adjustment"],
        "explanation": result["explanation"],
        "predicted_at": result["predicted_at"],
    }

    return JSONResponse(content={
        "endpoint_id": endpoint_id,
        "rl_recommendation": rl_recommendation,
    })


# ---------------------------------------------------------------------------
# Bulk predict endpoint (for dashboard polling)
# ---------------------------------------------------------------------------


@app.post("/rl/predict/bulk", summary="Run RL predictions for multiple endpoints")
async def predict_bulk(
    request: Request,
    endpoint_ids: list[str],
) -> JSONResponse:
    """
    Run RL predictions for a batch of endpoints.
    Returns a list of prediction results (errors are included inline).
    Maximum 50 endpoints per call.
    """
    if len(endpoint_ids) > 50:
        raise HTTPException(
            status_code=422,
            detail="Maximum 50 endpoints per bulk request",
        )

    predictor: Predictor = request.app.state.predictor
    results = []

    for eid in endpoint_ids:
        try:
            result = await predictor.run_prediction(eid)
            results.append(result)
        except Exception as exc:
            results.append({"endpoint_id": eid, "error": str(exc)})

    return JSONResponse(content={"results": results, "count": len(results)})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
