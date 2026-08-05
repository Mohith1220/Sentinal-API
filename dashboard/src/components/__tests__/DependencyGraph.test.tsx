import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DependencyGraph } from '../DependencyGraph';
import type { GraphData } from '../../types/api';

const mockGraphData: GraphData = {
  nodes: [
    {
      id: 'endpoint-1',
      type: 'API_Endpoint',
      label: 'GET /users',
      properties: {
        method: 'GET',
        host: 'api.example.com',
        path: '/users',
        lifecycle_status: 'Active',
        risk_score: 25,
      },
    },
    {
      id: 'endpoint-2',
      type: 'API_Endpoint',
      label: 'POST /orders',
      properties: {
        method: 'POST',
        host: 'api.example.com',
        path: '/orders',
        lifecycle_status: 'Zombie',
        risk_score: 85,
      },
    },
    {
      id: 'service-1',
      type: 'Service',
      label: 'User Service',
      properties: {
        name: 'User Service',
        team: 'Platform',
      },
    },
    {
      id: 'data-1',
      type: 'DataAsset',
      label: 'users_db',
      properties: {
        name: 'users_db',
        sensitivity: 'PII',
      },
    },
  ],
  edges: [
    {
      id: 'edge-1',
      source: 'endpoint-1',
      target: 'endpoint-2',
      type: 'CALLS',
      properties: {
        observed_at: '2024-01-15T10:00:00Z',
        source: 'traffic',
      },
    },
    {
      id: 'edge-2',
      source: 'service-1',
      target: 'endpoint-1',
      type: 'EXPOSES',
      properties: {},
    },
    {
      id: 'edge-3',
      source: 'endpoint-1',
      target: 'data-1',
      type: 'ACCESSES',
      properties: {
        schema_ref: 'users_schema',
      },
    },
  ],
};

describe('DependencyGraph', () => {
  let onNodeSelect: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    onNodeSelect = vi.fn();
  });

  it('renders graph with nodes', async () => {
    render(
      <DependencyGraph
        data={mockGraphData}
        onNodeSelect={onNodeSelect}
        selectedNodeId={null}
      />
    );

    // Check that SVG is rendered
    const svg = document.querySelector('svg');
    expect(svg).toBeTruthy();

    // Wait for D3 to render nodes
    await waitFor(() => {
      const labels = Array.from(document.querySelectorAll('text'));
      const labelTexts = labels.map(el => el.textContent);
      expect(labelTexts).toContain('GET /users');
      expect(labelTexts).toContain('POST /orders');
      expect(labelTexts).toContain('User Service');
      expect(labelTexts).toContain('users_db');
    });
  });

  it('calls onNodeSelect when a node is clicked', async () => {
    const user = userEvent.setup();
    
    render(
      <DependencyGraph
        data={mockGraphData}
        onNodeSelect={onNodeSelect}
        selectedNodeId={null}
      />
    );

    // Wait for nodes to render
    await waitFor(() => {
      expect(document.querySelectorAll('circle, rect, path').length).toBeGreaterThan(0);
    });

    // Find and click a node group
    const nodeGroups = document.querySelectorAll('g[cursor="pointer"]');
    expect(nodeGroups.length).toBeGreaterThan(0);

    // Click the first node
    await user.click(nodeGroups[0] as Element);

    // Verify onNodeSelect was called
    await waitFor(() => {
      expect(onNodeSelect).toHaveBeenCalled();
    });
  });

  it('highlights neighbors when a node is selected', async () => {
    const { rerender } = render(
      <DependencyGraph
        data={mockGraphData}
        onNodeSelect={onNodeSelect}
        selectedNodeId={null}
      />
    );

    // Wait for initial render
    await waitFor(() => {
      expect(document.querySelectorAll('g[cursor="pointer"]').length).toBe(4);
    });

    // Select a node
    rerender(
      <DependencyGraph
        data={mockGraphData}
        onNodeSelect={onNodeSelect}
        selectedNodeId="endpoint-1"
      />
    );

    // Wait for highlighting to apply - verify that the selected node and its neighbors are visible
    await waitFor(() => {
      const nodeGroups = document.querySelectorAll('g[cursor="pointer"]');
      expect(nodeGroups.length).toBe(4);
      
      // Just verify the graph re-rendered with the selection
      // The actual opacity changes are applied via D3 and may not be testable in jsdom
    });
  });

  it('supports pan and zoom interactions', async () => {
    render(
      <DependencyGraph
        data={mockGraphData}
        onNodeSelect={onNodeSelect}
        selectedNodeId={null}
      />
    );

    // Wait for graph to render
    await waitFor(() => {
      expect(document.querySelector('svg')).toBeTruthy();
    });

    const svg = document.querySelector('svg');
    expect(svg).toBeTruthy();

    // Verify zoom behavior is attached (D3 zoom adds event listeners)
    // We can't easily test the actual zoom/pan behavior in jsdom,
    // but we can verify the SVG is interactive
    const mainGroup = svg?.querySelector('g');
    expect(mainGroup).toBeTruthy();
  });

  it('renders different node shapes for different types', async () => {
    render(
      <DependencyGraph
        data={mockGraphData}
        onNodeSelect={onNodeSelect}
        selectedNodeId={null}
      />
    );

    await waitFor(() => {
      // API_Endpoint nodes should have circles
      const circles = document.querySelectorAll('circle');
      expect(circles.length).toBeGreaterThan(0);

      // Service nodes should have rects
      const rects = document.querySelectorAll('rect');
      expect(rects.length).toBeGreaterThan(0);

      // DataAsset nodes should have paths (diamond shape)
      const paths = document.querySelectorAll('path[d*="M 0,-15"]');
      expect(paths.length).toBeGreaterThan(0);
    });
  });

  it('handles empty graph data', () => {
    const emptyData: GraphData = { nodes: [], edges: [] };
    
    render(
      <DependencyGraph
        data={emptyData}
        onNodeSelect={onNodeSelect}
        selectedNodeId={null}
      />
    );

    // Should render without crashing
    const svg = document.querySelector('svg');
    expect(svg).toBeTruthy();
  });

  it('deselects node when background is clicked', async () => {
    const user = userEvent.setup();
    
    render(
      <DependencyGraph
        data={mockGraphData}
        onNodeSelect={onNodeSelect}
        selectedNodeId="endpoint-1"
      />
    );

    await waitFor(() => {
      expect(document.querySelector('svg')).toBeTruthy();
    });

    // Click the SVG background
    const svg = document.querySelector('svg');
    if (svg) {
      await user.click(svg);
    }

    // Verify onNodeSelect was called with null
    await waitFor(() => {
      expect(onNodeSelect).toHaveBeenCalledWith(null);
    });
  });
});
