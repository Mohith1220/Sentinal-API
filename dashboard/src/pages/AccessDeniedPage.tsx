import React from 'react';
import { useNavigate } from 'react-router-dom';
import { ShieldAlert, ArrowLeft, LifeBuoy } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

export const AccessDeniedPage: React.FC = () => {
  const navigate = useNavigate();
  const { role } = useAuth();

  return (
    <div className="min-h-screen flex items-center justify-center bg-cyber-bg px-6 relative font-mono scanlines">
      {/* Visual warning backdrop */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-96 h-96 rounded-full bg-cyber-red/5 blur-3xl" />

      {/* Main Container */}
      <div className="w-full max-w-lg glass-panel border border-cyber-red/35 p-8 relative flex flex-col items-center text-center shadow-[0_0_50px_rgba(239,68,68,0.15)] z-10">
        
        {/* Flashing shield indicator */}
        <div className="w-16 h-16 rounded-full bg-cyber-red/10 border border-cyber-red flex items-center justify-center mb-6 threat-pulse-red">
          <ShieldAlert className="w-9 h-9 text-cyber-red" />
        </div>

        {/* Alarm Headers */}
        <h1 className="text-xl md:text-2xl font-bold tracking-widest text-cyber-red uppercase mb-2">
          SECURITY BOUNDARY VIOLATION
        </h1>
        <div className="bg-cyber-red/15 text-cyber-red border border-cyber-red/30 px-3 py-1 rounded text-xs font-bold tracking-wider mb-6">
          STATUS: CLEARANCE LEVEL INSIGNIFICANT
        </div>

        {/* Troubleshooting Text */}
        <p className="text-gray-300 text-xs leading-relaxed mb-6">
          The requested system node requires higher SOC authorization credentials than your current account clearance level holds. All authorization violations are automatically logged to the SentinelAPI central immutable audit trail for security compliance.
        </p>

        {/* Account Details Box */}
        <div className="w-full bg-black/40 rounded-lg p-4 border border-cyber-border mb-8 text-left text-xs flex flex-col gap-2">
          <div className="flex justify-between">
            <span className="text-gray-500">YOUR_ROLE:</span>
            <span className="text-cyber-purple font-semibold uppercase">{role || 'UNKNOWN'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">TERMINAL_IP:</span>
            <span className="text-cyber-cyan">10.14.82.119</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-500">AUDIT_LOG_HASH:</span>
            <span className="text-gray-400 font-bold tracking-tighter">SEC_FAIL_X28A1923</span>
          </div>
        </div>

        {/* Actions panel */}
        <div className="w-full flex flex-col sm:flex-row gap-3">
          <button
            onClick={() => navigate('/')}
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded border border-cyber-border hover:border-cyber-cyan/50 hover:bg-white/5 text-gray-300 hover:text-cyber-cyan transition-colors text-xs font-bold cursor-pointer"
          >
            <ArrowLeft className="w-4 h-4" />
            <span>RETURN TO DECK</span>
          </button>
          
          <a
            href="mailto:soc-admin@sentinelapi.ai"
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded bg-cyber-red/15 hover:bg-cyber-red/35 border border-cyber-red/40 hover:border-cyber-red text-cyber-red hover:text-white transition-all text-xs font-bold"
          >
            <LifeBuoy className="w-4 h-4" />
            <span>REQUEST CLEARANCE</span>
          </a>
        </div>
      </div>
    </div>
  );
};
