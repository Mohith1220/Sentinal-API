"""
Shared data models for SentinelAPI.

All dataclasses and enums from design §4.4, implemented as Pydantic v2 models
with validators and JSON serialization/deserialization support.
"""

from datetime import datetime
from typing import Optional
from enum import Enum
import uuid

from pydantic import BaseModel, Field, field_validator, model_validator


class LifecycleStatus(str, Enum):
    ACTIVE = "Active"
    DEPRECATED = "Deprecated"
    ORPHANED = "Orphaned"
    ZOMBIE = "Zombie"
    SHADOW = "Shadow_API"


class AuthScheme(str, Enum):
    OAUTH2 = "OAuth2"
    JWT = "JWT"
    API_KEY = "api_key"
    NONE = "none"
    UNKNOWN = "unknown"


class DataSensitivity(str, Enum):
    PII = "PII"
    FINANCIAL = "financial"
    INTERNAL = "internal"
    PUBLIC = "public"


class EndpointRecord(BaseModel):
    """
    Represents a discovered API endpoint with its metadata.

    Deduplication key: (http_method, host, normalized_path).
    """

    http_method: str
    host: str
    normalized_path: str
    auth_scheme: AuthScheme = AuthScheme.UNKNOWN
    data_sensitivity: DataSensitivity = DataSensitivity.INTERNAL
    lifecycle_status: LifecycleStatus = LifecycleStatus.ACTIVE
    risk_score: int = Field(default=0, ge=0, le=100)
    request_count_24h: int = Field(default=0, ge=0)
    last_access_at: Optional[datetime] = None
    owning_team: Optional[str] = None
    source_file_id: Optional[str] = None
    metadata: dict = Field(default_factory=dict)
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    @field_validator("http_method")
    @classmethod
    def validate_http_method(cls, v: str) -> str:
        allowed = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"http_method must be one of {allowed}, got '{v}'")
        return upper

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("host must be a non-empty string")
        return v.strip()

    @field_validator("normalized_path")
    @classmethod
    def validate_normalized_path(cls, v: str) -> str:
        if not v:
            raise ValueError("normalized_path must be a non-empty string")
        if not v.startswith("/"):
            v = "/" + v
        return v

    model_config = {"use_enum_values": False}


class RiskFactor(BaseModel):
    """A single contributing factor to an endpoint's risk score."""

    rule: str
    points: int = Field(ge=0)
    description: str

    @field_validator("rule")
    @classmethod
    def validate_rule(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("rule must be a non-empty string")
        return v.strip()

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("description must be a non-empty string")
        return v.strip()


class RiskScoreResult(BaseModel):
    """The result of a risk scoring computation for an endpoint."""

    endpoint_id: str
    score: int = Field(ge=0, le=100, description="Risk score capped at 100")
    factors: list[RiskFactor]
    computed_at: datetime

    @field_validator("endpoint_id")
    @classmethod
    def validate_endpoint_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("endpoint_id must be a non-empty string")
        return v.strip()


class AnomalyAlert(BaseModel):
    """
    An alert emitted when anomalous traffic is detected for an endpoint.

    feature_importance is a ranked list of (feature_name, contribution) pairs,
    sorted descending by abs(contribution).
    """

    endpoint_id: str
    anomaly_type: str
    observed_value: float
    baseline_value: float
    deviation_sigma: float
    feature_importance: list[tuple[str, float]]
    emitted_at: datetime
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    @field_validator("endpoint_id")
    @classmethod
    def validate_endpoint_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("endpoint_id must be a non-empty string")
        return v.strip()

    @field_validator("anomaly_type")
    @classmethod
    def validate_anomaly_type(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("anomaly_type must be a non-empty string")
        return v.strip()

    @field_validator("deviation_sigma")
    @classmethod
    def validate_deviation_sigma(cls, v: float) -> float:
        if v < 0:
            raise ValueError("deviation_sigma must be non-negative")
        return v


class RemediationRecommendation(BaseModel):
    """A prioritized remediation recommendation for a risky endpoint."""

    endpoint_id: str
    priority: str
    trigger_rule: str
    summary_text: str
    detail_json: dict
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        allowed = {"Critical", "High", "Medium", "Low"}
        if v not in allowed:
            raise ValueError(f"priority must be one of {allowed}, got '{v}'")
        return v

    @field_validator("endpoint_id")
    @classmethod
    def validate_endpoint_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("endpoint_id must be a non-empty string")
        return v.strip()

    @field_validator("summary_text")
    @classmethod
    def validate_summary_text(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("summary_text must be a non-empty string")
        return v.strip()

    @field_validator("trigger_rule")
    @classmethod
    def validate_trigger_rule(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("trigger_rule must be a non-empty string")
        return v.strip()
