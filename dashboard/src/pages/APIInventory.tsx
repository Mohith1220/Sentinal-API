import React, { useState } from 'react';
import { APIDataTable } from '../components/APIDataTable';
import { NodeDetailsPanel } from '../components/NodeDetailsPanel';
import { Database } from 'lucide-react';

export const APIInventory: React.FC = () => {
  const [selectedEndpointId, setSelectedEndpointId] = useState<string | null>(null);

  return (
    <div className="flex flex-col gap-6 font-mono text-xs select-none">
      
      {/* Header Panel */}
      <div className="glass-panel border border-cyber-border p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded bg-cyber-blue/15 border border-cyber-blue/35 flex items-center justify-center">
            <Database className="w-5 h-5 text-cyber-blue" />
          </div>
          <div>
            <h2 className="font-bold text-gray-200 text-sm tracking-wider uppercase">INVENTORIED_API_CONTROL_DECK</h2>
            <div className="text-[10px] text-gray-400 mt-0.5">
              Querying active gateway caches, security schemas, and lifecycle states in real-time.
            </div>
          </div>
        </div>
      </div>

      {/* Primary High Density Datatable */}
      <div className="glass-panel border border-cyber-border p-5 flex flex-col gap-4">
        <APIDataTable
          onRowSelect={(id) => setSelectedEndpointId(id)}
          selectedEndpointId={selectedEndpointId}
        />
      </div>

      {/* Expanded Details Slide Drawer */}
      {selectedEndpointId && (
        <NodeDetailsPanel
          nodeId={selectedEndpointId}
          onClose={() => setSelectedEndpointId(null)}
        />
      )}
    </div>
  );
};
