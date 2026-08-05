import axios, { AxiosError } from 'axios';
import { UserRole } from '../types/api';
import type { EndpointRecord, PaginatedResponse, EndpointFilters, LoginRequest, LoginResponse } from '../types/api';

const mapRole = (backendRole: string): UserRole => {
  const normalized = (backendRole || '').toUpperCase();
  if (normalized === 'ADMIN') return UserRole.SUPER_ADMIN;
  if (normalized === 'SECURITY_ADMIN' || normalized === 'SEC_ADMIN') return UserRole.SECURITY_ADMIN;
  if (normalized === 'ANALYST' || normalized === 'SECURITY_ANALYST') return UserRole.SECURITY_ANALYST;
  if (normalized === 'API_GOVERNANCE_MANAGER' || normalized === 'GOVERNANCE') return UserRole.API_GOVERNANCE_MANAGER;
  if (normalized === 'COMPLIANCE_OFFICER' || normalized === 'COMPLIANCE') return UserRole.COMPLIANCE_OFFICER;
  return UserRole.VIEWER;
};

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true, // Send cookies with requests
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor to attach JWT from cookie
apiClient.interceptors.request.use(
  (config) => {
    // JWT is stored in httpOnly cookie, so it's automatically sent
    // We just need to ensure withCredentials is true
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor to handle 401 errors
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      // Redirect to login page
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

// Auth API
export const authApi = {
  login: async (credentials: LoginRequest): Promise<LoginResponse> => {
    const response = await apiClient.post<any>('/auth/token', credentials);
    const data = response.data;
    
    const token = data.access_token;
    let username = credentials.username;
    let role = data.role || 'viewer';
    
    try {
      const payloadBase64 = token.split('.')[1];
      const payload = JSON.parse(atob(payloadBase64));
      if (payload.sub) username = payload.sub;
      if (payload.role) role = payload.role;
    } catch (e) {
      console.error('Failed to decode JWT token:', e);
    }
    
    const mappedRole = mapRole(role);
    
    return {
      access_token: token,
      token_type: data.token_type || 'bearer',
      role: mappedRole,
      user: {
        id: username,
        username: username,
        email: `${username}@example.com`,
        role: mappedRole,
      }
    };
  },
  
  logout: async (): Promise<void> => {
    await apiClient.post('/auth/logout');
  },
};

// Endpoints API
export const endpointsApi = {
  getEndpoints: async (filters: EndpointFilters = {}): Promise<PaginatedResponse<EndpointRecord>> => {
    const params = new URLSearchParams();
    
    if (filters.lifecycle_status) params.append('lifecycle_status', filters.lifecycle_status);
    if (filters.risk_score_min !== undefined) params.append('risk_score_min', filters.risk_score_min.toString());
    if (filters.risk_score_max !== undefined) params.append('risk_score_max', filters.risk_score_max.toString());
    if (filters.auth_scheme) params.append('auth_scheme', filters.auth_scheme);
    if (filters.data_sensitivity) params.append('data_sensitivity', filters.data_sensitivity);
    if (filters.page) params.append('page', filters.page.toString());
    if (filters.page_size) params.append('page_size', filters.page_size.toString());
    
    const response = await apiClient.get<PaginatedResponse<EndpointRecord>>(`/endpoints?${params.toString()}`);
    return response.data;
  },
  
  getEndpoint: async (id: string): Promise<EndpointRecord> => {
    const response = await apiClient.get<EndpointRecord>(`/endpoints/${id}`);
    return response.data;
  },
};

// Graph API
export const graphApi = {
  getGraph: async (): Promise<import('../types/api').GraphData> => {
    const response = await apiClient.get<import('../types/api').GraphData>('/graph/nodes');
    return response.data;
  },
};

// Recommendations API
export const recommendationsApi = {
  getRecommendations: async (endpointId: string): Promise<import('../types/api').RemediationRecommendation[]> => {
    const response = await apiClient.get<any>(`/recommendations/${endpointId}`);
    if (response.data && response.data.recommendations) {
      return response.data.recommendations;
    }
    return Array.isArray(response.data) ? response.data : [];
  },
  
  getAllRecommendations: async (): Promise<import('../types/api').RemediationRecommendation[]> => {
    const response = await apiClient.get<any>('/recommendations');
    if (response.data && response.data.items) {
      return response.data.items;
    }
    if (response.data && response.data.recommendations) {
      return response.data.recommendations;
    }
    return Array.isArray(response.data) ? response.data : [];
  },

  resolveRecommendation: async (recommendationId: string): Promise<any> => {
    // Post resolve action carrying acting security user
    const response = await apiClient.post(`/recommendations/${recommendationId}/resolve`, {
      resolved_by: 'sec_admin'
    });
    return response.data;
  }
};

// WebSocket URL for alerts
export const getAlertsWebSocketUrl = (): string => {
  const wsProtocol = API_BASE_URL.startsWith('https') ? 'wss' : 'ws';
  const wsBaseUrl = API_BASE_URL.replace(/^https?/, wsProtocol);
  return `${wsBaseUrl}/ws/alerts`;
};
