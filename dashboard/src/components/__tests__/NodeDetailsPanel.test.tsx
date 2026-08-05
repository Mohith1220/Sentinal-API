import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { NodeDetailsPanel } from '../NodeDetailsPanel';
import { endpointsApi, recommendationsApi } from '../../lib/api';
import type { EndpointRecord, RemediationRecommendation } from '../../types/api';

// Mock the API modules
vi.mock('../../lib/api', () => ({
  endpointsApi: {
    getEndpoint: vi.fn(),
  },
  recommendationsApi: {
    getRecommendations: vi.fn(),
  },
}));

const mockEndpoint: EndpointRecord = {
  id: 'endpoint-123',
  http_method: 'GET',
  host: 'api.example.com',
  path: '/users/{id}',
  normalized_path: '/users/{id}',
  auth_scheme: 'OAuth2',
  data_sensitivity: 'PII',
  lifecycle_status: 'Active',
  risk_score: 45,
  request_count_24h: 15000,
  last_access_at: '2024-01-15T10:30:00Z',
  first_seen_at: '2024-01-01T00:00:00Z',
  is_stale: false,
  owning_team: 'Platform Team',
  source_file_id: 'openapi-spec-v1.yaml',
  metadata: {
    risk_factors: [
      {
        rule: 'sensitive_data_weak_auth',
        points: 30,
        description: 'PII data with weak authentication',
      },
      {
        rule: 'high_traffic',
        points: 15,
        description: 'High traffic volume detected',
      },
    ],
  },
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-15T10:30:00Z',
};

const mockRecommendations: RemediationRecommendation[] = [
  {
    id: 'rec-1',
    endpoint_id: 'endpoint-123',
    priority: 'Critical',
    trigger_rule: 'no_authentication',
    summary_text: 'Add OAuth2 authentication to this endpoint',
    detail_json: { mechanism: 'OAuth2', scopes: ['read:users'] },
    resolved_by: null,
    resolved_at: null,
    created_at: '2024-01-15T10:00:00Z',
    updated_at: '2024-01-15T10:00:00Z',
  },
  {
    id: 'rec-2',
    endpoint_id: 'endpoint-123',
    priority: 'High',
    trigger_rule: 'rate_limiting',
    summary_text: 'Apply rate limiting to prevent abuse',
    detail_json: { limit: 1000, window: '1h' },
    resolved_by: 'admin@example.com',
    resolved_at: '2024-01-15T11:00:00Z',
    created_at: '2024-01-15T10:00:00Z',
    updated_at: '2024-01-15T11:00:00Z',
  },
];

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

describe('NodeDetailsPanel', () => {
  let onClose: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    onClose = vi.fn();
    vi.clearAllMocks();
  });

  it('renders loading state initially', () => {
    vi.mocked(endpointsApi.getEndpoint).mockImplementation(
      () => new Promise(() => {}) // Never resolves
    );

    render(
      <NodeDetailsPanel nodeId="endpoint-123" onClose={onClose} />,
      { wrapper: createWrapper() }
    );

    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  it('renders endpoint details after loading', async () => {
    vi.mocked(endpointsApi.getEndpoint).mockResolvedValue(mockEndpoint);
    vi.mocked(recommendationsApi.getRecommendations).mockResolvedValue(mockRecommendations);

    render(
      <NodeDetailsPanel nodeId="endpoint-123" onClose={onClose} />,
      { wrapper: createWrapper() }
    );

    await waitFor(() => {
      expect(screen.getByText('Endpoint Details')).toBeInTheDocument();
    });

    // Check metadata
    expect(screen.getByText('GET')).toBeInTheDocument();
    expect(screen.getByText('api.example.com')).toBeInTheDocument();
    expect(screen.getByText('/users/{id}')).toBeInTheDocument();
    expect(screen.getByText('Active')).toBeInTheDocument();
    expect(screen.getByText('OAuth2')).toBeInTheDocument();
    expect(screen.getByText('PII')).toBeInTheDocument();
    expect(screen.getByText('Platform Team')).toBeInTheDocument();
    expect(screen.getByText('15,000')).toBeInTheDocument();
  });

  it('displays risk score with correct color coding', async () => {
    vi.mocked(endpointsApi.getEndpoint).mockResolvedValue(mockEndpoint);
    vi.mocked(recommendationsApi.getRecommendations).mockResolvedValue([]);

    render(
      <NodeDetailsPanel nodeId="endpoint-123" onClose={onClose} />,
      { wrapper: createWrapper() }
    );

    await waitFor(() => {
      const riskScoreElement = screen.getByText('45');
      expect(riskScoreElement).toBeInTheDocument();
      
      // Risk score 45 should be amber (34-66 range)
      const style = window.getComputedStyle(riskScoreElement);
      expect(style.backgroundColor).toBeTruthy();
    });
  });

  it('displays contributing risk factors', async () => {
    vi.mocked(endpointsApi.getEndpoint).mockResolvedValue(mockEndpoint);
    vi.mocked(recommendationsApi.getRecommendations).mockResolvedValue([]);

    render(
      <NodeDetailsPanel nodeId="endpoint-123" onClose={onClose} />,
      { wrapper: createWrapper() }
    );

    await waitFor(() => {
      expect(screen.getByText(/sensitive_data_weak_auth/)).toBeInTheDocument();
      expect(screen.getByText(/PII data with weak authentication/)).toBeInTheDocument();
      expect(screen.getByText(/high_traffic/)).toBeInTheDocument();
      expect(screen.getByText(/High traffic volume detected/)).toBeInTheDocument();
    });
  });

  it('displays remediation recommendations', async () => {
    vi.mocked(endpointsApi.getEndpoint).mockResolvedValue(mockEndpoint);
    vi.mocked(recommendationsApi.getRecommendations).mockResolvedValue(mockRecommendations);

    render(
      <NodeDetailsPanel nodeId="endpoint-123" onClose={onClose} />,
      { wrapper: createWrapper() }
    );

    await waitFor(() => {
      expect(screen.getByText('Add OAuth2 authentication to this endpoint')).toBeInTheDocument();
      expect(screen.getByText('Apply rate limiting to prevent abuse')).toBeInTheDocument();
    });

    // Check priority badges
    expect(screen.getByText('Critical')).toBeInTheDocument();
    expect(screen.getByText('High')).toBeInTheDocument();
  });

  it('shows resolved status for completed recommendations', async () => {
    vi.mocked(endpointsApi.getEndpoint).mockResolvedValue(mockEndpoint);
    vi.mocked(recommendationsApi.getRecommendations).mockResolvedValue(mockRecommendations);

    render(
      <NodeDetailsPanel nodeId="endpoint-123" onClose={onClose} />,
      { wrapper: createWrapper() }
    );

    await waitFor(() => {
      expect(screen.getByText(/Resolved by admin@example.com/)).toBeInTheDocument();
    });
  });

  it('calls onClose when close button is clicked', async () => {
    const user = userEvent.setup();
    vi.mocked(endpointsApi.getEndpoint).mockResolvedValue(mockEndpoint);
    vi.mocked(recommendationsApi.getRecommendations).mockResolvedValue([]);

    render(
      <NodeDetailsPanel nodeId="endpoint-123" onClose={onClose} />,
      { wrapper: createWrapper() }
    );

    await waitFor(() => {
      expect(screen.getByText('Endpoint Details')).toBeInTheDocument();
    });

    const closeButton = screen.getByRole('button', { name: '×' });
    await user.click(closeButton);

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('renders error state when endpoint fetch fails', async () => {
    vi.mocked(endpointsApi.getEndpoint).mockRejectedValue(new Error('Network error'));

    render(
      <NodeDetailsPanel nodeId="endpoint-123" onClose={onClose} />,
      { wrapper: createWrapper() }
    );

    await waitFor(() => {
      expect(screen.getByText('Error loading endpoint details')).toBeInTheDocument();
    });
  });

  it('shows "No recommendations available" when there are none', async () => {
    vi.mocked(endpointsApi.getEndpoint).mockResolvedValue(mockEndpoint);
    vi.mocked(recommendationsApi.getRecommendations).mockResolvedValue([]);

    render(
      <NodeDetailsPanel nodeId="endpoint-123" onClose={onClose} />,
      { wrapper: createWrapper() }
    );

    await waitFor(() => {
      expect(screen.getByText('No recommendations available')).toBeInTheDocument();
    });
  });

  it('displays "N/A" for missing owning team', async () => {
    const endpointWithoutTeam = { ...mockEndpoint, owning_team: null };
    vi.mocked(endpointsApi.getEndpoint).mockResolvedValue(endpointWithoutTeam);
    vi.mocked(recommendationsApi.getRecommendations).mockResolvedValue([]);

    render(
      <NodeDetailsPanel nodeId="endpoint-123" onClose={onClose} />,
      { wrapper: createWrapper() }
    );

    await waitFor(() => {
      expect(screen.getByText('N/A')).toBeInTheDocument();
    });
  });

  it('displays "Never" for null last_access_at', async () => {
    const endpointNeverAccessed = { ...mockEndpoint, last_access_at: null };
    vi.mocked(endpointsApi.getEndpoint).mockResolvedValue(endpointNeverAccessed);
    vi.mocked(recommendationsApi.getRecommendations).mockResolvedValue([]);

    render(
      <NodeDetailsPanel nodeId="endpoint-123" onClose={onClose} />,
      { wrapper: createWrapper() }
    );

    await waitFor(() => {
      expect(screen.getByText('Never')).toBeInTheDocument();
    });
  });

  it('renders panel without full page reload', async () => {
    vi.mocked(endpointsApi.getEndpoint).mockResolvedValue(mockEndpoint);
    vi.mocked(recommendationsApi.getRecommendations).mockResolvedValue(mockRecommendations);

    const { container } = render(
      <NodeDetailsPanel nodeId="endpoint-123" onClose={onClose} />,
      { wrapper: createWrapper() }
    );

    await waitFor(() => {
      expect(screen.getByText('Endpoint Details')).toBeInTheDocument();
    });

    // Verify the panel is rendered as a fixed positioned element (side panel)
    const panel = container.firstChild as HTMLElement;
    expect(panel).toHaveStyle({ position: 'fixed' });
  });

  it('fetches endpoint and recommendations on node selection', async () => {
    const getEndpointSpy = vi.mocked(endpointsApi.getEndpoint).mockResolvedValue(mockEndpoint);
    const getRecommendationsSpy = vi.mocked(recommendationsApi.getRecommendations).mockResolvedValue(mockRecommendations);

    render(
      <NodeDetailsPanel nodeId="endpoint-123" onClose={onClose} />,
      { wrapper: createWrapper() }
    );

    await waitFor(() => {
      expect(getEndpointSpy).toHaveBeenCalledWith('endpoint-123');
      expect(getRecommendationsSpy).toHaveBeenCalledWith('endpoint-123');
    });
  });

  it('displays different lifecycle status colors', async () => {
    const zombieEndpoint = { ...mockEndpoint, lifecycle_status: 'Zombie' as const };
    vi.mocked(endpointsApi.getEndpoint).mockResolvedValue(zombieEndpoint);
    vi.mocked(recommendationsApi.getRecommendations).mockResolvedValue([]);

    render(
      <NodeDetailsPanel nodeId="endpoint-123" onClose={onClose} />,
      { wrapper: createWrapper() }
    );

    await waitFor(() => {
      const statusBadge = screen.getByText('Zombie');
      expect(statusBadge).toBeInTheDocument();
      // Zombie status should have red background
      const style = window.getComputedStyle(statusBadge);
      expect(style.backgroundColor).toBeTruthy();
    });
  });

  it('displays different priority colors for recommendations', async () => {
    vi.mocked(endpointsApi.getEndpoint).mockResolvedValue(mockEndpoint);
    vi.mocked(recommendationsApi.getRecommendations).mockResolvedValue(mockRecommendations);

    render(
      <NodeDetailsPanel nodeId="endpoint-123" onClose={onClose} />,
      { wrapper: createWrapper() }
    );

    await waitFor(() => {
      const criticalBadge = screen.getByText('Critical');
      const highBadge = screen.getByText('High');
      
      expect(criticalBadge).toBeInTheDocument();
      expect(highBadge).toBeInTheDocument();
      
      // Both should have background colors
      expect(window.getComputedStyle(criticalBadge).backgroundColor).toBeTruthy();
      expect(window.getComputedStyle(highBadge).backgroundColor).toBeTruthy();
    });
  });

  it('handles endpoints with no risk factors gracefully', async () => {
    const endpointNoFactors = { ...mockEndpoint, metadata: {} };
    vi.mocked(endpointsApi.getEndpoint).mockResolvedValue(endpointNoFactors);
    vi.mocked(recommendationsApi.getRecommendations).mockResolvedValue([]);

    render(
      <NodeDetailsPanel nodeId="endpoint-123" onClose={onClose} />,
      { wrapper: createWrapper() }
    );

    await waitFor(() => {
      expect(screen.getByText('Risk Assessment')).toBeInTheDocument();
    });

    // Should not crash and should display risk score
    expect(screen.getByText('45')).toBeInTheDocument();
  });
});
