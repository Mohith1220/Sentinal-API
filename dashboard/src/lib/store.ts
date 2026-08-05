import { create } from 'zustand';
import type { User, AnomalyAlert, SecurityAlert } from '../types/api';

interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  setUser: (user: User | null) => void;
  setToken: (token: string | null) => void;
  setIsAuthenticated: (isAuthenticated: boolean) => void;
  setIsLoading: (isLoading: boolean) => void;
}

interface AlertState {
  alerts: AnomalyAlert[];
  securityAlerts: SecurityAlert[];
  addAlert: (alert: AnomalyAlert) => void;
  addSecurityAlert: (alert: SecurityAlert) => void;
  acknowledgeAlert: (alertId: string) => void;
  resolveAlert: (alertId: string) => void;
  clearAlerts: () => void;
  setAlerts: (alerts: AnomalyAlert[]) => void;
  setSecurityAlerts: (alerts: SecurityAlert[]) => void;
}

interface UIState {
  sidebarCollapsed: boolean;
  commandPaletteOpen: boolean;
  notificationOpen: boolean;
  toggleSidebar: () => void;
  setCommandPaletteOpen: (open: boolean) => void;
  setNotificationOpen: (open: boolean) => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: null,
  isAuthenticated: false,
  isLoading: false,
  setUser: (user) => set({ user }),
  setToken: (token) => set({ token }),
  setIsAuthenticated: (isAuthenticated) => set({ isAuthenticated }),
  setIsLoading: (isLoading) => set({ isLoading }),
}));

export const useAlertStore = create<AlertState>((set) => ({
  alerts: [],
  securityAlerts: [],
  
  addAlert: (alert) => set((state) => {
    const exists = state.alerts.some((a) => a.id === alert.id);
    if (exists) return {};
    const newAlerts = [alert, ...state.alerts];
    return { alerts: newAlerts.sort((a, b) => b.deviation_sigma - a.deviation_sigma) };
  }),
  
  addSecurityAlert: (alert) => set((state) => {
    const exists = state.securityAlerts.some((a) => a.id === alert.id);
    if (exists) return {};
    return { securityAlerts: [alert, ...state.securityAlerts] };
  }),
  
  acknowledgeAlert: (alertId) => set((state) => ({
    securityAlerts: state.securityAlerts.map((a) =>
      a.id === alertId ? { ...a, acknowledged_at: new Date().toISOString() } : a
    ),
  })),
  
  resolveAlert: (alertId) => set((state) => ({
    alerts: state.alerts.filter((a) => a.id !== alertId),
    securityAlerts: state.securityAlerts.map((a) =>
      a.id === alertId ? { ...a, resolved_at: new Date().toISOString() } : a
    ),
  })),
  
  clearAlerts: () => set({ alerts: [], securityAlerts: [] }),
  setAlerts: (alerts) => set({ alerts }),
  setSecurityAlerts: (securityAlerts) => set({ securityAlerts }),
}));

export const useUIStore = create<UIState>((set) => ({
  sidebarCollapsed: false,
  commandPaletteOpen: false,
  notificationOpen: false,
  toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
  setCommandPaletteOpen: (open) => set({ commandPaletteOpen: open }),
  setNotificationOpen: (open) => set({ notificationOpen: open }),
}));
