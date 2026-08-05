import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { InventoryTable } from '../InventoryTable';
import * as api from '../../lib/api';
import type { PaginatedResponse, EndpointRecord } from '../../types/api';

// Mock the API
vi.mock('../../lib/api', () => ({
  endpointsApi: {
    getEndpoints: vi.fn(),
  },
}));

const mockEndpoints: PaginatedResponse<EndpointRecord> = {
  items: [
    {
      id: '1',
      http_method: 'GET',
      host: 'api.example.com',
      path: '/users',
      normalized_path: '/users',
      auth_scheme: 'JWT',
      data_sensitivity: 'PII',
      lifecycle_status: 'Active',
      risk_score: 25,
      request_count_24h: 1000,
      last_access_at: '2024-01-15T10:00:00Z',
      first_seen_at: '2024-01-01T00:00:00Z',
      is_stale: false,
      owning_team: 'Platform',
      source_file_id: 'spec-1',
      metadata: {},
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-15T10:00:00Z',
    },
    {
      id: '2',
      http_method: 'POST',
      host: 'api.example.com',
      path: '/orders',
      normalized_path: '/orders',
      auth_scheme: 'OAuth2',
      data_sensitivity: 'financial',
      lifecycle_status: 'Zombie',
      risk_score: 85,
      request_count_24h: 50,
      last_access_at: '2024-01-14T10:00:00Z',
      first_seen_at: '2024-01-01T00:00:00Z',
      is_stale: false,
      owning_team: null,
      source_file_id: null,
      metadata: {},
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-14T10:00:00Z',
    },
  ],
  total: 2,
  page: 1,
  page_size: 20,
  has_next: false,
};

describe('InventoryTable', () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    });
    vi.clearAllMocks();
  });

  const renderWithProviders = (component: React.ReactElement) => {
    return render(
      <QueryClientProvider client={queryClient}>
        {component}
      </QueryClientProvider>
    );
  };

  it('renders table with endpoint rows', async () => {
    vi.mocked(api.endpointsApi.getEndpoints).mockResolvedValue(mockEndpoints);

    renderWithProviders(<InventoryTable />);

    await waitFor(() => {
      expect(screen.getByText('GET')).toBeInTheDocument();
      expect(screen.getByText('POST')).toBeInTheDocument();
      expect(screen.getByText('/users')).toBeInTheDocument();
      expect(screen.getByText('/orders')).toBeInTheDocument();
    });
  });

  it('updates query params when filter controls change', async () => {
    const user = userEvent.setup();
    vi.mocked(api.endpointsApi.getEndpoints).mockResolvedValue(mockEndpoints);

    renderWithProviders(<InventoryTable />);

    // Wait for initial load
    await waitFor(() => {
      expect(screen.getByText('GET')).toBeInTheDocument();
    });

    // Change lifecycle status filter
    const lifecycleFilter = screen.getByLabelText('Lifecycle Status');
    await user.selectOptions(lifecycleFilter, 'Zombie');

    // Verify API was called with the filter
    await waitFor(() => {
      expect(api.endpointsApi.getEndpoints).toHaveBeenCalledWith(
        expect.objectContaining({
          lifecycle_status: 'Zombie',
          page: 1,
        })
      );
    });
  });

  it('updates query params when risk score filters change', async () => {
    const user = userEvent.setup();
    vi.mocked(api.endpointsApi.getEndpoints).mockResolvedValue(mockEndpoints);

    renderWithProviders(<InventoryTable />);

    // Wait for initial load
    await waitFor(() => {
      expect(screen.getByText('GET')).toBeInTheDocument();
    });

    // Change min risk score
    const minRiskFilter = screen.getByLabelText('Min Risk Score');
    await user.clear(minRiskFilter);
    await user.type(minRiskFilter, '50');

    // Verify API was called with the filter
    await waitFor(() => {
      expect(api.endpointsApi.getEndpoints).toHaveBeenCalledWith(
        expect.objectContaining({
          risk_score_min: 50,
          page: 1,
        })
      );
    });
  });

  it('updates query params when auth scheme filter changes', async () => {
    const user = userEvent.setup();
    vi.mocked(api.endpointsApi.getEndpoints).mockResolvedValue(mockEndpoints);

    renderWithProviders(<InventoryTable />);

    // Wait for initial load
    await waitFor(() => {
      expect(screen.getByText('GET')).toBeInTheDocument();
    });

    // Change auth scheme filter
    const authFilter = screen.getByLabelText('Auth Scheme');
    await user.selectOptions(authFilter, 'none');

    // Verify API was called with the filter
    await waitFor(() => {
      expect(api.endpointsApi.getEndpoints).toHaveBeenCalledWith(
        expect.objectContaining({
          auth_scheme: 'none',
          page: 1,
        })
      );
    });
  });

  it('updates query params when data sensitivity filter changes', async () => {
    const user = userEvent.setup();
    vi.mocked(api.endpointsApi.getEndpoints).mockResolvedValue(mockEndpoints);

    renderWithProviders(<InventoryTable />);

    // Wait for initial load
    await waitFor(() => {
      expect(screen.getByText('GET')).toBeInTheDocument();
    });

    // Change data sensitivity filter
    const sensitivityFilter = screen.getByLabelText('Data Sensitivity');
    await user.selectOptions(sensitivityFilter, 'PII');

    // Verify API was called with the filter
    await waitFor(() => {
      expect(api.endpointsApi.getEndpoints).toHaveBeenCalledWith(
        expect.objectContaining({
          data_sensitivity: 'PII',
          page: 1,
        })
      );
    });
  });

  it('handles pagination', async () => {
    const user = userEvent.setup();
    const mockWithPagination = {
      ...mockEndpoints,
      has_next: true,
    };
    vi.mocked(api.endpointsApi.getEndpoints).mockResolvedValue(mockWithPagination);

    renderWithProviders(<InventoryTable />);

    // Wait for initial load
    await waitFor(() => {
      expect(screen.getByText('GET')).toBeInTheDocument();
    });

    // Click next page
    const nextButton = screen.getByText('Next');
    await user.click(nextButton);

    // Verify API was called with page 2
    await waitFor(() => {
      expect(api.endpointsApi.getEndpoints).toHaveBeenCalledWith(
        expect.objectContaining({
          page: 2,
        })
      );
    });
  });

  it('displays loading state', () => {
    vi.mocked(api.endpointsApi.getEndpoints).mockImplementation(
      () => new Promise(() => {}) // Never resolves
    );

    renderWithProviders(<InventoryTable />);

    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  it('displays error state', async () => {
    vi.mocked(api.endpointsApi.getEndpoints).mockRejectedValue(new Error('API Error'));

    renderWithProviders(<InventoryTable />);

    await waitFor(() => {
      expect(screen.getByText('Error loading endpoints')).toBeInTheDocument();
    });
  });
});
