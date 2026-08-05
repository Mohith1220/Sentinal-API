import React, { useState, useMemo } from 'react';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table';
import { useQuery } from '@tanstack/react-query';
import { endpointsApi } from '../lib/api';
import type { EndpointRecord, EndpointFilters, LifecycleStatus, AuthScheme, DataSensitivity } from '../types/api';

export const InventoryTable: React.FC = () => {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [filters, setFilters] = useState<EndpointFilters>({
    page: 1,
    page_size: 20,
  });

  const { data, isLoading, error } = useQuery({
    queryKey: ['endpoints', filters],
    queryFn: () => endpointsApi.getEndpoints(filters),
  });

  const columns = useMemo<ColumnDef<EndpointRecord>[]>(
    () => [
      {
        accessorKey: 'http_method',
        header: 'Method',
        cell: (info) => (
          <span style={{ 
            fontWeight: 'bold',
            color: getMethodColor(info.getValue() as string)
          }}>
            {info.getValue() as string}
          </span>
        ),
      },
      {
        accessorKey: 'host',
        header: 'Host',
      },
      {
        accessorKey: 'path',
        header: 'Path',
        cell: (info) => (
          <code style={{ fontSize: '0.9em' }}>{info.getValue() as string}</code>
        ),
      },
      {
        accessorKey: 'lifecycle_status',
        header: 'Status',
        cell: (info) => (
          <span style={{
            padding: '0.25rem 0.5rem',
            borderRadius: '4px',
            fontSize: '0.85em',
            fontWeight: 'bold',
            backgroundColor: getStatusColor(info.getValue() as LifecycleStatus),
            color: 'white',
          }}>
            {info.getValue() as string}
          </span>
        ),
      },
      {
        accessorKey: 'risk_score',
        header: 'Risk Score',
        cell: (info) => {
          const score = info.getValue() as number;
          return (
            <span style={{
              padding: '0.25rem 0.5rem',
              borderRadius: '4px',
              fontWeight: 'bold',
              backgroundColor: getRiskColor(score),
              color: 'white',
            }}>
              {score}
            </span>
          );
        },
      },
      {
        accessorKey: 'auth_scheme',
        header: 'Auth',
      },
      {
        accessorKey: 'data_sensitivity',
        header: 'Sensitivity',
      },
      {
        accessorKey: 'last_access_at',
        header: 'Last Access',
        cell: (info) => {
          const value = info.getValue() as string | null;
          return value ? new Date(value).toLocaleString() : 'Never';
        },
      },
    ],
    []
  );

  const table = useReactTable({
    data: data?.items ?? [],
    columns,
    state: {
      sorting,
    },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const handleFilterChange = (key: keyof EndpointFilters, value: string | number | undefined) => {
    setFilters((prev) => ({
      ...prev,
      [key]: value || undefined,
      page: 1, // Reset to first page when filters change
    }));
  };

  const handlePageChange = (newPage: number) => {
    setFilters((prev) => ({ ...prev, page: newPage }));
  };

  if (error) {
    return <div style={{ color: 'red', padding: '1rem' }}>Error loading endpoints</div>;
  }

  return (
    <div style={{ padding: '1rem' }}>
      <h2>API Inventory</h2>

      {/* Filter Controls */}
      <div style={{ 
        display: 'grid', 
        gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
        gap: '1rem',
        marginBottom: '1rem',
        padding: '1rem',
        backgroundColor: '#f5f5f5',
        borderRadius: '8px'
      }}>
        <div>
          <label htmlFor="lifecycle-filter" style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.9em' }}>
            Lifecycle Status
          </label>
          <select
            id="lifecycle-filter"
            value={filters.lifecycle_status || ''}
            onChange={(e) => handleFilterChange('lifecycle_status', e.target.value as LifecycleStatus)}
            style={{ width: '100%', padding: '0.5rem', borderRadius: '4px', border: '1px solid #ddd' }}
          >
            <option value="">All</option>
            <option value="Active">Active</option>
            <option value="Deprecated">Deprecated</option>
            <option value="Orphaned">Orphaned</option>
            <option value="Zombie">Zombie</option>
            <option value="Shadow_API">Shadow API</option>
          </select>
        </div>

        <div>
          <label htmlFor="auth-filter" style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.9em' }}>
            Auth Scheme
          </label>
          <select
            id="auth-filter"
            value={filters.auth_scheme || ''}
            onChange={(e) => handleFilterChange('auth_scheme', e.target.value as AuthScheme)}
            style={{ width: '100%', padding: '0.5rem', borderRadius: '4px', border: '1px solid #ddd' }}
          >
            <option value="">All</option>
            <option value="OAuth2">OAuth2</option>
            <option value="JWT">JWT</option>
            <option value="api_key">API Key</option>
            <option value="none">None</option>
            <option value="unknown">Unknown</option>
          </select>
        </div>

        <div>
          <label htmlFor="sensitivity-filter" style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.9em' }}>
            Data Sensitivity
          </label>
          <select
            id="sensitivity-filter"
            value={filters.data_sensitivity || ''}
            onChange={(e) => handleFilterChange('data_sensitivity', e.target.value as DataSensitivity)}
            style={{ width: '100%', padding: '0.5rem', borderRadius: '4px', border: '1px solid #ddd' }}
          >
            <option value="">All</option>
            <option value="PII">PII</option>
            <option value="financial">Financial</option>
            <option value="internal">Internal</option>
            <option value="public">Public</option>
          </select>
        </div>

        <div>
          <label htmlFor="risk-min-filter" style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.9em' }}>
            Min Risk Score
          </label>
          <input
            id="risk-min-filter"
            type="number"
            min="0"
            max="100"
            value={filters.risk_score_min ?? ''}
            onChange={(e) => handleFilterChange('risk_score_min', e.target.value ? parseInt(e.target.value) : undefined)}
            style={{ width: '100%', padding: '0.5rem', borderRadius: '4px', border: '1px solid #ddd' }}
            placeholder="0"
          />
        </div>

        <div>
          <label htmlFor="risk-max-filter" style={{ display: 'block', marginBottom: '0.25rem', fontSize: '0.9em' }}>
            Max Risk Score
          </label>
          <input
            id="risk-max-filter"
            type="number"
            min="0"
            max="100"
            value={filters.risk_score_max ?? ''}
            onChange={(e) => handleFilterChange('risk_score_max', e.target.value ? parseInt(e.target.value) : undefined)}
            style={{ width: '100%', padding: '0.5rem', borderRadius: '4px', border: '1px solid #ddd' }}
            placeholder="100"
          />
        </div>
      </div>

      {/* Table */}
      {isLoading ? (
        <div style={{ padding: '2rem', textAlign: 'center' }}>Loading...</div>
      ) : (
        <>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ 
              width: '100%', 
              borderCollapse: 'collapse',
              backgroundColor: 'white',
              boxShadow: '0 1px 3px rgba(0,0,0,0.1)'
            }}>
              <thead>
                {table.getHeaderGroups().map((headerGroup) => (
                  <tr key={headerGroup.id} style={{ backgroundColor: '#f8f9fa' }}>
                    {headerGroup.headers.map((header) => (
                      <th
                        key={header.id}
                        onClick={header.column.getToggleSortingHandler()}
                        style={{
                          padding: '0.75rem',
                          textAlign: 'left',
                          borderBottom: '2px solid #dee2e6',
                          cursor: header.column.getCanSort() ? 'pointer' : 'default',
                          userSelect: 'none',
                        }}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {{
                          asc: ' 🔼',
                          desc: ' 🔽',
                        }[header.column.getIsSorted() as string] ?? null}
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody>
                {table.getRowModel().rows.map((row) => (
                  <tr 
                    key={row.id}
                    style={{ 
                      borderBottom: '1px solid #dee2e6',
                      transition: 'background-color 0.2s'
                    }}
                    onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#f8f9fa'}
                    onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'white'}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} style={{ padding: '0.75rem' }}>
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {data && (
            <div style={{ 
              display: 'flex', 
              justifyContent: 'space-between', 
              alignItems: 'center',
              marginTop: '1rem',
              padding: '1rem',
              backgroundColor: '#f8f9fa',
              borderRadius: '4px'
            }}>
              <div>
                Showing {data.items.length} of {data.total} endpoints
              </div>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <button
                  onClick={() => handlePageChange(filters.page! - 1)}
                  disabled={filters.page === 1}
                  style={{
                    padding: '0.5rem 1rem',
                    border: '1px solid #ddd',
                    borderRadius: '4px',
                    backgroundColor: 'white',
                    cursor: filters.page === 1 ? 'not-allowed' : 'pointer',
                    opacity: filters.page === 1 ? 0.5 : 1
                  }}
                >
                  Previous
                </button>
                <span style={{ padding: '0.5rem 1rem' }}>
                  Page {filters.page}
                </span>
                <button
                  onClick={() => handlePageChange(filters.page! + 1)}
                  disabled={!data.has_next}
                  style={{
                    padding: '0.5rem 1rem',
                    border: '1px solid #ddd',
                    borderRadius: '4px',
                    backgroundColor: 'white',
                    cursor: !data.has_next ? 'not-allowed' : 'pointer',
                    opacity: !data.has_next ? 0.5 : 1
                  }}
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};

// Helper functions for colors
function getMethodColor(method: string): string {
  const colors: Record<string, string> = {
    GET: '#28a745',
    POST: '#007bff',
    PUT: '#ffc107',
    PATCH: '#17a2b8',
    DELETE: '#dc3545',
  };
  return colors[method] || '#6c757d';
}

function getStatusColor(status: LifecycleStatus): string {
  const colors: Record<LifecycleStatus, string> = {
    Active: '#28a745',
    Deprecated: '#ffc107',
    Orphaned: '#fd7e14',
    Zombie: '#dc3545',
    Shadow_API: '#6f42c1',
  };
  return colors[status] || '#6c757d';
}

function getRiskColor(score: number): string {
  if (score <= 33) return '#28a745'; // green
  if (score <= 66) return '#ffc107'; // amber
  return '#dc3545'; // red
}
