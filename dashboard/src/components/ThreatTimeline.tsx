import React from 'react';
import { AlertOctagon, UserCheck, Flame, Radio, Clock } from 'lucide-react';

export interface TimelineEvent {
  id: string;
  timestamp: string;
  type: 'discovery' | 'anomaly' | 'audit' | 'vulnerability' | 'remediation';
  title: string;
  description: string;
  severity: 'Critical' | 'High' | 'Medium' | 'Low' | 'Info';
  operator?: string;
}

interface ThreatTimelineProps {
  events: TimelineEvent[];
}

export const ThreatTimeline: React.FC<ThreatTimelineProps> = ({ events }) => {
  const getEventIcon = (type: TimelineEvent['type']) => {
    switch (type) {
      case 'discovery': return <Radio className="w-4 h-4 text-cyber-green" />;
      case 'anomaly': return <Flame className="w-4 h-4 text-cyber-red" />;
      case 'audit': return <Clock className="w-4 h-4 text-cyber-blue" />;
      case 'vulnerability': return <AlertOctagon className="w-4 h-4 text-cyber-amber" />;
      case 'remediation': return <UserCheck className="w-4 h-4 text-cyber-purple" />;
    }
  };

  const getSeverityStyles = (severity: TimelineEvent['severity']) => {
    switch (severity) {
      case 'Critical': return 'text-cyber-red border-cyber-red/30 bg-cyber-red/10';
      case 'High': return 'text-cyber-amber border-cyber-amber/20 bg-cyber-amber/10';
      case 'Medium': return 'text-cyber-yellow border-cyber-yellow/20 bg-cyber-yellow/10';
      case 'Low': return 'text-cyber-green border-cyber-green/20 bg-cyber-green/10';
      default: return 'text-gray-400 border-cyber-border bg-black/30';
    }
  };

  return (
    <div className="font-mono text-xs relative select-none">
      {events.length === 0 ? (
        <div className="text-center text-gray-500 italic p-6 border border-cyber-border rounded-lg bg-black/20">
          No security events or anomalies captured in timeline.
        </div>
      ) : (
        <div className="relative border-l border-cyber-border pl-6 ml-4 flex flex-col gap-6">
          {events.map((event) => (
            <div key={event.id} className="relative group">
              {/* Floating icon bullet */}
              <div className="absolute -left-10 top-0.5 w-8 h-8 rounded-full bg-cyber-panel border border-cyber-border flex items-center justify-center transition-all group-hover:border-cyber-cyan/50 shadow-[0_0_10px_rgba(0,0,0,0.5)] z-10">
                {getEventIcon(event.type)}
              </div>

              {/* Event card content */}
              <div className="glass-panel border border-cyber-border hover:border-cyber-border-hover p-4 flex flex-col gap-2 transition-all">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-gray-200 text-xs tracking-wider">{event.title}</span>
                    <span className={`px-2 py-0.5 rounded text-[9px] font-bold uppercase border ${getSeverityStyles(event.severity)}`}>
                      {event.severity}
                    </span>
                  </div>
                  <span className="text-[10px] text-gray-500">{new Date(event.timestamp).toLocaleString()}</span>
                </div>

                <p className="text-gray-400 text-[11px] leading-relaxed font-sans">{event.description}</p>

                {event.operator && (
                  <div className="flex items-center gap-1.5 text-[10px] text-cyber-cyan mt-1 border-t border-cyber-border/40 pt-1.5">
                    <span className="text-gray-500">OPERATOR_ID:</span>
                    <span>{event.operator}</span>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
