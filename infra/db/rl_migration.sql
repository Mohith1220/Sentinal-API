-- SentinelAPI — RL Intelligence Service database migration
-- Adds six new tables for the PPO RL agent.
-- Idempotent: all statements guarded by IF NOT EXISTS.
-- Run AFTER the base init.sql has been applied.

-- ---------------------------------------------------------------------------
-- 1. rl_agent_state — current per-endpoint RL state
--    One row per endpoint; updated on every prediction.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rl_agent_state (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    endpoint_id     UUID         NOT NULL REFERENCES api_endpoints(id),
    state_vector    JSONB        NOT NULL,          -- 18-element float array
    last_action     SMALLINT     NOT NULL DEFAULT 0, -- RLAction enum value
    last_reward     FLOAT        NOT NULL DEFAULT 0.0,
    total_reward    FLOAT        NOT NULL DEFAULT 0.0,
    episode_step    INTEGER      NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (endpoint_id)
);

CREATE INDEX IF NOT EXISTS idx_rl_agent_state_endpoint
    ON rl_agent_state (endpoint_id);

CREATE INDEX IF NOT EXISTS idx_rl_agent_state_updated
    ON rl_agent_state (updated_at DESC);

-- ---------------------------------------------------------------------------
-- 2. rl_training_history — PPO training run records
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rl_training_history (
    id                          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_version              INTEGER      NOT NULL,
    total_timesteps             INTEGER      NOT NULL,
    mean_reward                 FLOAT        NOT NULL DEFAULT 0.0,
    std_reward                  FLOAT        NOT NULL DEFAULT 0.0,
    entropy_loss                FLOAT        NOT NULL DEFAULT 0.0,
    policy_loss                 FLOAT        NOT NULL DEFAULT 0.0,
    value_loss                  FLOAT        NOT NULL DEFAULT 0.0,
    explained_variance          FLOAT        NOT NULL DEFAULT 0.0,
    training_duration_seconds   FLOAT        NOT NULL DEFAULT 0.0,
    trained_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rl_training_history_policy
    ON rl_training_history (policy_version);

CREATE INDEX IF NOT EXISTS idx_rl_training_history_trained
    ON rl_training_history (trained_at DESC);

-- ---------------------------------------------------------------------------
-- 3. rl_reward_events — individual reward signals
--    Append-only; used as the offline replay buffer for PPO training.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rl_reward_events (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    endpoint_id     UUID         NOT NULL REFERENCES api_endpoints(id),
    event_type      VARCHAR(50)  NOT NULL,     -- RewardEventType enum value
    reward_value    FLOAT        NOT NULL,
    action_taken    SMALLINT     NOT NULL DEFAULT 0,
    state_snapshot  JSONB        NOT NULL,     -- 18-element state vector at time of event
    source          VARCHAR(50)  NOT NULL DEFAULT 'kafka',  -- 'kafka','analyst_feedback','auto','api'
    occurred_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rl_reward_events_endpoint
    ON rl_reward_events (endpoint_id);

CREATE INDEX IF NOT EXISTS idx_rl_reward_events_occurred
    ON rl_reward_events (occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_rl_reward_events_type
    ON rl_reward_events (event_type);

-- ---------------------------------------------------------------------------
-- 4. rl_predictions — every prediction the agent makes
--    Full audit trail of PPO decisions.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rl_predictions (
    id                      UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    endpoint_id             UUID         NOT NULL REFERENCES api_endpoints(id),
    policy_version          INTEGER      NOT NULL DEFAULT 0,
    action                  SMALLINT     NOT NULL,  -- RLAction enum value (0-11)
    action_confidence       FLOAT        NOT NULL DEFAULT 0.0,
    action_probabilities    JSONB        NOT NULL,  -- 12-element float array
    rl_risk_adjustment      SMALLINT     NOT NULL DEFAULT 0,  -- -20 to +20
    zombie_probability      FLOAT        NOT NULL DEFAULT 0.0,
    threat_probability      FLOAT        NOT NULL DEFAULT 0.0,
    remediation_probability FLOAT        NOT NULL DEFAULT 0.0,
    shap_values             JSONB        NOT NULL,  -- 18-element SHAP array
    top_features            JSONB        NOT NULL,  -- [{feature, contribution, value}]
    rule_risk_score         SMALLINT     NOT NULL DEFAULT 0,
    ml_risk_contribution    FLOAT        NOT NULL DEFAULT 0.0,
    final_risk_score        SMALLINT     NOT NULL DEFAULT 0,
    predicted_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rl_predictions_endpoint
    ON rl_predictions (endpoint_id);

CREATE INDEX IF NOT EXISTS idx_rl_predictions_policy_version
    ON rl_predictions (policy_version);

CREATE INDEX IF NOT EXISTS idx_rl_predictions_predicted_at
    ON rl_predictions (predicted_at DESC);

-- ---------------------------------------------------------------------------
-- 5. rl_policy_versions — policy version registry
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rl_policy_versions (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    version         INTEGER      NOT NULL UNIQUE,
    artifact_path   VARCHAR(512) NOT NULL DEFAULT '',
    mean_reward     FLOAT        NOT NULL DEFAULT 0.0,
    is_active       BOOLEAN      NOT NULL DEFAULT FALSE,
    promoted_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rl_policy_versions_active
    ON rl_policy_versions (is_active) WHERE is_active = TRUE;

-- ---------------------------------------------------------------------------
-- 6. analyst_feedback — human feedback that drives reward generation
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analyst_feedback (
    id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    endpoint_id         UUID         NOT NULL REFERENCES api_endpoints(id),
    analyst_id          VARCHAR(255) NOT NULL,
    feedback_type       VARCHAR(50)  NOT NULL,   -- see RewardEventType values
    previous_value      TEXT,
    new_value           TEXT,
    rl_prediction_id    UUID         REFERENCES rl_predictions(id),
    reward_generated    FLOAT        NOT NULL DEFAULT 0.0,
    notes               TEXT,
    occurred_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analyst_feedback_endpoint
    ON analyst_feedback (endpoint_id);

CREATE INDEX IF NOT EXISTS idx_analyst_feedback_analyst
    ON analyst_feedback (analyst_id);

CREATE INDEX IF NOT EXISTS idx_analyst_feedback_occurred
    ON analyst_feedback (occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_analyst_feedback_type
    ON analyst_feedback (feedback_type);

-- ---------------------------------------------------------------------------
-- users table (for api-gateway auth — added here so migration is complete)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    username        VARCHAR(255) NOT NULL UNIQUE,
    email           VARCHAR(255) NOT NULL UNIQUE,
    password_hash   VARCHAR(512) NOT NULL,
    role            VARCHAR(50)  NOT NULL DEFAULT 'viewer',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
