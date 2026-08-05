"""
Unit tests for sentinel_shared.models.

Covers:
- EndpointRecord creation with defaults
- EndpointRecord JSON round-trip
- RiskScoreResult with factors list
- AnomalyAlert with feature_importance list
- RemediationRecommendation validation
- RiskFactor validation
- Enum values
"""

import json
import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from sentinel_shared.models import (
    AnomalyAlert,
    AuthScheme,
    DataSensitivity,
    EndpointRecord,
    LifecycleStatus,
    RemediationRecommendation,
    RiskFactor,
    RiskScoreResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_endpoint(**kwargs) -> EndpointRecord:
    defaults = dict(
        http_method="GET",
        host="api.example.com",
        normalized_path="/accounts/{n}",
    )
    defaults.update(kwargs)
    return EndpointRecord(**defaults)


def make_risk_factor(**kwargs) -> RiskFactor:
    defaults = dict(rule="no_auth", points=40, description="No authentication scheme")
    defaults.update(kwargs)
    return RiskFactor(**defaults)


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# EndpointRecord — creation with defaults
# ---------------------------------------------------------------------------

class TestEndpointRecordDefaults:
    def test_required_fields_only(self):
        ep = make_endpoint()
        assert ep.http_method == "GET"
        assert ep.host == "api.example.com"
        assert ep.normalized_path == "/accounts/{n}"

    def test_default_auth_scheme(self):
        ep = make_endpoint()
        assert ep.auth_scheme == AuthScheme.UNKNOWN

    def test_default_data_sensitivity(self):
        ep = make_endpoint()
        assert ep.data_sensitivity == DataSensitivity.INTERNAL

    def test_default_lifecycle_status(self):
        ep = make_endpoint()
        assert ep.lifecycle_status == LifecycleStatus.ACTIVE

    def test_default_risk_score_zero(self):
        ep = make_endpoint()
        assert ep.risk_score == 0

    def test_default_request_count_zero(self):
        ep = make_endpoint()
        assert ep.request_count_24h == 0

    def test_default_last_access_at_none(self):
        ep = make_endpoint()
        assert ep.last_access_at is None

    def test_default_owning_team_none(self):
        ep = make_endpoint()
        assert ep.owning_team is None

    def test_default_source_file_id_none(self):
        ep = make_endpoint()
        assert ep.source_file_id is None

    def test_default_metadata_empty_dict(self):
        ep = make_endpoint()
        assert ep.metadata == {}

    def test_auto_generated_id_is_uuid(self):
        ep = make_endpoint()
        # Should not raise
        uuid.UUID(ep.id)

    def test_two_instances_have_different_ids(self):
        ep1 = make_endpoint()
        ep2 = make_endpoint()
        assert ep1.id != ep2.id

    def test_http_method_normalized_to_uppercase(self):
        ep = make_endpoint(http_method="get")
        assert ep.http_method == "GET"

    def test_normalized_path_gets_leading_slash(self):
        ep = make_endpoint(normalized_path="accounts/{n}")
        assert ep.normalized_path == "/accounts/{n}"


# ---------------------------------------------------------------------------
# EndpointRecord — validation errors
# ---------------------------------------------------------------------------

class TestEndpointRecordValidation:
    def test_invalid_http_method_raises(self):
        with pytest.raises(ValidationError):
            make_endpoint(http_method="FETCH")

    def test_empty_host_raises(self):
        with pytest.raises(ValidationError):
            make_endpoint(host="")

    def test_whitespace_host_raises(self):
        with pytest.raises(ValidationError):
            make_endpoint(host="   ")

    def test_risk_score_above_100_raises(self):
        with pytest.raises(ValidationError):
            make_endpoint(risk_score=101)

    def test_risk_score_below_0_raises(self):
        with pytest.raises(ValidationError):
            make_endpoint(risk_score=-1)

    def test_negative_request_count_raises(self):
        with pytest.raises(ValidationError):
            make_endpoint(request_count_24h=-1)

    def test_invalid_auth_scheme_raises(self):
        with pytest.raises(ValidationError):
            make_endpoint(auth_scheme="bearer")

    def test_invalid_lifecycle_status_raises(self):
        with pytest.raises(ValidationError):
            make_endpoint(lifecycle_status="Unknown")


# ---------------------------------------------------------------------------
# EndpointRecord — JSON round-trip
# ---------------------------------------------------------------------------

class TestEndpointRecordRoundTrip:
    def test_model_dump_and_validate_roundtrip(self):
        ep = EndpointRecord(
            http_method="POST",
            host="payments.bank.internal",
            normalized_path="/payments/{id}/confirm",
            auth_scheme=AuthScheme.JWT,
            data_sensitivity=DataSensitivity.FINANCIAL,
            lifecycle_status=LifecycleStatus.ACTIVE,
            risk_score=70,
            request_count_24h=1500,
            last_access_at=datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            owning_team="payments-team",
            source_file_id="openapi/payments.yaml",
            metadata={"version": "v2", "deprecated": False},
        )
        dumped = ep.model_dump()
        restored = EndpointRecord.model_validate(dumped)

        assert restored.http_method == ep.http_method
        assert restored.host == ep.host
        assert restored.normalized_path == ep.normalized_path
        assert restored.auth_scheme == ep.auth_scheme
        assert restored.data_sensitivity == ep.data_sensitivity
        assert restored.lifecycle_status == ep.lifecycle_status
        assert restored.risk_score == ep.risk_score
        assert restored.request_count_24h == ep.request_count_24h
        assert restored.last_access_at == ep.last_access_at
        assert restored.owning_team == ep.owning_team
        assert restored.source_file_id == ep.source_file_id
        assert restored.metadata == ep.metadata
        assert restored.id == ep.id

    def test_json_serialization_roundtrip(self):
        ep = make_endpoint(
            auth_scheme=AuthScheme.OAUTH2,
            data_sensitivity=DataSensitivity.PII,
            lifecycle_status=LifecycleStatus.ZOMBIE,
            risk_score=90,
        )
        json_str = ep.model_dump_json()
        restored = EndpointRecord.model_validate_json(json_str)

        assert restored.http_method == ep.http_method
        assert restored.auth_scheme == ep.auth_scheme
        assert restored.data_sensitivity == ep.data_sensitivity
        assert restored.lifecycle_status == ep.lifecycle_status
        assert restored.risk_score == ep.risk_score
        assert restored.id == ep.id

    def test_model_dump_contains_expected_keys(self):
        ep = make_endpoint()
        d = ep.model_dump()
        expected_keys = {
            "http_method", "host", "normalized_path", "auth_scheme",
            "data_sensitivity", "lifecycle_status", "risk_score",
            "request_count_24h", "last_access_at", "owning_team",
            "source_file_id", "metadata", "id",
        }
        assert expected_keys.issubset(d.keys())

    def test_roundtrip_preserves_metadata_dict(self):
        ep = make_endpoint(metadata={"key": "value", "nested": {"a": 1}})
        restored = EndpointRecord.model_validate(ep.model_dump())
        assert restored.metadata == {"key": "value", "nested": {"a": 1}}

    def test_roundtrip_with_none_optional_fields(self):
        ep = make_endpoint()
        restored = EndpointRecord.model_validate(ep.model_dump())
        assert restored.last_access_at is None
        assert restored.owning_team is None
        assert restored.source_file_id is None


# ---------------------------------------------------------------------------
# RiskFactor
# ---------------------------------------------------------------------------

class TestRiskFactor:
    def test_basic_creation(self):
        rf = make_risk_factor()
        assert rf.rule == "no_auth"
        assert rf.points == 40
        assert rf.description == "No authentication scheme"

    def test_zero_points_allowed(self):
        rf = make_risk_factor(points=0)
        assert rf.points == 0

    def test_negative_points_raises(self):
        with pytest.raises(ValidationError):
            make_risk_factor(points=-1)

    def test_empty_rule_raises(self):
        with pytest.raises(ValidationError):
            make_risk_factor(rule="")

    def test_empty_description_raises(self):
        with pytest.raises(ValidationError):
            make_risk_factor(description="")

    def test_whitespace_rule_raises(self):
        with pytest.raises(ValidationError):
            make_risk_factor(rule="   ")

    def test_roundtrip(self):
        rf = make_risk_factor()
        restored = RiskFactor.model_validate(rf.model_dump())
        assert restored.rule == rf.rule
        assert restored.points == rf.points
        assert restored.description == rf.description


# ---------------------------------------------------------------------------
# RiskScoreResult — with factors list
# ---------------------------------------------------------------------------

class TestRiskScoreResult:
    def test_creation_with_factors(self):
        factors = [
            RiskFactor(rule="no_auth", points=40, description="No auth"),
            RiskFactor(rule="zombie", points=20, description="Zombie endpoint"),
        ]
        result = RiskScoreResult(
            endpoint_id=str(uuid.uuid4()),
            score=60,
            factors=factors,
            computed_at=utcnow(),
        )
        assert result.score == 60
        assert len(result.factors) == 2

    def test_score_capped_at_100(self):
        # Pydantic should reject scores > 100
        with pytest.raises(ValidationError):
            RiskScoreResult(
                endpoint_id="ep-1",
                score=101,
                factors=[],
                computed_at=utcnow(),
            )

    def test_score_below_0_raises(self):
        with pytest.raises(ValidationError):
            RiskScoreResult(
                endpoint_id="ep-1",
                score=-1,
                factors=[],
                computed_at=utcnow(),
            )

    def test_empty_factors_list_allowed(self):
        result = RiskScoreResult(
            endpoint_id="ep-1",
            score=0,
            factors=[],
            computed_at=utcnow(),
        )
        assert result.factors == []

    def test_factors_are_risk_factor_instances(self):
        rf = make_risk_factor()
        result = RiskScoreResult(
            endpoint_id="ep-1",
            score=40,
            factors=[rf],
            computed_at=utcnow(),
        )
        assert isinstance(result.factors[0], RiskFactor)

    def test_roundtrip(self):
        factors = [make_risk_factor()]
        result = RiskScoreResult(
            endpoint_id="ep-abc",
            score=40,
            factors=factors,
            computed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        restored = RiskScoreResult.model_validate(result.model_dump())
        assert restored.endpoint_id == result.endpoint_id
        assert restored.score == result.score
        assert len(restored.factors) == len(result.factors)
        assert restored.factors[0].rule == result.factors[0].rule

    def test_empty_endpoint_id_raises(self):
        with pytest.raises(ValidationError):
            RiskScoreResult(
                endpoint_id="",
                score=0,
                factors=[],
                computed_at=utcnow(),
            )


# ---------------------------------------------------------------------------
# AnomalyAlert — with feature_importance list
# ---------------------------------------------------------------------------

class TestAnomalyAlert:
    def _make_alert(self, **kwargs) -> AnomalyAlert:
        defaults = dict(
            endpoint_id=str(uuid.uuid4()),
            anomaly_type="volume_spike",
            observed_value=1500.0,
            baseline_value=300.0,
            deviation_sigma=4.2,
            feature_importance=[("request_rate", 0.85), ("geo_entropy", 0.15)],
            emitted_at=utcnow(),
        )
        defaults.update(kwargs)
        return AnomalyAlert(**defaults)

    def test_basic_creation(self):
        alert = self._make_alert()
        assert alert.anomaly_type == "volume_spike"
        assert alert.observed_value == 1500.0
        assert alert.baseline_value == 300.0
        assert alert.deviation_sigma == 4.2

    def test_feature_importance_list(self):
        alert = self._make_alert()
        assert len(alert.feature_importance) == 2
        assert alert.feature_importance[0] == ("request_rate", 0.85)
        assert alert.feature_importance[1] == ("geo_entropy", 0.15)

    def test_empty_feature_importance_allowed(self):
        # SHAP failure case: feature_importance = []
        alert = self._make_alert(feature_importance=[])
        assert alert.feature_importance == []

    def test_auto_generated_id(self):
        alert = self._make_alert()
        uuid.UUID(alert.id)  # Should not raise

    def test_two_alerts_have_different_ids(self):
        a1 = self._make_alert()
        a2 = self._make_alert()
        assert a1.id != a2.id

    def test_negative_deviation_sigma_raises(self):
        with pytest.raises(ValidationError):
            self._make_alert(deviation_sigma=-1.0)

    def test_zero_deviation_sigma_allowed(self):
        alert = self._make_alert(deviation_sigma=0.0)
        assert alert.deviation_sigma == 0.0

    def test_empty_endpoint_id_raises(self):
        with pytest.raises(ValidationError):
            self._make_alert(endpoint_id="")

    def test_empty_anomaly_type_raises(self):
        with pytest.raises(ValidationError):
            self._make_alert(anomaly_type="")

    def test_roundtrip(self):
        alert = self._make_alert()
        restored = AnomalyAlert.model_validate(alert.model_dump())
        assert restored.endpoint_id == alert.endpoint_id
        assert restored.anomaly_type == alert.anomaly_type
        assert restored.observed_value == alert.observed_value
        assert restored.baseline_value == alert.baseline_value
        assert restored.deviation_sigma == alert.deviation_sigma
        assert restored.feature_importance == alert.feature_importance
        assert restored.id == alert.id

    def test_json_roundtrip(self):
        alert = self._make_alert()
        json_str = alert.model_dump_json()
        restored = AnomalyAlert.model_validate_json(json_str)
        assert restored.id == alert.id
        assert restored.feature_importance == alert.feature_importance


# ---------------------------------------------------------------------------
# RemediationRecommendation
# ---------------------------------------------------------------------------

class TestRemediationRecommendation:
    def _make_rec(self, **kwargs) -> RemediationRecommendation:
        defaults = dict(
            endpoint_id=str(uuid.uuid4()),
            priority="High",
            trigger_rule="no_auth",
            summary_text="Add authentication to this endpoint.",
            detail_json={"mechanism": "JWT", "steps": ["Configure JWT middleware"]},
        )
        defaults.update(kwargs)
        return RemediationRecommendation(**defaults)

    def test_basic_creation(self):
        rec = self._make_rec()
        assert rec.priority == "High"
        assert rec.trigger_rule == "no_auth"

    def test_all_valid_priorities(self):
        for priority in ("Critical", "High", "Medium", "Low"):
            rec = self._make_rec(priority=priority)
            assert rec.priority == priority

    def test_invalid_priority_raises(self):
        with pytest.raises(ValidationError):
            self._make_rec(priority="Urgent")

    def test_empty_summary_text_raises(self):
        with pytest.raises(ValidationError):
            self._make_rec(summary_text="")

    def test_empty_trigger_rule_raises(self):
        with pytest.raises(ValidationError):
            self._make_rec(trigger_rule="")

    def test_empty_endpoint_id_raises(self):
        with pytest.raises(ValidationError):
            self._make_rec(endpoint_id="")

    def test_auto_generated_id(self):
        rec = self._make_rec()
        uuid.UUID(rec.id)  # Should not raise

    def test_detail_json_can_be_empty_dict(self):
        rec = self._make_rec(detail_json={})
        assert rec.detail_json == {}

    def test_roundtrip(self):
        rec = self._make_rec()
        restored = RemediationRecommendation.model_validate(rec.model_dump())
        assert restored.endpoint_id == rec.endpoint_id
        assert restored.priority == rec.priority
        assert restored.trigger_rule == rec.trigger_rule
        assert restored.summary_text == rec.summary_text
        assert restored.detail_json == rec.detail_json
        assert restored.id == rec.id


# ---------------------------------------------------------------------------
# Enum completeness
# ---------------------------------------------------------------------------

class TestEnums:
    def test_lifecycle_status_values(self):
        assert LifecycleStatus.ACTIVE.value == "Active"
        assert LifecycleStatus.DEPRECATED.value == "Deprecated"
        assert LifecycleStatus.ORPHANED.value == "Orphaned"
        assert LifecycleStatus.ZOMBIE.value == "Zombie"
        assert LifecycleStatus.SHADOW.value == "Shadow_API"

    def test_auth_scheme_values(self):
        assert AuthScheme.OAUTH2.value == "OAuth2"
        assert AuthScheme.JWT.value == "JWT"
        assert AuthScheme.API_KEY.value == "api_key"
        assert AuthScheme.NONE.value == "none"
        assert AuthScheme.UNKNOWN.value == "unknown"

    def test_data_sensitivity_values(self):
        assert DataSensitivity.PII.value == "PII"
        assert DataSensitivity.FINANCIAL.value == "financial"
        assert DataSensitivity.INTERNAL.value == "internal"
        assert DataSensitivity.PUBLIC.value == "public"
