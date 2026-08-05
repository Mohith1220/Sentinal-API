import React, { createContext, useContext, useState, useEffect } from 'react';
import type { User, UserRole, Permission } from '../types/api';
import { useAuthStore } from '../lib/store';
import { hasPermission, getRolePermissions } from '../lib/rbac';
import { authApi, apiClient } from '../lib/api';

interface AuthContextType {
  user: User | null;
  role: UserRole | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  hasPermission: (permission: Permission) => boolean;
  hasRole: (role: UserRole) => boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

interface AuthProviderProps {
  children: React.ReactNode;
}

export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const { user, setUser, setToken, isAuthenticated, setIsAuthenticated, isLoading } =
    useAuthStore();
  const [localIsLoading, setLocalIsLoading] = useState(true);

  useEffect(() => {
    // Check if user is already authenticated via stored token
    const storedToken = localStorage.getItem('access_token');
    const storedUser = localStorage.getItem('user');

    if (storedToken && storedUser) {
      try {
        const parsedUser = JSON.parse(storedUser);
        apiClient.defaults.headers.common['Authorization'] = `Bearer ${storedToken}`;
        setToken(storedToken);
        setUser(parsedUser);
        setIsAuthenticated(true);
      } catch (error) {
        console.error('Failed to restore auth state:', error);
        localStorage.removeItem('access_token');
        localStorage.removeItem('user');
      }
    }
    setLocalIsLoading(false);
  }, [setToken, setUser, setIsAuthenticated]);

  const login = async (username: string, password: string) => {
    try {
      setLocalIsLoading(true);
      const response = await authApi.login({ username, password });

      const userData: User = {
        id: response.user.id,
        username: response.user.username,
        email: response.user.email,
        role: response.user.role,
        permissions: getRolePermissions(response.user.role),
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };

      localStorage.setItem('access_token', response.access_token);
      localStorage.setItem('user', JSON.stringify(userData));
      apiClient.defaults.headers.common['Authorization'] = `Bearer ${response.access_token}`;

      setToken(response.access_token);
      setUser(userData);
      setIsAuthenticated(true);
    } catch (error) {
      setIsAuthenticated(false);
      setUser(null);
      setToken(null);
      throw error;
    } finally {
      setLocalIsLoading(false);
    }
  };

  const logout = async () => {
    try {
      await authApi.logout();
    } catch (error) {
      console.error('Logout error:', error);
    } finally {
      localStorage.removeItem('access_token');
      localStorage.removeItem('user');
      delete apiClient.defaults.headers.common['Authorization'];
      setIsAuthenticated(false);
      setUser(null);
      setToken(null);
    }
  };

  const checkPermission = (permission: Permission): boolean => {
    if (!user) return false;
    return hasPermission(user.role, permission);
  };

  const checkRole = (role: UserRole): boolean => {
    if (!user) return false;
    return user.role === role;
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        role: user ? user.role : null,
        isAuthenticated,
        isLoading: localIsLoading || isLoading,
        login,
        logout,
        hasPermission: checkPermission,
        hasRole: checkRole,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};
