import React, { useState } from 'react';
import type { AuditLog } from '../types/api';
import { Search, Eye, Filter, Terminal, Copy } from 'lucide-react';

interface AuditLogViewerProps {
  logs: AuditLog[];
}

export const AuditLogViewer: React.FC<AuditLogViewerProps> = ({ logs }) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [filterType, setFilterType] = useState('');
  const [expandedLogId, setExpandedLogId] = useState<string | null>(null);

  // Filter logs based on inputs
  const filteredLogs = logs.filter(log => {
    const matchesSearch =
      log.action.toLowerCase().includes(searchTerm.toLowerCase()) ||
      log.user_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      log.ip_address.toLowerCase().includes(searchTerm.toLowerCase()) ||
      log.resource_id.toLowerCase().includes(searchTerm.toLowerCase());
    
    const matchesType = filterType ? log.resource_type === filterType : true;

    return matchesSearch && matchesType;
  });

  const getActionColor = (action: string) => {
    const lower = action.toLowerCase();
    if (lower.includes('delete') || lower.includes('decommission') || lower.includes('revoke')) return 'text-cyber-red';
    if (lower.includes('update') || lower.includes('override') || lower.includes('tune')) return 'text-cyber-amber';
    if (lower.includes('create') || lower.includes('resolve') || lower.includes('approve')) return 'text-cyber-green';
    return 'text-cyber-blue';
  };

  const getResourceTypeBadge = (type: string) => {
    switch (type) {
      case 'ENDPOINT': return 'bg-cyber-blue/10 text-cyber-blue border-cyber-blue/20';
      case 'ALERT': return 'bg-cyber-red/10 text-cyber-red border-cyber-red/20';
      case 'ML_CONFIGURATION': return 'bg-cyber-purple/10 text-cyber-purple border-cyber-purple/20';
      case 'USER': return 'bg-cyber-green/10 text-cyber-green border-cyber-green/20';
      default: return 'bg-gray-800 text-gray-400 border-gray-700';
    }
  };

  return (
    <div className="flex flex-col gap-4 font-mono text-xs">
      {/* SEARCH AND FILTERS TOOLBAR */}
      <div className="glass-panel border border-cyber-border p-4 flex flex-col md:flex-row gap-3 items-center justify-between">
        <div className="relative w-full md:w-80">
          <Search className="absolute left-3 top-2.5 w-4 h-4 text-cyber-cyan" />
          <input
            type="text"
            placeholder="Search audit trail by user, action, IP..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full bg-black/30 border border-cyber-border rounded pl-9 pr-4 py-2 text-xs text-gray-200 focus:outline-none focus:border-cyber-cyan placeholder-gray-600"
          />
        </div>

        <div className="flex items-center gap-3 w-full md:w-auto">
          <div className="flex items-center gap-2 shrink-0 text-gray-500">
            <Filter className="w-4 h-4 text-cyber-cyan" />
            <span>RESOURCE_TYPE:</span>
          </div>
          <select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            className="flex-1 md:w-48 bg-black/30 border border-cyber-border rounded px-2.5 py-1.5 text-xs text-gray-300 focus:outline-none focus:border-cyber-cyan"
          >
            <option value="">ALL RESOURCES</option>
            <option value="ENDPOINT">API ENDPOINTS</option>
            <option value="ALERT">SECURITY ALERTS</option>
            <option value="ML_CONFIGURATION">ML CORE CONFIG</option>
            <option value="USER">USER ACCOUNTS</option>
            <option value="KAFKA_STREAM">KAFKA INTEGRATIONS</option>
          </select>
        </div>
      </div>

      {/* LOG GRID */}
      <div className="glass-panel border border-cyber-border overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-black/30 border-b border-cyber-border">
                <th className="p-3 text-[10px] text-gray-500 font-bold tracking-wider">TIMESTAMP</th>
                <th className="p-3 text-[10px] text-gray-500 font-bold tracking-wider">OPERATOR ID</th>
                <th className="p-3 text-[10px] text-gray-500 font-bold tracking-wider">ACTION PERFORMED</th>
                <th className="p-3 text-[10px] text-gray-500 font-bold tracking-wider">RESOURCE</th>
                <th className="p-3 text-[10px] text-gray-500 font-bold tracking-wider">TERMINAL IP</th>
                <th className="p-3 text-[10px] text-gray-500 font-bold tracking-wider text-center">PAYLOAD</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-cyber-border/40 bg-cyber-panel/10">
              {filteredLogs.length === 0 ? (
                <tr>
                  <td colSpan={6} className="p-8 text-center text-gray-500 italic">
                    No compliant log events recorded in historical audit buffer
                  </td>
                </tr>
              ) : (
                filteredLogs.map((log) => {
                  const isExpanded = expandedLogId === log.id;
                  return (
                    <React.Fragment key={log.id}>
                      <tr className={`hover:bg-white/5 transition-colors ${isExpanded ? 'bg-cyber-cyan/5' : ''}`}>
                        <td className="p-3 text-gray-400 font-mono text-[11px] whitespace-nowrap">
                          {new Date(log.timestamp).toLocaleString()}
                        </td>
                        <td className="p-3 text-cyber-purple font-semibold">{log.user_id}</td>
                        <td className={`p-3 font-bold ${getActionColor(log.action)}`}>
                          {log.action.toUpperCase()}
                        </td>
                        <td className="p-3">
                          <span className={`px-2 py-0.5 rounded text-[9px] font-bold uppercase border ${getResourceTypeBadge(log.resource_type)}`}>
                            {log.resource_type}
                          </span>
                        </td>
                        <td className="p-3 text-cyber-cyan font-mono">{log.ip_address}</td>
                        <td className="p-3 text-center">
                          <button
                            onClick={() => setExpandedLogId(isExpanded ? null : log.id)}
                            className="p-1 rounded border border-cyber-border hover:border-cyber-cyan hover:bg-cyber-cyan/10 text-gray-400 hover:text-cyber-cyan transition-all cursor-pointer"
                            title="Inspect Diff Payload"
                          >
                            <Eye className="w-3.5 h-3.5" />
                          </button>
                        </td>
                      </tr>

                      {/* Expanded Payload row */}
                      {isExpanded && (
                        <tr>
                          <td colSpan={6} className="p-4 bg-black/40 border-y border-cyber-border">
                            <div className="flex flex-col gap-2">
                              <div className="flex justify-between items-center text-[10px] text-gray-500 pb-1.5 border-b border-cyber-border/40">
                                <span className="flex items-center gap-1.5 text-cyber-cyan">
                                  <Terminal className="w-3.5 h-3.5" />
                                  <span>LOG_PAYLOAD_DIAGNOSTICS - UUID: {log.id}</span>
                                </span>
                                <button
                                  onClick={() => navigator.clipboard.writeText(JSON.stringify(log.changes, null, 2))}
                                  className="flex items-center gap-1 hover:text-white cursor-pointer"
                                >
                                  <Copy className="w-3 h-3" />
                                  <span>COPY RAW JSON</span>
                                </button>
                              </div>
                              <pre className="p-3 rounded bg-cyber-bg border border-cyber-border/70 text-cyber-cyan text-[11px] overflow-x-auto leading-relaxed max-h-56">
                                {JSON.stringify(log.changes, null, 2)}
                              </pre>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
