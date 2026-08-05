import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { endpointsApi, recommendationsApi } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import { Permission } from '../types/api';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
} from 'recharts';
import {
  ArrowLeft,
  ShieldAlert,
  Sliders,
  Cpu,
  FileCheck,
  CheckCircle,
  Activity,
  AlertTriangle,
} from 'lucide-react';
import type { RiskFactor, LifecycleStatus } from '../types/api';

export const APIDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { hasPermission } = useAuth();

  const [complianceChecks] = useState({
    pci_dss: true,
    gdpr: false,
    owasp_top_10: false,
    soc2: true,
  });

  // Fetch Endpoint details
  const { data: endpoint, isLoading: endpointLoading, error: endpointError } = useQuery({
    queryKey: ['endpoint', id],
    queryFn: () => endpointsApi.getEndpoint(id || ''),
    enabled: !!id,
  });

  // Fetch Recommendations
  const { data: recommendations, isLoading: recommendationsLoading } = useQuery({
    queryKey: ['recommendations', id],
    queryFn: () => recommendationsApi.getRecommendations(id || ''),
    enabled: !!id,
  });

  // Mutation to patch/resolve recommendation
  const resolveMutation = useMutation({
    mutationFn: (recId: string) => recommendationsApi.resolveRecommendation(recId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['recommendations', id] });
      queryClient.invalidateQueries({ queryKey: ['endpoint', id] });
    },
  });

  if (endpointLoading) {
    return (
      <div className="min-h-[500px] flex items-center justify-center font-mono text-xs text-cyber-cyan">
        <div className="flex flex-col items-center gap-3">
          <div className="w-10 h-10 rounded-full border-4 border-cyber-border border-t-cyber-cyan animate-spin" />
          <span className="animate-pulse">DECRYPTING ENDPOINT MEMORY BASES...</span>
        </div>
      </div>
    );
  }

  if (endpointError || !endpoint) {
    return (
      <div className="glass-panel border border-cyber-red/40 bg-cyber-red/5 p-8 text-center text-cyber-red font-mono text-xs max-w-md mx-auto mt-12">
        <AlertTriangle className="w-8 h-8 mx-auto mb-3 animate-bounce" />
        <span>DIAGNOSTICS_ERROR: Failed to trace endpoint node #{id}</span>
        <button onClick={() => navigate('/inventory')} className="mt-4 px-4 py-2 border border-cyber-red/40 rounded hover:bg-cyber-red/10 block mx-auto">
          RETURN TO INVENTORY
        </button>
      </div>
    );
  }

  // Mock Traffic trend history
  const trafficHistory = [
    { date: '05-13', requests: 1200, latency: 120 },
    { date: '05-14', requests: 1450, latency: 125 },
    { date: '05-15', requests: 1900, latency: 140 },
    { date: '05-16', requests: 1100, latency: 115 },
    { date: '05-17', requests: 2800, latency: 190 }, // anomaly spike
    { date: '05-18', requests: 1600, latency: 128 },
    { date: '05-19', requests: endpoint.request_count_24h, latency: 122 },
  ];

  const getMethodStyles = (method: string) => {
    switch (method) {
      case 'GET': return 'text-cyber-green border-cyber-green/30 bg-cyber-green/5';
      case 'POST': return 'text-cyber-blue border-cyber-blue/30 bg-cyber-blue/5';
      case 'PUT': return 'text-cyber-amber border-cyber-amber/30 bg-cyber-amber/5';
      default: return 'text-cyber-red border-cyber-red/30 bg-cyber-red/5';
    }
  };

  const getStatusStyles = (status: LifecycleStatus) => {
    switch (status) {
      case 'Active': return 'text-cyber-green border-cyber-green/30 bg-cyber-green/10';
      case 'Deprecated': return 'text-cyber-yellow border-cyber-yellow/30 bg-cyber-yellow/10';
      case 'Zombie': return 'text-cyber-red border-cyber-red/40 bg-cyber-red/10 threat-pulse-red';
      default: return 'text-cyber-purple border-cyber-purple/40 bg-cyber-purple/10';
    }
  };

  const getPriorityStyles = (prio: string) => {
    switch (prio) {
      case 'Critical': return 'text-cyber-red border-cyber-red/40 bg-cyber-red/10 threat-pulse-red';
      case 'High': return 'text-cyber-amber border-cyber-amber/35 bg-cyber-amber/10';
      case 'Medium': return 'text-cyber-yellow border-cyber-yellow/20 bg-cyber-yellow/10';
      default: return 'text-cyber-green border-cyber-green/20 bg-cyber-green/10';
    }
  };

  return (
    <div className="flex flex-col gap-6 font-mono text-xs select-none">
      
      {/* Return Navigation Top Bar */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => navigate('/inventory')}
          className="flex items-center gap-2 px-3 py-1.5 rounded border border-cyber-border hover:border-cyber-cyan/50 hover:bg-white/5 text-gray-400 hover:text-cyber-cyan transition-colors cursor-pointer"
        >
          <ArrowLeft className="w-4 h-4" />
          <span>INVENTORY_DECK</span>
        </button>
        <span className="text-gray-600">/</span>
        <span className="text-gray-400 font-bold truncate max-w-[300px]">{endpoint.path}</span>
      </div>

      {/* Primary Detail and Risk hud */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* Left Side: General diagnostics */}
        <div className="lg:col-span-2 flex flex-col gap-6">
          <div className="glass-panel border border-cyber-border p-5 flex flex-col gap-4">
            <span className="text-[10px] text-gray-500 flex items-center gap-1.5 pb-2 border-b border-cyber-border/40">
              <Cpu className="w-3.5 h-3.5 text-cyber-cyan" />
              <span>CORE_DIAGNOSTIC_TELEMETRY</span>
            </span>

            <div className="flex items-center gap-2">
              <span className={`px-2.5 py-1 rounded font-bold border text-xs ${getMethodStyles(endpoint.http_method)}`}>
                {endpoint.http_method}
              </span>
              <code className="text-cyber-cyan bg-black/40 px-2 py-1 rounded border border-white/5 font-bold text-sm truncate flex-1">
                {endpoint.path}
              </code>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mt-3 text-[11px]">
              <div className="flex flex-col gap-1">
                <span className="text-gray-500 text-[10px]">HOST_ENVIRONMENT:</span>
                <span className="text-gray-300 font-medium truncate">{endpoint.host}</span>
              </div>
              <div className="flex flex-col gap-1">
                <span className="text-gray-500 text-[10px]">LIFECYCLE_STATUS:</span>
                <span className={`px-2 py-0.5 rounded border text-[9px] font-bold w-fit uppercase ${getStatusStyles(endpoint.lifecycle_status)}`}>
                  {endpoint.lifecycle_status.replace('_', ' ')}
                </span>
              </div>
              <div className="flex flex-col gap-1">
                <span className="text-gray-500 text-[10px]">SECURE_AUTH_SCHEME:</span>
                <span className={`font-semibold uppercase ${endpoint.auth_scheme === 'none' ? 'text-cyber-red' : 'text-gray-300'}`}>
                  {endpoint.auth_scheme}
                </span>
              </div>
              <div className="flex flex-col gap-1">
                <span className="text-gray-500 text-[10px]">DATA_SENSITIVITY:</span>
                <span className="text-cyber-purple font-semibold uppercase">{endpoint.data_sensitivity}</span>
              </div>
              <div className="flex flex-col gap-1">
                <span className="text-gray-500 text-[10px]">TRAFFIC_COUNT_24H:</span>
                <span className="text-cyber-blue font-bold">{endpoint.request_count_24h.toLocaleString()} Req</span>
              </div>
              <div className="flex flex-col gap-1">
                <span className="text-gray-500 text-[10px]">OWNING_PERSONA_TEAM:</span>
                <span className="text-gray-300 font-medium">{endpoint.owning_team || 'SOC_GATEWAY'}</span>
              </div>
            </div>
          </div>

          {/* Traffic history Recharts */}
          <div className="glass-panel border border-cyber-border p-5 flex flex-col gap-4">
            <span className="text-[10px] text-gray-500 flex items-center gap-1.5 pb-2 border-b border-cyber-border/40">
              <Activity className="w-3.5 h-3.5 text-cyber-blue" />
              <span>TRAFFIC_VOLUMETRIC_HISTOGRAM (7 DAYS)</span>
            </span>
            <div className="h-48">
              <ResponsiveContainer width="100%" height={192} minWidth={0}>
                <AreaChart data={trafficHistory} margin={{ top: 10, right: 10, left: -25, bottom: 0 }}>
                  <defs>
                    <linearGradient id="colorRequests" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#0ea5e9" stopOpacity={0.25} />
                      <stop offset="95%" stopColor="#0ea5e9" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="date" stroke="#6b7280" fontSize={9} tickLine={false} />
                  <YAxis stroke="#6b7280" fontSize={9} tickLine={false} />
                  <Tooltip contentStyle={{ backgroundColor: '#0b1220', borderColor: 'rgba(255,255,255,0.08)', fontSize: '10px' }} />
                  <Area type="monotone" dataKey="requests" name="Volumetric Rate" stroke="#0ea5e9" fillOpacity={1} fill="url(#colorRequests)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        {/* Right Side: Risk score and Contributing factors */}
        <div className="flex flex-col gap-6">
          <div className="glass-panel border border-cyber-border p-5 flex flex-col gap-4">
            <span className="text-[10px] text-gray-500 flex items-center gap-1.5 pb-2 border-b border-cyber-border/40">
              <ShieldAlert className="w-3.5 h-3.5 text-cyber-red" />
              <span>COMPLIANCE_RISK_GAGE</span>
            </span>

            <div className="flex items-center justify-between">
              <span className="text-gray-400 font-semibold">RISK LEVEL INDEX:</span>
              <span className={`px-2.5 py-0.5 rounded font-bold text-sm border ${
                endpoint.risk_score >= 75 ? 'text-cyber-red border-cyber-red/30 bg-cyber-red/10 animate-pulse' :
                endpoint.risk_score >= 40 ? 'text-cyber-amber border-cyber-amber/20 bg-cyber-amber/10' :
                'text-cyber-green border-cyber-green/20 bg-cyber-green/10'
              }`}>
                {endpoint.risk_score} / 100
              </span>
            </div>

            {/* contributing factors list */}
            {(endpoint.metadata as any).risk_factors && Array.isArray((endpoint.metadata as any).risk_factors) && (
              <div className="flex flex-col gap-2.5 mt-2">
                <span className="text-gray-500 text-[10px]">RISK_CONTRIBUTING_VULNS:</span>
                <div className="flex flex-col gap-2 max-h-56 overflow-y-auto pr-1">
                  {((endpoint.metadata as any).risk_factors as RiskFactor[]).map((factor, idx) => (
                    <div key={idx} className="bg-black/30 border border-cyber-border/60 rounded p-2 flex flex-col gap-1">
                      <div className="flex justify-between items-center text-[10px] font-bold text-cyber-amber">
                        <span>{factor.rule}</span>
                        <span className="text-cyber-red">+{factor.points} PTS</span>
                      </div>
                      <p className="text-[10px] text-gray-400 leading-normal font-sans">{factor.description}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

      </div>

      {/* Compliance auditing checks */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        
        {/* GDPR, SOC2 compliance toggles card */}
        <div className="glass-panel border border-cyber-border p-5 flex flex-col gap-4">
          <span className="text-[10px] text-gray-500 flex items-center gap-1.5 pb-2 border-b border-cyber-border/40">
            <FileCheck className="w-3.5 h-3.5 text-cyber-cyan" />
            <span>REGULATORY_COMPLIANCE_STATUS</span>
          </span>

          <div className="flex flex-col gap-3.5 mt-2">
            <div className="flex items-center justify-between border-b border-cyber-border/30 pb-2">
              <div className="flex flex-col gap-0.5">
                <span className="font-bold text-gray-200">PCI-DSS COMPLIANCE SEC.4</span>
                <span className="text-[10px] text-gray-500 font-sans">Payment ledger data asset isolation</span>
              </div>
              <span className={`px-2 py-0.5 rounded border text-[10px] font-bold ${
                complianceChecks.pci_dss ? 'text-cyber-green border-cyber-green/30 bg-cyber-green/10' : 'text-cyber-red border-cyber-red/30 bg-cyber-red/10'
              }`}>
                {complianceChecks.pci_dss ? 'PASSED' : 'VIOLATION'}
              </span>
            </div>

            <div className="flex items-center justify-between border-b border-cyber-border/30 pb-2">
              <div className="flex flex-col gap-0.5">
                <span className="font-bold text-gray-200">GDPR DATA PRIVACY CONTROLS</span>
                <span className="text-[10px] text-gray-500 font-sans">Exposing PII records without encryption</span>
              </div>
              <span className={`px-2 py-0.5 rounded border text-[10px] font-bold ${
                complianceChecks.gdpr ? 'text-cyber-green border-cyber-green/30 bg-cyber-green/10' : 'text-cyber-red border-cyber-red/30 bg-cyber-red/10'
              }`}>
                {complianceChecks.gdpr ? 'PASSED' : 'VIOLATION'}
              </span>
            </div>

            <div className="flex items-center justify-between">
              <div className="flex flex-col gap-0.5">
                <span className="font-bold text-gray-200">OWASP API TOP 10 RATING</span>
                <span className="text-[10px] text-gray-500 font-sans">Broken Object Level Authorization audits</span>
              </div>
              <span className={`px-2 py-0.5 rounded border text-[10px] font-bold ${
                complianceChecks.owasp_top_10 ? 'text-cyber-green border-cyber-green/30 bg-cyber-green/10' : 'text-cyber-red border-cyber-red/30 bg-cyber-red/10'
              }`}>
                {complianceChecks.owasp_top_10 ? 'SECURE' : 'COMPROMISED'}
              </span>
            </div>
          </div>
        </div>

        {/* AI patch prescriptions card */}
        <div className="glass-panel border border-cyber-border p-5 flex flex-col gap-4">
          <span className="text-[10px] text-gray-500 flex items-center gap-1.5 pb-2 border-b border-cyber-border/40">
            <Sliders className="w-3.5 h-3.5 text-cyber-purple" />
            <span>AI_REMEDIATION_PATCHES</span>
          </span>

          {recommendationsLoading ? (
            <div className="py-6 text-center text-cyber-cyan animate-pulse">GENERATING RECOMMENDATIONS...</div>
          ) : recommendations && recommendations.length > 0 ? (
            <div className="flex flex-col gap-3">
              {recommendations.map((rec) => (
                <div key={rec.id} className="p-3 bg-black/45 border border-cyber-border rounded flex flex-col gap-2">
                  <div className="flex items-center justify-between">
                    <span className={`px-2 py-0.5 rounded border text-[9px] font-bold uppercase ${getPriorityStyles(rec.priority)}`}>
                      {rec.priority}
                    </span>
                    <span className="text-gray-500 text-[10px]">Rule: {rec.trigger_rule}</span>
                  </div>

                  <p className="text-[10px] text-gray-300 leading-relaxed font-sans">{rec.summary_text}</p>

                  {rec.resolved_at ? (
                    <div className="text-[10px] text-cyber-green bg-cyber-green/10 border border-cyber-green/20 px-2 py-1 rounded flex items-center gap-1.5 font-bold">
                      <CheckCircle className="w-3.5 h-3.5 animate-pulse" />
                      <span>RESOLVED BY {rec.resolved_by?.toUpperCase()}</span>
                    </div>
                  ) : (
                    hasPermission(Permission.RESOLVE_REMEDIATION) ? (
                      <button
                        onClick={() => resolveMutation.mutate(rec.id)}
                        disabled={resolveMutation.isPending}
                        className="w-full bg-cyber-green/15 hover:bg-cyber-green/35 border border-cyber-green/45 hover:border-cyber-green text-cyber-green hover:text-white transition-all py-1.5 rounded font-bold cursor-pointer disabled:opacity-40"
                      >
                        {resolveMutation.isPending ? 'DEPLOYING PATCH...' : 'APPLY AI PATCH CONFIG'}
                      </button>
                    ) : (
                      <div className="text-[9px] text-cyber-red/50 italic border border-cyber-red/20 bg-cyber-red/5 p-1 rounded text-center">
                        Clearance SEC_ADMIN required to resolve recommendations
                      </div>
                    )
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="py-8 text-center text-gray-500 italic flex flex-col items-center gap-2">
              <CheckCircle className="w-8 h-8 text-cyber-green animate-pulse" />
              <span>This endpoint node complies fully with all banking core baselines</span>
            </div>
          )}
        </div>

      </div>

    </div>
  );
};
