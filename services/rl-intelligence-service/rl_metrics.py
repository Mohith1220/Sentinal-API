"""
Prometheus custom metrics for the RL Intelligence Service.

All metrics are registered once at module load time. The sentinel_shared
metrics module instruments HTTP latency; this file adds RL-specific counters,
gauges, and histograms.
"""

from prometheus_client import Counter, Gauge, Histogram, REGISTRY

# Guard against duplicate registration during hot-reload / test runs
_registered: dict[str, object] = {}


def _get_or_create(cls, name: str, doc: str, **kwargs) -> object:
    if name in _registered:
        return _registered[name]
    try:
        metric = cls(name, doc, **kwargs)
    except ValueError:
        # Already registered (e.g. in a test environment)
        metric = REGISTRY._names_to_collectors.get(name)
    _registered[name] = metric
    return metric


# --- Prediction counters ---

rl_predictions_total = _get_or_create(
    Counter,
    "rl_predictions_total",
    "Total number of RL predictions made",
    ["action_name"],
)

rl_reward_events_total = _get_or_create(
    Counter,
    "rl_reward_events_total",
    "Total reward events received by type",
    ["event_type"],
)

rl_training_runs_total = _get_or_create(
    Counter,
    "rl_training_runs_total",
    "Total number of PPO training runs completed",
)

rl_analyst_feedbacks_total = _get_or_create(
    Counter,
    "rl_analyst_feedbacks_total",
    "Total analyst feedback events processed",
    ["feedback_type"],
)

# --- Gauges ---

rl_active_policy_version = _get_or_create(
    Gauge,
    "rl_active_policy_version",
    "Currently active PPO policy version number",
)

rl_mean_reward_last_100 = _get_or_create(
    Gauge,
    "rl_mean_reward_last_100",
    "Mean reward value over the last 100 reward events",
)

rl_analyst_agreement_rate = _get_or_create(
    Gauge,
    "rl_analyst_agreement_rate",
    "Fraction of RL recommendations that analysts agreed with",
)

rl_false_positive_rate = _get_or_create(
    Gauge,
    "rl_false_positive_rate",
    "Fraction of alerts that were rejected by analysts",
)

rl_endpoints_monitored = _get_or_create(
    Gauge,
    "rl_endpoints_monitored",
    "Number of API endpoints currently being monitored by the RL service",
)

rl_graph_features_last_refresh_timestamp = _get_or_create(
    Gauge,
    "rl_graph_features_last_refresh_timestamp",
    "Unix timestamp of the last successful graph centrality refresh",
)

# --- Histograms ---

rl_risk_adjustment = _get_or_create(
    Histogram,
    "rl_risk_adjustment",
    "Distribution of RL risk score adjustments (-20 to +20)",
    buckets=[-20, -15, -10, -5, 0, 5, 10, 15, 20],
)

rl_zombie_probability = _get_or_create(
    Histogram,
    "rl_zombie_probability",
    "Distribution of zombie probability estimates",
    buckets=[0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

rl_threat_probability = _get_or_create(
    Histogram,
    "rl_threat_probability",
    "Distribution of threat probability estimates",
    buckets=[0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

rl_prediction_latency_seconds = _get_or_create(
    Histogram,
    "rl_prediction_latency_seconds",
    "Time taken to produce a single RL prediction end-to-end",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)


def record_prediction(action_name: str, zombie_prob: float, threat_prob: float,
                      rl_adjustment: int, latency_seconds: float) -> None:
    """Convenience function to record all prediction-related metrics at once."""
    rl_predictions_total.labels(action_name=action_name).inc()
    rl_zombie_probability.observe(zombie_prob)
    rl_threat_probability.observe(threat_prob)
    rl_risk_adjustment.observe(rl_adjustment)
    rl_prediction_latency_seconds.observe(latency_seconds)


def record_reward_event(event_type: str) -> None:
    rl_reward_events_total.labels(event_type=event_type).inc()


def record_analyst_feedback(feedback_type: str) -> None:
    rl_analyst_feedbacks_total.labels(feedback_type=feedback_type).inc()


def update_policy_gauges(version: int, mean_reward: float,
                          agreement_rate: float, fp_rate: float,
                          endpoints_monitored: int) -> None:
    rl_active_policy_version.set(version)
    rl_mean_reward_last_100.set(mean_reward)
    rl_analyst_agreement_rate.set(agreement_rate)
    rl_false_positive_rate.set(fp_rate)
    rl_endpoints_monitored.set(endpoints_monitored)
