// ============================================================================
// ROLE-BASED ACCESS CONTROL (RBAC)
// ============================================================================

export const UserRole = {
  SUPER_ADMIN: 'SUPER_ADMIN',
  SECURITY_ADMIN: 'SECURITY_ADMIN',
  SECURITY_ANALYST: 'SECURITY_ANALYST',
  API_GOVERNANCE_MANAGER: 'API_GOVERNANCE_MANAGER',
  COMPLIANCE_OFFICER: 'COMPLIANCE_OFFICER',
  VIEWER: 'VIEWER',
} as const;
export type UserRole = typeof UserRole[keyof typeof UserRole];

export const Permission = {
  // Dashboard
  VIEW_DASHBOARD: 'VIEW_DASHBOARD',
  VIEW_KPI: 'VIEW_KPI',

  // API Inventory
  VIEW_API_INVENTORY: 'VIEW_API_INVENTORY',
  EDIT_API_INVENTORY: 'EDIT_API_INVENTORY',
  DELETE_API: 'DELETE_API',

  // Dependency Graph
  VIEW_DEPENDENCY_GRAPH: 'VIEW_DEPENDENCY_GRAPH',
  EXPORT_GRAPH: 'EXPORT_GRAPH',

  // Alerts & Anomalies
  VIEW_ALERTS: 'VIEW_ALERTS',
  ACKNOWLEDGE_ALERT: 'ACKNOWLEDGE_ALERT',
  RESOLVE_ALERT: 'RESOLVE_ALERT',

  // Risk Management
  VIEW_RISK_HEATMAP: 'VIEW_RISK_HEATMAP',
  MANAGE_RISK: 'MANAGE_RISK',

  // Remediation
  VIEW_REMEDIATION: 'VIEW_REMEDIATION',
  CREATE_REMEDIATION: 'CREATE_REMEDIATION',
  RESOLVE_REMEDIATION: 'RESOLVE_REMEDIATION',

  // Compliance
  VIEW_COMPLIANCE: 'VIEW_COMPLIANCE',
  MANAGE_COMPLIANCE: 'MANAGE_COMPLIANCE',

  // Administration
  MANAGE_USERS: 'MANAGE_USERS',
  MANAGE_ROLES: 'MANAGE_ROLES',
  VIEW_AUDIT_LOG: 'VIEW_AUDIT_LOG',
  MANAGE_SETTINGS: 'MANAGE_SETTINGS',
} as const;
export type Permission = typeof Permission[keyof typeof Permission];

// ============================================================================
// API TYPES
// ============================================================================

export type LifecycleStatus = 'Active' | 'Deprecated' | 'Orphaned' | 'Zombie' | 'Shadow_API';

export type AuthScheme = 'OAuth2' | 'JWT' | 'api_key' | 'none' | 'unknown';

export type DataSensitivity = 'PII' | 'financial' | 'internal' | 'public';

export type RiskLevel = 'Critical' | 'High' | 'Medium' | 'Low' | 'Info';

export type AlertSeverity = 'Critical' | 'High' | 'Medium' | 'Low' | 'Info';

export type AnomalyType = 'unusual_traffic' | 'auth_failure' | 'data_exfiltration' | 'unauthorized_access' | 'rate_anomaly';

export interface EndpointRecord {
  id: string;
  http_method: string;
  host: string;
  path: string;
  normalized_path: string;
  auth_scheme: AuthScheme;
  data_sensitivity: DataSensitivity;
  lifecycle_status: LifecycleStatus;
  risk_score: number;
  request_count_24h: number;
  last_access_at: string | null;
  first_seen_at: string;
  is_stale: boolean;
  owning_team: string | null;
  source_file_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  has_next: boolean;
}

export interface EndpointFilters {
  lifecycle_status?: LifecycleStatus;
  risk_score_min?: number;
  risk_score_max?: number;
  auth_scheme?: AuthScheme;
  data_sensitivity?: DataSensitivity;
  page?: number;
  page_size?: number;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  role: UserRole;
  user: {
    id: string;
    username: string;
    email: string;
    role: UserRole;
  };
}

// Graph types
export type NodeType = 'API_Endpoint' | 'Service' | 'DataAsset';

export interface GraphNode {
  id: string;
  type: NodeType;
  label: string;
  properties: {
    method?: string;
    host?: string;
    path?: string;
    lifecycle_status?: LifecycleStatus;
    risk_score?: number;
    name?: string;
    team?: string;
    sensitivity?: DataSensitivity;
  };
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: 'CALLS' | 'EXPOSES' | 'ACCESSES';
  properties: {
    observed_at?: string;
    source?: string;
    schema_ref?: string;
  };
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// Risk factor types
export interface RiskFactor {
  rule: string;
  points: number;
  description: string;
}

// Remediation types
export type RemediationPriority = 'Critical' | 'High' | 'Medium' | 'Low';

export interface RemediationRecommendation {
  id: string;
  endpoint_id: string;
  priority: RemediationPriority;
  trigger_rule: string;
  summary_text: string;
  detail_json: Record<string, unknown>;
  resolved_by: string | null;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
}

// Anomaly alert types
export interface AnomalyAlert {
  id: string;
  endpoint_id: string;
  anomaly_type: AnomalyType;
  observed_value: number;
  baseline_value: number;
  deviation_sigma: number;
  feature_importance: Array<{ feature: string; contribution: number }>;
  emitted_at: string;
  resolved_at: string | null;
}

// Security Alert types
export interface SecurityAlert {
  id: string;
  title: string;
  description: string;
  severity: AlertSeverity;
  type: string;
  endpoint_id?: string;
  created_at: string;
  acknowledged_at?: string;
  resolved_at?: string;
  metadata: Record<string, unknown>;
}

// Dashboard KPI types
export interface DashboardKPI {
  total_endpoints: number;
  critical_risks: number;
  active_alerts: number;
  compliance_score: number;
  api_coverage: number;
  threat_level: RiskLevel;
}

// User types
export interface User {
  id: string;
  username: string;
  email: string;
  role: UserRole;
  permissions: Permission[];
  created_at: string;
  updated_at: string;
  last_login?: string;
}

// Audit Log types
export interface AuditLog {
  id: string;
  user_id: string;
  action: string;
  resource_type: string;
  resource_id: string;
  changes: Record<string, unknown>;
  timestamp: string;
  ip_address: string;
}
