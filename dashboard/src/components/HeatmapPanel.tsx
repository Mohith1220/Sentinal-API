import React, { useEffect, useRef, useState } from 'react';
import * as d3 from 'd3';
import { useQuery } from '@tanstack/react-query';
import { endpointsApi } from '../lib/api';
import type { EndpointRecord, LifecycleStatus, DataSensitivity } from '../types/api';
import { Shield, HelpCircle, Activity } from 'lucide-react';

interface HeatmapCell {
  lifecycle: LifecycleStatus;
  sensitivity: DataSensitivity;
  count: number;
  avgRisk: number;
  endpoints: EndpointRecord[];
}

export const HeatmapPanel: React.FC = () => {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoveredCell, setHoveredCell] = useState<HeatmapCell | null>(null);

  // Fetch all endpoints to aggregate locally
  const { data: endpointsData, isLoading } = useQuery({
    queryKey: ['endpoints-heatmap'],
    queryFn: () => endpointsApi.getEndpoints({ page_size: 1000 }), // large page size for accurate local aggregation
  });

  useEffect(() => {
    if (isLoading || !endpointsData?.items || !svgRef.current) return;

    const items = endpointsData.items;

    // Define standard categories
    const lifecycles: LifecycleStatus[] = ['Active', 'Deprecated', 'Orphaned', 'Shadow_API', 'Zombie'];
    const sensitivities: DataSensitivity[] = ['public', 'internal', 'PII', 'financial'];

    // Group items into cell matrices
    const cells: HeatmapCell[] = [];
    lifecycles.forEach(lif => {
      sensitivities.forEach(sens => {
        const matching = items.filter(
          item => item.lifecycle_status === lif && item.data_sensitivity === sens
        );
        const avgRisk = matching.length > 0
          ? matching.reduce((sum, current) => sum + current.risk_score, 0) / matching.length
          : 0;

        cells.push({
          lifecycle: lif,
          sensitivity: sens,
          count: matching.length,
          avgRisk: Math.round(avgRisk),
          endpoints: matching,
        });
      });
    });

    const margin = { top: 40, right: 20, bottom: 50, left: 110 };
    const width = 500 - margin.left - margin.right;
    const height = 350 - margin.top - margin.bottom;

    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const g = svg.append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`);

    // X scale
    const x = d3.scaleBand()
      .range([0, width])
      .domain(sensitivities)
      .padding(0.08);

    // Y scale
    const y = d3.scaleBand()
      .range([height, 0])
      .domain(lifecycles)
      .padding(0.08);

    // Add X Axis
    g.append('g')
      .attr('transform', `translate(0,${height})`)
      .call(d3.axisBottom(x).tickSize(0))
      .select('.domain').remove();

    g.selectAll('.tick text')
      .attr('font-size', '10px')
      .attr('font-family', 'JetBrains Mono, monospace')
      .attr('fill', '#9ca3af')
      .attr('dy', '15px')
      .text(d => (d as string).toUpperCase());

    // Add Y Axis
    g.append('g')
      .call(d3.axisLeft(y).tickSize(0))
      .select('.domain').remove();

    g.selectAll('g.tick text')
      .attr('font-size', '10px')
      .attr('font-family', 'JetBrains Mono, monospace')
      .attr('fill', '#9ca3af')
      .attr('dx', '-8px')
      .text(d => (d as string).replace('_', ' ').toUpperCase());

    // Cell coloring scale (deep steel to glowing red)
    const colorScale = d3.scaleLinear<string>()
      .domain([0, 1, 5, 15])
      .range(['rgba(30, 41, 59, 0.25)', 'rgba(16, 185, 129, 0.45)', 'rgba(249, 115, 22, 0.65)', 'rgba(239, 68, 68, 0.95)']);

    // Draw Heatmap rect tiles
    g.selectAll()
      .data(cells)
      .join('rect')
      .attr('x', d => x(d.sensitivity) || 0)
      .attr('y', d => y(d.lifecycle) || 0)
      .attr('rx', 4)
      .attr('ry', 4)
      .attr('width', x.bandwidth())
      .attr('height', y.bandwidth())
      .style('fill', d => colorScale(d.count))
      .style('stroke', d => (d.count > 0 ? 'rgba(255, 255, 255, 0.08)' : 'rgba(255,255,255,0.02)'))
      .style('stroke-width', '1px')
      .style('cursor', 'pointer')
      .style('transition', 'all 0.2s')
      .on('mouseover', function(_event, d) {
        d3.select(this)
          .style('stroke', '#06b6d4')
          .style('stroke-width', '2px')
          .style('filter', 'drop-shadow(0 0 6px rgba(6,182,212,0.4))');
        setHoveredCell(d);
      })
      .on('mouseleave', function() {
        d3.select(this)
          .style('stroke', d => ((d as any).count > 0 ? 'rgba(255, 255, 255, 0.08)' : 'rgba(255,255,255,0.02)'))
          .style('stroke-width', '1px')
          .style('filter', 'none');
      });

    // Add text labels inside tiles (only for non-zero counts)
    g.selectAll()
      .data(cells)
      .join('text')
      .attr('x', d => (x(d.sensitivity) || 0) + x.bandwidth() / 2)
      .attr('y', d => (y(d.lifecycle) || 0) + y.bandwidth() / 2 + 4)
      .attr('text-anchor', 'middle')
      .attr('font-size', '10px')
      .attr('font-family', 'JetBrains Mono, monospace')
      .attr('font-weight', 'bold')
      .attr('fill', d => (d.count > 0 ? '#ffffff' : 'rgba(255, 255, 255, 0.15)'))
      .text(d => d.count);

  }, [endpointsData, isLoading]);

  return (
    <div className="glass-panel border border-cyber-border p-5 flex flex-col lg:flex-row gap-6 font-mono text-xs select-none">
      {/* HEATMAP CHART CANVAS */}
      <div className="flex-1 flex flex-col items-center justify-center relative min-h-[350px]" ref={containerRef}>
        {isLoading ? (
          <div className="flex flex-col items-center gap-3">
            <div className="w-8 h-8 rounded-full border-4 border-cyber-border border-t-cyber-cyan animate-spin" />
            <span className="text-[10px] text-cyber-cyan animate-pulse">BINNING EXPOSURE HOTSPOTS...</span>
          </div>
        ) : (
          <>
            <div className="absolute top-0 left-0 text-[10px] text-gray-500 flex items-center gap-1.5">
              <Activity className="w-3.5 h-3.5 text-cyber-cyan" />
              <span>D3_MATRIX_RENDER: EXPOSURE_DENSITY</span>
            </div>
            <svg
              ref={svgRef}
              width={500}
              height={350}
              className="max-w-full block bg-transparent"
            />
          </>
        )}
      </div>

      {/* DYNAMIC HUD METRICS OVERLAY */}
      <div className="w-full lg:w-72 border-t lg:border-t-0 lg:border-l border-cyber-border pt-4 lg:pt-0 lg:pl-6 flex flex-col gap-4">
        <div className="flex items-center gap-2 border-b border-cyber-border pb-2 text-cyber-cyan font-bold">
          <Shield className="w-4 h-4" />
          <span>CELL_DIAGNOSTICS</span>
        </div>

        {hoveredCell ? (
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <span className="text-[10px] text-gray-500">LIFECYCLE_ZONE:</span>
              <span className="text-white font-bold text-sm tracking-wider">
                {hoveredCell.lifecycle.replace('_', ' ').toUpperCase()}
              </span>
            </div>
            <div className="flex flex-col gap-1.5">
              <span className="text-[10px] text-gray-500">DATA_ASSET_SENSITIVITY:</span>
              <span className={`font-bold text-xs uppercase ${
                hoveredCell.sensitivity === 'financial' ? 'text-cyber-amber' :
                hoveredCell.sensitivity === 'PII' ? 'text-cyber-purple' : 'text-gray-300'
              }`}>
                {hoveredCell.sensitivity}
              </span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-gray-500">API_COUNT:</span>
              <span className="text-cyber-blue text-lg font-bold">{hoveredCell.count} Endpoints</span>
            </div>
            <div className="flex flex-col gap-1.5">
              <span className="text-[10px] text-gray-500">AVERAGE_RISK_SCORE:</span>
              <span className={`px-2 py-0.5 rounded text-xs font-bold border inline-block w-fit ${
                hoveredCell.avgRisk >= 75 ? 'text-cyber-red bg-cyber-red/10 border-cyber-red/30' :
                hoveredCell.avgRisk >= 40 ? 'text-cyber-amber bg-cyber-amber/10 border-cyber-amber/20' :
                hoveredCell.count > 0 ? 'text-cyber-green bg-cyber-green/10 border-cyber-green/20' : 'text-gray-600 border-cyber-border'
              }`}>
                {hoveredCell.avgRisk} / 100
              </span>
            </div>

            {/* List top anomalous endpoint previews in this cell */}
            {hoveredCell.endpoints.length > 0 && (
              <div className="flex flex-col gap-2 mt-2">
                <span className="text-[10px] text-gray-500">HIGHEST_RISK_RECORDS:</span>
                <div className="flex flex-col gap-1.5 max-h-32 overflow-y-auto">
                  {hoveredCell.endpoints.slice(0, 3).map((ep) => (
                    <div key={ep.id} className="bg-black/30 rounded border border-cyber-border p-1.5 flex flex-col gap-0.5 text-[10px]">
                      <div className="flex justify-between items-center text-[10px] font-bold text-gray-400">
                        <span>{ep.http_method}</span>
                        <span className="text-cyber-red">{ep.risk_score} Risk</span>
                      </div>
                      <code className="text-cyber-cyan truncate">{ep.path}</code>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="h-full flex flex-col items-center justify-center text-center text-gray-500 py-12 gap-2">
            <HelpCircle className="w-10 h-10 text-gray-600 animate-bounce" />
            <p className="text-[11px] leading-relaxed">
              Hover mouse cursor over any heatmap matrix grid cell to output active diagnostic metrics, aggregated risk indexes, and anomalous endpoints.
            </p>
          </div>
        )}
      </div>
    </div>
  );
};
