// ---------------------------------------------------------------------------
// Demo node info — used when the nodeId is a demo graph string (not a UUID)
// ---------------------------------------------------------------------------

const DEMO_NODE_MAP: Record<string, any> = {
  'api-zombie-transfers': {
    http_method: 'POST', path: '/internal/transfers/bulk', host: 'api.bank.internal',
    lifecycle_status: 'Zombie', risk_score: 95, auth_scheme: 'none',
    data_sensitivity: 'financial', owning_team: null, metadata: {
      risk_factors: [
        { rule: 'no_auth', points: 40, description: 'Endpoint has no authentication scheme' },
        { rule: 'zombie_orphaned', points: 20, description: 'Zombie lifecycle — undocumented, active traffic' },
        { rule: 'sensitive_data_weak_auth', points: 30, description: 'Financial data with no auth' },
      ]
    }
  },
  'api-zombie-admin': {
    http_method: 'DELETE', path: '/v0/admin/users', host: 'api.bank.internal',
    lifecycle_status: 'Zombie', risk_score: 90, auth_scheme: 'none',
    data_sensitivity: 'PII', owning_team: null, metadata: {
      risk_factors: [
        { rule: 'no_auth', points: 40, description: 'No authentication — unauthenticated DELETE on user data' },
        { rule: 'zombie_orphaned', points: 20, description: 'Zombie — no spec, no owner' },
        { rule: 'sensitive_data_weak_auth', points: 30, description: 'PII data with no auth' },
      ]
    }
  },
  'api-zombie-export': {
    http_method: 'GET', path: '/legacy/export/customers', host: 'api.bank.internal',
    lifecycle_status: 'Zombie', risk_score: 88, auth_scheme: 'none',
    data_sensitivity: 'PII', owning_team: null, metadata: {}
  },
  'api-shadow-debug': {
    http_method: 'GET', path: '/debug/config', host: 'api.bank.internal',
    lifecycle_status: 'Shadow_API', risk_score: 97, auth_scheme: 'none',
    data_sensitivity: 'internal', owning_team: null, metadata: {
      risk_factors: [
        { rule: 'no_auth', points: 40, description: 'Unauthenticated debug config endpoint' },
        { rule: 'zombie_orphaned', points: 20, description: 'Shadow API — not in any spec or gateway' },
        { rule: 'abnormal_traffic', points: 10, description: 'Spike: 3.8σ above 30-day baseline' },
      ]
    }
  },
  'api-payment-initiate': {
    http_method: 'POST', path: '/v2/payments', host: 'api.bank.internal',
    lifecycle_status: 'Active', risk_score: 80, auth_scheme: 'OAuth2',
    data_sensitivity: 'financial', owning_team: 'fintech-team', metadata: {}
  },
  'api-user-profile': {
    http_method: 'GET', path: '/v1/users/{id}', host: 'api.bank.internal',
    lifecycle_status: 'Active', risk_score: 62, auth_scheme: 'JWT',
    data_sensitivity: 'PII', owning_team: 'core-team', metadata: {}
  },
  'api-user-kyc': {
    http_method: 'POST', path: '/v1/users/kyc', host: 'api.bank.internal',
    lifecycle_status: 'Active', risk_score: 74, auth_scheme: 'OAuth2',
    data_sensitivity: 'PII', owning_team: 'core-team', metadata: {}
  },
  'api-login': {
    http_method: 'POST', path: '/auth/login', host: 'api.bank.internal',
    lifecycle_status: 'Active', risk_score: 45, auth_scheme: 'JWT',
    data_sensitivity: 'internal', owning_team: 'platform-team', metadata: {}
  },
  'api-orders-create': {
    http_method: 'POST', path: '/v1/orders', host: 'api.bank.internal',
    lifecycle_status: 'Active', risk_score: 42, auth_scheme: 'OAuth2',
    data_sensitivity: 'internal', owning_team: 'commerce-team', metadata: {}
  },
  'api-payment-status': {
    http_method: 'GET', path: '/v2/payments/{id}', host: 'api.bank.internal',
    lifecycle_status: 'Active', risk_score: 55, auth_scheme: 'OAuth2',
    data_sensitivity: 'financial', owning_team: 'fintech-team', metadata: {}
  },
  'api-deprecated-v1-pay': {
    http_method: 'POST', path: '/v1/payments', host: 'api.bank.internal',
    lifecycle_status: 'Deprecated', risk_score: 30, auth_scheme: 'api_key',
    data_sensitivity: 'financial', owning_team: 'fintech-team', metadata: {}
  },
};

function _getDemoNodeInfo(nodeId: string): any | null {
  const known = DEMO_NODE_MAP[nodeId];
  if (known) return known;
  // For service and data asset nodes, return a minimal display object
  if (nodeId.startsWith('svc-') || nodeId.startsWith('db-') || nodeId.startsWith('cache-') || nodeId.startsWith('queue-')) {
    return {
      http_method: 'N/A',
      path: `/${nodeId}`,
      host: 'internal',
      lifecycle_status: 'Active',
      risk_score: 0,
      auth_scheme: 'internal',
      data_sensitivity: 'internal',
      owning_team: 'platform-team',
      metadata: {},
    };
  }
  return null;
}
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { endpointsApi, recommendationsApi } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import { Permission } from '../types/api';
import { X, ShieldAlert, Cpu, AlertTriangle, ShieldCheck, Database, FileText, CheckCircle } from 'lucide-react';
import type { RiskFactor, LifecycleStatus } from '../types/api';

interface NodeDetailsPanelProps {
  nodeId: string;
  onClose: () => void;
}

export const NodeDetailsPanel: React.FC<NodeDetailsPanelProps> = ({ nodeId, onClose }) => {
  const queryClient = useQueryClient();
  const { hasPermission } = useAuth();

  // Demo graph nodes use string IDs like "api-zombie-transfers", not UUIDs.
  // Only fetch from backend if the nodeId looks like a real UUID.
  const isRealUUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(nodeId);

  // Queries for endpoint details & recommendations
  const { data: endpoint, isLoading: endpointLoading, error: endpointError } = useQuery({
    queryKey: ['endpoint', nodeId],
    queryFn: () => endpointsApi.getEndpoint(nodeId),
    enabled: !!nodeId && isRealUUID,
    retry: false,
  });

  const { data: recommendations, isLoading: recommendationsLoading } = useQuery({
    queryKey: ['recommendations', nodeId],
    queryFn: () => recommendationsApi.getRecommendations(nodeId),
    enabled: !!nodeId && isRealUUID,
    retry: false,
  });

  // For demo graph nodes (non-UUID IDs), derive display info from the node ID
  const demoNodeInfo = !isRealUUID ? _getDemoNodeInfo(nodeId) : null;

  // Mutation to resolve recommendation
  const resolveMutation = useMutation({
    mutationFn: (recommendationId: string) => recommendationsApi.resolveRecommendation(recommendationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['recommendations', nodeId] });
      queryClient.invalidateQueries({ queryKey: ['endpoints'] });
      queryClient.invalidateQueries({ queryKey: ['endpoint', nodeId] });
    },
  });

  if (endpointLoading) {
    return (
      <div className="fixed right-0 top-0 w-full sm:w-[420px] h-screen bg-cyber-panel/90 backdrop-blur-lg border-l border-cyber-border shadow-2xl z-50 p-6 flex flex-col items-center justify-center font-mono">
        <div className="w-10 h-10 rounded-full border-4 border-cyber-border border-t-cyber-cyan animate-spin" />
        <span className="text-xs text-cyber-cyan mt-3 animate-pulse">PULLING TELEMETRY METRICS...</span>
      </div>
    );
  }

  // If demo node or fetch failed, show rich demo panel
  const displayData = endpoint || demoNodeInfo;

  if (!displayData) {
    return (
      <div className="fixed right-0 top-0 w-full sm:w-[420px] h-screen bg-cyber-panel/90 backdrop-blur-lg border-l border-cyber-border shadow-2xl z-50 p-6 flex flex-col font-mono">
        <div className="flex items-center justify-between border-b border-cyber-border pb-4 mb-4">
          <h3 className="font-bold text-cyber-red">NODE_NOT_FOUND</h3>
          <button onClick={onClose} className="p-1 rounded hover:bg-white/5 text-gray-500 hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </div>
        <p className="text-xs text-cyber-red">Node ID: {nodeId} — no details available.</p>
      </div>
    );
  }

  const getMethodColor = (method: string) => {
    switch (method) {
      case 'GET': return 'text-cyber-green border-cyber-green/30 bg-cyber-green/5';
      case 'POST': return 'text-cyber-blue border-cyber-blue/30 bg-cyber-blue/5';
      case 'PUT': return 'text-cyber-amber border-cyber-amber/30 bg-cyber-amber/5';
      case 'PATCH': return 'text-cyber-cyan border-cyber-cyan/30 bg-cyber-cyan/5';
      default: return 'text-cyber-red border-cyber-red/30 bg-cyber-red/5';
    }
  };

  const getStatusColor = (status: LifecycleStatus) => {
    switch (status) {
      case 'Active': return 'text-cyber-green border-cyber-green/30 bg-cyber-green/10';
      case 'Deprecated': return 'text-cyber-yellow border-cyber-yellow/30 bg-cyber-yellow/10';
      case 'Orphaned': return 'text-cyber-amber border-cyber-amber/30 bg-cyber-amber/10';
      case 'Zombie': return 'text-cyber-red border-cyber-red/40 bg-cyber-red/10 threat-pulse-red';
      default: return 'text-cyber-purple border-cyber-purple/40 bg-cyber-purple/10';
    }
  };

  const getRiskMeterColor = (score: number) => {
    if (score >= 75) return 'bg-cyber-red';
    if (score >= 40) return 'bg-cyber-amber';
    return 'bg-cyber-green';
  };

  const getPriorityStyles = (prio: string) => {
    switch (prio) {
      case 'Critical': return 'text-cyber-red border-cyber-red/30 bg-cyber-red/10';
      case 'High': return 'text-cyber-amber border-cyber-amber/20 bg-cyber-amber/10';
      case 'Medium': return 'text-cyber-yellow border-cyber-yellow/20 bg-cyber-yellow/10';
      default: return 'text-cyber-green border-cyber-green/20 bg-cyber-green/10';
    }
  };

  return (
    <div className="fixed right-0 top-0 w-full sm:w-[420px] h-screen bg-cyber-panel/95 backdrop-blur-md border-l border-cyber-border shadow-2xl z-50 flex flex-col font-mono text-xs overflow-hidden select-none">
      
      {/* Header */}
      <div className="h-16 flex items-center justify-between px-6 border-b border-cyber-border bg-black/20 shrink-0">
        <div className="flex items-center gap-2">
          <Database className="w-4 h-4 text-cyber-cyan" />
          <span className="font-bold text-gray-200 uppercase tracking-widest text-sm">NODE_INSIGHTS</span>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded border border-cyber-border hover:border-cyber-cyan hover:bg-cyber-cyan/15 text-gray-400 hover:text-cyber-cyan transition-colors cursor-pointer"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6 flex flex-col gap-6">
        
        {/* Core Metadata */}
        <section className="glass-panel border border-cyber-border p-4 flex flex-col gap-3">
          <span className="text-[10px] text-gray-500 flex items-center gap-1.5 pb-2 border-b border-cyber-border/40">
            <Cpu className="w-3.5 h-3.5 text-cyber-cyan" />
            <span>IDENTIFICATION_METADATA</span>
          </span>

          <div className="flex items-center gap-2 mt-1">
            <span className={`px-2 py-0.5 rounded font-bold border text-[10px] ${getMethodColor(displayData.http_method)}`}>
              {displayData.http_method}
            </span>
            <code className="text-cyber-cyan bg-black/40 px-1.5 py-0.5 rounded border border-white/5 truncate flex-1 font-semibold">
              {displayData.path}
            </code>
          </div>

          <div className="grid grid-cols-2 gap-3 mt-2 text-[11px]">
            <div className="flex flex-col gap-0.5">
              <span className="text-gray-500 text-[10px]">HOST:</span>
              <span className="text-gray-300 font-medium truncate">{displayData.host}</span>
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="text-gray-500 text-[10px]">STATUS:</span>
              <span className={`px-2 py-0.5 rounded border text-[9px] font-bold w-fit uppercase ${getStatusColor(displayData.lifecycle_status)}`}>
                {displayData.lifecycle_status.replace('_', ' ')}
              </span>
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="text-gray-500 text-[10px]">AUTH_SCHEME:</span>
              <span className={`font-medium ${displayData.auth_scheme === 'none' ? 'text-cyber-red' : 'text-gray-300'}`}>
                {displayData.auth_scheme.toUpperCase()}
              </span>
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="text-gray-500 text-[10px]">DATA_SENSITIVITY:</span>
              <span className="text-cyber-purple font-semibold uppercase">{displayData.data_sensitivity}</span>
            </div>
            <div className="flex flex-col gap-0.5 col-span-2">
              <span className="text-gray-500 text-[10px]">OWNING_TEAM:</span>
              <span className="text-gray-300 font-medium">{displayData.owning_team || 'SECURITY_INFRASTRUCTURE'}</span>
            </div>
          </div>
        </section>

        {/* Risk Assessment */}
        <section className="glass-panel border border-cyber-border p-4 flex flex-col gap-3">
          <span className="text-[10px] text-gray-500 flex items-center gap-1.5 pb-2 border-b border-cyber-border/40">
            <ShieldAlert className="w-3.5 h-3.5 text-cyber-red" />
            <span>RISK_EXPOSURE_INDEX</span>
          </span>

          <div className="flex items-center justify-between mt-1">
            <span className="text-gray-400 font-semibold">COMPUTED SCORE:</span>
            <span className={`px-2.5 py-0.5 rounded font-bold text-sm border ${
              displayData.risk_score >= 75 ? 'text-cyber-red border-cyber-red/30 bg-cyber-red/10 animate-pulse' :
              displayData.risk_score >= 40 ? 'text-cyber-amber border-cyber-amber/20 bg-cyber-amber/10' :
              'text-cyber-green border-cyber-green/20 bg-cyber-green/10'
            }`}>
              {displayData.risk_score} / 100
            </span>
          </div>

          {/* Risk progress bar */}
          <div className="w-full bg-gray-800 h-2 rounded-full overflow-hidden mt-1">
            <div className={`h-full rounded-full transition-all duration-500 ${getRiskMeterColor(displayData.risk_score)}`} style={{ width: `${displayData.risk_score}%` }} />
          </div>

          {/* Risk Factors */}
          {(displayData.metadata as any)?.risk_factors && Array.isArray((displayData.metadata as any).risk_factors) && (
            <div className="flex flex-col gap-2 mt-2">
              <span className="text-gray-400 text-[10px] font-bold">CONTRIBUTING_COMPLIANCE_FAILS:</span>
              <div className="flex flex-col gap-1.5">
                {((endpoint.metadata as any).risk_factors as RiskFactor[]).map((factor, idx) => (
                  <div key={idx} className="bg-black/35 rounded border border-cyber-border/50 p-2 flex flex-col gap-1">
                    <div className="flex justify-between items-center text-[10px] font-bold">
                      <span className="text-cyber-amber flex items-center gap-1">
                        <AlertTriangle className="w-3 h-3 text-cyber-amber shrink-0" />
                        {factor.rule}
                      </span>
                      <span className="text-cyber-red">+{factor.points} PTS</span>
                    </div>
                    <p className="text-[10px] text-gray-400 leading-normal font-sans">{factor.description}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>

        {/* Remediations Recommendations */}
        <section className="glass-panel border border-cyber-border p-4 flex flex-col gap-3">
          <span className="text-[10px] text-gray-500 flex items-center gap-1.5 pb-2 border-b border-cyber-border/40">
            <FileText className="w-3.5 h-3.5 text-cyber-purple" />
            <span>AI_REMEDIATION_PRESCRIPTIONS</span>
          </span>

          {recommendationsLoading ? (
            <div className="py-4 text-center text-cyber-cyan animate-pulse">GENERATING RECOMMENDATIONS...</div>
          ) : recommendations && recommendations.length > 0 ? (
            <div className="flex flex-col gap-3 mt-1">
              {recommendations.map((rec) => (
                <div key={rec.id} className="p-3 bg-black/45 border border-cyber-border rounded flex flex-col gap-2 relative">
                  <div className="flex items-center justify-between">
                    <span className={`px-2 py-0.5 rounded text-[9px] font-bold uppercase border ${getPriorityStyles(rec.priority)}`}>
                      {rec.priority}
                    </span>
                    <span className="text-[9px] text-gray-500 truncate max-w-[150px]" title={rec.trigger_rule}>
                      Rule: {rec.trigger_rule}
                    </span>
                  </div>

                  <p className="text-[10px] text-gray-300 font-sans leading-relaxed">{rec.summary_text}</p>

                  {rec.resolved_at ? (
                    <div className="text-[10px] text-cyber-green bg-cyber-green/10 border border-cyber-green/20 px-2 py-1 rounded flex items-center gap-1.5 mt-1 font-bold">
                      <CheckCircle className="w-3.5 h-3.5" />
                      <span>RESOLVED BY {rec.resolved_by?.toUpperCase()}</span>
                    </div>
                  ) : (
                    /* Guarded Action button */
                    hasPermission(Permission.RESOLVE_REMEDIATION) ? (
                      <button
                        onClick={() => resolveMutation.mutate(rec.id)}
                        disabled={resolveMutation.isPending}
                        className="mt-1 w-full bg-cyber-green/15 hover:bg-cyber-green/35 border border-cyber-green/45 hover:border-cyber-green text-cyber-green hover:text-white transition-all py-1.5 rounded font-bold cursor-pointer disabled:opacity-40"
                      >
                        {resolveMutation.isPending ? 'PROCESSING...' : 'APPLY PATCH & RESOLVE'}
                      </button>
                    ) : (
                      <div className="mt-1 text-[9px] text-cyber-red/50 italic border border-cyber-red/20 bg-cyber-red/5 p-1 rounded text-center">
                        Requires SEC_ADMIN clearance to apply patches
                      </div>
                    )
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="py-6 text-center text-gray-500 italic flex flex-col items-center gap-1.5">
              <ShieldCheck className="w-8 h-8 text-cyber-green" />
              <span>Complies with all banking ML baselines</span>
            </div>
          )}
        </section>

      </div>
    </div>
  );
};
