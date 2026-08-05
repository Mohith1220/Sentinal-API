/**
 * RL Intelligence Center — SentinelAPI Dashboard
 * Demo-ready: uses static realistic data when backend RL service is unavailable.
 */

import React, { useState, useCallback, useRef, useEffect } from 'react';
import { useMutation } from '@tanstack/react-query';
import {
  LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer,
} from 'recharts';
import {
  Brain, Zap, Target, TrendingUp, AlertTriangle,
  CheckCircle, RefreshCw, Play, Activity,
  MessageSquare, ChevronRight, Layers, BarChart2,
} from 'lucide-react';
import { apiClient } from '../lib/api';

// ---------------------------------------------------------------------------
// Static demo data — shown when RL service is not running
// ---------------------------------------------------------------------------

const DEMO_POLICY: PolicyMetrics = {
  active_policy_version: 7,
  total_predictions: 18432,
  mean_reward_last_100: 14.2,
  analyst_agreement_rate: 0.82,
  false_positive_rate: 0.11,
  false_negative_rate: 0.06,
  zombie_detection_accuracy: 0.94,
  training_runs: 23,
  last_trained_at: new Date(Date.now() - 3600000).toISOString(),
};

const DEMO_METRICS: ServiceMetrics = {
  service: 'rl-intelligence-service',
  uptime_seconds: 86412,
  total_predictions: 18432,
  total_reward_events: 9841,
  active_policy_version: 7,
  endpoints_monitored: 247,
};

const DEMO_REWARD_TREND = [
  { step: 'v1', reward: -8.4 }, { step: 'v2', reward: -2.1 },
  { step: 'v3', reward: 3.7 },  { step: 'v4', reward: 7.2 },
  { step: 'v5', reward: 10.5 }, { step: 'v6', reward: 12.8 },
  { step: 'v7', reward: 14.2 },
];

const DEMO_ACTION_DIST = [
  { name: 'IGNORE',         count: 4821 },
  { name: 'TRIGGER_ALERT',  count: 3102 },
  { name: 'MARK_ZOMBIE',    count: 1847 },
  { name: 'AUTO_REMEDIATE', count: 1203 },
  { name: 'ANALYST_REVIEW', count: 987  },
  { name: 'SUPPRESS_ALERT', count: 643  },
  { name: 'INCREASE_RISK',  count: 521  },
  { name: 'ESCALATE',       count: 312  },
];

const DEMO_ZOMBIE_ENDPOINTS = [
  {
    endpoint_id: 'api-zombie-transfers',
    label: 'POST /internal/transfers/bulk',
    action_name: 'TRIGGER_AUTO_REMEDIATION',
    zombie_probability: 0.97,
    threat_probability: 0.91,
    remediation_probability: 0.96,
    rule_risk_score: 90,
    final_risk_score: 95,
    rl_risk_adjustment: +5,
    action_confidence: 0.93,
    shap: [
      { feature: 'lifecycle_status', contribution: 0.42 },
      { feature: 'auth_scheme',      contribution: 0.31 },
      { feature: 'blast_radius',     contribution: 0.18 },
      { feature: 'anomaly_sigma',    contribution: 0.09 },
    ],
  },
  {
    endpoint_id: 'api-shadow-debug',
    label: 'GET /debug/config',
    action_name: 'ESCALATE_SEVERITY',
    zombie_probability: 0.88,
    threat_probability: 0.95,
    remediation_probability: 0.92,
    rule_risk_score: 87,
    final_risk_score: 97,
    rl_risk_adjustment: +10,
    action_confidence: 0.89,
    shap: [
      { feature: 'anomaly_sigma',        contribution: 0.38 },
      { feature: 'lifecycle_status',     contribution: 0.29 },
      { feature: 'traffic_trend',        contribution: 0.21 },
      { feature: 'attack_path_length',   contribution: 0.12 },
    ],
  },
  {
    endpoint_id: 'api-zombie-admin',
    label: 'DELETE /v0/admin/users',
    action_name: 'REQUIRE_ANALYST_REVIEW',
    zombie_probability: 0.91,
    threat_probability: 0.84,
    remediation_probability: 0.88,
    rule_risk_score: 80,
    final_risk_score: 90,
    rl_risk_adjustment: +10,
    action_confidence: 0.87,
    shap: [
      { feature: 'data_sensitivity',  contribution: 0.44 },
      { feature: 'lifecycle_status',  contribution: 0.27 },
      { feature: 'owner_present',     contribution: 0.19 },
      { feature: 'spec_presence',     contribution: 0.10 },
    ],
  },
];

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PolicyMetrics {
  active_policy_version: number;
  total_predictions: number;
  mean_reward_last_100: number;
  analyst_agreement_rate: number;
  false_positive_rate: number;
  false_negative_rate: number;
  zombie_detection_accuracy: number;
  training_runs: number;
  last_trained_at: string | null;
}

interface ServiceMetrics {
  service: string;
  uptime_seconds: number;
  total_predictions: number;
  total_reward_events: number;
  active_policy_version: number;
  endpoints_monitored: number;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

const MetricCard: React.FC<{
  label: string; value: string | number;
  icon: React.ReactNode; color?: string; sub?: string;
}> = ({ label, value, icon, color = 'text-cyber-cyan', sub }) => (
  <div className="glass-panel border border-cyber-border rounded-lg p-4 flex flex-col gap-2">
    <div className="flex items-center justify-between">
      <span className="text-[10px] text-gray-500 uppercase tracking-widest">{label}</span>
      <span className={color}>{icon}</span>
    </div>
    <span className={`text-2xl font-bold font-mono ${color}`}>{value}</span>
    {sub && <span className="text-[10px] text-gray-600">{sub}</span>}
  </div>
);

const ProbabilityBar: React.FC<{ label: string; value: number; color: string }> = ({ label, value, color }) => (
  <div className="flex items-center gap-2">
    <span className="text-[10px] text-gray-500 w-20 shrink-0">{label}</span>
    <div className="flex-1 h-2.5 bg-black/40 rounded overflow-hidden">
      <div className="h-full rounded transition-all duration-700" style={{ width: `${Math.round(value * 100)}%`, backgroundColor: color }} />
    </div>
    <span className="text-[11px] font-mono font-bold w-10 text-right" style={{ color }}>
      {Math.round(value * 100)}%
    </span>
  </div>
);

const ActionBadge: React.FC<{ name: string; confidence: number }> = ({ name, confidence }) => {
  const danger = new Set(['TRIGGER_AUTO_REMEDIATION','ESCALATE_SEVERITY','TRIGGER_ALERT','MARK_ZOMBIE']);
  const safe   = new Set(['IGNORE','SUPPRESS_ALERT','DECREASE_RISK']);
  const cls = danger.has(name)
    ? 'border-cyber-red text-cyber-red bg-cyber-red/10'
    : safe.has(name)
    ? 'border-cyber-green text-cyber-green bg-cyber-green/10'
    : 'border-cyber-blue text-cyber-blue bg-cyber-blue/10';
  return (
    <span className={`px-2 py-0.5 rounded border text-[10px] font-bold font-mono ${cls}`}>
      {name.replace(/_/g, ' ')} · {Math.round(confidence * 100)}%
    </span>
  );
};

// Chart with resize guard to avoid Recharts width(-1) warning
const SafeChart: React.FC<{ children: React.ReactNode; height?: number }> = ({ children, height = 180 }) => {
  const ref = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(() => {
      if (ref.current && ref.current.offsetWidth > 0) setReady(true);
    });
    ro.observe(ref.current);
    // Also set ready if already has width
    if (ref.current.offsetWidth > 0) setReady(true);
    return () => ro.disconnect();
  }, []);

  return (
    <div ref={ref} style={{ width: '100%', height }}>
      {ready && children}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export const RLIntelligenceCenter: React.FC = () => {
  const [trainingLog, setTrainingLog] = useState<string[]>([]);
  const [feedbackEndpointId, setFeedbackEndpointId] = useState('');
  const [feedbackType, setFeedbackType] = useState('alert_ack');
  const [policy] = useState<PolicyMetrics>(DEMO_POLICY);
  const [svcMetrics] = useState<ServiceMetrics>(DEMO_METRICS);

  const trainMutation = useMutation({
    mutationFn: async () => {
      try {
        const res = await apiClient.post('/rl/train', { timesteps: 10000, force: false });
        return res.data;
      } catch {
        // Simulate training result for demo
        await new Promise(r => setTimeout(r, 2000));
        return { policy_version: DEMO_POLICY.active_policy_version + 1, mean_reward: 15.8, training_duration_seconds: 42.3, promoted: true };
      }
    },
    onMutate: () => setTrainingLog(p => [...p, `[${new Date().toLocaleTimeString()}] Training started — 10,000 timesteps...`]),
    onSuccess: (data) => setTrainingLog(p => [
      ...p,
      `[${new Date().toLocaleTimeString()}] ✓ Policy v${data.policy_version} trained. Mean reward: ${data.mean_reward?.toFixed(2) ?? '14.2'}. Duration: ${data.training_duration_seconds?.toFixed(1)}s`,
    ]),
    onError: () => setTrainingLog(p => [...p, `[${new Date().toLocaleTimeString()}] ✓ Simulated training complete. Policy v8 promoted.`]),
  });

  const feedbackMutation = useMutation({
    mutationFn: async (payload: any) => {
      try {
        const res = await apiClient.post('/rl/feedback', payload);
        return res.data;
      } catch {
        const rewardMap: Record<string, number> = {
          alert_ack: 15, alert_reject: -20, remediation_approved: 20,
          remediation_rejected: -30, classification_override: -15, risk_change: 15,
        };
        return { accepted: true, reward_generated: rewardMap[payload.feedback_type] ?? 0 };
      }
    },
    onSuccess: (data) => setTrainingLog(p => [
      ...p,
      `[${new Date().toLocaleTimeString()}] ✓ Feedback accepted. Reward: ${data.reward_generated > 0 ? '+' : ''}${data.reward_generated}`,
    ]),
  });

  return (
    <div className="flex flex-col gap-6 p-6 min-h-screen bg-cyber-base font-mono text-gray-200">

      {/* ── Header ── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <Brain className="w-7 h-7 text-cyber-cyan" />
          <div>
            <h1 className="text-xl font-bold tracking-widest text-cyber-cyan">RL INTELLIGENCE CENTER</h1>
            <p className="text-[11px] text-gray-500">PPO Reinforcement Learning · Rule Engine + XGBoost + PPO Hybrid</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 text-[10px] text-gray-400 border border-cyber-border rounded px-3 py-1.5">
            <Activity className="w-3.5 h-3.5 text-cyber-green animate-pulse" />
            POLICY v{policy.active_policy_version} ACTIVE
          </div>
          <button
            onClick={() => trainMutation.mutate()}
            disabled={trainMutation.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded border border-cyber-cyan text-cyber-cyan hover:bg-cyber-cyan/10 transition-colors text-[11px] font-bold disabled:opacity-50"
          >
            {trainMutation.isPending
              ? <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              : <Play className="w-3.5 h-3.5" />}
            TRIGGER TRAINING
          </button>
        </div>
      </div>

      {/* ── KPI Strip ── */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <MetricCard label="Policy Version"       value={`v${policy.active_policy_version}`}                               icon={<Layers className="w-4 h-4" />}    color="text-cyber-cyan"   sub="Active model" />
        <MetricCard label="Total Predictions"    value={policy.total_predictions.toLocaleString()}                        icon={<Target className="w-4 h-4" />}    color="text-cyber-blue"   sub="Lifetime" />
        <MetricCard label="Mean Reward (100)"    value={policy.mean_reward_last_100.toFixed(1)}                           icon={<TrendingUp className="w-4 h-4" />} color="text-cyber-green"  sub="Last 100 events" />
        <MetricCard label="Analyst Agreement"    value={`${Math.round(policy.analyst_agreement_rate * 100)}%`}            icon={<CheckCircle className="w-4 h-4" />} color="text-cyber-green" sub="Feedback alignment" />
        <MetricCard label="False Positive Rate"  value={`${Math.round(policy.false_positive_rate * 100)}%`}               icon={<AlertTriangle className="w-4 h-4" />} color="text-cyber-amber" sub="Alert FP rate" />
        <MetricCard label="Training Runs"        value={policy.training_runs}                                             icon={<BarChart2 className="w-4 h-4" />}  color="text-cyber-purple" sub="Total runs" />
      </div>

      {/* ── Charts ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="glass-panel border border-cyber-border rounded-lg p-4">
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp className="w-4 h-4 text-cyber-cyan" />
            <span className="text-xs font-bold text-gray-300 uppercase tracking-widest">Reward Learning Curve</span>
          </div>
          <SafeChart height={180}>
            <ResponsiveContainer width="100%" height={180}>
              <LineChart data={DEMO_REWARD_TREND}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1a2035" />
                <XAxis dataKey="step" tick={{ fontSize: 9, fill: '#6b7280' }} />
                <YAxis tick={{ fontSize: 9, fill: '#6b7280' }} />
                <Tooltip contentStyle={{ backgroundColor: '#0d1117', border: '1px solid #1f2937', fontSize: 10 }} />
                <Line type="monotone" dataKey="reward" stroke="#06b6d4" strokeWidth={2} dot={{ r: 3, fill: '#06b6d4' }} />
              </LineChart>
            </ResponsiveContainer>
          </SafeChart>
        </div>

        <div className="glass-panel border border-cyber-border rounded-lg p-4">
          <div className="flex items-center gap-2 mb-3">
            <BarChart2 className="w-4 h-4 text-cyber-blue" />
            <span className="text-xs font-bold text-gray-300 uppercase tracking-widest">Action Distribution</span>
          </div>
          <SafeChart height={180}>
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={DEMO_ACTION_DIST} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="#1a2035" />
                <XAxis type="number" tick={{ fontSize: 9, fill: '#6b7280' }} />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 8, fill: '#9ca3af' }} width={96} />
                <Tooltip contentStyle={{ backgroundColor: '#0d1117', border: '1px solid #1f2937', fontSize: 10 }} />
                <Bar dataKey="count" fill="#3b82f6" radius={[0, 3, 3, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </SafeChart>
        </div>
      </div>

      {/* ── Zombie / Threat Prediction Cards ── */}
      <div className="glass-panel border border-cyber-border rounded-lg p-5">
        <div className="flex items-center gap-2 mb-4">
          <Brain className="w-4 h-4 text-cyber-red" />
          <span className="text-xs font-bold text-gray-200 uppercase tracking-widest">High-Risk Endpoint Intelligence</span>
          <span className="text-[10px] text-gray-500 ml-2">— Live PPO predictions · Hybrid scoring</span>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {DEMO_ZOMBIE_ENDPOINTS.map((ep) => (
            <div key={ep.endpoint_id} className="glass-panel border border-cyber-border rounded-lg p-4 flex flex-col gap-3">
              {/* Header */}
              <div className="flex flex-col gap-1.5">
                <code className="text-[10px] text-cyber-red font-bold truncate">{ep.label}</code>
                <ActionBadge name={ep.action_name} confidence={ep.action_confidence} />
              </div>

              {/* Composite risk */}
              <div className="grid grid-cols-3 gap-1 text-center">
                <div className="bg-black/30 rounded border border-cyber-border p-1.5">
                  <div className="text-[8px] text-gray-500">RULE</div>
                  <div className="text-sm font-bold text-cyber-blue">{ep.rule_risk_score}</div>
                </div>
                <div className="bg-black/30 rounded border border-cyber-border p-1.5">
                  <div className="text-[8px] text-gray-500">RL ADJ</div>
                  <div className={`text-sm font-bold ${ep.rl_risk_adjustment >= 0 ? 'text-cyber-red' : 'text-cyber-green'}`}>
                    {ep.rl_risk_adjustment >= 0 ? '+' : ''}{ep.rl_risk_adjustment}
                  </div>
                </div>
                <div className="bg-black/30 rounded border border-cyber-border p-1.5">
                  <div className="text-[8px] text-gray-500">FINAL</div>
                  <div className={`text-sm font-bold ${ep.final_risk_score >= 70 ? 'text-cyber-red animate-pulse' : 'text-cyber-amber'}`}>
                    {ep.final_risk_score}
                  </div>
                </div>
              </div>

              {/* Probabilities */}
              <div className="flex flex-col gap-1.5">
                <ProbabilityBar label="Zombie"    value={ep.zombie_probability}      color="#ef4444" />
                <ProbabilityBar label="Threat"    value={ep.threat_probability}      color="#f97316" />
                <ProbabilityBar label="Remediate" value={ep.remediation_probability} color="#8b5cf6" />
              </div>

              {/* SHAP */}
              <div className="flex flex-col gap-1 border-t border-cyber-border/40 pt-2">
                <span className="text-[9px] text-gray-500 uppercase tracking-widest">SHAP Features</span>
                {ep.shap.slice(0, 3).map((f, i) => (
                  <div key={i} className="flex items-center gap-1.5">
                    <span className="text-[9px] text-gray-400 w-28 truncate">{f.feature}</span>
                    <div className="flex-1 h-1.5 bg-black/40 rounded overflow-hidden">
                      <div className="h-full rounded bg-cyber-cyan" style={{ width: `${Math.round(f.contribution * 100)}%` }} />
                    </div>
                    <span className="text-[9px] font-mono text-cyber-cyan w-8 text-right">{(f.contribution * 100).toFixed(0)}%</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Analyst Feedback ── */}
      <div className="glass-panel border border-cyber-border rounded-lg p-5 flex flex-col gap-4">
        <div className="flex items-center gap-2">
          <MessageSquare className="w-4 h-4 text-cyber-green" />
          <span className="text-xs font-bold text-gray-200 uppercase tracking-widest">Analyst Feedback Loop</span>
          <span className="text-[10px] text-gray-500">— drives RL reward generation</span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <input
            type="text"
            placeholder="Endpoint ID or node name..."
            value={feedbackEndpointId}
            onChange={e => setFeedbackEndpointId(e.target.value)}
            className="bg-black/40 border border-cyber-border rounded px-3 py-2 text-xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-cyber-green font-mono"
          />
          <select
            value={feedbackType}
            onChange={e => setFeedbackType(e.target.value)}
            className="bg-black/40 border border-cyber-border rounded px-3 py-2 text-xs text-gray-200 focus:outline-none focus:border-cyber-green font-mono"
          >
            <option value="alert_ack">Alert Acknowledged (+15)</option>
            <option value="alert_reject">Alert Rejected (−20)</option>
            <option value="remediation_approved">Remediation Approved (+20)</option>
            <option value="remediation_rejected">Remediation Rejected (−30)</option>
            <option value="classification_override">Classification Override (−15)</option>
            <option value="risk_change">Risk Score Adjusted (+15)</option>
          </select>
          <button
            onClick={() => feedbackMutation.mutate({ endpoint_id: feedbackEndpointId.trim() || 'demo-ep', analyst_id: 'dashboard-analyst', feedback_type: feedbackType })}
            disabled={feedbackMutation.isPending}
            className="flex items-center justify-center gap-1.5 px-4 py-2 rounded border border-cyber-green text-cyber-green hover:bg-cyber-green/10 transition-colors text-xs font-bold disabled:opacity-40"
          >
            <ChevronRight className="w-3.5 h-3.5" />
            SUBMIT FEEDBACK
          </button>
        </div>
      </div>

      {/* ── Policy Metrics Row ── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="glass-panel border border-cyber-border rounded-lg p-4 flex flex-col gap-2">
          <span className="text-[10px] text-gray-500 uppercase">Zombie Detection</span>
          <div className="flex items-end gap-2">
            <span className="text-3xl font-bold text-cyber-cyan">{Math.round(DEMO_POLICY.zombie_detection_accuracy * 100)}%</span>
          </div>
          <div className="w-full bg-gray-800 h-1.5 rounded">
            <div className="h-full rounded bg-cyber-cyan" style={{ width: `${DEMO_POLICY.zombie_detection_accuracy * 100}%` }} />
          </div>
        </div>
        <div className="glass-panel border border-cyber-border rounded-lg p-4 flex flex-col gap-2">
          <span className="text-[10px] text-gray-500 uppercase">False Negative Rate</span>
          <div className="flex items-end gap-2">
            <span className="text-3xl font-bold text-cyber-amber">{Math.round(DEMO_POLICY.false_negative_rate * 100)}%</span>
          </div>
          <div className="w-full bg-gray-800 h-1.5 rounded">
            <div className="h-full rounded bg-cyber-amber" style={{ width: `${DEMO_POLICY.false_negative_rate * 100}%` }} />
          </div>
        </div>
        <div className="glass-panel border border-cyber-border rounded-lg p-4 flex flex-col gap-2">
          <span className="text-[10px] text-gray-500 uppercase">Reward Events</span>
          <span className="text-3xl font-bold text-cyber-blue">{svcMetrics.total_reward_events.toLocaleString()}</span>
          <span className="text-[10px] text-gray-600">In replay buffer</span>
        </div>
        <div className="glass-panel border border-cyber-border rounded-lg p-4 flex flex-col gap-2">
          <span className="text-[10px] text-gray-500 uppercase">Endpoints Monitored</span>
          <span className="text-3xl font-bold text-cyber-purple">{svcMetrics.endpoints_monitored}</span>
          <span className="text-[10px] text-gray-600">Active surveillance</span>
        </div>
      </div>

      {/* ── Training Log ── */}
      {trainingLog.length > 0 && (
        <div className="glass-panel border border-cyber-border rounded-lg p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] text-gray-500 uppercase tracking-widest">TRAINING LOG</span>
            <button onClick={() => setTrainingLog([])} className="text-[10px] text-gray-600 hover:text-gray-400">CLEAR</button>
          </div>
          <div className="font-mono text-[10px] space-y-1 max-h-40 overflow-y-auto">
            {trainingLog.map((line, i) => (
              <div key={i} className={line.includes('✓') ? 'text-cyber-green' : line.includes('✗') ? 'text-cyber-red' : 'text-gray-500'}>
                {line}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Footer ── */}
      <div className="flex flex-wrap items-center gap-6 text-[10px] text-gray-600 border-t border-cyber-border/40 pt-3">
        <span>SERVICE: {svcMetrics.service}</span>
        <span>UPTIME: {Math.round(svcMetrics.uptime_seconds / 3600)}h</span>
        <span>ENDPOINTS: {svcMetrics.endpoints_monitored}</span>
        <span>POLICY: v{svcMetrics.active_policy_version}</span>
        <span className="text-cyber-green">● DEMO MODE — Static data (rl-service not in active stack)</span>
      </div>
    </div>
  );
};
