# Feature: sentinel-api, Property 10: Classification Conflict Resolution
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
from hypothesis import given, settings, assume
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Path setup — add classification-service to sys.path so we can import
# rule_engine, db, etc. directly without installing the service as a package.
# ---------------------------------------------------------------------------
import sys, os
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

_ALL_STATUSES = [
    LifecycleStatus.ACTIVE,
    LifecycleStatus.DEPRECATED,
    LifecycleStatus.ORPHANED,
    LifecycleStatus.ZOMBIE,
]

lifecycle_status_st = st.sampled_from(_ALL_STATUSES)

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
    """Run a coroutine synchronously inside a Hypothesis test."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Property tests
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

    After conflict resolution, the endpoint's lifecycle_status in the store
    SHALL equal the rule-based status, regardless of what the ML model predicted.
    """
    endpoint_id = "ep-conflict-authoritative"
    rule_status = apply_rules(inputs)

    store = InMemoryClassificationStore()
    store.seed_endpoint(endpoint_id)

    async def _run():
        # Conflict resolution: write rule-based status as authoritative
        await store.update_lifecycle_status(endpoint_id, rule_status)
        # Record both statuses in history (as the classifier does)
        await store.insert_classification_history(
            endpoint_id=endpoint_id,
            rule_status=rule_status,
            ml_status=ml_status,
            ml_confidence=ml_confidence,
        )
        return await store.get_endpoint(endpoint_id)

    endpoint = run_async(_run())

    assert endpoint is not None
    assert endpoint["lifecycle_status"] == rule_status.value, (
        f"lifecycle_status should be rule_status={rule_status.value!r}, "
        f"got {endpoint['lifecycle_status']!r} (ml_status={ml_status.value!r})"
    )


@given(
    inputs=classification_input_st,
    ml_status=lifecycle_status_st,
    ml_confidence=confidence_st,
)
@settings(max_examples=10)
def test_p10_history_contains_both_statuses_and_confidence(
    inputs: ClassificationInput,
    ml_status: LifecycleStatus,
    ml_confidence: float,
):
    """
    **Validates: Requirements 5.6**

    The classification history record SHALL contain both the rule-based status
    and the ML status with its confidence score.
    """
    endpoint_id = "ep-history-both"
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

    assert len(history) == 1, f"Expected 1 history record, got {len(history)}"
    record = history[0]

    # Rule-based status must be present
    assert record["rule_status"] == rule_status.value, (
        f"rule_status mismatch: expected {rule_status.value!r}, "
        f"got {record['rule_status']!r}"
    )

    # ML status must be present
    assert record["ml_status"] == ml_status.value, (
        f"ml_status mismatch: expected {ml_status.value!r}, "
        f"got {record['ml_status']!r}"
    )

    # ML confidence must be present and match
    assert record["ml_confidence"] is not None, "ml_confidence should not be None"
    assert abs(record["ml_confidence"] - ml_confidence) < 1e-9, (
        f"ml_confidence mismatch: expected {ml_confidence}, "
        f"got {record['ml_confidence']}"
    )


@given(
    inputs=classification_input_st,
    ml_confidence=confidence_st,
)
@settings(max_examples=10)
def test_p10_authoritative_status_when_ml_differs(
    inputs: ClassificationInput,
    ml_confidence: float,
):
    """
    **Validates: Requirements 5.6**

    When the ML status differs from the rule-based status, the endpoint's
    lifecycle_status SHALL still equal the rule-based result, and the history
    record SHALL contain both statuses.
    """
    endpoint_id = "ep-conflict-differ"
    rule_status = apply_rules(inputs)

    # Select an ML status that is explicitly different from the rule status
    different_statuses = [s for s in _ALL_STATUSES if s != rule_status]
    # There are always at least 3 other statuses, so this list is never empty
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

    # Authoritative status is always the rule-based result
    assert endpoint is not None
    assert endpoint["lifecycle_status"] == rule_status.value, (
        f"lifecycle_status should be rule_status={rule_status.value!r} "
        f"(not ml_status={ml_status.value!r})"
    )

    # History contains both statuses
    assert len(history) == 1
    record = history[0]
    assert record["rule_status"] == rule_status.value
    assert record["ml_status"] == ml_status.value
    assert record["ml_confidence"] is not None


@given(inputs=classification_input_st)
@settings(max_examples=10)
def test_p10_history_ml_fields_none_when_no_ml_result(
    inputs: ClassificationInput,
):
    """
    **Validates: Requirements 5.6**

    When no ML result is available (model not found or inference failed),
    ml_status and ml_confidence in the history record SHALL be None, while
    the rule-based status is still recorded.
    """
    endpoint_id = "ep-no-ml-result"
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
    assert record["ml_status"] is None, (
        f"ml_status should be None when no ML result, got {record['ml_status']!r}"
    )
    assert record["ml_confidence"] is None, (
        f"ml_confidence should be None when no ML result, got {record['ml_confidence']}"
    )

