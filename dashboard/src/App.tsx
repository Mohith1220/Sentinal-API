import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from './contexts/AuthContext';
import { SidebarLayout } from './components/SidebarLayout';
import { AuthGuard } from './components/AuthGuard';
import { UserRole } from './types/api';

// Pages
import { Login } from './pages/Login';
import { Signup } from './pages/Signup';
import { Dashboard } from './pages/Dashboard';
import { APIInventory } from './pages/APIInventory';
import { APIDetail } from './pages/APIDetail';
import { DependencyGraphView } from './pages/DependencyGraphView';
import { AlertsCenter } from './pages/AlertsCenter';
import { RiskHeatmapView } from './pages/RiskHeatmapView';
import { RemediationCenter } from './pages/RemediationCenter';
import { Administration } from './pages/Administration';
import { AccessDeniedPage } from './pages/AccessDeniedPage';
import { RLIntelligenceCenter } from './pages/RLIntelligenceCenter';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

function AppRoutes() {
  return (
    <Routes>
      {/* Public Unauthenticated Routes */}
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route path="/access-denied" element={<AccessDeniedPage />} />

      {/* Secure Authenticated SOC Workspace Routes sharing SidebarLayout */}
      <Route
        element={
          <AuthGuard>
            <SidebarLayout />
          </AuthGuard>
        }
      >
        {/* adattive landing dashboard overview */}
        <Route path="/" element={<Dashboard />} />

        {/* Operational Inventory Control deck */}
        <Route path="/inventory" element={<APIInventory />} />

        {/* Endpoint specific deep diagnostics details */}
        <Route path="/endpoints/:id" element={<APIDetail />} />

        {/* Dedicated high capacity Force directed Call dependency visual graph */}
        <Route path="/graph" element={<DependencyGraphView />} />

        {/* Live incident alarms feed WebSocket streams */}
        <Route path="/alerts" element={<AlertsCenter />} />

        {/* Multi-sensory heatmap matrices mapping sensitive endpoints */}
        <Route path="/heatmap" element={<RiskHeatmapView />} />

        {/* AI-driven containment patching recommendation center */}
        <Route path="/remediation" element={<RemediationCenter />} />

        {/* RL Intelligence Center — PPO agent + analyst feedback */}
        <Route path="/rl" element={<RLIntelligenceCenter />} />

        {/* Governance console with ML sliders, kafka hubs, user RBAC and logs */}
        <Route
          path="/administration"
          element={
            <AuthGuard
              allowedRoles={[
                UserRole.SUPER_ADMIN,
                UserRole.SECURITY_ADMIN,
                UserRole.SECURITY_ANALYST,
                UserRole.API_GOVERNANCE_MANAGER,
                UserRole.COMPLIANCE_OFFICER,
              ]}
            />
          }
        >
          <Route index element={<Administration />} />
        </Route>
      </Route>

      {/* Redirect wildcards */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
