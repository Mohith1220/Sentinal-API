import React, { useState, useEffect, useRef } from 'react';
import { useNavigate, useLocation, Link, Outlet } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useUIStore, useAlertStore } from '../lib/store';
import {
  Shield,
  LayoutDashboard,
  Database,
  Network,
  AlertTriangle,
  Grid,
  Settings,
  Sliders,
  ChevronLeft,
  ChevronRight,
  Search,
  Bell,
  User,
  LogOut,
  Clock,
  Terminal,
  Volume2,
  VolumeX,
  Brain,
} from 'lucide-react';
import { Permission } from '../types/api';

interface SidebarLayoutProps {
  children?: React.ReactNode;
}

export const SidebarLayout: React.FC<SidebarLayoutProps> = ({ children }) => {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout, hasPermission, role } = useAuth();
  const { sidebarCollapsed, toggleSidebar, commandPaletteOpen, setCommandPaletteOpen } = useUIStore();
  const { alerts, resolveAlert } = useAlertStore();

  const [notificationOpen, setNotificationOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [soundEnabled, setSoundEnabled] = useState(false);

  const commandPaletteRef = useRef<HTMLDivElement>(null);
  const notificationRef = useRef<HTMLDivElement>(null);
  const profileRef = useRef<HTMLDivElement>(null);

  // Health Metrics State
  const [healthMetrics, setHealthMetrics] = useState({
    cpu: 24,
    traffic: 342,
    threatLevel: 'STABLE',
  });

  // Handle Global Hotkey (Ctrl+K) for Command Palette
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        setCommandPaletteOpen(!commandPaletteOpen);
      }
      if (e.key === 'Escape') {
        setCommandPaletteOpen(false);
        setNotificationOpen(false);
        setProfileOpen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [commandPaletteOpen, setCommandPaletteOpen]);

  // Click outside listeners
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (commandPaletteOpen && commandPaletteRef.current && !commandPaletteRef.current.contains(target)) {
        setCommandPaletteOpen(false);
      }
      if (notificationOpen && notificationRef.current && !notificationRef.current.contains(target)) {
        setNotificationOpen(false);
      }
      if (profileOpen && profileRef.current && !profileRef.current.contains(target)) {
        setProfileOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [commandPaletteOpen, notificationOpen, profileOpen, setCommandPaletteOpen]);

  // Update health metrics periodically
  useEffect(() => {
    const interval = setInterval(() => {
      setHealthMetrics({
        cpu: Math.floor(Math.random() * 25) + 15,
        traffic: Math.floor(Math.random() * 100) + 300,
        threatLevel: alerts.length > 5 ? 'ELEVATED' : alerts.length > 2 ? 'WARNING' : 'STABLE',
      });
    }, 5000);
    return () => clearInterval(interval);
  }, [alerts]);

  // Play beep sound for critical threats if sound is enabled
  useEffect(() => {
    if (soundEnabled && alerts.length > 0) {
      const latest = alerts[0];
      if (latest.deviation_sigma >= 5) {
        const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
        const oscillator = audioCtx.createOscillator();
        const gainNode = audioCtx.createGain();
        
        oscillator.connect(gainNode);
        gainNode.connect(audioCtx.destination);
        
        oscillator.type = 'sine';
        oscillator.frequency.setValueAtTime(880, audioCtx.currentTime); // A5
        gainNode.gain.setValueAtTime(0.05, audioCtx.currentTime);
        
        oscillator.start();
        oscillator.stop(audioCtx.currentTime + 0.15);
      }
    }
  }, [alerts, soundEnabled]);

  // Filtered command palette items
  const menuItems = [
    { name: 'Overview', path: '/', icon: LayoutDashboard, permission: Permission.VIEW_DASHBOARD },
    { name: 'API Inventory', path: '/inventory', icon: Database, permission: Permission.VIEW_API_INVENTORY },
    { name: 'Dependency Graph', path: '/graph', icon: Network, permission: Permission.VIEW_DEPENDENCY_GRAPH },
    { name: 'Alerts & Anomalies', path: '/alerts', icon: AlertTriangle, permission: Permission.VIEW_ALERTS },
    { name: 'Risk Heatmap', path: '/heatmap', icon: Grid, permission: Permission.VIEW_RISK_HEATMAP },
    { name: 'Remediation Center', path: '/remediation', icon: Sliders, permission: Permission.VIEW_REMEDIATION },
    { name: 'RL Intelligence', path: '/rl', icon: Brain, permission: Permission.VIEW_RISK_HEATMAP },
    { name: 'Administration', path: '/admin', icon: Settings, permission: Permission.VIEW_AUDIT_LOG },
  ];

  const visibleMenuItems = menuItems.filter(item => hasPermission(item.permission));

  const filteredPaletteItems = menuItems.filter(item =>
    item.name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const getThreatBadgeColor = (level: string) => {
    switch (level) {
      case 'ELEVATED': return 'bg-cyber-red/10 text-cyber-red border-cyber-red/30';
      case 'WARNING': return 'bg-cyber-amber/10 text-cyber-amber border-cyber-amber/30';
      default: return 'bg-cyber-green/10 text-cyber-green border-cyber-green/30';
    }
  };

  const activeAlertsCount = alerts.filter(a => !a.resolved_at).length;

  return (
    <div className="flex min-h-screen bg-cyber-bg text-gray-100 overflow-hidden font-sans">
      {/* SIDEBAR */}
      <aside
        className={`glass-panel border-r border-cyber-border transition-all duration-300 z-40 flex flex-col ${
          sidebarCollapsed ? 'w-16' : 'w-64'
        }`}
      >
        {/* Brand/Logo */}
        <div className="h-16 flex items-center gap-3 px-4 border-b border-cyber-border overflow-hidden">
          <div className="w-8 h-8 rounded bg-cyber-cyan/10 border border-cyber-cyan flex items-center justify-center shrink-0">
            <Shield className="w-5 h-5 text-cyber-cyan animate-pulse" />
          </div>
          {!sidebarCollapsed && (
            <div className="flex flex-col">
              <span className="font-mono font-bold tracking-widest text-cyber-cyan text-sm">SENTINEL_API</span>
              <span className="text-[10px] text-gray-400 font-mono tracking-tighter">BANK SECURE v1.4</span>
            </div>
          )}
        </div>

        {/* Dynamic Sidebar Links */}
        <nav className="flex-1 py-4 px-3 flex flex-col gap-1 overflow-y-auto">
          {visibleMenuItems.map((item) => {
            const isActive = location.pathname === item.path;
            const Icon = item.icon;
            return (
              <Link
                key={item.name}
                to={item.path}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-200 group text-sm ${
                  isActive
                    ? 'bg-cyber-cyan/10 border border-cyber-cyan/35 text-cyber-cyan shadow-[0_0_10px_rgba(6,182,212,0.15)] font-medium'
                    : 'border border-transparent text-gray-400 hover:text-gray-200 hover:bg-white/5'
                }`}
              >
                <Icon className={`w-5 h-5 shrink-0 transition-transform group-hover:scale-105 ${
                  isActive ? 'text-cyber-cyan' : 'text-gray-400 group-hover:text-cyber-cyan'
                }`} />
                {!sidebarCollapsed && <span>{item.name}</span>}
              </Link>
            );
          })}
        </nav>

        {/* System Health Summary Panel */}
        {!sidebarCollapsed && (
          <div className="p-4 mx-3 mb-3 rounded-lg border border-cyber-border bg-black/30 flex flex-col gap-2.5 text-xs font-mono">
            <div className="flex items-center justify-between">
              <span className="text-gray-500">THREAT_PULSE:</span>
              <span className={`px-1.5 py-0.5 rounded border text-[10px] tracking-wide animate-pulse ${getThreatBadgeColor(healthMetrics.threatLevel)}`}>
                ● {healthMetrics.threatLevel}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-gray-500">KAFKA_INGEST:</span>
              <span className="text-cyber-cyan">{healthMetrics.traffic} API/s</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-gray-500">SYSTEM_CPU:</span>
              <div className="w-16 bg-gray-800 h-1.5 rounded-full overflow-hidden">
                <div className="bg-cyber-cyan h-full rounded-full" style={{ width: `${healthMetrics.cpu}%` }} />
              </div>
            </div>
          </div>
        )}

        {/* Sidebar Collapse Toggle */}
        <div className="p-3 border-t border-cyber-border flex justify-end">
          <button
            onClick={toggleSidebar}
            className="p-1.5 rounded border border-cyber-border hover:border-cyber-cyan/50 hover:bg-white/5 text-gray-400 hover:text-cyber-cyan transition-colors"
          >
            {sidebarCollapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
          </button>
        </div>
      </aside>

      {/* MAIN CONTAINER */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden relative">
        
        {/* TOP BAR */}
        <header className="h-16 border-b border-cyber-border flex items-center justify-between px-6 bg-cyber-panel/60 backdrop-blur-md z-30 shrink-0 select-none">
          {/* Quick Search trigger */}
          <div className="flex items-center gap-3">
            <button
              onClick={() => setCommandPaletteOpen(true)}
              className="flex items-center gap-2.5 px-3 py-1.5 rounded-md border border-cyber-border bg-black/20 text-gray-400 hover:text-gray-200 hover:border-cyber-cyan/40 transition-colors text-xs font-mono"
            >
              <Search className="w-4 h-4 text-cyber-cyan" />
              <span>Quick Search...</span>
              <span className="bg-gray-800 text-[10px] px-1 rounded border border-gray-700">Ctrl + K</span>
            </button>
            <div className="hidden lg:flex items-center gap-1.5 text-[11px] font-mono text-gray-500">
              <Clock className="w-3.5 h-3.5" />
              <span>EST TIME: {new Date().toLocaleTimeString()}</span>
            </div>
          </div>

          {/* User Operations */}
          <div className="flex items-center gap-4">
            {/* Audio alarm toggle */}
            <button
              onClick={() => setSoundEnabled(!soundEnabled)}
              title={soundEnabled ? 'Disable Alarm Audio' : 'Enable Alarm Audio'}
              className={`p-2 rounded border transition-colors ${
                soundEnabled 
                  ? 'border-cyber-cyan/30 text-cyber-cyan bg-cyber-cyan/5' 
                  : 'border-cyber-border text-gray-500 hover:text-gray-300'
              }`}
            >
              {soundEnabled ? <Volume2 className="w-4 h-4 animate-pulse" /> : <VolumeX className="w-4 h-4" />}
            </button>

            {/* Notification Bell */}
            <div className="relative" ref={notificationRef}>
              <button
                onClick={() => setNotificationOpen(!notificationOpen)}
                className={`p-2 rounded border border-cyber-border transition-colors hover:border-cyber-cyan/40 text-gray-300 hover:text-cyber-cyan relative ${
                  notificationOpen ? 'border-cyber-cyan/40 text-cyber-cyan' : ''
                }`}
              >
                <Bell className="w-4 h-4" />
                {activeAlertsCount > 0 && (
                  <span className="absolute -top-1 -right-1 bg-cyber-red text-white text-[9px] font-bold w-4 h-4 rounded-full flex items-center justify-center animate-bounce">
                    {activeAlertsCount}
                  </span>
                )}
              </button>

              {/* Notification Slideout Dropdown */}
              {notificationOpen && (
                <div className="absolute right-0 mt-2 w-80 rounded-lg border border-cyber-border bg-cyber-panel shadow-2xl z-50 p-1 flex flex-col font-mono text-xs max-h-96 overflow-y-auto">
                  <div className="p-3 border-b border-cyber-border flex items-center justify-between text-gray-400">
                    <span className="font-bold text-cyber-cyan">ACTIVE THREAT STREAM</span>
                    <span>{activeAlertsCount} Alert(s)</span>
                  </div>
                  {alerts.length === 0 ? (
                    <div className="p-6 text-center text-gray-500 italic">No anomalies logged in current session</div>
                  ) : (
                    <div className="flex flex-col divide-y divide-cyber-border/40">
                      {alerts.slice(0, 5).map((a) => (
                        <div key={a.id} className="p-3 hover:bg-white/5 flex flex-col gap-1 text-[11px]">
                          <div className="flex items-center justify-between">
                            <span className="text-cyber-red font-bold uppercase tracking-wider">{a.anomaly_type.replace('_', ' ')}</span>
                            <span className="text-cyber-amber text-[10px]">{a.deviation_sigma.toFixed(1)}σ Deviation</span>
                          </div>
                          <div className="text-gray-400 truncate">EP: {a.endpoint_id}</div>
                          <div className="flex justify-between items-center mt-1">
                            <span className="text-gray-500 text-[10px]">Value: {a.observed_value.toFixed(1)}</span>
                            <button
                              onClick={() => resolveAlert(a.id)}
                              className="text-cyber-green hover:underline cursor-pointer"
                            >
                              [DISMISS]
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                  <Link
                    to="/alerts"
                    onClick={() => setNotificationOpen(false)}
                    className="p-2 text-center text-cyber-cyan hover:bg-cyber-cyan/10 font-bold border-t border-cyber-border block mt-1"
                  >
                    VIEW ALL SOC ALERTS
                  </Link>
                </div>
              )}
            </div>

            {/* ProfileDropdown */}
            <div className="relative" ref={profileRef}>
              <button
                onClick={() => setProfileOpen(!profileOpen)}
                className={`flex items-center gap-2 px-3 py-1.5 rounded border border-cyber-border bg-black/20 hover:border-cyber-cyan/40 transition-colors text-xs font-mono ${
                  profileOpen ? 'border-cyber-cyan/40 text-cyber-cyan' : ''
                }`}
              >
                <div className="w-5 h-5 rounded-full bg-cyber-purple/20 border border-cyber-purple flex items-center justify-center">
                  <User className="w-3.5 h-3.5 text-cyber-purple" />
                </div>
                <span className="hidden sm:inline text-gray-300 font-bold text-[11px] truncate max-w-[120px]">{user?.username || 'SOC ANALYST'}</span>
              </button>

              {/* Profile Dropdown panel */}
              {profileOpen && (
                <div className="absolute right-0 mt-2 w-56 rounded-lg border border-cyber-border bg-cyber-panel shadow-2xl z-50 p-1 flex flex-col font-mono text-xs">
                  <div className="p-3 border-b border-cyber-border">
                    <div className="text-gray-300 font-bold truncate">{user?.username}</div>
                    <div className="text-cyber-purple text-[10px] font-semibold mt-0.5 tracking-wider uppercase">ROLE: {role}</div>
                  </div>
                  <div className="py-1">
                    <div className="px-3 py-1.5 text-gray-500 flex items-center gap-1.5">
                      <Terminal className="w-3.5 h-3.5 text-cyber-cyan" />
                      <span>Clearance: API_READ</span>
                    </div>
                    {user?.last_login && (
                      <div className="px-3 py-1.5 text-gray-500 flex items-center gap-1.5">
                        <Clock className="w-3.5 h-3.5" />
                        <span className="text-[10px]">Login: {new Date(user.last_login).toLocaleTimeString()}</span>
                      </div>
                    )}
                  </div>
                  <button
                    onClick={() => {
                      setProfileOpen(false);
                      logout();
                      navigate('/login');
                    }}
                    className="p-2.5 text-left text-cyber-red hover:bg-cyber-red/10 border-t border-cyber-border flex items-center gap-2 rounded-b-md w-full"
                  >
                    <LogOut className="w-4 h-4" />
                    <span className="font-bold">TERMINATE SESSION</span>
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>

        {/* PAGE CONTENT CONTAINER */}
        <main className="flex-1 overflow-y-auto bg-cyber-bg relative p-6">
          {children || <Outlet />}
        </main>
      </div>

      {/* GLOBAL COMMAND PALETTE MODAL */}
      {commandPaletteOpen && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-start justify-center pt-24">
          <div
            ref={commandPaletteRef}
            className="w-full max-w-lg rounded-lg border border-cyber-cyan/35 bg-cyber-panel shadow-[0_0_50px_rgba(6,182,212,0.25)] flex flex-col font-mono text-sm overflow-hidden"
          >
            {/* Search Input bar */}
            <div className="h-12 border-b border-cyber-border flex items-center gap-3 px-4 bg-black/30">
              <Search className="w-5 h-5 text-cyber-cyan animate-pulse" />
              <input
                type="text"
                placeholder="Search command palette... (e.g. Overview, Inventory, Settings)"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="flex-1 bg-transparent border-none text-gray-200 placeholder-gray-500 text-sm focus:outline-none"
                autoFocus
              />
              <span className="text-gray-500 text-xs">[ESC]</span>
            </div>

            {/* List matches */}
            <div className="max-h-60 overflow-y-auto py-2">
              {filteredPaletteItems.length === 0 ? (
                <div className="p-4 text-center text-gray-500 text-xs italic">No matched commands found</div>
              ) : (
                filteredPaletteItems.map((item) => {
                  const Icon = item.icon;
                  return (
                    <button
                      key={item.name}
                      onClick={() => {
                        setCommandPaletteOpen(false);
                        navigate(item.path);
                      }}
                      className="w-full text-left px-4 py-2.5 hover:bg-cyber-cyan/15 flex items-center justify-between text-gray-300 hover:text-white transition-colors"
                    >
                      <div className="flex items-center gap-3">
                        <Icon className="w-4 h-4 text-cyber-cyan" />
                        <span>Navigate to {item.name}</span>
                      </div>
                      <span className="text-[10px] text-gray-500 uppercase tracking-tighter">ROUTE: {item.path}</span>
                    </button>
                  );
                })
              )}
            </div>

            {/* Footer */}
            <div className="h-9 border-t border-cyber-border bg-black/35 px-4 flex items-center justify-between text-[10px] text-gray-500 select-none">
              <span>Use ↑↓ to navigate, ENTER to trigger</span>
              <span>Cleared level: {role}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
