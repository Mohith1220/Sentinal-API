import React from 'react';
import { AlertsPanel } from '../components/AlertsPanel';
import { ThreatTimeline } from '../components/ThreatTimeline';
import { useAlertStore } from '../lib/store';
import { ShieldAlert, Flame, Radio, Activity, AlertTriangle } from 'lucide-react';

export const AlertsCenter: React.FC = () => {
  const { alerts } = useAlertStore();

  const criticalCount = alerts.filter(a => a.deviation_sigma >= 5).length;
  const highCount = alerts.filter(a => a.deviation_sigma >= 4 && a.deviation_sigma < 5).length;

  const mockTimelineEvents: import('../components/ThreatTimeline').TimelineEvent[] = [
    {
      id: 'evt-001',
      timestamp: new Date(Date.now() - 600000).toISOString(),
      type: 'anomaly',
      title: 'ZOMBIE_CALLS_DETECTED',
      description: 'API path /v1/deprecate/ledger observed with unusually high requests (34 calls/min). Triggered priority anomaly alert.',
      severity: 'Critical'
    },
    {
      id: 'evt-002',
      timestamp: new Date(Date.now() - 1800000).toISOString(),
      type: 'discovery',
      title: 'SHADOW_API_DISCOVERED',
      description: 'Discovered shadow route /v1/transfers/anonymous bypassing standard core-auth gateway policies.',
      severity: 'High'
    },
    {
      id: 'evt-003',
      timestamp: new Date(Date.now() - 3600000).toISOString(),
      type: 'remediation',
      title: 'CONTAINMENT_PATCH_DEPLOYED',
      description: 'Remediation config for rate-limiting successfully registered on gateway ledger. Endpoint /v1/auth/token status corrected.',
      severity: 'Medium',
      operator: 'sec_admin'
    },
    {
      id: 'evt-004',
      timestamp: new Date(Date.now() - 7200000).toISOString(),
      type: 'vulnerability',
      title: 'OWASP_BOLA_VIOLATION',
      description: 'Endpoint /v1/accounts/{id} failed secure parameter binding validations. Data exposure risk high.',
      severity: 'High'
    }
  ];

  return (
    <div className="flex flex-col gap-6 font-mono text-xs select-none">
      
      {/* Header Deck */}
      <div className="glass-panel border border-cyber-border p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded bg-cyber-red/10 border border-cyber-red/35 flex items-center justify-center">
            <ShieldAlert className="w-5 h-5 text-cyber-red animate-pulse" />
          </div>
          <div>
            <h2 className="font-bold text-gray-200 text-sm tracking-wider uppercase">INCIDENT_RESPONSE_COMMAND</h2>
            <div className="text-[10px] text-gray-400 mt-0.5">
              Live Kafka stream parsing anomaly alerts, threshold stress levels, and security event logs.
            </div>
          </div>
        </div>
      </div>

      {/* KPI Counters */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="glass-panel border border-cyber-border p-4 flex items-center justify-between hover:border-cyber-red/45 transition-colors">
          <div className="flex flex-col gap-1">
            <span className="text-gray-500 text-[10px]">CRITICAL_THREATS</span>
            <span className={`text-lg font-bold ${criticalCount > 0 ? 'text-cyber-red animate-pulse' : 'text-gray-400'}`}>
              {criticalCount} ACTIVE
            </span>
          </div>
          <Flame className={`w-6 h-6 ${criticalCount > 0 ? 'text-cyber-red' : 'text-gray-700'}`} />
        </div>

        <div className="glass-panel border border-cyber-border p-4 flex items-center justify-between hover:border-cyber-amber/45 transition-colors">
          <div className="flex flex-col gap-1">
            <span className="text-gray-500 text-[10px]">HIGH_WARNINGS</span>
            <span className={`text-lg font-bold ${highCount > 0 ? 'text-cyber-amber animate-pulse' : 'text-gray-400'}`}>
              {highCount} DETECTED
            </span>
          </div>
          <AlertTriangle className={`w-6 h-6 ${highCount > 0 ? 'text-cyber-amber' : 'text-gray-700'}`} />
        </div>

        <div className="glass-panel border border-cyber-border p-4 flex items-center justify-between hover:border-cyber-cyan/45 transition-colors">
          <div className="flex flex-col gap-1">
            <span className="text-gray-500 text-[10px]">TOTAL_ALERTS_IN_SESSION</span>
            <span className="text-cyber-cyan text-lg font-bold">
              {alerts.length} ALARMS
            </span>
          </div>
          <Radio className="w-6 h-6 text-cyber-cyan animate-pulse" />
        </div>
      </div>

      {/* Main Double Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        
        {/* Left Column: Real time WebSocket Alerts */}
        <div className="flex flex-col gap-3">
          <span className="text-[10px] text-gray-500 flex items-center gap-1.5 pb-1 border-b border-cyber-border/40 font-bold">
            <Activity className="w-3.5 h-3.5 text-cyber-cyan" />
            <span>REALTIME_KAFKA_STREAMING_DIAGNOSTICS</span>
          </span>
          <AlertsPanel />
        </div>

        {/* Right Column: Threat chronological audit events */}
        <div className="flex flex-col gap-3">
          <span className="text-[10px] text-gray-500 flex items-center gap-1.5 pb-1 border-b border-cyber-border/40 font-bold">
            <Radio className="w-3.5 h-3.5 text-cyber-purple" />
            <span>HISTORICAL_CHRONOLOGICAL_INCIDENT_TIMELINE</span>
          </span>
          <div className="glass-panel border border-cyber-border p-4 max-h-[550px] overflow-y-auto">
            <ThreatTimeline events={mockTimelineEvents} />
          </div>
        </div>

      </div>

    </div>
  );
};
