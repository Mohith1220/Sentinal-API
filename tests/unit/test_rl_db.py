"""
Unit tests for the RL database layer (InMemoryRLStore).
Tests all CRUD operations, replay buffer construction, and policy metrics.
"""
import sys
import os
import pytest
import asyncio
from datetime import datetime, timezone

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_RL_DIR = os.path.join(_REPO_ROOT, "services", "rl-intelligence-service")
_SHARED = os.path.join(_REPO_ROOT, "sentinel_shared")

for p in [_SHARED, _RL_DIR]:
    if p in sys.path:
        sys.path.remove(p)
sys.path.insert(0, _SHARED)
sys.path.insert(0, _RL_DIR)

from db import InMemoryRLStore
from models import (
    RLAgentStateRow, RLTrainingHistoryRow, RLRewardEventRow,
    RLPredictionRow, RLPolicyVersionRow, AnalystFeedbackRow,
    RewardEventType,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def store():
    s = InMemoryRLStore()
    s.seed_endpoint("ep-001", lifecycle_status="Active", risk_score=40)
    s.seed_endpoint("ep-002", lifecycle_status="Zombie", risk_score=80)
    return s


async def test_get_endpoint_found(store):
    ep = await store.get_endpoint("ep-001")
    assert ep is not None
    assert ep["id"] == "ep-001"


async def test_get_endpoint_not_found(store):
    ep = await store.get_endpoint("does-not-exist")
    assert ep is None


async def test_upsert_and_get_agent_state(store):
    row = RLAgentStateRow(
        endpoint_id="ep-001",
        state_vector=[0.5] * 18,
        last_action=4,
        last_reward=10.0,
        total_reward=10.0,
        episode_step=1,
        updated_at=datetime.now(timezone.utc),
    )
    await store.upsert_agent_state(row)
    state = await store.get_agent_state("ep-001")
    assert state is not None
    assert state["last_action"] == 4
    assert len(state["state_vector"]) == 18


async def test_upsert_agent_state_overwrites(store):
    for action in [3, 7]:
        row = RLAgentStateRow(
            endpoint_id="ep-001",
            state_vector=[0.1] * 18,
            last_action=action,
            last_reward=0.0,
            total_reward=0.0,
            episode_step=0,
            updated_at=datetime.now(timezone.utc),
        )
        await store.upsert_agent_state(row)

    state = await store.get_agent_state("ep-001")
    assert state["last_action"] == 7


async def test_insert_reward_event(store):
    row = RLRewardEventRow(
        endpoint_id="ep-001",
        event_type=RewardEventType.CORRECT_CLASSIFICATION.value,
        reward_value=10.0,
        action_taken=1,
        state_snapshot=[0.0] * 18,
        source="test",
        occurred_at=datetime.now(timezone.utc),
    )
    rid = await store.insert_reward_event(row)
    assert rid is not None
    assert len(store._reward_events) == 1


async def test_insert_analyst_feedback(store):
    row = AnalystFeedbackRow(
        endpoint_id="ep-001",
        analyst_id="analyst-1",
        feedback_type="alert_ack",
        reward_generated=15.0,
        occurred_at=datetime.now(timezone.utc),
    )
    await store.insert_analyst_feedback(row)
    stats = await store.get_feedback_stats("ep-001")
    assert stats["analyst_agreement_rate"] > 0


async def test_feedback_stats_false_positive(store):
    for _ in range(3):
        row = AnalystFeedbackRow(
            endpoint_id="ep-001",
            analyst_id="analyst-1",
            feedback_type="alert_reject",
            reward_generated=-20.0,
            occurred_at=datetime.now(timezone.utc),
        )
        await store.insert_analyst_feedback(row)

    stats = await store.get_feedback_stats("ep-001")
    assert stats["false_positive_rate"] > 0


async def test_replay_buffer_from_reward_events(store):
    for i in range(5):
        row = RLRewardEventRow(
            endpoint_id="ep-001",
            event_type=RewardEventType.CORRECT_CLASSIFICATION.value,
            reward_value=10.0,
            action_taken=1,
            state_snapshot=[float(i)] * 18,
            source="test",
            occurred_at=datetime.now(timezone.utc),
        )
        await store.insert_reward_event(row)

    buffer = await store.get_replay_buffer(limit=100)
    assert len(buffer) == 5
    for entry in buffer:
        assert "state_vector" in entry
        assert "action" in entry
        assert "event_type" in entry
        assert len(entry["state_vector"]) == 18


async def test_policy_version_lifecycle(store):
    # No policy yet
    version = await store.get_active_policy_version()
    assert version == 0

    row = RLPolicyVersionRow(
        version=1,
        artifact_path="/models/policy_v1.zip",
        mean_reward=12.5,
        is_active=True,
        promoted_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    await store.insert_policy_version(row)
    version = await store.get_active_policy_version()
    assert version == 1

    # Second policy deactivates first
    row2 = RLPolicyVersionRow(
        version=2,
        artifact_path="/models/policy_v2.zip",
        mean_reward=15.0,
        is_active=True,
        promoted_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    await store.insert_policy_version(row2)
    version = await store.get_active_policy_version()
    assert version == 2


async def test_list_all_endpoint_ids(store):
    ids = await store.list_all_endpoint_ids()
    assert "ep-001" in ids
    assert "ep-002" in ids


async def test_policy_metrics_empty(store):
    metrics = await store.get_policy_metrics()
    assert "active_policy_version" in metrics
    assert "total_predictions" in metrics
    assert "mean_reward_last_100" in metrics
    assert "analyst_agreement_rate" in metrics
    assert isinstance(metrics["training_runs"], int)


async def test_insert_training_history(store):
    row = RLTrainingHistoryRow(
        policy_version=1,
        total_timesteps=10000,
        mean_reward=8.5,
        std_reward=2.1,
        entropy_loss=0.01,
        policy_loss=0.05,
        value_loss=0.03,
        explained_variance=0.65,
        training_duration_seconds=42.3,
        trained_at=datetime.now(timezone.utc),
    )
    tid = await store.insert_training_history(row)
    assert tid is not None
    assert len(store._training_history) == 1
