import React from 'react';
import { HeatmapPanel } from '../components/HeatmapPanel';
import { ShieldCheck, Sliders, AlertTriangle } from 'lucide-react';

export const RiskHeatmapView: React.FC = () => {
  return (
    <div className="flex flex-col gap-6 font-mono text-xs select-none">
      
      {/* Header */}
      <div className="glass-panel border border-cyber-border p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded bg-cyber-purple/10 border border-cyber-purple/35 flex items-center justify-center">
            <Sliders className="w-5 h-5 text-cyber-purple animate-pulse" />
          </div>
          <div>
            <h2 className="font-bold text-gray-200 text-sm tracking-wider uppercase">REGULATORY_EXPOSURE_HEAT_MATRIX</h2>
            <div className="text-[10px] text-gray-400 mt-0.5">
              Visualizing data sensitivity clusters against endpoint lifecycle statuses to pinpoint governance hot zones.
            </div>
          </div>
        </div>
      </div>

      {/* Main Heatmap Container */}
      <div className="glass-panel border border-cyber-border p-5 flex flex-col gap-4">
        <div className="flex items-center justify-between border-b border-cyber-border/40 pb-2">
          <span className="text-[10px] text-gray-500 font-bold">MULTI-DIMENSIONAL CLUSTERING HEATMAP</span>
          <span className="text-[9px] text-gray-500">Hover over active nodes to audit compliance score matrices</span>
        </div>

        <HeatmapPanel />
      </div>

      {/* Audit Explanations */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="glass-panel border border-cyber-border p-4 flex flex-col gap-2 bg-cyber-panel/10">
          <span className="font-bold text-gray-200 flex items-center gap-1.5 text-cyber-cyan border-b border-cyber-border/30 pb-1.5">
            <ShieldCheck className="w-4 h-4 text-cyber-cyan" />
            <span>HOW TO ANALYZE HIGH-SENSITIVITY NODES</span>
          </span>
          <p className="text-gray-400 leading-relaxed font-sans text-[11px] pt-1">
            The X-axis indicates data sensitivity classifications (Public to PII/Financial core systems). The Y-axis captures endpoint lifecycle state classifications. Glowing crimson/yellow intersection blocks represent extreme risk hotspots. Endpoints mapped into these blocks are targets for immediate security containment protocols (patch application or deprecation).
          </p>
        </div>

        <div className="glass-panel border border-cyber-border p-4 flex flex-col gap-2 bg-cyber-panel/10">
          <span className="font-bold text-gray-200 flex items-center gap-1.5 text-cyber-amber border-b border-cyber-border/30 pb-1.5">
            <AlertTriangle className="w-4 h-4 text-cyber-amber" />
            <span>ML GOVERNANCE ACTION TRIGGER BASES</span>
          </span>
          <p className="text-gray-400 leading-relaxed font-sans text-[11px] pt-1">
            Nodes falling under <strong className="text-cyber-red">Zombie / PII</strong> or <strong className="text-cyber-red">Zombie / Financial</strong> classifications instantly generate critical priority tickets in the Remediation Center. Ensure appropriate authentication tokens are provisioned before auditing sensitive sectors.
          </p>
        </div>
      </div>

    </div>
  );
};
