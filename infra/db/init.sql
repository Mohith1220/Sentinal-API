-- SentinelAPI — PostgreSQL initialisation script
-- Creates all seven tables from design §4.1.
-- Run once against a fresh database; idempotent via IF NOT EXISTS guards.

-- Enable the pgcrypto extension for gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- 1. Core endpoint record
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_endpoints (
    id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    http_method      VARCHAR(10)  NOT NULL,
    host             VARCHAR(255) NOT NULL,
    path             VARCHAR(1024) NOT NULL,
    normalized_path  VARCHAR(1024) NOT NULL,
    auth_scheme      VARCHAR(50)  NOT NULL DEFAULT 'unknown',
    data_sensitivity VARCHAR(20)  NOT NULL DEFAULT 'internal',
    lifecycle_status VARCHAR(20)  NOT NULL DEFAULT 'Active',
    risk_score       SMALLINT     NOT NULL DEFAULT 0,
    request_count_24h BIGINT      NOT NULL DEFAULT 0,
    last_access_at   TIMESTAMPTZ,
    first_seen_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    is_stale         BOOLEAN      NOT NULL DEFAULT FALSE,
    owning_team      VARCHAR(255),
    source_file_id   VARCHAR(512),
    metadata         JSONB        NOT NULL DEFAULT '{}',
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Composite unique index used as the deduplication key (design §2.1)
CREATE UNIQUE INDEX IF NOT EXISTS uq_api_endpoints_method_host_path
    ON api_endpoints (http_method, host, normalized_path);

-- ---------------------------------------------------------------------------
-- 2. Classification history
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS classification_history (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    endpoint_id     UUID        NOT NULL REFERENCES api_endpoints(id),
    rule_status     VARCHAR(20) NOT NULL,
    ml_status       VARCHAR(20),
    ml_confidence   FLOAT,
    override_by     VARCHAR(255),
    override_reason TEXT,
    classified_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_classification_history_endpoint
    ON classification_history (endpoint_id);

-- ---------------------------------------------------------------------------
-- 3. Risk score history and factors
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS risk_score_history (
    id          UUID     PRIMARY KEY DEFAULT gen_random_uuid(),
    endpoint_id UUID     NOT NULL REFERENCES api_endpoints(id),
    score       SMALLINT NOT NULL,
    factors     JSONB    NOT NULL,   -- [{rule, points, description}]
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_risk_score_history_endpoint
    ON risk_score_history (endpoint_id);

-- ---------------------------------------------------------------------------
-- 4. Anomaly alerts
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS anomaly_alerts (
    id                 UUID  PRIMARY KEY DEFAULT gen_random_uuid(),
    endpoint_id        UUID  NOT NULL REFERENCES api_endpoints(id),
    anomaly_type       VARCHAR(50)  NOT NULL,
    observed_value     FLOAT        NOT NULL,
    baseline_value     FLOAT        NOT NULL,
    deviation_sigma    FLOAT        NOT NULL,
    feature_importance JSONB        NOT NULL,  -- [{feature, contribution}]
    emitted_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    resolved_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_anomaly_alerts_endpoint
    ON anomaly_alerts (endpoint_id);

-- ---------------------------------------------------------------------------
-- 5. Remediation recommendations
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS remediation_recommendations (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    endpoint_id  UUID        NOT NULL REFERENCES api_endpoints(id),
    priority     VARCHAR(10) NOT NULL,  -- Critical, High, Medium, Low
    trigger_rule VARCHAR(100) NOT NULL,
    summary_text TEXT        NOT NULL,
    detail_json  JSONB       NOT NULL,
    resolved_by  VARCHAR(255),
    resolved_at  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_remediation_recommendations_endpoint
    ON remediation_recommendations (endpoint_id);

-- ---------------------------------------------------------------------------
-- 6. Audit log (append-only)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_identity  VARCHAR(255) NOT NULL,
    action_type     VARCHAR(100) NOT NULL,
    resource_type   VARCHAR(100) NOT NULL,
    resource_id     UUID,
    payload         JSONB       NOT NULL,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_actor
    ON audit_log (actor_identity);

CREATE INDEX IF NOT EXISTS idx_audit_log_resource
    ON audit_log (resource_type, resource_id);

-- ---------------------------------------------------------------------------
-- 7. Anomaly detector baselines
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS anomaly_baselines (
    id             UUID     PRIMARY KEY DEFAULT gen_random_uuid(),
    endpoint_id    UUID     REFERENCES api_endpoints(id),  -- NULL = cluster baseline
    cluster_key    VARCHAR(100),  -- e.g. "Zombie:PII"
    model_artifact BYTEA    NOT NULL,  -- serialized PyTorch model
    trained_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    training_days  SMALLINT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_anomaly_baselines_endpoint
    ON anomaly_baselines (endpoint_id);

CREATE INDEX IF NOT EXISTS idx_anomaly_baselines_cluster
    ON anomaly_baselines (cluster_key);


-- ---------------------------------------------------------------------------
-- RL Intelligence Service tables (migration applied inline)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS rl_agent_state (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    endpoint_id     UUID         NOT NULL REFERENCES api_endpoints(id),
    state_vector    JSONB        NOT NULL,
    last_action     SMALLINT     NOT NULL DEFAULT 0,
    last_reward     FLOAT        NOT NULL DEFAULT 0.0,
    total_reward    FLOAT        NOT NULL DEFAULT 0.0,
    episode_step    INTEGER      NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (endpoint_id)
);
CREATE INDEX IF NOT EXISTS idx_rl_agent_state_endpoint ON rl_agent_state (endpoint_id);
CREATE INDEX IF NOT EXISTS idx_rl_agent_state_updated  ON rl_agent_state (updated_at DESC);

CREATE TABLE IF NOT EXISTS rl_training_history (
    id                        UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_version            INTEGER      NOT NULL,
    total_timesteps           INTEGER      NOT NULL,
    mean_reward               FLOAT        NOT NULL DEFAULT 0.0,
    std_reward                FLOAT        NOT NULL DEFAULT 0.0,
    entropy_loss              FLOAT        NOT NULL DEFAULT 0.0,
    policy_loss               FLOAT        NOT NULL DEFAULT 0.0,
    value_loss                FLOAT        NOT NULL DEFAULT 0.0,
    explained_variance        FLOAT        NOT NULL DEFAULT 0.0,
    training_duration_seconds FLOAT        NOT NULL DEFAULT 0.0,
    trained_at                TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rl_training_history_policy  ON rl_training_history (policy_version);
CREATE INDEX IF NOT EXISTS idx_rl_training_history_trained ON rl_training_history (trained_at DESC);

CREATE TABLE IF NOT EXISTS rl_reward_events (
    id             UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    endpoint_id    UUID         NOT NULL REFERENCES api_endpoints(id),
    event_type     VARCHAR(50)  NOT NULL,
    reward_value   FLOAT        NOT NULL,
    action_taken   SMALLINT     NOT NULL DEFAULT 0,
    state_snapshot JSONB        NOT NULL,
    source         VARCHAR(50)  NOT NULL DEFAULT 'kafka',
    occurred_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rl_reward_events_endpoint ON rl_reward_events (endpoint_id);
CREATE INDEX IF NOT EXISTS idx_rl_reward_events_occurred ON rl_reward_events (occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_rl_reward_events_type     ON rl_reward_events (event_type);

CREATE TABLE IF NOT EXISTS rl_predictions (
    id                      UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    endpoint_id             UUID         NOT NULL REFERENCES api_endpoints(id),
    policy_version          INTEGER      NOT NULL DEFAULT 0,
    action                  SMALLINT     NOT NULL,
    action_confidence       FLOAT        NOT NULL DEFAULT 0.0,
    action_probabilities    JSONB        NOT NULL,
    rl_risk_adjustment      SMALLINT     NOT NULL DEFAULT 0,
    zombie_probability      FLOAT        NOT NULL DEFAULT 0.0,
    threat_probability      FLOAT        NOT NULL DEFAULT 0.0,
    remediation_probability FLOAT        NOT NULL DEFAULT 0.0,
    shap_values             JSONB        NOT NULL,
    top_features            JSONB        NOT NULL,
    rule_risk_score         SMALLINT     NOT NULL DEFAULT 0,
    ml_risk_contribution    FLOAT        NOT NULL DEFAULT 0.0,
    final_risk_score        SMALLINT     NOT NULL DEFAULT 0,
    predicted_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rl_predictions_endpoint      ON rl_predictions (endpoint_id);
CREATE INDEX IF NOT EXISTS idx_rl_predictions_policy        ON rl_predictions (policy_version);
CREATE INDEX IF NOT EXISTS idx_rl_predictions_predicted_at  ON rl_predictions (predicted_at DESC);

CREATE TABLE IF NOT EXISTS rl_policy_versions (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    version       INTEGER      NOT NULL UNIQUE,
    artifact_path VARCHAR(512) NOT NULL DEFAULT '',
    mean_reward   FLOAT        NOT NULL DEFAULT 0.0,
    is_active     BOOLEAN      NOT NULL DEFAULT FALSE,
    promoted_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rl_policy_versions_active
    ON rl_policy_versions (is_active) WHERE is_active = TRUE;

CREATE TABLE IF NOT EXISTS analyst_feedback (
    id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    endpoint_id      UUID         NOT NULL REFERENCES api_endpoints(id),
    analyst_id       VARCHAR(255) NOT NULL,
    feedback_type    VARCHAR(50)  NOT NULL,
    previous_value   TEXT,
    new_value        TEXT,
    rl_prediction_id UUID         REFERENCES rl_predictions(id),
    reward_generated FLOAT        NOT NULL DEFAULT 0.0,
    notes            TEXT,
    occurred_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_analyst_feedback_endpoint ON analyst_feedback (endpoint_id);
CREATE INDEX IF NOT EXISTS idx_analyst_feedback_analyst  ON analyst_feedback (analyst_id);
CREATE INDEX IF NOT EXISTS idx_analyst_feedback_occurred ON analyst_feedback (occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_analyst_feedback_type     ON analyst_feedback (feedback_type);

-- Users table for API Gateway authentication
CREATE TABLE IF NOT EXISTS users (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    username      VARCHAR(255) NOT NULL UNIQUE,
    email         VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(512) NOT NULL,
    role          VARCHAR(50)  NOT NULL DEFAULT 'viewer',
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
