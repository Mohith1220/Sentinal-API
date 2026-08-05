# Feature: sentinel-api, Property 9: Classification Rule Determinism
"""
Property 9: Classification Rule Determinism

For any endpoint record with known values for
(traffic_recency_days, spec_presence, deprecated_flag, owner_present),
the Classification Engine's rule-based classifier SHALL assign exactly one
lifecycle status from {Active, Deprecated, Orphaned, Zombie}, and the
assigned status SHALL match the highest-priority rule whose conditions
are satisfied.

Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5
"""

import sys
import os

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
SERVICE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "services", "classification-service"
)
if SERVICE_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(SERVICE_DIR))

from rule_engine import ClassificationInput, apply_rules
from sentinel_shared.models import LifecycleStatus

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# traffic_recency_days: None (no traffic ever) or a non-negative float
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
# Properties
# ---------------------------------------------------------------------------


@given(inputs=classification_input_st)
@settings(max_examples=10)
def test_p9_exactly_one_status_returned(inputs: ClassificationInput):
    """
    **Validates: Requirements 5.1**

    apply_rules always returns exactly one LifecycleStatus value.
    """
    result = apply_rules(inputs)
    assert isinstance(result, LifecycleStatus)
    # Must be one of the four valid statuses
    assert result in {
        LifecycleStatus.ACTIVE,
        LifecycleStatus.DEPRECATED,
        LifecycleStatus.ORPHANED,
        LifecycleStatus.ZOMBIE,
    }


@given(
    traffic_recency_days=st.floats(
        min_value=0.0, max_value=30.0, allow_nan=False, allow_infinity=False
    ),
    deprecated_flag=st.booleans(),
    owner_present=st.booleans(),
)
@settings(max_examples=10)
def test_p9_active_rule_priority_1(
    traffic_recency_days: float,
    deprecated_flag: bool,
    owner_present: bool,
):
    """
    **Validates: Requirements 5.2**

    When spec_presence=True AND traffic_recency_days <= 30,
    the result is always Active regardless of other flags.
    (Rule 1 has highest priority.)
    """
    inputs = ClassificationInput(
        traffic_recency_days=traffic_recency_days,
        spec_presence=True,
        deprecated_flag=deprecated_flag,
        owner_present=owner_present,
    )
    result = apply_rules(inputs)
    assert result == LifecycleStatus.ACTIVE, (
        f"Expected Active for spec_presence=True, recency={traffic_recency_days}, "
        f"deprecated={deprecated_flag}, owner={owner_present}; got {result}"
    )


@given(
    traffic_recency_days=st.floats(
        min_value=0.0, max_value=30.0, allow_nan=False, allow_infinity=False
    ),
    owner_present=st.booleans(),
)
@settings(max_examples=10)
def test_p9_deprecated_rule_priority_2(
    traffic_recency_days: float,
    owner_present: bool,
):
    """
    **Validates: Requirements 5.3**

    When spec_presence=False AND deprecated_flag=True AND traffic_recency_days <= 30,
    the result is always Deprecated.
    (Rule 2 fires when Rule 1 does not.)
    """
    inputs = ClassificationInput(
        traffic_recency_days=traffic_recency_days,
        spec_presence=False,
        deprecated_flag=True,
        owner_present=owner_present,
    )
    result = apply_rules(inputs)
    assert result == LifecycleStatus.DEPRECATED, (
        f"Expected Deprecated for spec_presence=False, deprecated=True, "
        f"recency={traffic_recency_days}; got {result}"
    )


@given(
    traffic_recency_days=st.one_of(
        st.none(),
        st.floats(
            min_value=90.01, max_value=3650.0, allow_nan=False, allow_infinity=False
        ),
    ),
)
@settings(max_examples=10)
def test_p9_orphaned_rule_priority_3(traffic_recency_days):
    """
    **Validates: Requirements 5.4**

    When traffic_recency_days > 90 (or None) AND owner_present=False
    AND spec_presence=False AND deprecated_flag=False,
    the result is always Orphaned.
    """
    inputs = ClassificationInput(
        traffic_recency_days=traffic_recency_days,
        spec_presence=False,
        deprecated_flag=False,
        owner_present=False,
    )
    result = apply_rules(inputs)
    assert result == LifecycleStatus.ORPHANED, (
        f"Expected Orphaned for recency={traffic_recency_days}, "
        f"no spec, no deprecated, no owner; got {result}"
    )


@given(
    traffic_recency_days=st.floats(
        min_value=0.0, max_value=30.0, allow_nan=False, allow_infinity=False
    ),
    owner_present=st.booleans(),
)
@settings(max_examples=10)
def test_p9_zombie_rule_priority_4(
    traffic_recency_days: float,
    owner_present: bool,
):
    """
    **Validates: Requirements 5.5**

    When spec_presence=False AND deprecated_flag=False AND traffic_recency_days <= 30,
    the result is always Zombie.
    (Rules 1, 2, 3 do not fire; Rule 4 fires.)
    """
    inputs = ClassificationInput(
        traffic_recency_days=traffic_recency_days,
        spec_presence=False,
        deprecated_flag=False,
        owner_present=owner_present,
    )
    result = apply_rules(inputs)
    assert result == LifecycleStatus.ZOMBIE, (
        f"Expected Zombie for spec_presence=False, deprecated=False, "
        f"recency={traffic_recency_days}, owner={owner_present}; got {result}"
    )


@given(inputs=classification_input_st)
@settings(max_examples=10)
def test_p9_determinism_same_inputs_same_output(inputs: ClassificationInput):
    """
    **Validates: Requirements 5.1**

    apply_rules is a pure function: calling it twice with the same inputs
    always produces the same result.
    """
    result1 = apply_rules(inputs)
    result2 = apply_rules(inputs)
    assert result1 == result2

