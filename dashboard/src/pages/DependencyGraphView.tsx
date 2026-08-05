import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { graphApi } from '../lib/api';
import { DependencyGraph } from '../components/DependencyGraph';
import { NodeDetailsPanel } from '../components/NodeDetailsPanel';
import { Network, Search, RefreshCw } from 'lucide-react';

export const DependencyGraphView: React.FC = () => {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  // Fetch Dependency Graph Topology
  const { data: graphData, isLoading, refetch } = useQuery({
    queryKey: ['graph-full'],
    queryFn: graphApi.getGraph,
  });

  // Filter nodes matching search query
  const filteredGraphData = React.useMemo(() => {
    if (!graphData) return { nodes: [], edges: [] };
    if (!searchQuery) return graphData;

    const query = searchQuery.toLowerCase();
    const matchedNodes = graphData.nodes.filter(
      node =>
        node.label.toLowerCase().includes(query) ||
        node.type.toLowerCase().includes(query) ||
        (node.properties.lifecycle_status || '').toLowerCase().includes(query)
    );

    const matchedNodeIds = new Set(matchedNodes.map(n => n.id));
    const matchedEdges = graphData.edges.filter(
      edge => matchedNodeIds.has(edge.source) || matchedNodeIds.has(edge.target)
    );

    return {
      nodes: matchedNodes,
      edges: matchedEdges,
    };
  }, [graphData, searchQuery]);

  return (
    <div className="flex flex-col gap-6 font-mono text-xs select-none">
      
      {/* Header and Toolbar */}
      <div className="glass-panel border border-cyber-border p-4 flex flex-col md:flex-row items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded bg-cyber-cyan/15 border border-cyber-cyan/35 flex items-center justify-center">
            <Network className="w-5 h-5 text-cyber-cyan" />
          </div>
          <div>
            <h2 className="font-bold text-gray-200 text-sm tracking-wider uppercase">CALL_DEPENDENCY_INTEL_MESH</h2>
            <div className="text-[10px] text-gray-400 mt-0.5">
              Visualizing routing connections between client API gateways, banking core microservices, and databases.
            </div>
          </div>
        </div>

        {/* Search isolate & refresh */}
        <div className="flex items-center gap-3 w-full md:w-auto">
          <div className="relative flex-1 md:w-64">
            <Search className="absolute left-3 top-2 w-3.5 h-3.5 text-cyber-cyan" />
            <input
              type="text"
              placeholder="Isolate node by label/type..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-black/30 border border-cyber-border rounded pl-8 pr-3 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-cyber-cyan placeholder-gray-600"
            />
          </div>
          
          <button
            onClick={() => refetch()}
            className="p-2 rounded border border-cyber-border hover:border-cyber-cyan bg-cyber-panel hover:bg-cyber-cyan/10 text-gray-400 hover:text-cyber-cyan transition-colors cursor-pointer"
            title="Refresh Mesh"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Main Full View Canvas */}
      <div className="glass-panel border border-cyber-border p-5 flex flex-col gap-4 relative">
        {isLoading ? (
          <div className="w-full h-[580px] bg-black/25 flex flex-col items-center justify-center gap-3">
            <div className="w-8 h-8 rounded-full border-4 border-cyber-border border-t-cyber-cyan animate-spin" />
            <span className="text-[10px] text-cyber-cyan animate-pulse">COMPILING DEPENDENCY CONNECTIONS...</span>
          </div>
        ) : (
          <DependencyGraph
            data={filteredGraphData}
            onNodeSelect={setSelectedNodeId}
            selectedNodeId={selectedNodeId}
          />
        )}
      </div>

      {/* Node details slide panel drawer */}
      {selectedNodeId && (
        <NodeDetailsPanel
          nodeId={selectedNodeId}
          onClose={() => setSelectedNodeId(null)}
        />
      )}
    </div>
  );
};
