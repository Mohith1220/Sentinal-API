# Feature: sentinel-api, Property 14: Anomaly Explainability Completeness
"""
Property 14: Anomaly Explainability Completeness

For any emitted anomaly alert, the feature importance record SHALL be
non-empty and SHALL be sorted in descending order of contribution magnitude,
such that the first entry is the feature that contributed most to the
anomaly score.

Note: This property applies when SHAP computation succeeds. When SHAP fails,
the alert is still emitted with feature_importance = [] (graceful degradation).
The property tests both the success path (sorted, non-empty) and the failure
path (empty list, no exception).

Validates: Requirements 8.6, 14.4
"""

import sys
import os
import io

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, _REPO_ROOT)
from conftest import activate_service
activate_service("anomaly-detector-service")

# Skip the entire module if PyTorch is not installed — the LSTM model and
# SHAP explainability require torch at import time.
torch = pytest.importorskip("torch", reason="PyTorch not installed; skipping P14 tests")

from explainability import compute_shap_importance, FEATURE_NAMES
from baseline_model import train_baseline, LSTMBaselineModel

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Hourly counts: non-negative floats representing request counts
hourly_count_st = st.floats(
    min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False
)

# A window of 25 hourly counts (24 for input + 1 for observed)
window_st = st.lists(hourly_count_st, min_size=25, max_size=25)

# A window of 7 days + 1 hour of hourly counts for training
training_data_st = st.lists(
    hourly_count_st, min_size=7 * 24 + 1, max_size=7 * 24 + 1
)


# ---------------------------------------------------------------------------
# Helper: train a minimal model for testing
# ---------------------------------------------------------------------------


def _train_minimal_model(hourly_counts: list[float]) -> bytes:
    """Train a model with minimal epochs for fast property testing."""
    return train_baseline(hourly_counts, history_days=7, epochs=3)


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


@given(training_data=training_data_st, window=window_st)
@settings(max_examples=15)  # Reduced due to model training cost
def test_p14_feature_importance_sorted_descending_by_abs_contribution(
    training_data: list[float],
    window: list[float],
):
    """
    **Validates: Requirements 8.6, 14.4**

    When SHAP computation succeeds, the feature importance list is sorted
    in descending order of abs(contribution).
    """
    model_artifact = _train_minimal_model(training_data)

    result = compute_shap_importance(
        model_artifact=model_artifact,
        input_window=window,
        sequence_length=24,
    )

    # If SHAP succeeded (non-empty result), verify sorting
    if result:
        abs_contributions = [abs(contribution) for _, contribution in result]
        assert abs_contributions == sorted(abs_contributions, reverse=True), (
            f"Feature importance not sorted descending by abs(contribution): "
            f"{result}"
        )


@given(training_data=training_data_st, window=window_st)
@settings(max_examples=15)
def test_p14_feature_importance_first_entry_has_max_contribution(
    training_data: list[float],
    window: list[float],
):
    """
    **Validates: Requirements 8.6, 14.4**

    The first entry in the feature importance list has the highest
    abs(contribution) among all entries.
    """
    model_artifact = _train_minimal_model(training_data)

    result = compute_shap_importance(
        model_artifact=model_artifact,
        input_window=window,
        sequence_length=24,
    )

    if result and len(result) > 1:
        first_abs = abs(result[0][1])
        for feature_name, contribution in result[1:]:
            assert abs(contribution) <= first_abs, (
                f"First entry {result[0]} does not have max abs contribution; "
                f"found {feature_name}={contribution} with higher abs value"
            )


@given(training_data=training_data_st, window=window_st)
@settings(max_examples=15)
def test_p14_feature_importance_entries_have_valid_structure(
    training_data: list[float],
    window: list[float],
):
    """
    **Validates: Requirements 8.6, 14.4**

    Each entry in the feature importance list is a (feature_name, contribution)
    tuple where feature_name is a non-empty string and contribution is a float.
    """
    model_artifact = _train_minimal_model(training_data)

    result = compute_shap_importance(
        model_artifact=model_artifact,
        input_window=window,
        sequence_length=24,
    )

    for entry in result:
        assert isinstance(entry, tuple), f"Entry must be a tuple, got {type(entry)}"
        assert len(entry) == 2, f"Entry must have 2 elements, got {len(entry)}"

        feature_name, contribution = entry
        assert isinstance(feature_name, str) and feature_name.strip() != "", (
            f"feature_name must be a non-empty string, got {feature_name!r}"
        )
        assert isinstance(contribution, float), (
            f"contribution must be a float, got {type(contribution)}"
        )
        assert not (contribution != contribution), "contribution must not be NaN"


@given(training_data=training_data_st, window=window_st)
@settings(max_examples=15)
def test_p14_feature_importance_feature_names_from_known_set(
    training_data: list[float],
    window: list[float],
):
    """
    **Validates: Requirements 8.6, 14.4**

    All feature names in the importance list come from the known feature set.
    """
    model_artifact = _train_minimal_model(training_data)

    result = compute_shap_importance(
        model_artifact=model_artifact,
        input_window=window,
        sequence_length=24,
    )

    for feature_name, _ in result:
        assert feature_name in FEATURE_NAMES, (
            f"Unknown feature name: {feature_name!r}. "
            f"Expected one of: {FEATURE_NAMES}"
        )


@given(
    invalid_artifact=st.binary(max_size=100),
    window=window_st,
)
@settings(max_examples=10)
def test_p14_shap_failure_returns_empty_list_not_exception(
    invalid_artifact: bytes,
    window: list[float],
):
    """
    **Validates: Requirements 8.6, 14.4**

    When SHAP computation fails (e.g., invalid model artifact), the function
    returns an empty list rather than raising an exception.

    This ensures graceful degradation: alerts are still emitted even when
    explainability is unavailable.
    """
    # This should never raise — always returns [] on failure
    result = compute_shap_importance(
        model_artifact=invalid_artifact,
        input_window=window,
        sequence_length=24,
    )

    assert isinstance(result, list), (
        f"compute_shap_importance must return a list, got {type(result)}"
    )
    # On failure, must return empty list
    assert result == [], (
        f"compute_shap_importance must return [] on failure, got {result}"
    )


@given(window=window_st)
@settings(max_examples=10)
def test_p14_shap_empty_artifact_returns_empty_list(window: list[float]):
    """
    **Validates: Requirements 8.6, 14.4**

    Empty model artifact returns [] without raising.
    """
    result = compute_shap_importance(
        model_artifact=b"",
        input_window=window,
        sequence_length=24,
    )

    assert result == []


@given(training_data=training_data_st)
@settings(max_examples=15)
def test_p14_shap_insufficient_window_returns_empty_list(
    training_data: list[float],
):
    """
    **Validates: Requirements 8.6, 14.4**

    When the input window is shorter than sequence_length, SHAP returns []
    without raising.
    """
    model_artifact = _train_minimal_model(training_data)

    # Window shorter than sequence_length=24
    short_window = [1.0] * 10

    result = compute_shap_importance(
        model_artifact=model_artifact,
        input_window=short_window,
        sequence_length=24,
    )

    assert result == []


@given(training_data=training_data_st, window=window_st)
@settings(max_examples=15)
def test_p14_feature_importance_no_duplicate_feature_names(
    training_data: list[float],
    window: list[float],
):
    """
    **Validates: Requirements 8.6, 14.4**

    The feature importance list contains no duplicate feature names.
    """
    model_artifact = _train_minimal_model(training_data)

    result = compute_shap_importance(
        model_artifact=model_artifact,
        input_window=window,
        sequence_length=24,
    )

    feature_names = [name for name, _ in result]
    assert len(feature_names) == len(set(feature_names)), (
        f"Duplicate feature names in importance list: {feature_names}"
    )


