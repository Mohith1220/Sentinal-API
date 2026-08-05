import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import type { UserRole } from '../types/api';

interface RequireRoleProps {
  roles: UserRole[];
  children: React.ReactNode;
}

export const RequireRole: React.FC<RequireRoleProps> = ({ roles, children }) => {
  const { isAuthenticated, role, isLoading } = useAuth();

  if (isLoading) {
    return <div>Loading...</div>;
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  if (role && !roles.includes(role)) {
    return (
      <div style={{ padding: '2rem', textAlign: 'center' }}>
        <h2>Authorization Error</h2>
        <p>You do not have permission to access this page.</p>
        <p>Required role: {roles.join(' or ')}</p>
        <p>Your role: {role}</p>
      </div>
    );
  }

  return <>{children}</>;
};
