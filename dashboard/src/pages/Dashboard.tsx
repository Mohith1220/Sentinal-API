import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from '../contexts/AuthContext';
import { graphApi, endpointsApi } from '../lib/api';
import { DependencyGraph } from '../components/DependencyGraph';
import { NodeDetailsPanel } from '../components/NodeDetailsPanel';
import { APIDataTable } from '../components/APIDataTable';
import { StalenessIndicator } from '../components/StalenessIndicator';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  BarChart,
  Bar,
  Cell,
} from 'recharts';
import {
  Shield,
  Activity,
  AlertOctagon,
  Flame,
  RefreshCw,
  HardDrive,
  Cpu,
  Fingerprint,
  FileCode,
} from 'lucide-react';
import { UserRole } from '../types/api';

export const Dashboard: React.FC = () => {
  const [lastRefreshedAt, setLastRefreshedAt] = useState(Date.now());
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const { role, user } = useAuth();

  // Queries for Graph infrastructure and inventory lists
  const { data: graphData, refetch: refetchGraph } = useQuery({
    queryKey: ['graph'],
    queryFn: graphApi.getGraph,
    refetchInterval: 30000, // Sync every 30 seconds
  });

  const { data: endpointsData } = useQuery({
    queryKey: ['endpoints-kpis'],
    queryFn: () => endpointsApi.getEndpoints({ page_size: 1000 }),
  });

  const handleRefresh = () => {
    setLastRefreshedAt(Date.now());
    refetchGraph();
  };

  // Aggregate KPI metrics locally
  const kpis = React.useMemo(() => {
    if (!endpointsData?.items) {
      return { total: 0, zombies: 0, shadows: 0, unsecured: 0, avgRisk: 0 };
    }
    const items = endpointsData.items;
    const zombies = items.filter(i => i.lifecycle_status === 'Zombie').length;
    const shadows = items.filter(i => i.lifecycle_status === 'Shadow_API').length;
    const unsecured = items.filter(i => i.auth_scheme === 'none' && (i.data_sensitivity === 'PII' || i.data_sensitivity === 'financial')).length;
    const avgRisk = items.reduce((sum, curr) => sum + curr.risk_score, 0) / items.length;

    return {
      total: items.length,
      zombies,
      shadows,
      unsecured,
      avgRisk: Math.round(avgRisk),
    };
  }, [endpointsData]);

  // Mock charts historical dataset
  const trafficChartData = [
    { time: '00:00', traffic: 240, anomalies: 0 },
    { time: '04:00', traffic: 180, anomalies: 1 },
    { time: '08:00', traffic: 320, anomalies: 3 },
    { time: '12:00', traffic: 450, anomalies: 5 },
    { time: '16:00', traffic: 390, anomalies: 1 },
    { time: '20:00', traffic: 280, anomalies: 12 }, // spike!
    { time: '24:00', traffic: 260, anomalies: 2 },
  ];

  const sensitivityChartData = [
    { category: 'PUBLIC', count: kpis.total ? Math.round(kpis.total * 0.15) : 3, fill: '#10b981' },
    { category: 'INTERNAL', count: kpis.total ? Math.round(kpis.total * 0.45) : 10, fill: '#3b82f6' },
    { category: 'PII', count: kpis.total ? Math.round(kpis.total * 0.25) : 6, fill: '#8b5cf6' },
    { category: 'FINANCIAL', count: kpis.total ? Math.round(kpis.total * 0.15) : 4, fill: '#f97316' },
  ];

  const getClearanceLevel = (r: UserRole | null) => {
    switch (r) {
      case UserRole.SUPER_ADMIN: return 'LEVEL 5 (UNRESTRICTED COMMAND)';
      case UserRole.SECURITY_ADMIN: return 'LEVEL 4 (CONTROL OVERRIDE)';
      case UserRole.SECURITY_ANALYST: return 'LEVEL 3 (THREAT DIAGNOSIS)';
      case UserRole.API_GOVERNANCE_MANAGER: return 'LEVEL 3 (ASSET AUDITING)';
      case UserRole.COMPLIANCE_OFFICER: return 'LEVEL 2 (REGULATORY AUDITING)';
      default: return 'LEVEL 1 (READ ONLY SHADOW)';
    }
  };

  return (
    <div className="flex flex-col gap-6 font-mono text-xs select-none">
      
      {/* SOC Clearance Banner */}
      <div className="glass-panel border border-cyber-border-hover/30 p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 shadow-[0_0_20px_rgba(6,182,212,0.04)]">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded bg-cyber-purple/10 border border-cyber-purple/35 flex items-center justify-center">
            <Shield className="w-5 h-5 text-cyber-purple animate-pulse" />
          </div>
          <div>
            <h2 className="font-bold text-gray-200 text-sm tracking-wider uppercase">SENTINEL_API CENTRAL SOC DECK</h2>
            <div className="text-[10px] text-gray-400 mt-0.5">
              SECURE OPERATOR SESSION ID: <span className="text-cyber-cyan font-bold">{user?.username}</span> | CLEARANCE: <span className="text-cyber-purple font-bold">{getClearanceLevel(role)}</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleRefresh}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded border border-cyber-border hover:border-cyber-cyan bg-cyber-panel hover:bg-cyber-cyan/10 text-gray-400 hover:text-cyber-cyan transition-colors cursor-pointer"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>SYNC TELEMETRY</span>
          </button>
        </div>
      </div>

      <StalenessIndicator lastRefreshedAt={lastRefreshedAt} />

      {/* KPI HUD GRID */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        {/* Total endpoints */}
        <div className="glass-panel border border-cyber-border p-4 flex flex-col gap-1.5 hover:border-cyber-cyan/35 transition-all">
          <span className="text-[10px] text-gray-500 flex items-center gap-1">
            <Cpu className="w-3.5 h-3.5 text-cyber-blue" />
            <span>GATEWAY_ENDPOINTS</span>
          </span>
          <span className="text-white text-xl font-bold">{kpis.total} Active</span>
          <span className="text-[9px] text-cyber-green">▲ 4 Discovered 24h</span>
        </div>

        {/* Zombie APIs */}
        <div className={`glass-panel border p-4 flex flex-col gap-1.5 hover:border-cyber-red/35 transition-all ${
          kpis.zombies > 0 ? 'border-cyber-red/35 bg-cyber-red/5' : 'border-cyber-border'
        }`}>
          <span className="text-[10px] text-gray-500 flex items-center gap-1">
            <Flame className="w-3.5 h-3.5 text-cyber-red animate-bounce" />
            <span>ZOMBIE_APIS</span>
          </span>
          <span className={`text-xl font-bold ${kpis.zombies > 0 ? 'text-cyber-red animate-pulse' : 'text-white'}`}>
            {kpis.zombies} Alerts
          </span>
          <span className="text-[9px] text-gray-500">Deprecated, still receiving calls</span>
        </div>

        {/* Shadow APIs */}
        <div className={`glass-panel border p-4 flex flex-col gap-1.5 hover:border-cyber-purple/35 transition-all ${
          kpis.shadows > 0 ? 'border-cyber-purple/35 bg-cyber-purple/5' : 'border-cyber-border'
        }`}>
          <span className="text-[10px] text-gray-500 flex items-center gap-1">
            <Fingerprint className="w-3.5 h-3.5 text-cyber-purple" />
            <span>SHADOW_APIS</span>
          </span>
          <span className={`text-xl font-bold ${kpis.shadows > 0 ? 'text-cyber-purple' : 'text-white'}`}>
            {kpis.shadows} Found
          </span>
          <span className="text-[9px] text-gray-500">Exposed but uninventoried</span>
        </div>

        {/* Unsecured Sensitive Assets */}
        <div className="glass-panel border border-cyber-border p-4 flex flex-col gap-1.5 hover:border-cyber-amber/35 transition-all">
          <span className="text-[10px] text-gray-500 flex items-center gap-1">
            <AlertOctagon className="w-3.5 h-3.5 text-cyber-amber" />
            <span>UNSECURED_ASSETS</span>
          </span>
          <span className={`text-xl font-bold ${kpis.unsecured > 0 ? 'text-cyber-amber animate-pulse' : 'text-white'}`}>
            {kpis.unsecured} Warning
          </span>
          <span className="text-[9px] text-gray-500">No Auth + High Exposure</span>
        </div>

        {/* System integrity level */}
        <div className="glass-panel border border-cyber-border p-4 flex flex-col gap-1.5 hover:border-cyber-green/35 transition-all col-span-2 lg:col-span-1">
          <span className="text-[10px] text-gray-500 flex items-center gap-1">
            <HardDrive className="w-3.5 h-3.5 text-cyber-green" />
            <span>INTEGRITY_LEVEL</span>
          </span>
          <span className="text-cyber-green text-xl font-bold">{100 - kpis.avgRisk}% Safe</span>
          <span className="text-[9px] text-gray-500">Aggregated Risk Index: {kpis.avgRisk}%</span>
        </div>
      </div>

      {/* DOUBLE GRAPH PLOTS */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        
        {/* Throughput Area Chart */}
        <div className="glass-panel border border-cyber-border p-5 flex flex-col gap-4">
          <span className="text-[10px] text-gray-500 flex items-center gap-1.5 pb-2 border-b border-cyber-border/40">
            <Activity className="w-3.5 h-3.5 text-cyber-cyan" />
            <span>TRAFFIC_METRICS_VS_THREAT_DETECTIONS (24H)</span>
          </span>
          <div className="h-56">
            <ResponsiveContainer width="100%" height={224} minWidth={0}>
              <AreaChart data={trafficChartData} margin={{ top: 10, right: 10, left: -25, bottom: 0 }}>
                <defs>
                  <linearGradient id="colorTraffic" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="colorThreat" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#ef4444" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="time" stroke="#6b7280" fontSize={9} tickLine={false} />
                <YAxis stroke="#6b7280" fontSize={9} tickLine={false} />
                <Tooltip contentStyle={{ backgroundColor: '#0b1220', borderColor: 'rgba(255,255,255,0.08)', fontSize: '10px' }} />
                <Area type="monotone" dataKey="traffic" name="Gateway Volume (Requests/s)" stroke="#3b82f6" fillOpacity={1} fill="url(#colorTraffic)" />
                <Area type="monotone" dataKey="anomalies" name="Anomaly Alarms Triggered" stroke="#ef4444" fillOpacity={1} fill="url(#colorThreat)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Data Exposure Bar Chart */}
        <div className="glass-panel border border-cyber-border p-5 flex flex-col gap-4">
          <span className="text-[10px] text-gray-500 flex items-center gap-1.5 pb-2 border-b border-cyber-border/40">
            <FileCode className="w-3.5 h-3.5 text-cyber-purple" />
            <span>ENDPOINT_DATA_EXPOSURE_INVENTORY</span>
          </span>
          <div className="h-56">
            <ResponsiveContainer width="100%" height={224} minWidth={0}>
              <BarChart data={sensitivityChartData} margin={{ top: 10, right: 10, left: -25, bottom: 0 }}>
                <XAxis dataKey="category" stroke="#6b7280" fontSize={9} tickLine={false} />
                <YAxis stroke="#6b7280" fontSize={9} tickLine={false} />
                <Tooltip contentStyle={{ backgroundColor: '#0b1220', borderColor: 'rgba(255,255,255,0.08)', fontSize: '10px' }} cursor={{ fill: 'rgba(255,255,255,0.02)' }} />
                <Bar dataKey="count" name="Identified Endpoint Nodes" fill="#3b82f6" radius={[4, 4, 0, 0]}>
                  {sensitivityChartData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

      </div>

      {/* Dependency Graph visual map */}
      <div className="glass-panel border border-cyber-border p-5 flex flex-col gap-4">
        <div className="flex items-center justify-between border-b border-cyber-border/40 pb-2">
          <span className="text-[10px] text-gray-500 flex items-center gap-1.5">
            <Shield className="w-3.5 h-3.5 text-cyber-cyan" />
            <span>INFRASTRUCTURE_CALLS_INTELLIGENCE_MESH</span>
          </span>
          <span className="text-[9px] text-gray-500">Zoom scroll & drag nodes to reorganize topology</span>
        </div>
        
        {graphData ? (
          <DependencyGraph
            data={graphData}
            onNodeSelect={setSelectedNodeId}
            selectedNodeId={selectedNodeId}
          />
        ) : (
          <div className="w-full h-[550px] border border-cyber-border rounded-lg bg-black/20 flex flex-col items-center justify-center gap-3">
            <div className="w-8 h-8 rounded-full border-4 border-cyber-border border-t-cyber-cyan animate-spin" />
            <span className="text-[10px] text-cyber-cyan animate-pulse">BINNING TOPOLOGY GRAPH...</span>
          </div>
        )}
      </div>

      {/* Tanstack high-density Inventory */}
      <div className="glass-panel border border-cyber-border p-5 flex flex-col gap-4">
        <span className="text-[10px] text-gray-500 flex items-center gap-1.5 pb-2 border-b border-cyber-border/40">
          <HardDrive className="w-3.5 h-3.5 text-cyber-cyan" />
          <span>INVENTORIED_API_ASSETS</span>
        </span>
        <APIDataTable
          onRowSelect={(id) => setSelectedNodeId(id)}
          selectedEndpointId={selectedNodeId}
        />
      </div>

      {/* Node Details Drawer slide-out */}
      {selectedNodeId && (
        <NodeDetailsPanel
          nodeId={selectedNodeId}
          onClose={() => setSelectedNodeId(null)}
        />
      )}
    </div>
  );
};
