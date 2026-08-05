/**
 * RiskHeatmap — cyberpunk-styled risk distribution bar chart.
 * Uses explicit pixel heights on ResponsiveContainer to avoid the
 * Recharts width(-1)/height(-1) warning that fires when the container
 * hasn't been painted yet.
 */
import React from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell, LabelList,
} from 'recharts';
import { useQuery } from '@tanstack/react-query';
import { endpointsApi } from '../lib/api';

const DEMO_BUCKETS = [
  { range: 'LOW  0-33',    count: 12, color: '#10b981' },
  { range: 'MED  34-66',   count: 8,  color: '#f97316' },
  { range: 'HIGH  67-100', count: 5,  color: '#ef4444' },
];

export const RiskHeatmap: React.FC = () => {
  const { data: endpoints, isLoading } = useQuery({
    queryKey: ['endpoints-risk-heatmap'],
    queryFn: () => endpointsApi.getEndpoints({ page_size: 1000 }),
    staleTime: 60_000,
  });

  const buckets = React.useMemo(() => {
    if (!endpoints?.items?.length) return DEMO_BUCKETS;
    const low  = endpoints.items.filter(e => e.risk_score <= 33).length;
    const med  = endpoints.items.filter(e => e.risk_score > 33 && e.risk_score <= 66).length;
    const high = endpoints.items.filter(e => e.risk_score > 66).length;
    return [
      { range: 'LOW  0-33',    count: low,  color: '#10b981' },
      { range: 'MED  34-66',   count: med,  color: '#f97316' },
      { range: 'HIGH  67-100', count: high, color: '#ef4444' },
    ];
  }, [endpoints]);

  const total = buckets.reduce((s, b) => s + b.count, 0) || 1;

  return (
    <div className="flex flex-col gap-4 font-mono text-xs">
      {isLoading && (
        <div className="text-[10px] text-cyber-cyan animate-pulse">
          COMPUTING RISK DISTRIBUTION...
        </div>
      )}

      {/* Bar chart — explicit pixel height avoids the width(-1) warning */}
      <div style={{ width: '100%', height: 220 }}>
        <ResponsiveContainer width="100%" height={220} minWidth={0}>
          <BarChart
            data={buckets}
            margin={{ top: 10, right: 10, left: -20, bottom: 5 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
            <XAxis
              dataKey="range"
              tick={{ fontSize: 9, fill: '#6b7280', fontFamily: 'JetBrains Mono, monospace' }}
              tickLine={false}
              axisLine={{ stroke: 'rgba(255,255,255,0.06)' }}
            />
            <YAxis
              tick={{ fontSize: 9, fill: '#6b7280' }}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#0d1117',
                border: '1px solid rgba(255,255,255,0.1)',
                borderRadius: 6,
                fontSize: 10,
                fontFamily: 'JetBrains Mono, monospace',
              }}
              cursor={{ fill: 'rgba(255,255,255,0.03)' }}
              formatter={(value: number) => [`${value} endpoints`, 'Count']}
            />
            <Bar dataKey="count" radius={[4, 4, 0, 0]} maxBarSize={80}>
              {buckets.map((entry, i) => (
                <Cell key={i} fill={entry.color} fillOpacity={0.85} />
              ))}
              <LabelList
                dataKey="count"
                position="top"
                style={{ fontSize: 10, fill: '#d1d5db', fontFamily: 'monospace' }}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-3">
        {buckets.map((b, i) => (
          <div
            key={i}
            className="glass-panel border border-cyber-border rounded-lg p-3 flex flex-col gap-1 text-center"
            style={{ borderColor: `${b.color}33` }}
          >
            <span
              className="text-3xl font-bold"
              style={{ color: b.color }}
            >
              {b.count}
            </span>
            <span className="text-[9px] text-gray-400 uppercase tracking-widest">
              {b.range}
            </span>
            <div className="w-full bg-black/40 rounded h-1 mt-1">
              <div
                className="h-1 rounded transition-all duration-700"
                style={{
                  width: `${Math.round((b.count / total) * 100)}%`,
                  backgroundColor: b.color,
                }}
              />
            </div>
            <span className="text-[9px]" style={{ color: b.color }}>
              {Math.round((b.count / total) * 100)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
};
