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
import { SlidersHorizontal, ArrowUpDown, ChevronLeft, ChevronRight, Eye } from 'lucide-react';

interface APIDataTableProps {
  onRowSelect?: (endpointId: string) => void;
  selectedEndpointId?: string | null;
}

export const APIDataTable: React.FC<APIDataTableProps> = ({
  onRowSelect,
  selectedEndpointId,
}) => {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [filters, setFilters] = useState<EndpointFilters>({
    page: 1,
    page_size: 15,
  });

  // Query endpoints based on our filters and search queries
  const { data, isLoading, error } = useQuery({
    queryKey: ['endpoints', filters],
    queryFn: () => endpointsApi.getEndpoints(filters),
  });

  const columns = useMemo<ColumnDef<EndpointRecord>[]>(
    () => [
      {
        accessorKey: 'http_method',
        header: 'METHOD',
        cell: (info) => {
          const method = info.getValue() as string;
          return (
            <span className={`px-2 py-0.5 rounded font-mono font-bold text-xs tracking-wider border ${getMethodStyles(method)}`}>
              {method}
            </span>
          );
        },
      },
      {
        accessorKey: 'path',
        header: 'ENDPOINT PATH',
        cell: (info) => {
          const path = info.getValue() as string;
          return (
            <code className="text-xs text-cyber-cyan font-mono bg-black/30 px-1.5 py-0.5 rounded border border-white/5 truncate max-w-[240px] inline-block" title={path}>
              {path}
            </code>
          );
        },
      },
      {
        accessorKey: 'lifecycle_status',
        header: 'STATUS',
        cell: (info) => {
          const status = info.getValue() as LifecycleStatus;
          return (
            <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-bold tracking-wide uppercase border ${getStatusStyles(status)}`}>
              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${getStatusDotStyles(status)}`} />
              {status.replace('_', ' ')}
            </span>
          );
        },
      },
      {
        accessorKey: 'risk_score',
        header: 'RISK SCORE',
        cell: (info) => {
          const score = info.getValue() as number;
          return (
            <span className={`px-2 py-0.5 rounded text-xs font-mono font-bold border ${getRiskStyles(score)}`}>
              {score} / 100
            </span>
          );
        },
      },
      {
        accessorKey: 'auth_scheme',
        header: 'AUTH SCHEME',
        cell: (info) => {
          const scheme = info.getValue() as AuthScheme;
          return (
            <span className={`text-xs font-mono px-2 py-0.5 rounded ${
              scheme === 'none' ? 'text-cyber-red bg-cyber-red/10 border border-cyber-red/20' : 'text-gray-300'
            }`}>
              {scheme}
            </span>
          );
        },
      },
      {
        accessorKey: 'data_sensitivity',
        header: 'SENSITIVITY',
        cell: (info) => {
          const sens = info.getValue() as DataSensitivity;
          return (
            <span className={`px-2 py-0.5 rounded text-xs font-bold ${
              sens === 'financial' ? 'text-cyber-amber bg-cyber-amber/10 border border-cyber-amber/20' :
              sens === 'PII' ? 'text-cyber-purple bg-cyber-purple/10 border border-cyber-purple/20' : 'text-gray-400'
            }`}>
              {sens.toUpperCase()}
            </span>
          );
        },
      },
      {
        accessorKey: 'request_count_24h',
        header: 'TRAFFIC (24H)',
        cell: (info) => {
          const val = info.getValue() as number;
          return <span className="font-mono text-xs text-cyber-blue font-bold">{val.toLocaleString()} Req</span>;
        },
      },
      {
        id: 'actions',
        header: 'ACTION',
        cell: (info) => (
          <button
            onClick={(e) => {
              e.stopPropagation();
              if (onRowSelect) onRowSelect(info.row.original.id);
            }}
            className="p-1 rounded border border-cyber-border hover:border-cyber-cyan hover:bg-cyber-cyan/10 text-gray-400 hover:text-cyber-cyan transition-colors"
            title="Inspect Details"
          >
            <Eye className="w-3.5 h-3.5" />
          </button>
        ),
      },
    ],
    [onRowSelect]
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
      page: 1, // Reset page
    }));
  };

  const handlePageChange = (newPage: number) => {
    setFilters((prev) => ({ ...prev, page: newPage }));
  };

  // Helper styles mappings
  const getMethodStyles = (method: string) => {
    switch (method) {
      case 'GET': return 'text-cyber-green bg-cyber-green/5 border-cyber-green/30';
      case 'POST': return 'text-cyber-blue bg-cyber-blue/5 border-cyber-blue/30';
      case 'PUT': return 'text-cyber-amber bg-cyber-amber/5 border-cyber-amber/30';
      case 'PATCH': return 'text-cyber-cyan bg-cyber-cyan/5 border-cyber-cyan/30';
      case 'DELETE': return 'text-cyber-red bg-cyber-red/5 border-cyber-red/30';
      default: return 'text-gray-400 bg-gray-500/5 border-gray-500/30';
    }
  };

  const getStatusStyles = (status: LifecycleStatus) => {
    switch (status) {
      case 'Active': return 'text-cyber-green bg-cyber-green/5 border-cyber-green/30';
      case 'Deprecated': return 'text-cyber-yellow bg-cyber-yellow/5 border-cyber-yellow/30';
      case 'Orphaned': return 'text-cyber-amber bg-cyber-amber/5 border-cyber-amber/30';
      case 'Zombie': return 'text-cyber-red bg-cyber-red/10 border-cyber-red/40 threat-pulse-red';
      case 'Shadow_API': return 'text-cyber-purple bg-cyber-purple/10 border-cyber-purple/40';
      default: return 'text-gray-400 bg-gray-500/5 border-gray-500/30';
    }
  };

  const getStatusDotStyles = (status: LifecycleStatus) => {
    switch (status) {
      case 'Active': return 'bg-cyber-green';
      case 'Deprecated': return 'bg-cyber-yellow';
      case 'Orphaned': return 'bg-cyber-amber';
      case 'Zombie': return 'bg-cyber-red animate-ping';
      case 'Shadow_API': return 'bg-cyber-purple animate-pulse';
      default: return 'bg-gray-400';
    }
  };

  const getRiskStyles = (score: number) => {
    if (score >= 75) return 'text-cyber-red bg-cyber-red/10 border-cyber-red/30 shadow-[0_0_10px_rgba(239,68,68,0.15)]';
    if (score >= 40) return 'text-cyber-amber bg-cyber-amber/10 border-cyber-amber/20';
    return 'text-cyber-green bg-cyber-green/10 border-cyber-green/20';
  };

  return (
    <div className="flex flex-col gap-4 font-mono">
      {/* FILTER CONTROL BAR */}
      <div className="glass-panel border border-cyber-border p-4 flex flex-col gap-4">
        <div className="flex items-center justify-between text-xs text-cyber-cyan border-b border-cyber-border pb-2">
          <span className="flex items-center gap-1.5">
            <SlidersHorizontal className="w-4 h-4" />
            <span>CRITERIA_FILTERS</span>
          </span>
          <span className="text-[10px] text-gray-500">Querying live gateway cache</span>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-xs">
          {/* Status filter */}
          <div className="flex flex-col gap-1.5">
            <label className="text-gray-500">LIFECYCLE_STATUS:</label>
            <select
              value={filters.lifecycle_status || ''}
              onChange={(e) => handleFilterChange('lifecycle_status', e.target.value as LifecycleStatus)}
              className="bg-black/30 border border-cyber-border rounded px-2.5 py-1.5 text-gray-300 focus:outline-none focus:border-cyber-cyan"
            >
              <option value="">ALL STATUSES</option>
              <option value="Active">ACTIVE</option>
              <option value="Deprecated">DEPRECATED</option>
              <option value="Orphaned">ORPHANED</option>
              <option value="Zombie">ZOMBIE API</option>
              <option value="Shadow_API">SHADOW API</option>
            </select>
          </div>

          {/* Auth filter */}
          <div className="flex flex-col gap-1.5">
            <label className="text-gray-500">AUTHENTICATION:</label>
            <select
              value={filters.auth_scheme || ''}
              onChange={(e) => handleFilterChange('auth_scheme', e.target.value as AuthScheme)}
              className="bg-black/30 border border-cyber-border rounded px-2.5 py-1.5 text-gray-300 focus:outline-none focus:border-cyber-cyan"
            >
              <option value="">ALL METHOD SCHEMES</option>
              <option value="OAuth2">OAUTH2</option>
              <option value="JWT">JWT TOKEN</option>
              <option value="api_key">API KEY</option>
              <option value="none">NONE (UNSECURED)</option>
              <option value="unknown">UNKNOWN</option>
            </select>
          </div>

          {/* Sensitivity filter */}
          <div className="flex flex-col gap-1.5">
            <label className="text-gray-500">DATA_EXPOSURE:</label>
            <select
              value={filters.data_sensitivity || ''}
              onChange={(e) => handleFilterChange('data_sensitivity', e.target.value as DataSensitivity)}
              className="bg-black/30 border border-cyber-border rounded px-2.5 py-1.5 text-gray-300 focus:outline-none focus:border-cyber-cyan"
            >
              <option value="">ALL DATA ASSETS</option>
              <option value="PII">PII (IDENTITY)</option>
              <option value="financial">FINANCIAL (CARD/LEDGER)</option>
              <option value="internal">INTERNAL RESTRICTED</option>
              <option value="public">PUBLIC DIRECTORY</option>
            </select>
          </div>

          {/* Risk Range Min */}
          <div className="flex flex-col gap-1.5">
            <label className="text-gray-500">MIN_RISK:</label>
            <input
              type="number"
              min="0"
              max="100"
              value={filters.risk_score_min ?? ''}
              onChange={(e) => handleFilterChange('risk_score_min', e.target.value ? parseInt(e.target.value) : undefined)}
              className="bg-black/30 border border-cyber-border rounded px-2.5 py-1.5 text-gray-300 placeholder-gray-600 focus:outline-none focus:border-cyber-cyan"
              placeholder="0"
            />
          </div>

          {/* Risk Range Max */}
          <div className="flex flex-col gap-1.5">
            <label className="text-gray-500">MAX_RISK:</label>
            <input
              type="number"
              min="0"
              max="100"
              value={filters.risk_score_max ?? ''}
              onChange={(e) => handleFilterChange('risk_score_max', e.target.value ? parseInt(e.target.value) : undefined)}
              className="bg-black/30 border border-cyber-border rounded px-2.5 py-1.5 text-gray-300 placeholder-gray-600 focus:outline-none focus:border-cyber-cyan"
              placeholder="100"
            />
          </div>
        </div>
      </div>

      {/* DATA GRAPH SHEET */}
      {isLoading ? (
        <div className="glass-panel border border-cyber-border p-12 flex flex-col items-center justify-center gap-3">
          <div className="w-10 h-10 rounded-full border-4 border-cyber-border border-t-cyber-cyan animate-spin" />
          <span className="text-xs text-cyber-cyan animate-pulse">QUERYING GATEWAY RECORDS...</span>
        </div>
      ) : error ? (
        <div className="glass-panel border border-cyber-red/40 bg-cyber-red/5 p-6 text-center text-cyber-red text-xs">
          ERROR_CODE: DATABASE_CONNECTION_FAILED - Failed to pull latest discovery lists
        </div>
      ) : (
        <div className="glass-panel border border-cyber-border overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                {table.getHeaderGroups().map((headerGroup) => (
                  <tr key={headerGroup.id} className="bg-black/30 border-b border-cyber-border/80">
                    {headerGroup.headers.map((header) => (
                      <th
                        key={header.id}
                        onClick={header.column.getToggleSortingHandler()}
                        className="p-3 text-[11px] text-gray-400 font-bold tracking-wider cursor-pointer hover:bg-white/5 select-none transition-colors"
                      >
                        <div className="flex items-center gap-1">
                          <span>{flexRender(header.column.columnDef.header, header.getContext())}</span>
                          {header.column.getCanSort() && <ArrowUpDown className="w-3 h-3 text-gray-500" />}
                        </div>
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody className="divide-y divide-cyber-border/40 bg-cyber-panel/20 text-xs">
                {table.getRowModel().rows.length === 0 ? (
                  <tr>
                    <td colSpan={columns.length} className="p-8 text-center text-gray-500 italic">
                      No APIs discovered matching selection criteria
                    </td>
                  </tr>
                ) : (
                  table.getRowModel().rows.map((row) => {
                    const isSelected = selectedEndpointId === row.original.id;
                    return (
                      <tr
                        key={row.id}
                        onClick={() => {
                          if (onRowSelect) onRowSelect(row.original.id);
                        }}
                        className={`hover:bg-white/5 cursor-pointer transition-colors ${
                          isSelected ? 'bg-cyber-cyan/5 border-l-2 border-l-cyber-cyan' : ''
                        }`}
                      >
                        {row.getVisibleCells().map((cell) => (
                          <td key={cell.id} className="p-3 align-middle text-gray-300 font-medium">
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </td>
                        ))}
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {/* PAGINATION PANEL */}
          {data && (
            <div className="flex items-center justify-between p-3 border-t border-cyber-border bg-black/20 text-[11px] text-gray-500 select-none">
              <div>
                SHOWING <span className="text-gray-300 font-bold">{data.items.length}</span> OF{' '}
                <span className="text-gray-300 font-bold">{data.total}</span> ENDPOINTS DISCOVERED
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => handlePageChange(filters.page! - 1)}
                  disabled={filters.page === 1}
                  className="px-2 py-1 rounded border border-cyber-border hover:border-cyber-cyan bg-cyber-panel text-gray-400 hover:text-cyber-cyan transition-colors disabled:opacity-30 disabled:pointer-events-none cursor-pointer"
                >
                  <ChevronLeft className="w-3.5 h-3.5" />
                </button>
                <span className="font-bold text-gray-300">PAGE {filters.page}</span>
                <button
                  onClick={() => handlePageChange(filters.page! + 1)}
                  disabled={!data.has_next}
                  className="px-2 py-1 rounded border border-cyber-border hover:border-cyber-cyan bg-cyber-panel text-gray-400 hover:text-cyber-cyan transition-colors disabled:opacity-30 disabled:pointer-events-none cursor-pointer"
                >
                  <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
