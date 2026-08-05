# Feature: sentinel-api, Property 15: Cold-Start Baseline Assignment
"""
Property 15: Cold-Start Baseline Assignment

For any new API endpoint with fewer than 7 days of traffic history, the
Anomaly Detector SHALL assign a cluster-derived baseline (keyed on
lifecycle_status and data_sensitivity) rather than an individual endpoint
baseline, and SHALL not emit a "no baseline available" error.

Validates: Requirements 8.5
"""

import sys
import os
import asyncio
from typing import Optional

from hypothesis import given, settings, assume
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, _REPO_ROOT)
from conftest import activate_service
activate_service("anomaly-detector-service")

from anomaly_service import resolve_baseline
from db import InMemoryAnomalyStore
from sentinel_shared.models import LifecycleStatus, DataSensitivity

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

endpoint_id_st = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-_"),
    min_size=1,
    max_size=64,
)

lifecycle_status_st = st.sampled_from([s.value for s in LifecycleStatus])
data_sensitivity_st = st.sampled_from([s.value for s in DataSensitivity])

# training_days < 7 = cold-start
cold_start_training_days_st = st.integers(min_value=0, max_value=6)

# training_days >= 7 = sufficient history
sufficient_training_days_st = st.integers(min_value=7, max_value=365)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _run(coro):
    """Run a coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


@given(
    endpoint_id=endpoint_id_st,
    lifecycle_status=lifecycle_status_st,
    data_sensitivity=data_sensitivity_st,
    training_days=cold_start_training_days_st,
)
@settings(max_examples=10)
def test_p15_cold_start_uses_cluster_baseline(
    endpoint_id: str,
    lifecycle_status: str,
    data_sensitivity: str,
    training_days: int,
):
    """
    **Validates: Requirements 8.5**

    When an endpoint has fewer than 7 days of training history, resolve_baseline
    SHALL return the cluster baseline keyed on
    f"{lifecycle_status}:{data_sensitivity}".
    """
    store = InMemoryAnomalyStore()

    # Seed endpoint
    store.seed_endpoint(
        endpoint_id,
        lifecycle_status=lifecycle_status,
        data_sensitivity=data_sensitivity,
    )

    # Seed individual baseline with insufficient training
    store.seed_baseline(
        endpoint_id=endpoint_id,
        cluster_key=None,
        model_artifact=b"individual_model",
        training_days=training_days,
    )

    # Seed cluster baseline
    cluster_key = f"{lifecycle_status}:{data_sensitivity}"
    store.seed_baseline(
        endpoint_id=None,
        cluster_key=cluster_key,
        model_artifact=b"cluster_model",
        training_days=30,
    )

    baseline = _run(resolve_baseline(endpoint_id, store))

    assert baseline is not None, (
        f"resolve_baseline must not return None when a cluster baseline exists "
        f"(endpoint_id={endpoint_id}, training_days={training_days})"
    )
    assert baseline.get("cluster_key") == cluster_key, (
        f"Expected cluster baseline with key {cluster_key!r}, "
        f"got cluster_key={baseline.get('cluster_key')!r}"
    )
    assert baseline.get("model_artifact") == b"cluster_model", (
        "Expected cluster model artifact to be returned"
    )


@given(
    endpoint_id=endpoint_id_st,
    lifecycle_status=lifecycle_status_st,
    data_sensitivity=data_sensitivity_st,
    training_days=sufficient_training_days_st,
)
@settings(max_examples=10)
def test_p15_sufficient_history_uses_individual_baseline(
    endpoint_id: str,
    lifecycle_status: str,
    data_sensitivity: str,
    training_days: int,
):
    """
    **Validates: Requirements 8.5**

    When an endpoint has >= 7 days of training history, resolve_baseline
    SHALL return the individual endpoint baseline (not the cluster baseline).
    """
    store = InMemoryAnomalyStore()

    store.seed_endpoint(
        endpoint_id,
        lifecycle_status=lifecycle_status,
        data_sensitivity=data_sensitivity,
    )

    # Seed individual baseline with sufficient training
    store.seed_baseline(
        endpoint_id=endpoint_id,
        cluster_key=None,
        model_artifact=b"individual_model_sufficient",
        training_days=training_days,
    )

    # Also seed a cluster baseline (should NOT be used)
    cluster_key = f"{lifecycle_status}:{data_sensitivity}"
    store.seed_baseline(
        endpoint_id=None,
        cluster_key=cluster_key,
        model_artifact=b"cluster_model",
        training_days=30,
    )

    baseline = _run(resolve_baseline(endpoint_id, store))

    assert baseline is not None
    assert baseline.get("model_artifact") == b"individual_model_sufficient", (
        f"Expected individual baseline for training_days={training_days} >= 7, "
        f"but got cluster baseline"
    )


@given(
    endpoint_id=endpoint_id_st,
    lifecycle_status=lifecycle_status_st,
    data_sensitivity=data_sensitivity_st,
    training_days=cold_start_training_days_st,
)
@settings(max_examples=10)
def test_p15_cold_start_never_raises_no_baseline_error(
    endpoint_id: str,
    lifecycle_status: str,
    data_sensitivity: str,
    training_days: int,
):
    """
    **Validates: Requirements 8.5**

    resolve_baseline SHALL never raise an exception — it always returns
    a baseline dict or None, never raises "no baseline available".
    """
    store = InMemoryAnomalyStore()

    store.seed_endpoint(
        endpoint_id,
        lifecycle_status=lifecycle_status,
        data_sensitivity=data_sensitivity,
    )

    # Seed individual baseline with insufficient training
    store.seed_baseline(
        endpoint_id=endpoint_id,
        cluster_key=None,
        model_artifact=b"individual_model",
        training_days=training_days,
    )

    # No cluster baseline seeded — should still not raise

    try:
        baseline = _run(resolve_baseline(endpoint_id, store))
        # Must return either a dict or None — never raise
        assert baseline is None or isinstance(baseline, dict), (
            f"resolve_baseline must return dict or None, got {type(baseline)}"
        )
    except Exception as exc:
        raise AssertionError(
            f"resolve_baseline raised an exception instead of returning None: "
            f"{type(exc).__name__}: {exc}"
        ) from exc


@given(
    endpoint_id=endpoint_id_st,
    lifecycle_status=lifecycle_status_st,
    data_sensitivity=data_sensitivity_st,
)
@settings(max_examples=10)
def test_p15_no_baseline_at_all_returns_none_not_exception(
    endpoint_id: str,
    lifecycle_status: str,
    data_sensitivity: str,
):
    """
    **Validates: Requirements 8.5**

    When no baseline exists at all (neither individual nor cluster),
    resolve_baseline returns None without raising.
    """
    store = InMemoryAnomalyStore()

    store.seed_endpoint(
        endpoint_id,
        lifecycle_status=lifecycle_status,
        data_sensitivity=data_sensitivity,
    )

    # No baselines seeded at all

    try:
        baseline = _run(resolve_baseline(endpoint_id, store))
        assert baseline is None, (
            f"Expected None when no baseline exists, got {baseline}"
        )
    except Exception as exc:
        raise AssertionError(
            f"resolve_baseline raised an exception when no baseline exists: "
            f"{type(exc).__name__}: {exc}"
        ) from exc


@given(
    endpoint_id=endpoint_id_st,
    lifecycle_status=lifecycle_status_st,
    data_sensitivity=data_sensitivity_st,
    training_days=cold_start_training_days_st,
)
@settings(max_examples=10)
def test_p15_cluster_key_format_is_lifecycle_colon_sensitivity(
    endpoint_id: str,
    lifecycle_status: str,
    data_sensitivity: str,
    training_days: int,
):
    """
    **Validates: Requirements 8.5**

    The cluster key used for cold-start lookup is always formatted as
    f"{lifecycle_status}:{data_sensitivity}".
    """
    store = InMemoryAnomalyStore()

    store.seed_endpoint(
        endpoint_id,
        lifecycle_status=lifecycle_status,
        data_sensitivity=data_sensitivity,
    )

    # Seed individual baseline with insufficient training
    store.seed_baseline(
        endpoint_id=endpoint_id,
        cluster_key=None,
        model_artifact=b"individual_model",
        training_days=training_days,
    )

    # Seed cluster baseline with the expected key format
    expected_cluster_key = f"{lifecycle_status}:{data_sensitivity}"
    store.seed_baseline(
        endpoint_id=None,
        cluster_key=expected_cluster_key,
        model_artifact=b"cluster_model",
        training_days=30,
    )

    # Also seed a cluster baseline with a WRONG key format (should NOT be used)
    wrong_key = f"{data_sensitivity}:{lifecycle_status}"  # reversed
    if wrong_key != expected_cluster_key:
        store.seed_baseline(
            endpoint_id=None,
            cluster_key=wrong_key,
            model_artifact=b"wrong_cluster_model",
            training_days=30,
        )

    baseline = _run(resolve_baseline(endpoint_id, store))

    assert baseline is not None
    assert baseline.get("cluster_key") == expected_cluster_key, (
        f"Expected cluster key {expected_cluster_key!r}, "
        f"got {baseline.get('cluster_key')!r}"
    )
    assert baseline.get("model_artifact") == b"cluster_model", (
        "Expected the correctly-keyed cluster model to be returned"
    )


@given(
    endpoint_id=endpoint_id_st,
    lifecycle_status=lifecycle_status_st,
    data_sensitivity=data_sensitivity_st,
    training_days=cold_start_training_days_st,
)
@settings(max_examples=10)
def test_p15_cold_start_baseline_is_returned_as_dict(
    endpoint_id: str,
    lifecycle_status: str,
    data_sensitivity: str,
    training_days: int,
):
    """
    **Validates: Requirements 8.5**

    When a cluster baseline is returned, it is a dict with the expected fields.
    """
    store = InMemoryAnomalyStore()

    store.seed_endpoint(
        endpoint_id,
        lifecycle_status=lifecycle_status,
        data_sensitivity=data_sensitivity,
    )

    store.seed_baseline(
        endpoint_id=endpoint_id,
        cluster_key=None,
        model_artifact=b"individual_model",
        training_days=training_days,
    )

    cluster_key = f"{lifecycle_status}:{data_sensitivity}"
    store.seed_baseline(
        endpoint_id=None,
        cluster_key=cluster_key,
        model_artifact=b"cluster_model",
        training_days=30,
    )

    baseline = _run(resolve_baseline(endpoint_id, store))

    assert baseline is not None
    assert isinstance(baseline, dict), (
        f"resolve_baseline must return a dict, got {type(baseline)}"
    )
    # Must have the required fields
    assert "model_artifact" in baseline, "Baseline must have model_artifact field"
    assert "training_days" in baseline, "Baseline must have training_days field"
    assert "cluster_key" in baseline, "Baseline must have cluster_key field"

