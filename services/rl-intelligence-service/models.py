"""
Pydantic data models for the RL Intelligence Service.

All request/response schemas, internal state representations,
and database row models are defined here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, Any
from enum import Enum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# RL Action Space
# ---------------------------------------------------------------------------

class RLAction(int, Enum):
    """
    Discrete action space for the SentinelAPI PPO agent.

    Each value maps to a concrete security operation the agent can recommend.
    """
    IGNORE               = 0
    MARK_ACTIVE          = 1
    MARK_DEPRECATED      = 2
    MARK_ORPHANED        = 3
    MARK_ZOMBIE          = 4
    INCREASE_RISK        = 5
    DECREASE_RISK        = 6
    TRIGGER_ALERT        = 7
    TRIGGER_AUTO_REMEDIATION = 8
    REQUIRE_ANALYST_REVIEW   = 9
    ESCALATE_SEVERITY    = 10
    SUPPRESS_ALERT       = 11


ACTION_DESCRIPTIONS: dict[int, str] = {
    0:  "Ignore — no action required for this endpoint",
    1:  "Mark as Active — endpoint is healthy and in use",
    2:  "Mark as Deprecated — endpoint is aging and should be sunset",
    3:  "Mark as Orphaned — no owner or traffic found",
    4:  "Mark as Zombie — undocumented endpoint actively receiving traffic",
    5:  "Increase Risk Score — elevate risk by RL adjustment (+1 to +20)",
    6:  "Decrease Risk Score — reduce risk by RL adjustment (-1 to -20)",
    7:  "Trigger Alert — emit anomaly alert to analyst queue",
    8:  "Trigger Auto-Remediation — execute automated remediation pipeline",
    9:  "Require Analyst Review — flag for human review with context",
    10: "Escalate Severity — escalate existing alert to Critical",
    11: "Suppress Alert — mark alert as known-good and suppress",
}


# ---------------------------------------------------------------------------
# State Space
# ---------------------------------------------------------------------------

class RLStateVector(BaseModel):
    """
    The 18-dimensional state vector fed into the PPO policy network.

    All values are normalised to [0, 1] or [-1, 1] before being passed
    to the network. Raw values are preserved here for explainability.
    """
    # API Metadata (5 features)
    auth_scheme_encoded: float = Field(ge=0.0, le=1.0, description="Auth scheme ordinal [0=none,0.25=api_key,0.5=JWT,0.75=OAuth2,1=unknown]")
    data_sensitivity_encoded: float = Field(ge=0.0, le=1.0, description="Sensitivity ordinal [0=public,0.33=internal,0.67=financial,1=PII]")
    lifecycle_status_encoded: float = Field(ge=0.0, le=1.0, description="Lifecycle ordinal [0=Active,0.25=Deprecated,0.5=Orphaned,0.75=Zombie,1=Shadow]")
    owner_present: float = Field(ge=0.0, le=1.0, description="1=owner known, 0=ownerless")
    spec_presence: float = Field(ge=0.0, le=1.0, description="1=in OpenAPI spec/gateway, 0=undocumented")

    # Traffic Features (3 features)
    traffic_recency_normalized: float = Field(ge=0.0, le=1.0, description="Days since last traffic, normalized by 90-day window (capped at 1)")
    traffic_frequency_normalized: float = Field(ge=0.0, le=1.0, description="24h request count, log-normalized")
    traffic_trend: float = Field(ge=-1.0, le=1.0, description="Traffic trend: +1=rapidly increasing, -1=rapidly decreasing")

    # Graph Intelligence (4 features)
    pagerank_score: float = Field(ge=0.0, le=1.0, description="PageRank centrality normalized to [0,1]")
    betweenness_centrality: float = Field(ge=0.0, le=1.0, description="Betweenness centrality normalized to [0,1]")
    blast_radius_normalized: float = Field(ge=0.0, le=1.0, description="Number of reachable DataAssets / max observed blast radius")
    attack_path_length_normalized: float = Field(ge=0.0, le=1.0, description="Shortest attack path length from internet, normalized")

    # Risk & Anomaly Scores (2 features)
    rule_risk_score_normalized: float = Field(ge=0.0, le=1.0, description="Rule-based risk score / 100")
    anomaly_sigma_normalized: float = Field(ge=0.0, le=1.0, description="Max anomaly deviation_sigma / 10, capped at 1")

    # Historical Context (4 features)
    historical_incident_rate: float = Field(ge=0.0, le=1.0, description="Incidents per 30 days, log-normalized and capped")
    analyst_agreement_rate: float = Field(ge=0.0, le=1.0, description="Fraction of past RL recommendations analyst agreed with")
    remediation_success_rate: float = Field(ge=0.0, le=1.0, description="Fraction of past remediations that reduced risk score")
    false_positive_rate: float = Field(ge=0.0, le=1.0, description="Fraction of past alerts that were analyst-suppressed")

    def to_numpy(self) -> "np.ndarray":
        import numpy as np
        return np.array([
            self.auth_scheme_encoded,
            self.data_sensitivity_encoded,
            self.lifecycle_status_encoded,
            self.owner_present,
            self.spec_presence,
            self.traffic_recency_normalized,
            self.traffic_frequency_normalized,
            self.traffic_trend,
            self.pagerank_score,
            self.betweenness_centrality,
            self.blast_radius_normalized,
            self.attack_path_length_normalized,
            self.rule_risk_score_normalized,
            self.anomaly_sigma_normalized,
            self.historical_incident_rate,
            self.analyst_agreement_rate,
            self.remediation_success_rate,
            self.false_positive_rate,
        ], dtype=np.float32)


STATE_FEATURE_NAMES: list[str] = [
    "auth_scheme",
    "data_sensitivity",
    "lifecycle_status",
    "owner_present",
    "spec_presence",
    "traffic_recency",
    "traffic_frequency",
    "traffic_trend",
    "pagerank_score",
    "betweenness_centrality",
    "blast_radius",
    "attack_path_length",
    "rule_risk_score",
    "anomaly_sigma",
    "historical_incident_rate",
    "analyst_agreement_rate",
    "remediation_success_rate",
    "false_positive_rate",
]

STATE_DIM = len(STATE_FEATURE_NAMES)   # 18
ACTION_DIM = len(RLAction)              # 12


# ---------------------------------------------------------------------------
# Reward Events
# ---------------------------------------------------------------------------

class RewardEventType(str, Enum):
    CORRECT_CLASSIFICATION    = "correct_classification"
    ANALYST_AGREEMENT         = "analyst_agreement"
    SUCCESSFUL_REMEDIATION    = "successful_remediation"
    THREAT_PREVENTION         = "threat_prevention"
    REDUCED_FALSE_POSITIVE    = "reduced_false_positive"
    REDUCED_FALSE_NEGATIVE    = "reduced_false_negative"
    FALSE_POSITIVE            = "false_positive"
    WRONG_CLASSIFICATION      = "wrong_classification"
    MISSED_ATTACK             = "missed_attack"
    FAILED_REMEDIATION        = "failed_remediation"
    ANALYST_OVERRIDE          = "analyst_override"
    ALERT_FATIGUE             = "alert_fatigue"


REWARD_VALUES: dict[RewardEventType, float] = {
    RewardEventType.CORRECT_CLASSIFICATION:  +10.0,
    RewardEventType.ANALYST_AGREEMENT:       +15.0,
    RewardEventType.SUCCESSFUL_REMEDIATION:  +20.0,
    RewardEventType.THREAT_PREVENTION:       +30.0,
    RewardEventType.REDUCED_FALSE_POSITIVE:  +15.0,
    RewardEventType.REDUCED_FALSE_NEGATIVE:  +25.0,
    RewardEventType.FALSE_POSITIVE:          -20.0,
    RewardEventType.WRONG_CLASSIFICATION:    -25.0,
    RewardEventType.MISSED_ATTACK:           -50.0,
    RewardEventType.FAILED_REMEDIATION:      -30.0,
    RewardEventType.ANALYST_OVERRIDE:        -15.0,
    RewardEventType.ALERT_FATIGUE:           -10.0,
}


# ---------------------------------------------------------------------------
# Database row models (what we persist)
# ---------------------------------------------------------------------------

class RLAgentStateRow(BaseModel):
    """Maps to rl_agent_state table — current per-endpoint agent state."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    endpoint_id: str
    state_vector: list[float]          # 18-element list
    last_action: int
    last_reward: float
    total_reward: float
    episode_step: int
    updated_at: datetime


class RLTrainingHistoryRow(BaseModel):
    """Maps to rl_training_history table — PPO training run records."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    policy_version: int
    total_timesteps: int
    mean_reward: float
    std_reward: float
    entropy_loss: float
    policy_loss: float
    value_loss: float
    explained_variance: float
    training_duration_seconds: float
    trained_at: datetime


class RLRewardEventRow(BaseModel):
    """Maps to rl_reward_events table — individual reward signals."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    endpoint_id: str
    event_type: str
    reward_value: float
    action_taken: int
    state_snapshot: list[float]        # 18-element snapshot at time of event
    source: str                        # "kafka", "analyst_feedback", "auto"
    occurred_at: datetime


class RLPredictionRow(BaseModel):
    """Maps to rl_predictions table — each prediction the agent makes."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    endpoint_id: str
    policy_version: int
    action: int
    action_confidence: float           # max probability from softmax
    action_probabilities: list[float]  # 12-element distribution
    rl_risk_adjustment: int            # -20 to +20
    zombie_probability: float
    threat_probability: float
    remediation_probability: float
    shap_values: list[float]           # per-feature contribution to action
    top_features: list[dict]           # [{"feature": str, "contribution": float}]
    rule_risk_score: int
    ml_risk_contribution: float
    final_risk_score: int              # rule_score + ml_contribution + rl_adjustment
    predicted_at: datetime


class RLPolicyVersionRow(BaseModel):
    """Maps to rl_policy_versions table."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    version: int
    artifact_path: str                 # path to saved PPO model artifact
    mean_reward: float
    is_active: bool
    promoted_at: Optional[datetime] = None
    created_at: datetime


class AnalystFeedbackRow(BaseModel):
    """Maps to analyst_feedback table — human feedback that generates rewards."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    endpoint_id: str
    analyst_id: str
    feedback_type: str                 # "classification_override","risk_change","alert_ack","alert_reject","remediation_approved","remediation_rejected"
    previous_value: Optional[str] = None
    new_value: Optional[str] = None
    rl_prediction_id: Optional[str] = None
    reward_generated: float
    notes: Optional[str] = None
    occurred_at: datetime


# ---------------------------------------------------------------------------
# API Request/Response models
# ---------------------------------------------------------------------------

class PredictRequest(BaseModel):
    endpoint_id: str
    force_refresh_graph: bool = False


class PredictResponse(BaseModel):
    endpoint_id: str
    action: int
    action_name: str
    action_description: str
    action_confidence: float
    action_probabilities: dict[str, float]  # action_name -> probability
    rl_risk_adjustment: int
    zombie_probability: float
    threat_probability: float
    remediation_probability: float
    rule_risk_score: int
    final_risk_score: int
    explanation: "ExplanationResponse"
    predicted_at: str


class ExplanationResponse(BaseModel):
    top_features: list[dict]           # [{"feature": str, "contribution": float, "value": float}]
    action_rationale: str
    historical_comparison: dict        # {"similar_endpoints": int, "avg_reward": float}
    confidence_level: str              # "High", "Medium", "Low"
    policy_version: int


class TrainRequest(BaseModel):
    timesteps: int = Field(default=10000, ge=1000, le=500000)
    force: bool = False                # force even if not enough new data


class TrainResponse(BaseModel):
    policy_version: int
    total_timesteps: int
    mean_reward: float
    training_duration_seconds: float
    promoted: bool
    message: str


class RewardRequest(BaseModel):
    endpoint_id: str
    event_type: str
    source: str = "api"
    notes: Optional[str] = None


class RewardResponse(BaseModel):
    reward_value: float
    event_type: str
    endpoint_id: str
    accepted: bool


class AnalystFeedbackRequest(BaseModel):
    endpoint_id: str
    analyst_id: str
    feedback_type: str
    previous_value: Optional[str] = None
    new_value: Optional[str] = None
    rl_prediction_id: Optional[str] = None
    notes: Optional[str] = None


class PolicyMetricsResponse(BaseModel):
    active_policy_version: int
    total_predictions: int
    mean_reward_last_100: float
    analyst_agreement_rate: float
    false_positive_rate: float
    false_negative_rate: float
    zombie_detection_accuracy: float
    training_runs: int
    last_trained_at: Optional[str]


class RLMetricsResponse(BaseModel):
    service: str
    uptime_seconds: float
    total_predictions: int
    total_reward_events: int
    total_analyst_feedbacks: int
    active_policy_version: int
    kafka_lag: dict[str, int]
    graph_features_last_updated: Optional[str]
    endpoints_monitored: int
