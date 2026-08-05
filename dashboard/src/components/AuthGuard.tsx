import React from 'react';
import { Navigate, useLocation, Outlet } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import type { UserRole, Permission } from '../types/api';

interface AuthGuardProps {
  children?: React.ReactNode;
  allowedRoles?: UserRole[];
  requiredPermission?: Permission;
}

export const AuthGuard: React.FC<AuthGuardProps> = ({
  children,
  allowedRoles,
  requiredPermission,
}) => {
  const { isAuthenticated, role, isLoading, hasPermission } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-cyber-bg text-cyber-blue font-mono">
        <div className="flex flex-col items-center gap-4">
          <div className="w-12 h-12 rounded-full border-4 border-cyber-border border-t-cyber-cyan animate-spin" />
          <span className="text-sm tracking-widest text-cyber-cyan animate-pulse">
            ESTABLISHING SECURE CONNECTION CHANNEL...
          </span>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (allowedRoles && role && !allowedRoles.includes(role)) {
    return <Navigate to="/access-denied" replace />;
  }

  if (requiredPermission && !hasPermission(requiredPermission)) {
    return <Navigate to="/access-denied" replace />;
  }

  return <>{children || <Outlet />}</>;
};
