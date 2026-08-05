import React, { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { Permission, UserRole } from '../types/api';
import { AuditLogViewer } from '../components/AuditLogViewer';
import { Sliders, Shield, Radio, Users, Terminal } from 'lucide-react';
import type { AuditLog } from '../types/api';

export const Administration: React.FC = () => {
  const { hasPermission } = useAuth();
  const [activeTab, setActiveTab] = useState<'ML_MODELS' | 'KAFKA' | 'RBAC' | 'AUDIT'>('ML_MODELS');

  // ML sliders parameters state
  const [mlParams, setMlParams] = useState({
    zombieCallCount: 15,
    shadowFreqThreshold: 5.5,
    anomalySigma: 3.5,
    rateLimitLimit: 500,
  });

  // User list mock for RBAC Controls Grid
  const [users, setUsers] = useState([
    { id: '1', username: 'admin', role: UserRole.SUPER_ADMIN, department: 'GLOBAL_SOC' },
    { id: '2', username: 'sec_admin', role: UserRole.SECURITY_ADMIN, department: 'CORE_INFRA' },
    { id: '3', username: 'analyst', role: UserRole.SECURITY_ANALYST, department: 'SOC_RESPONSE' },
    { id: '4', username: 'governance', role: UserRole.API_GOVERNANCE_MANAGER, department: 'REGULATORY' },
    { id: '5', username: 'compliance', role: UserRole.COMPLIANCE_OFFICER, department: 'LEGAL' },
    { id: '6', username: 'viewer', role: UserRole.VIEWER, department: 'GUEST_AUDIT' },
  ]);

  // Immutable Regulatory Audit Trail mock logs
  const auditLogs: AuditLog[] = [
    {
      id: 'aud-001',
      timestamp: new Date(Date.now() - 50000).toISOString(),
      user_id: 'sec_admin',
      action: 'UPDATE_ML_THRESHOLD',
      resource_type: 'ML_CONFIGURATION',
      resource_id: 'ml_tuning_baselines',
      ip_address: '10.200.4.45',
      changes: {
        anomalySigma: { old: 4.0, new: 3.5 },
        updated_by: 'sec_admin',
        timestamp: Date.now(),
      },
    },
    {
      id: 'aud-002',
      timestamp: new Date(Date.now() - 120000).toISOString(),
      user_id: 'admin',
      action: 'RESOLVE_RECOMMENDATION',
      resource_type: 'ALERT',
      resource_id: 'rec_zombie_pci_405',
      ip_address: '10.200.4.12',
      changes: {
        recommendation_id: 'rec_zombie_pci_405',
        status: { old: 'OPEN', new: 'RESOLVED' },
        remediated_at: new Date().toISOString(),
      },
    },
    {
      id: 'aud-003',
      timestamp: new Date(Date.now() - 300000).toISOString(),
      user_id: 'governance',
      action: 'DECOMMISSION_ENDPOINT',
      resource_type: 'ENDPOINT',
      resource_id: 'endpoint_shadow_p2p_transfer',
      ip_address: '10.200.6.88',
      changes: {
        path: '/v1/transfers/p2p',
        lifecycle_status: { old: 'Shadow_API', new: 'Deprecated' },
      },
    },
    {
      id: 'aud-004',
      timestamp: new Date(Date.now() - 900000).toISOString(),
      user_id: 'sec_admin',
      action: 'OVERRIDE_RBAC_POLICY',
      resource_type: 'USER',
      resource_id: 'analyst_clearance_level',
      ip_address: '10.200.4.45',
      changes: {
        target_user: 'analyst',
        permissions: { added: ['api.write', 'alerts.resolve'] },
      },
    },
  ];

  const handleRoleChange = (userId: string, newRole: typeof UserRole[keyof typeof UserRole]) => {
    setUsers(prev => prev.map(u => u.id === userId ? { ...u, role: newRole } : u));
  };

  return (
    <div className="flex flex-col gap-6 font-mono text-xs select-none">
      
      {/* Header Deck */}
      <div className="glass-panel border border-cyber-border p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded bg-cyber-cyan/15 border border-cyber-cyan/35 flex items-center justify-center animate-pulse">
            <Shield className="w-5 h-5 text-cyber-cyan" />
          </div>
          <div>
            <h2 className="font-bold text-gray-200 text-sm tracking-wider uppercase">GOVERNANCE_ADMINISTRATION_DECKS</h2>
            <div className="text-[10px] text-gray-400 mt-0.5">
              Tune telemetry engines, check streaming brokers, enforce role-based access grids, and audit compliant activities.
            </div>
          </div>
        </div>
      </div>

      {/* Tabs navigation panel */}
      <div className="flex border-b border-cyber-border/80 gap-1.5 overflow-x-auto pb-0.5">
        {[
          { id: 'ML_MODELS', label: 'ML BASINGS', icon: Sliders },
          { id: 'KAFKA', label: 'KAFKA BROADCAST', icon: Radio },
          { id: 'RBAC', label: 'RBAC PERMISSIONS', icon: Users },
          { id: 'AUDIT', label: 'REGULATORY LOGS', icon: Terminal },
        ].map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`flex items-center gap-1.5 px-4 py-2 border-t border-x rounded-t transition-all cursor-pointer font-bold ${
                isActive ? 'bg-cyber-cyan/10 text-cyber-cyan border-cyber-cyan/40 border-b-black bg-black' : 'border-cyber-border/40 text-gray-500 hover:text-white'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* Tab Panels */}
      <div className="flex flex-col gap-6">

        {/* Tab 1: ML Models Sliders */}
        {activeTab === 'ML_MODELS' && (
          <div className="glass-panel border border-cyber-border p-5 flex flex-col gap-6">
            <span className="text-[10px] text-gray-500 flex items-center gap-1.5 pb-2 border-b border-cyber-border/40">
              <Sliders className="w-4 h-4 text-cyber-cyan" />
              <span>ML_ANOMALY_SENSITIVITY_TUNER</span>
            </span>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              
              <div className="flex flex-col gap-2 p-4 bg-black/20 border border-cyber-border rounded">
                <div className="flex justify-between items-center text-[11px] font-bold">
                  <span className="text-gray-200">ZOMBIE API CALL THRESHOLD</span>
                  <span className="text-cyber-cyan">{mlParams.zombieCallCount} / 24H</span>
                </div>
                <input
                  type="range"
                  min="5"
                  max="100"
                  value={mlParams.zombieCallCount}
                  onChange={(e) => setMlParams(p => ({ ...p, zombieCallCount: parseInt(e.target.value) }))}
                  className="w-full h-1.5 bg-gray-800 rounded-lg appearance-none cursor-pointer accent-cyber-cyan"
                />
                <span className="text-[9px] text-gray-500 font-sans leading-normal mt-1">
                  Trigger zombie alerts if deprecated nodes receive more calls than this value within a 24h rolling window.
                </span>
              </div>

              <div className="flex flex-col gap-2 p-4 bg-black/20 border border-cyber-border rounded">
                <div className="flex justify-between items-center text-[11px] font-bold">
                  <span className="text-gray-200">SHADOW DISCOVERY REQS MIN</span>
                  <span className="text-cyber-cyan">{mlParams.shadowFreqThreshold} Req/s</span>
                </div>
                <input
                  type="range"
                  min="1"
                  max="20"
                  step="0.5"
                  value={mlParams.shadowFreqThreshold}
                  onChange={(e) => setMlParams(p => ({ ...p, shadowFreqThreshold: parseFloat(e.target.value) }))}
                  className="w-full h-1.5 bg-gray-800 rounded-lg appearance-none cursor-pointer accent-cyber-cyan"
                />
                <span className="text-[9px] text-gray-500 font-sans leading-normal mt-1">
                  Baseline requests per second required before the ML classifier indexes a path as a Shadow API.
                </span>
              </div>

              <div className="flex flex-col gap-2 p-4 bg-black/20 border border-cyber-border rounded">
                <div className="flex justify-between items-center text-[11px] font-bold">
                  <span className="text-gray-200">ANOMALOUS DEVIATION SIGMA BASIS</span>
                  <span className="text-cyber-red font-bold">{mlParams.anomalySigma}σ</span>
                </div>
                <input
                  type="range"
                  min="1"
                  max="10"
                  step="0.1"
                  value={mlParams.anomalySigma}
                  onChange={(e) => setMlParams(p => ({ ...p, anomalySigma: parseFloat(e.target.value) }))}
                  className="w-full h-1.5 bg-gray-800 rounded-lg appearance-none cursor-pointer accent-cyber-red"
                />
                <span className="text-[9px] text-gray-500 font-sans leading-normal mt-1">
                  Standard deviations (sigma) from mean request rates required to trigger transactional stress anomaly logs.
                </span>
              </div>

              <div className="flex flex-col gap-2 p-4 bg-black/20 border border-cyber-border rounded">
                <div className="flex justify-between items-center text-[11px] font-bold">
                  <span className="text-gray-200">GLOBAL TRANSACTION RATE CEILING</span>
                  <span className="text-cyber-cyan">{mlParams.rateLimitLimit} / SEC</span>
                </div>
                <input
                  type="range"
                  min="100"
                  max="2000"
                  step="50"
                  value={mlParams.rateLimitLimit}
                  onChange={(e) => setMlParams(p => ({ ...p, rateLimitLimit: parseInt(e.target.value) }))}
                  className="w-full h-1.5 bg-gray-800 rounded-lg appearance-none cursor-pointer accent-cyber-cyan"
                />
                <span className="text-[9px] text-gray-500 font-sans leading-normal mt-1">
                  Rate limiting injection triggers inside the downstream API Gateway proxies.
                </span>
              </div>

            </div>
          </div>
        )}

        {/* Tab 2: Kafka Streams HUD */}
        {activeTab === 'KAFKA' && (
          <div className="glass-panel border border-cyber-border p-5 flex flex-col gap-5 bg-cyber-panel/10">
            <span className="text-[10px] text-gray-500 flex items-center gap-1.5 pb-2 border-b border-cyber-border/40">
              <Radio className="w-4 h-4 text-cyber-cyan animate-pulse" />
              <span>REALTIME_KAFKA_BROKERS_CONSOLE</span>
            </span>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="p-3 bg-black/35 rounded border border-cyber-border/60">
                <span className="text-gray-500">BOOTSTRAP_SERVERS:</span>
                <p className="text-gray-200 font-bold mt-1 text-[11px]">kafka:9092</p>
              </div>
              <div className="p-3 bg-black/35 rounded border border-cyber-border/60">
                <span className="text-gray-500">SUBSCRIBED_TOPICS:</span>
                <p className="text-cyber-cyan font-bold mt-1 text-[11px]">anomaly.alerts, api.traffic</p>
              </div>
              <div className="p-3 bg-black/35 rounded border border-cyber-border/60">
                <span className="text-gray-500">KAFKA_CLUSTER_STATUS:</span>
                <p className="text-cyber-green font-bold mt-1 text-[11px]">ACTIVE (OK)</p>
              </div>
            </div>

            <div className="p-4 bg-black/35 rounded border border-cyber-border leading-relaxed font-sans text-gray-400 text-[11px] flex flex-col gap-3">
              <span className="font-mono text-cyber-cyan font-bold text-xs">[!] Kafka Transaction Consumer Pipeline</span>
              <p>
                The streaming pipelines proxy incoming HTTP packets through downstream gateways, writing telemetry buffers directly to the `api.traffic` Kafka topic. High-velocity stream processors consume and parse data sensitivity, outputting anomaly indicators onto `anomaly.alerts` on deviation anomalies.
              </p>
            </div>
          </div>
        )}

        {/* Tab 3: RBAC Grid */}
        {activeTab === 'RBAC' && (
          <div className="glass-panel border border-cyber-border p-5 flex flex-col gap-4">
            <span className="text-[10px] text-gray-500 flex items-center gap-1.5 pb-2 border-b border-cyber-border/40">
              <Users className="w-4 h-4 text-cyber-cyan" />
              <span>PERSONA_RBAC_CLEARANCE_ACCESS_GRIDS</span>
            </span>

            {/* Locked behind Permission check */}
            {hasPermission(Permission.MANAGE_ROLES) ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse font-mono">
                  <thead>
                    <tr className="bg-black/45 border-b border-cyber-border text-gray-500">
                      <th className="p-3 font-bold">USER_IDENTITY</th>
                      <th className="p-3 font-bold">DEPARTMENT</th>
                      <th className="p-3 font-bold">ASSIGNED_ROLE_CLEARANCE</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-cyber-border/45 bg-cyber-panel/10 text-gray-300">
                    {users.map(usr => (
                      <tr key={usr.id} className="hover:bg-white/5 transition-colors">
                        <td className="p-3 font-bold text-cyber-cyan">{usr.username}</td>
                        <td className="p-3">{usr.department}</td>
                        <td className="p-3">
                          <select
                            value={usr.role}
                            onChange={(e) => handleRoleChange(usr.id, e.target.value as any)}
                            className="bg-black/45 border border-cyber-border rounded px-2 py-1 text-xs text-cyber-cyan font-bold focus:outline-none focus:border-cyber-cyan cursor-pointer uppercase"
                          >
                            {Object.values(UserRole).map(roleOption => (
                              <option key={roleOption} value={roleOption}>
                                {roleOption.replace('_', ' ')}
                              </option>
                            ))}
                          </select>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="p-6 text-center text-cyber-red border border-cyber-red/30 bg-cyber-red/5 rounded font-mono">
                [ALERT] VISITOR BLOCK: REQUIRES LEVEL 5 (SUPER_ADMIN) SYSTEM PRIVILEGES TO MODIFY USER POLICIES.
              </div>
            )}
          </div>
        )}

        {/* Tab 4: Immutable Regulatory Audit Logs */}
        {activeTab === 'AUDIT' && (
          <div className="flex flex-col gap-3">
            <span className="text-[10px] text-gray-500 flex items-center gap-1.5 pb-1 border-b border-cyber-border/40 font-bold">
              <Terminal className="w-4 h-4 text-cyber-cyan" />
              <span>REGULATORY_COMPLIANT_IMMUTABLE_LOGS</span>
            </span>
            <AuditLogViewer logs={auditLogs} />
          </div>
        )}

      </div>

    </div>
  );
};
