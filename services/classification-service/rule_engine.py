"""
Rule Engine for the Classification Service.

Evaluates four priority-ordered rules against endpoint features and returns
exactly one LifecycleStatus.

Rule priority order (highest first):
  1. Active     — in spec/gateway AND traffic in last 30 days
  2. Deprecated — marked deprecated in spec AND traffic in last 30 days
  3. Orphaned   — no traffic for >90 days AND no owning team
  4. Zombie     — not in any spec/gateway AND traffic in last 30 days

If none of the four rules match, defaults to Active (conservative fallback).
"""

from dataclasses import dataclass
from typing import Optional

from sentinel_shared.models import LifecycleStatus


@dataclass
class ClassificationInput:
    """
    Feature inputs for the rule engine.

    Attributes:
        traffic_recency_days: Days since last traffic event. None means no traffic ever.
        spec_presence: True if the endpoint appears in at least one OpenAPI spec or
                       gateway configuration.
        deprecated_flag: True if the endpoint is marked deprecated in its source spec.
        owner_present: True if an owning team is recorded for this endpoint.
    """

    traffic_recency_days: Optional[float]
    spec_presence: bool
    deprecated_flag: bool
    owner_present: bool


def apply_rules(inputs: ClassificationInput) -> LifecycleStatus:
    """
    Evaluate the four priority-ordered classification rules.

    Rules are evaluated in priority order; the first matching rule wins.

    Args:
        inputs: Feature values for the endpoint being classified.

    Returns:
        Exactly one LifecycleStatus value.
    """
    has_recent_traffic = (
        inputs.traffic_recency_days is not None
        and inputs.traffic_recency_days <= 30
    )
    no_traffic_90_days = (
        inputs.traffic_recency_days is None
        or inputs.traffic_recency_days > 90
    )

    # Priority 1: Active — in spec/gateway AND traffic in last 30 days
    if inputs.spec_presence and has_recent_traffic:
        return LifecycleStatus.ACTIVE

    # Priority 2: Deprecated — marked deprecated AND traffic in last 30 days
    if inputs.deprecated_flag and has_recent_traffic:
        return LifecycleStatus.DEPRECATED

    # Priority 3: Orphaned — no traffic for >90 days AND no owning team
    if no_traffic_90_days and not inputs.owner_present:
        return LifecycleStatus.ORPHANED

    # Priority 4: Zombie — not in any spec/gateway AND traffic in last 30 days
    if not inputs.spec_presence and has_recent_traffic:
        return LifecycleStatus.ZOMBIE

    # Default fallback — none of the four rules matched
    # (e.g. has spec, has owner, but traffic is 31–90 days old)
    return LifecycleStatus.ACTIVE
