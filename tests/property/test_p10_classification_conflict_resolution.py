"""
Property 10: Classification Conflict Resolution

For any endpoint where the ML model's predicted lifecycle status differs from
the rule-based classification, the authoritative lifecycle_status field SHALL
equal the rule-based result, and the classification history record SHALL contain
both the rule-based status and the ML status with its confidence score.

Validates: Requirements 5.6
"""

import asyncio
import sys
import os
from typing import Optional

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, _REPO_ROOT)
from conftest import activate_service
activate_service("classification-service")

from rule_engine import ClassificationInput, apply_rules
from db import InMemoryClassificationStore
from sentinel_shared.models import LifecycleStatus

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

lifecycle_status_st = st.sampled_from(
    [
        LifecycleStatus.ACTIVE,
        LifecycleStatus.DEPRECATED,
        LifecycleStatus.ORPHANED,
        LifecycleStatus.ZOMBIE,
    ]
)

confidence_st = st.floats(
    min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
)

traffic_recency_st = st.one_of(
    st.none(),
    st.floats(min_value=0.0, max_value=365.0, allow_nan=False, allow_infinity=False),
)

classification_input_st = st.builds(
    ClassificationInput,
    traffic_recency_days=traffic_recency_st,
    spec_presence=st.booleans(),
    deprecated_flag=st.booleans(),
    owner_present=st.booleans(),
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def run_async(coro):
    """Run a coroutine synchronously (for use inside Hypothesis tests)."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


@given(
    inputs=classification_input_st,
    ml_status=lifecycle_status_st,
    ml_confidence=confidence_st,
)
@settings(max_examples=10)
def test_p10_rule_status_is_authoritative(
    inputs: ClassificationInput,
    ml_status: LifecycleStatus,
    ml_confidence: float,
):
    """
    **Validates: Requirements 5.6**

    After inserting a classification history record with both rule_status and
    ml_status, the endpoint's lifecycle_status in the store equals the
    rule_status (not the ml_status).
    """
    endpoint_id = "ep-conflict-test"
    rule_status = apply_rules(inputs)

    store = InMemoryClassificationStore()
    store.seed_endpoint(endpoint_id)

    async def _run():
        await store.update_lifecycle_status(endpoint_id, rule_status)
        await store.insert_classification_history(
            endpoint_id=endpoint_id,
            rule_status=rule_status,
            ml_status=ml_status,
            ml_confidence=ml_confidence,
        )
        endpoint = await store.get_endpoint(endpoint_id)
        return endpoint

    endpoint = run_async(_run())

    assert endpoint is not None
    assert endpoint["lifecycle_status"] == rule_status.value, (
        f"lifecycle_status should be rule_status={rule_status.value}, "
        f"not ml_status={ml_status.value}"
    )


@given(
    inputs=classification_input_st,
    ml_status=lifecycle_status_st,
    ml_confidence=confidence_st,
)
@settings(max_examples=10)
def test_p10_history_contains_both_statuses(
    inputs: ClassificationInput,
    ml_status: LifecycleStatus,
    ml_confidence: float,
):
    """
    **Validates: Requirements 5.6**

    The classification history record contains both the rule-based status
    and the ML status with its confidence score.
    """
    endpoint_id = "ep-history-test"
    rule_status = apply_rules(inputs)

    store = InMemoryClassificationStore()
    store.seed_endpoint(endpoint_id)

    async def _run():
        await store.insert_classification_history(
            endpoint_id=endpoint_id,
            rule_status=rule_status,
            ml_status=ml_status,
            ml_confidence=ml_confidence,
        )
        return await store.get_classification_history(endpoint_id)

    history = run_async(_run())

    assert len(history) == 1
    record = history[0]

    # Rule-based status must be present
    assert record["rule_status"] == rule_status.value

    # ML status and confidence must be present
    assert record["ml_status"] == ml_status.value
    assert record["ml_confidence"] is not None
    assert abs(record["ml_confidence"] - ml_confidence) < 1e-9


@given(
    inputs=classification_input_st,
    ml_confidence=confidence_st,
)
@settings(max_examples=10)
def test_p10_history_contains_both_when_statuses_differ(
    inputs: ClassificationInput,
    ml_confidence: float,
):
    """
    **Validates: Requirements 5.6**

    When ML status differs from rule status, both are stored in history
    and the endpoint's lifecycle_status still equals the rule-based result.
    """
    endpoint_id = "ep-differ-test"
    rule_status = apply_rules(inputs)

    # Pick an ML status that is different from the rule status
    all_statuses = [
        LifecycleStatus.ACTIVE,
        LifecycleStatus.DEPRECATED,
        LifecycleStatus.ORPHANED,
        LifecycleStatus.ZOMBIE,
    ]
    different_statuses = [s for s in all_statuses if s != rule_status]
    if not different_statuses:
        # All statuses are the same (shouldn't happen, but guard anyway)
        return
    ml_status = different_statuses[0]

    store = InMemoryClassificationStore()
    store.seed_endpoint(endpoint_id)

    async def _run():
        await store.update_lifecycle_status(endpoint_id, rule_status)
        await store.insert_classification_history(
            endpoint_id=endpoint_id,
            rule_status=rule_status,
            ml_status=ml_status,
            ml_confidence=ml_confidence,
        )
        endpoint = await store.get_endpoint(endpoint_id)
        history = await store.get_classification_history(endpoint_id)
        return endpoint, history

    endpoint, history = run_async(_run())

    # Authoritative status is rule-based
    assert endpoint["lifecycle_status"] == rule_status.value

    # History contains both
    assert len(history) == 1
    record = history[0]
    assert record["rule_status"] == rule_status.value
    assert record["ml_status"] == ml_status.value
    assert record["ml_confidence"] is not None


@given(
    inputs=classification_input_st,
)
@settings(max_examples=10)
def test_p10_history_ml_fields_none_when_no_ml(inputs: ClassificationInput):
    """
    **Validates: Requirements 5.6**

    When no ML result is available (model not found), ml_status and
    ml_confidence in the history record are None.
    """
    endpoint_id = "ep-no-ml"
    rule_status = apply_rules(inputs)

    store = InMemoryClassificationStore()
    store.seed_endpoint(endpoint_id)

    async def _run():
        await store.insert_classification_history(
            endpoint_id=endpoint_id,
            rule_status=rule_status,
            ml_status=None,
            ml_confidence=None,
        )
        return await store.get_classification_history(endpoint_id)

    history = run_async(_run())

    assert len(history) == 1
    record = history[0]
    assert record["rule_status"] == rule_status.value
    assert record["ml_status"] is None
    assert record["ml_confidence"] is None

