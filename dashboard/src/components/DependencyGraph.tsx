import React, { useEffect, useRef, useState } from 'react';
import * as d3 from 'd3';
import type { GraphNode, GraphEdge, GraphData } from '../types/api';
import { ZoomIn, ZoomOut, Maximize2, ShieldAlert, Layers } from 'lucide-react';

interface DependencyGraphProps {
  data: GraphData;
  onNodeSelect: (nodeId: string | null) => void;
  selectedNodeId: string | null;
}

interface D3Node extends d3.SimulationNodeDatum, GraphNode {
  x?: number;
  y?: number;
}

interface D3Link extends d3.SimulationLinkDatum<D3Node> {
  id: string;
  type: string;
  properties: GraphEdge['properties'];
}

export const DependencyGraph: React.FC<DependencyGraphProps> = ({
  data,
  onNodeSelect,
  selectedNodeId,
}) => {
  const svgRef = useRef<SVGSVGElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const [highlightAttackPaths, setHighlightAttackPaths] = useState(true);

  const nodesList = data?.nodes || [];
  const edgesList = data?.edges || [];

  // Resize listener
  useEffect(() => {
    const updateDimensions = () => {
      if (svgRef.current) {
        const container = svgRef.current.parentElement;
        if (container) {
          setDimensions({
            width: container.clientWidth,
            height: Math.max(500, container.clientHeight),
          });
        }
      }
    };
    updateDimensions();
    window.addEventListener('resize', updateDimensions);
    return () => window.removeEventListener('resize', updateDimensions);
  }, []);

  useEffect(() => {
    if (!svgRef.current || !nodesList.length) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const { width, height } = dimensions;

    // Define main SVG glow filter and styles
    const defs = svg.append('defs');

    // Red glow filter for Zombie nodes
    const redFilter = defs.append('filter')
      .attr('id', 'glow-red')
      .attr('x', '-50%')
      .attr('y', '-50%')
      .attr('width', '200%')
      .attr('height', '200%');
    redFilter.append('feGaussianBlur')
      .attr('stdDeviation', '4')
      .attr('result', 'blur');
    redFilter.append('feMerge').selectAll('feMergeNode')
      .data(['blur', 'SourceGraphic'])
      .join('feMergeNode')
      .attr('in', d => d);

    // Cyan glow filter for selected nodes
    const cyanFilter = defs.append('filter')
      .attr('id', 'glow-cyan')
      .attr('x', '-50%')
      .attr('y', '-50%')
      .attr('width', '200%')
      .attr('height', '200%');
    cyanFilter.append('feGaussianBlur')
      .attr('stdDeviation', '5')
      .attr('result', 'blur');
    cyanFilter.append('feMerge').selectAll('feMergeNode')
      .data(['blur', 'SourceGraphic'])
      .join('feMergeNode')
      .attr('in', d => d);

    // Zoom setup
    const zoomBehavior = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 4])
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
      });

    svg.call(zoomBehavior);

    // Create main container group for pan/zoom
    const g = svg.append('g');

    // Link markers
    ['CALLS', 'EXPOSES', 'ACCESSES'].forEach(type => {
      defs.append('marker')
        .attr('id', `arrow-${type}`)
        .attr('viewBox', '0 -5 10 10')
        .attr('refX', 22)
        .attr('refY', 0)
        .attr('markerWidth', 5)
        .attr('markerHeight', 5)
        .attr('orient', 'auto')
        .append('path')
        .attr('d', 'M0,-4L8,0L0,4')
        .attr('fill', type === 'CALLS' ? '#3b82f6' : type === 'ACCESSES' ? '#06b6d4' : '#8b5cf6');
    });

    // Deep clones of nodes & links
    const nodes: D3Node[] = nodesList.map(node => ({ ...node }));
    const links: D3Link[] = edgesList.map(edge => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      type: edge.type,
      properties: edge.properties,
    }));

    // Identify attack path sets (e.g. paths connected to Zombie or Shadow APIs)
    const attackPaths = new Set<string>();
    const highRiskNodes = new Set<string>();
    
    // Find high risk node IDs
    nodes.forEach(n => {
      const risk = n.properties.risk_score || 0;
      const lifecycle = n.properties.lifecycle_status;
      if (risk >= 70 || lifecycle === 'Zombie' || lifecycle === 'Shadow_API') {
        highRiskNodes.add(n.id);
      }
    });

    // Trace connections for high risk paths
    links.forEach(l => {
      const s = typeof l.source === 'object' ? (l.source as any).id : l.source;
      const t = typeof l.target === 'object' ? (l.target as any).id : l.target;
      if (highRiskNodes.has(s) || highRiskNodes.has(t)) {
        attackPaths.add(l.id);
      }
    });

    // Force Simulation Setup
    const simulation = d3.forceSimulation<D3Node>(nodes)
      .force('link', d3.forceLink<D3Node, D3Link>(links)
        .id(d => d.id)
        .distance(120))
      .force('charge', d3.forceManyBody().strength(-350))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(45));

    // Draw links
    const link = g.append('g')
      .selectAll('line')
      .data(links)
      .join('line')
      .attr('stroke', d => {
        if (highlightAttackPaths && attackPaths.has(d.id)) return '#ef4444';
        return d.type === 'CALLS' ? 'rgba(59, 130, 246, 0.4)' : 'rgba(255, 255, 255, 0.15)';
      })
      .attr('stroke-width', d => (highlightAttackPaths && attackPaths.has(d.id) ? 2.5 : 1.5))
      .attr('marker-end', d => `url(#arrow-${d.type})`)
      .attr('stroke-dasharray', d => (highlightAttackPaths && attackPaths.has(d.id) ? '4,4' : 'none'));

    // Node classification styling helper
    const getNodeStyles = (node: GraphNode) => {
      const type = node.type;
      const risk = node.properties.risk_score || 0;
      const status = node.properties.lifecycle_status;

      if (type === 'API_Endpoint') {
        if (status === 'Zombie') return { fill: '#ef4444', stroke: '#ef4444', filter: 'url(#glow-red)' };
        if (status === 'Shadow_API') return { fill: '#8b5cf6', stroke: '#8b5cf6', filter: 'url(#glow-red)' };
        if (risk >= 70) return { fill: '#f97316', stroke: '#f97316', filter: 'none' };
        return { fill: '#10b981', stroke: '#10b981', filter: 'none' };
      }
      if (type === 'Service') return { fill: '#0ea5e9', stroke: '#0ea5e9', filter: 'none' };
      return { fill: '#06b6d4', stroke: '#06b6d4', filter: 'none' }; // DataAsset
    };

    // Draw nodes
    const nodeGroup = g.append('g')
      .selectAll('g')
      .data(nodes)
      .join('g')
      .attr('cursor', 'pointer')
      .call(d3.drag<any, any>()
        .on('start', (event, d) => {
          if (!event.active) simulation.alphaTarget(0.3).restart();
          d.fx = d.x;
          d.fy = d.y;
        })
        .on('drag', (event, d) => {
          d.fx = event.x;
          d.fy = event.y;
        })
        .on('end', (event, d) => {
          if (!event.active) simulation.alphaTarget(0);
          d.fx = null;
          d.fy = null;
        }) as any);

    // Append Node custom shapes based on node classifications
    nodeGroup.each(function(d) {
      const parent = d3.select(this);
      const styles = getNodeStyles(d);

      if (d.type === 'API_Endpoint') {
        // Glowing Circle for APIs
        parent.append('circle')
          .attr('r', 12)
          .attr('fill', styles.fill)
          .attr('stroke', styles.stroke)
          .attr('stroke-width', 2)
          .attr('filter', styles.filter);
        
        // Add core dot inside APIs
        parent.append('circle')
          .attr('r', 4)
          .attr('fill', '#050a0f');
      } else if (d.type === 'Service') {
        // Rounded Rect for Services
        parent.append('rect')
          .attr('x', -14)
          .attr('y', -14)
          .attr('width', 28)
          .attr('height', 28)
          .attr('rx', 6)
          .attr('fill', '#050a0f')
          .attr('stroke', '#0ea5e9')
          .attr('stroke-width', 2);
        
        // Micro inner detail rect
        parent.append('rect')
          .attr('x', -6)
          .attr('y', -6)
          .attr('width', 12)
          .attr('height', 12)
          .attr('rx', 2)
          .attr('fill', '#0ea5e9');
      } else {
        // Diamond representing Databases / Data Assets
        parent.append('path')
          .attr('d', 'M 0,-14 L 14,0 L 0,14 L -14,0 Z')
          .attr('fill', '#050a0f')
          .attr('stroke', '#06b6d4')
          .attr('stroke-width', 2);

        // Core inner diamond
        parent.append('circle')
          .attr('r', 3)
          .attr('fill', '#06b6d4');
      }
    });

    // Add labels
    nodeGroup.append('text')
      .text(d => d.label)
      .attr('x', 0)
      .attr('y', 24)
      .attr('text-anchor', 'middle')
      .attr('font-size', '9px')
      .attr('font-family', 'JetBrains Mono, monospace')
      .attr('fill', '#9ca3af')
      .attr('font-weight', 'medium');

    // Selection indicators
    const highlightSelections = () => {
      if (!selectedNodeId) {
        nodeGroup.style('opacity', 1);
        link.style('opacity', 1);
      } else {
        // Find adjacent node IDs
        const adjacents = new Set<string>();
        links.forEach(l => {
          const s = String(typeof l.source === 'object' ? (l.source as any).id : l.source);
          const t = String(typeof l.target === 'object' ? (l.target as any).id : l.target);
          if (s === selectedNodeId) adjacents.add(t);
          if (t === selectedNodeId) adjacents.add(s);
        });

        nodeGroup.style('opacity', d => {
          if (d.id === selectedNodeId) return 1;
          if (adjacents.has(d.id)) return 0.9;
          return 0.2;
        });

        // Set visual highlighting on select node
        nodeGroup.selectAll('circle, rect, path')
          .attr('filter', function(d: any) {
            if (d.id === selectedNodeId) return 'url(#glow-cyan)';
            return getNodeStyles(d).filter;
          });

        link.style('opacity', d => {
          const s = typeof d.source === 'object' ? d.source.id : d.source;
          const t = typeof d.target === 'object' ? d.target.id : d.target;
          if (s === selectedNodeId || t === selectedNodeId) return 1;
          return 0.1;
        });
      }
    };

    highlightSelections();

    // Node click handler
    nodeGroup.on('click', (event, d) => {
      event.stopPropagation();
      onNodeSelect(d.id);
    });

    svg.on('click', () => {
      onNodeSelect(null);
    });

    // Update coordinates on tick
    simulation.on('tick', () => {
      link
        .attr('x1', d => (d.source as D3Node).x ?? 0)
        .attr('y1', d => (d.source as D3Node).y ?? 0)
        .attr('x2', d => (d.target as D3Node).x ?? 0)
        .attr('y2', d => (d.target as D3Node).y ?? 0);

      nodeGroup.attr('transform', d => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });

    // Toolbar Control Handlers
    const handleZoomIn = () => svg.transition().duration(300).call(zoomBehavior.scaleBy, 1.3);
    const handleZoomOut = () => svg.transition().duration(300).call(zoomBehavior.scaleBy, 1 / 1.3);
    const handleReset = () => svg.transition().duration(300).call(zoomBehavior.transform, d3.zoomIdentity);

    // Expose control functions to layout buttons
    d3.select('#btn-zoom-in').on('click', handleZoomIn);
    d3.select('#btn-zoom-out').on('click', handleZoomOut);
    d3.select('#btn-zoom-reset').on('click', handleReset);

    return () => {
      simulation.stop();
    };
  }, [nodesList, edgesList, dimensions, selectedNodeId, onNodeSelect, highlightAttackPaths]);

  return (
    <div className="relative w-full h-[550px] border border-cyber-border rounded-lg overflow-hidden bg-black/20 font-mono text-xs select-none">
      {/* HUD DIAGNOSTICS & CONTROLS OVERLAY */}
      <div className="absolute top-4 left-4 z-10 flex flex-col gap-2">
        <div className="glass-panel border border-cyber-border p-3 flex flex-col gap-1.5">
          <span className="text-[10px] text-gray-500">INFRA_MAP_MONITOR</span>
          <div className="flex items-center gap-2 text-xs">
            <span className="flex items-center gap-1 font-bold text-cyber-cyan">
              <Layers className="w-3.5 h-3.5" />
              <span>ACTIVE: {nodesList.length} NODES</span>
            </span>
            <span className="text-gray-600">|</span>
            <span className="text-cyber-blue font-bold">{edgesList.length} LINKS</span>
          </div>
        </div>

        {/* Legend */}
        <div className="glass-panel border border-cyber-border p-3 flex flex-col gap-2 text-[10px] text-gray-400">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-cyber-green shrink-0" />
            <span>ACTIVE API</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-cyber-red shrink-0 animate-pulse" />
            <span className="text-cyber-red font-semibold">ZOMBIE API (GLOWING RED)</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-cyber-purple shrink-0" />
            <span className="text-cyber-purple font-semibold">SHADOW API (VIOLET)</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 bg-cyber-blue rounded shrink-0" />
            <span>MICROSERVICE</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 bg-cyber-cyan rotate-45 shrink-0" />
            <span>DATABASE / ASSET</span>
          </div>
        </div>
      </div>

      {/* TOP RIGHT TOOLBAR */}
      <div className="absolute top-4 right-4 z-10 flex items-center gap-2">
        {/* Toggle attack paths */}
        <button
          onClick={() => setHighlightAttackPaths(!highlightAttackPaths)}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded border text-[10px] font-bold transition-all ${
            highlightAttackPaths
              ? 'bg-cyber-red/10 text-cyber-red border-cyber-red/50 shadow-[0_0_10px_rgba(239,68,68,0.1)]'
              : 'border-cyber-border text-gray-400 hover:text-white'
          }`}
        >
          <ShieldAlert className="w-3.5 h-3.5" />
          <span>ATTACK PATHS</span>
        </button>

        {/* D3 Control buttons */}
        <div className="flex items-center bg-cyber-panel border border-cyber-border rounded overflow-hidden">
          <button id="btn-zoom-in" className="p-2 border-r border-cyber-border hover:bg-white/5 text-gray-400 hover:text-cyber-cyan transition-colors" title="Zoom In">
            <ZoomIn className="w-4 h-4" />
          </button>
          <button id="btn-zoom-out" className="p-2 border-r border-cyber-border hover:bg-white/5 text-gray-400 hover:text-cyber-cyan transition-colors" title="Zoom Out">
            <ZoomOut className="w-4 h-4" />
          </button>
          <button id="btn-zoom-reset" className="p-2 hover:bg-white/5 text-gray-400 hover:text-cyber-cyan transition-colors" title="Reset View">
            <Maximize2 className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* CANVAS */}
      <svg
        ref={svgRef}
        width={dimensions.width}
        height={dimensions.height}
        className="block bg-cyber-base/40"
      />
    </div>
  );
};
