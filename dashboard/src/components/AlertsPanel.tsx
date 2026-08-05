import React, { useEffect, useState, useRef } from 'react';
import { getAlertsWebSocketUrl } from '../lib/api';
import { useAlertStore } from '../lib/store';
import { useAuth } from '../contexts/AuthContext';
import { Permission } from '../types/api';
import { Radio, ShieldCheck } from 'lucide-react';
import type { AnomalyAlert } from '../types/api';

export const AlertsPanel: React.FC = () => {
  const { alerts, addAlert, resolveAlert } = useAlertStore();
  const { hasPermission } = useAuth();
  const [connectionStatus, setConnectionStatus] = useState<'connecting' | 'connected' | 'disconnected'>('connecting');
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<any>(null);
  const reconnectAttemptsRef = useRef(0);

  const activeRef = useRef(true);

  const connectWebSocket = () => {
    if (!activeRef.current) return;
    try {
      const ws = new WebSocket(getAlertsWebSocketUrl());
      wsRef.current = ws;

      ws.onopen = () => {
        if (!activeRef.current) {
          ws.close();
          return;
        }
        console.log('WebSocket connected');
        setConnectionStatus('connected');
        reconnectAttemptsRef.current = 0;
      };

      ws.onmessage = (event) => {
        if (!activeRef.current) return;
        try {
          const alert: AnomalyAlert = JSON.parse(event.data);
          addAlert(alert);
        } catch (error) {
          console.error('Error parsing alert message:', error);
        }
      };

      ws.onerror = (error) => {
        if (!activeRef.current) return;
        console.error('WebSocket error:', error);
        setConnectionStatus('disconnected');
      };

      ws.onclose = () => {
        if (!activeRef.current) return;
        console.log('WebSocket disconnected');
        setConnectionStatus('disconnected');
        wsRef.current = null;

        // Attempt to reconnect with exponential backoff
        const delay = Math.min(1000 * Math.pow(2, reconnectAttemptsRef.current), 30000);
        reconnectAttemptsRef.current += 1;

        reconnectTimeoutRef.current = setTimeout(() => {
          if (activeRef.current) {
            console.log(`Attempting to reconnect (attempt ${reconnectAttemptsRef.current})...`);
            connectWebSocket();
          }
        }, delay);
      };
    } catch (error) {
      if (!activeRef.current) return;
      console.error('Error creating WebSocket:', error);
      setConnectionStatus('disconnected');
    }
  };

  useEffect(() => {
    activeRef.current = true;

    // Delay websocket initiation slightly to allow Strict Mode to unmount cleanly first
    const delayTimeout = setTimeout(() => {
      if (activeRef.current) {
        connectWebSocket();
      }
    }, 100);

    return () => {
      activeRef.current = false;
      if (delayTimeout) clearTimeout(delayTimeout);
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (wsRef.current) {
        // If connecting, suppress native browser console warnings by clearing onclose and closing quietly
        if (wsRef.current.readyState === WebSocket.CONNECTING) {
          wsRef.current.onclose = null;
        }
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, []);

  const getSeverityStyles = (sigma: number) => {
    if (sigma >= 5) return 'text-cyber-red border-cyber-red/30 bg-cyber-red/10 threat-pulse-red';
    if (sigma >= 4) return 'text-cyber-amber border-cyber-amber/20 bg-cyber-amber/10';
    if (sigma >= 3) return 'text-cyber-yellow border-cyber-yellow/20 bg-cyber-yellow/10';
    return 'text-cyber-green border-cyber-green/20 bg-cyber-green/10';
  };

  const getSeverityDot = (sigma: number) => {
    if (sigma >= 5) return 'bg-cyber-red animate-ping';
    if (sigma >= 4) return 'bg-cyber-amber animate-pulse';
    if (sigma >= 3) return 'bg-cyber-yellow';
    return 'bg-cyber-green';
  };

  const getSeverityLabel = (sigma: number) => {
    if (sigma >= 5) return 'CRITICAL THREAT';
    if (sigma >= 4) return 'HIGH WARNING';
    if (sigma >= 3) return 'MEDIUM STRESS';
    return 'LOW VARIATION';
  };

  const formatTimestamp = (timestamp: string): string => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString();
  };

  return (
    <div className="flex flex-col h-[550px] border border-cyber-border rounded-lg overflow-hidden bg-black/20 font-mono text-xs select-none">
      {/* Header Info */}
      <div className="h-14 border-b border-cyber-border flex items-center justify-between px-4 bg-cyber-panel/60">
        <div className="flex items-center gap-2">
          <Radio className="w-4 h-4 text-cyber-cyan animate-pulse" />
          <span className="font-bold text-gray-200 uppercase tracking-widest text-xs">LIVE_ALERTS_STREAM</span>
        </div>

        {/* Connection status pill */}
        <div className="flex items-center gap-1.5 px-2 py-0.5 rounded border border-cyber-border bg-black/20 text-[10px]">
          <span className={`w-1.5 h-1.5 rounded-full ${
            connectionStatus === 'connected' ? 'bg-cyber-green animate-pulse' :
            connectionStatus === 'connecting' ? 'bg-cyber-yellow animate-ping' : 'bg-cyber-red'
          }`} />
          <span className="text-gray-400 capitalize">{connectionStatus}</span>
        </div>
      </div>

      {/* Main Alerts List */}
      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3">
        {alerts.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center text-center text-gray-500 gap-2">
            <ShieldCheck className="w-10 h-10 text-cyber-green animate-bounce" />
            <div>
              <p className="font-bold text-gray-300">NO ANOMALIES LOGGED</p>
              <p className="text-[10px] text-gray-500 max-w-[200px] mt-1 mx-auto leading-normal font-sans">
                Real-time Kafka anomaly feeds will appear here as transaction logs parse.
              </p>
            </div>
          </div>
        ) : (
          alerts.map((alert) => (
            <div key={alert.id} className="glass-panel border border-cyber-border hover:border-cyber-border-hover overflow-hidden transition-all">
              
              {/* Card top */}
              <div className="p-2.5 bg-black/30 border-b border-cyber-border/40 flex items-center justify-between text-[10px]">
                <div className="flex items-center gap-1.5">
                  <span className={`w-2 h-2 rounded-full ${getSeverityDot(alert.deviation_sigma)}`} />
                  <span className={`px-1.5 py-0.5 rounded font-bold border text-[9px] ${getSeverityStyles(alert.deviation_sigma)}`}>
                    {getSeverityLabel(alert.deviation_sigma)}
                  </span>
                </div>
                <span className="text-gray-500">{formatTimestamp(alert.emitted_at)}</span>
              </div>

              {/* Card body */}
              <div className="p-3 flex flex-col gap-2">
                <div className="flex justify-between items-center">
                  <span className="text-gray-200 font-bold uppercase tracking-wide text-[11px]">{alert.anomaly_type.replace('_', ' ')}</span>
                  <span className="text-cyber-cyan text-[10px]">{alert.deviation_sigma.toFixed(2)}σ DEV</span>
                </div>

                <div className="bg-black/30 rounded border border-cyber-border p-2 grid grid-cols-3 gap-2 text-[10px]">
                  <div className="flex flex-col">
                    <span className="text-gray-500">OBSERVED:</span>
                    <span className="text-gray-300 font-bold">{alert.observed_value.toFixed(1)}</span>
                  </div>
                  <div className="flex flex-col">
                    <span className="text-gray-500">BASELINE:</span>
                    <span className="text-gray-400">{alert.baseline_value.toFixed(1)}</span>
                  </div>
                  <div className="flex flex-col">
                    <span className="text-gray-500">DEVIATION:</span>
                    <span className="text-cyber-red font-bold">+{Math.abs(alert.observed_value - alert.baseline_value).toFixed(1)}</span>
                  </div>
                </div>

                {alert.feature_importance && alert.feature_importance.length > 0 && (
                  <div className="flex flex-col gap-1 border-t border-cyber-border/30 pt-1.5">
                    <span className="text-gray-500 text-[9px]">CONTRIBUTING_TRANSACTION_FEATURES:</span>
                    <div className="flex flex-col gap-1 text-[10px]">
                      {alert.feature_importance.slice(0, 2).map((feat, idx) => (
                        <div key={idx} className="flex justify-between text-gray-400">
                          <span>• {feat.feature}</span>
                          <span className="text-cyber-blue font-bold">{(feat.contribution * 100).toFixed(1)}%</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div className="flex justify-between items-center border-t border-cyber-border/30 pt-2 text-[10px]">
                  <code className="text-cyber-cyan font-bold truncate max-w-[180px]">EP: {alert.endpoint_id}</code>
                  {hasPermission(Permission.RESOLVE_ALERT) ? (
                    <button
                      onClick={() => resolveAlert(alert.id)}
                      className="text-cyber-green font-bold hover:underline cursor-pointer"
                    >
                      [DISMISS]
                    </button>
                  ) : (
                    <span className="text-gray-600 italic">Viewer ReadOnly</span>
                  )}
                </div>

              </div>

            </div>
          ))
        )}
      </div>
    </div>
  );
};
