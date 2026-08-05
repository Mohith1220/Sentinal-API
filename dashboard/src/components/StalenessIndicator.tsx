import React, { useState, useEffect } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface StalenessIndicatorProps {
  lastRefreshedAt: number;
  threshold?: number; // in milliseconds, default 60000 (60 seconds)
}

export const StalenessIndicator: React.FC<StalenessIndicatorProps> = ({
  lastRefreshedAt,
  threshold = 60000,
}) => {
  const [isStale, setIsStale] = useState(false);
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    const checkStaleness = () => {
      const now = Date.now();
      const timeSinceRefresh = now - lastRefreshedAt;
      setIsStale(timeSinceRefresh > threshold);
      setSeconds(Math.floor(timeSinceRefresh / 1000));
    };

    checkStaleness();
    const interval = setInterval(checkStaleness, 1000);
    return () => clearInterval(interval);
  }, [lastRefreshedAt, threshold]);

  if (!isStale) {
    return null;
  }

  return (
    <div
      data-testid="staleness-banner"
      className="mb-6 p-4 rounded-lg bg-cyber-amber/10 border-l-4 border-l-cyber-amber border border-cyber-amber/25 text-cyber-amber flex items-center justify-between font-mono text-xs animate-pulse shadow-[0_0_15px_rgba(249,115,22,0.05)]"
    >
      <div className="flex items-center gap-3">
        <AlertTriangle className="w-5 h-5 shrink-0 text-cyber-amber" />
        <div>
          <strong className="tracking-wider">ALERT: TELEMETRY FEED OUT OF SYNC</strong>
          <div className="text-[10px] text-gray-400 mt-0.5 font-sans leading-normal">
            Central gateway caching pipeline has not reported metrics in the last {seconds} seconds.
          </div>
        </div>
      </div>
      <button
        onClick={() => window.location.reload()}
        className="px-2.5 py-1.5 rounded bg-cyber-amber/20 hover:bg-cyber-amber/40 border border-cyber-amber/35 hover:border-cyber-amber text-[10px] font-bold flex items-center gap-1.5 transition-colors cursor-pointer text-cyber-amber hover:text-white"
      >
        <RefreshCw className="w-3.5 h-3.5" />
        <span>RE-ESTABLISH FEED</span>
      </button>
    </div>
  );
};
