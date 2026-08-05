-- SentinelAPI — Sample Data for Demo/Testing
-- Inserts realistic API endpoints, classifications, risk scores, and anomaly alerts

-- Clear existing data (for demo purposes)
DELETE FROM anomaly_alerts;
DELETE FROM remediation_recommendations;
DELETE FROM risk_score_history;
DELETE FROM classification_history;
DELETE FROM api_endpoints;

-- ---------------------------------------------------------------------------
-- Sample API Endpoints
-- ---------------------------------------------------------------------------

INSERT INTO api_endpoints (
    http_method, host, path, normalized_path, auth_scheme, data_sensitivity,
    lifecycle_status, risk_score, request_count_24h, last_access_at, owning_team, metadata
) VALUES
-- High-risk endpoints (Zombie APIs)
('GET', 'api.internal.com', '/v1/users/{id}/profile', '/v1/users/profile', 'None', 'PII', 'Active', 85, 1250, NOW() - INTERVAL '5 minutes', 'Platform Team', '{"deprecated": true, "last_reviewed": "2025-01-01"}'),
('POST', 'api.internal.com', '/v1/admin/users/bulk-delete', '/v1/admin/users/bulk-delete', 'BasicAuth', 'PII', 'Active', 92, 45, NOW() - INTERVAL '2 hours', 'Admin Team', '{"requires_approval": true}'),
('GET', 'api.internal.com', '/v2/payments/transactions', '/v2/payments/transactions', 'OAuth2', 'Financial', 'Active', 78, 3200, NOW() - INTERVAL '1 minute', 'Finance Team', '{"pci_scope": true}'),

-- Medium-risk endpoints
('GET', 'api.internal.com', '/v1/products', '/v1/products', 'OAuth2', 'Public', 'Active', 35, 15000, NOW() - INTERVAL '30 seconds', 'Product Team', '{"cached": true}'),
('POST', 'api.internal.com', '/v1/orders', '/v1/orders', 'OAuth2', 'Internal', 'Active', 42, 8500, NOW() - INTERVAL '1 minute', 'Order Team', '{"rate_limited": true}'),
('GET', 'api.internal.com', '/v1/inventory/stock', '/v1/inventory/stock', 'OAuth2', 'Internal', 'Active', 28, 5600, NOW() - INTERVAL '45 seconds', 'Inventory Team', '{"read_only": true}'),

-- Low-risk endpoints
('GET', 'api.internal.com', '/health', '/health', 'None', 'Public', 'Active', 5, 50000, NOW() - INTERVAL '10 seconds', 'DevOps Team', '{"monitoring": true}'),
('GET', 'api.internal.com', '/v1/status', '/v1/status', 'None', 'Public', 'Active', 8, 25000, NOW() - INTERVAL '20 seconds', 'DevOps Team', '{"monitoring": true}'),
('GET', 'api.internal.com', '/v1/docs', '/v1/docs', 'None', 'Public', 'Active', 3, 1200, NOW() - INTERVAL '2 hours', 'Documentation Team', '{"static": true}'),

-- Stale/deprecated endpoints
('GET', 'api.internal.com', '/v0/legacy/users', '/v0/legacy/users', 'BasicAuth', 'PII', 'Deprecated', 88, 120, NOW() - INTERVAL '30 days', 'Legacy Team', '{"deprecated": true, "sunset_date": "2026-06-01"}'),
('POST', 'api.internal.com', '/v0/auth/login', '/v0/auth/login', 'None', 'Internal', 'Deprecated', 75, 50, NOW() - INTERVAL '45 days', 'Auth Team', '{"replaced_by": "/v2/auth/login"}');

-- Get the endpoint IDs for use in other tables
WITH endpoint_ids AS (
    SELECT id, normalized_path FROM api_endpoints
)

-- ---------------------------------------------------------------------------
-- Classification History
-- ---------------------------------------------------------------------------
INSERT INTO classification_history (endpoint_id, rule_status, ml_status, ml_confidence, classified_at)
SELECT id, 'Zombie', 'Zombie', 0.94, NOW() - INTERVAL '7 days'
FROM api_endpoints WHERE normalized_path = '/v1/users/profile'
UNION ALL
SELECT id, 'Zombie', 'Zombie', 0.89, NOW() - INTERVAL '7 days'
FROM api_endpoints WHERE normalized_path = '/v1/admin/users/bulk-delete'
UNION ALL
SELECT id, 'Sensitive', 'Sensitive', 0.92, NOW() - INTERVAL '7 days'
FROM api_endpoints WHERE normalized_path = '/v2/payments/transactions'
UNION ALL
SELECT id, 'Active', 'Active', 0.98, NOW() - INTERVAL '7 days'
FROM api_endpoints WHERE normalized_path = '/v1/products'
UNION ALL
SELECT id, 'Active', 'Active', 0.97, NOW() - INTERVAL '7 days'
FROM api_endpoints WHERE normalized_path = '/v1/orders'
UNION ALL
SELECT id, 'Deprecated', 'Deprecated', 0.99, NOW() - INTERVAL '30 days'
FROM api_endpoints WHERE normalized_path = '/v0/legacy/users';

-- ---------------------------------------------------------------------------
-- Risk Score History
-- ---------------------------------------------------------------------------
INSERT INTO risk_score_history (endpoint_id, score, factors, computed_at)
SELECT id, 85, 
  '[
    {"rule": "no_authentication", "points": 30, "description": "Endpoint has no authentication"},
    {"rule": "pii_exposure", "points": 35, "description": "Exposes PII data"},
    {"rule": "high_request_volume", "points": 20, "description": "High request volume (1250/24h)"}
  ]'::jsonb,
  NOW() - INTERVAL '1 day'
FROM api_endpoints WHERE normalized_path = '/v1/users/profile'
UNION ALL
SELECT id, 92,
  '[
    {"rule": "admin_operation", "points": 40, "description": "Admin-level operation"},
    {"rule": "destructive_action", "points": 35, "description": "Bulk delete operation"},
    {"rule": "weak_auth", "points": 17, "description": "Uses BasicAuth instead of OAuth2"}
  ]'::jsonb,
  NOW() - INTERVAL '1 day'
FROM api_endpoints WHERE normalized_path = '/v1/admin/users/bulk-delete'
UNION ALL
SELECT id, 78,
  '[
    {"rule": "financial_data", "points": 40, "description": "Handles financial data"},
    {"rule": "pci_scope", "points": 25, "description": "PCI DSS compliance required"},
    {"rule": "high_request_volume", "points": 13, "description": "High request volume (3200/24h)"}
  ]'::jsonb,
  NOW() - INTERVAL '1 day'
FROM api_endpoints WHERE normalized_path = '/v2/payments/transactions'
UNION ALL
SELECT id, 35,
  '[
    {"rule": "public_data", "points": 10, "description": "Exposes public data"},
    {"rule": "read_only", "points": 5, "description": "Read-only operation"},
    {"rule": "well_authenticated", "points": -5, "description": "Uses OAuth2"}
  ]'::jsonb,
  NOW() - INTERVAL '1 day'
FROM api_endpoints WHERE normalized_path = '/v1/products';

-- ---------------------------------------------------------------------------
-- Anomaly Alerts (Recent suspicious activity)
-- ---------------------------------------------------------------------------
INSERT INTO anomaly_alerts (endpoint_id, anomaly_type, observed_value, baseline_value, deviation_sigma, feature_importance, emitted_at)
SELECT id, 'Request Volume Spike', 5200, 1250, 5.8,
  '[
    {"feature": "request_count", "contribution": 0.65},
    {"feature": "unique_ips", "contribution": 0.25},
    {"feature": "error_rate", "contribution": 0.10}
  ]'::jsonb,
  NOW() - INTERVAL '15 minutes'
FROM api_endpoints WHERE normalized_path = '/v1/users/profile'
UNION ALL
SELECT id, 'Unusual Access Pattern', 450, 45, 6.2,
  '[
    {"feature": "request_count", "contribution": 0.55},
    {"feature": "time_of_day", "contribution": 0.30},
    {"feature": "user_agent_diversity", "contribution": 0.15}
  ]'::jsonb,
  NOW() - INTERVAL '8 minutes'
FROM api_endpoints WHERE normalized_path = '/v1/admin/users/bulk-delete'
UNION ALL
SELECT id, 'Error Rate Anomaly', 12.5, 0.8, 4.3,
  '[
    {"feature": "error_rate", "contribution": 0.70},
    {"feature": "response_time", "contribution": 0.20},
    {"feature": "timeout_count", "contribution": 0.10}
  ]'::jsonb,
  NOW() - INTERVAL '3 minutes'
FROM api_endpoints WHERE normalized_path = '/v2/payments/transactions'
UNION ALL
SELECT id, 'Response Time Degradation', 2850, 450, 5.1,
  '[
    {"feature": "p95_latency", "contribution": 0.60},
    {"feature": "database_queries", "contribution": 0.25},
    {"feature": "cache_misses", "contribution": 0.15}
  ]'::jsonb,
  NOW() - INTERVAL '2 minutes'
FROM api_endpoints WHERE normalized_path = '/v1/products'
UNION ALL
SELECT id, 'Unusual Geographic Distribution', 0.92, 0.15, 4.8,
  '[
    {"feature": "geographic_diversity", "contribution": 0.70},
    {"feature": "vpn_usage", "contribution": 0.20},
    {"feature": "proxy_detection", "contribution": 0.10}
  ]'::jsonb,
  NOW() - INTERVAL '1 minute'
FROM api_endpoints WHERE normalized_path = '/v1/orders';

-- ---------------------------------------------------------------------------
-- Remediation Recommendations
-- ---------------------------------------------------------------------------
INSERT INTO remediation_recommendations (endpoint_id, priority, trigger_rule, summary_text, detail_json, created_at)
SELECT id, 'Critical', 'zombie_api_no_auth', 
  'Deprecated API with no authentication exposing PII',
  '{
    "action": "Deprecate and migrate",
    "timeline": "Immediate",
    "steps": [
      "Notify all clients of deprecation",
      "Provide migration guide to /v2/users/profile",
      "Set sunset date to 2026-06-01",
      "Monitor usage for 30 days before removal"
    ],
    "impact": "High - affects 1250 requests/day"
  }'::jsonb,
  NOW() - INTERVAL '2 days'
FROM api_endpoints WHERE normalized_path = '/v1/users/profile'
UNION ALL
SELECT id, 'Critical', 'admin_bulk_delete_weak_auth',
  'Admin operation with weak authentication and no audit trail',
  '{
    "action": "Strengthen authentication and add audit logging",
    "timeline": "Within 48 hours",
    "steps": [
      "Upgrade from BasicAuth to OAuth2 with MFA",
      "Implement comprehensive audit logging",
      "Add approval workflow for bulk operations",
      "Implement rate limiting (max 100 deletes/hour)"
    ],
    "impact": "Critical - destructive operation"
  }'::jsonb,
  NOW() - INTERVAL '3 days'
FROM api_endpoints WHERE normalized_path = '/v1/admin/users/bulk-delete'
UNION ALL
SELECT id, 'High', 'pci_compliance_review',
  'Financial data endpoint requires PCI DSS compliance review',
  '{
    "action": "Conduct PCI compliance audit",
    "timeline": "Within 1 week",
    "steps": [
      "Review encryption in transit and at rest",
      "Verify access controls and authentication",
      "Audit logging and monitoring",
      "Penetration testing"
    ],
    "impact": "High - handles payment data"
  }'::jsonb,
  NOW() - INTERVAL '5 days'
FROM api_endpoints WHERE normalized_path = '/v2/payments/transactions'
UNION ALL
SELECT id, 'Medium', 'deprecated_api_removal',
  'Legacy API endpoint should be removed',
  '{
    "action": "Schedule removal",
    "timeline": "Before 2026-06-01",
    "steps": [
      "Verify all clients have migrated",
      "Remove endpoint and associated code",
      "Update documentation"
    ],
    "impact": "Low - only 120 requests/day"
  }'::jsonb,
  NOW() - INTERVAL '30 days'
FROM api_endpoints WHERE normalized_path = '/v0/legacy/users';

-- ---------------------------------------------------------------------------
-- Graph Nodes (for dependency visualization)
-- ---------------------------------------------------------------------------
INSERT INTO api_endpoints (
    http_method, host, path, normalized_path, auth_scheme, data_sensitivity,
    lifecycle_status, risk_score, request_count_24h, owning_team, metadata
) VALUES
('GET', 'auth-service.internal.com', '/v2/validate-token', '/v2/validate-token', 'OAuth2', 'Internal', 'Active', 15, 50000, 'Auth Team', '{"internal_only": true}'),
('GET', 'user-service.internal.com', '/v1/users/{id}', '/v1/users', 'OAuth2', 'PII', 'Active', 45, 8000, 'User Team', '{"internal_service": true}'),
('GET', 'database-service.internal.com', '/v1/query', '/v1/query', 'OAuth2', 'Internal', 'Active', 55, 12000, 'Data Team', '{"internal_service": true}');

COMMIT;
