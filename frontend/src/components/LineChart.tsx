/**
 * LineChart — lightweight-charts line series wrapper.
 *
 * Used for equity curves, P&L over time, performance metrics.
 * Supports multiple named series with distinct colours.
 */

import React, { useEffect, useRef } from 'react';
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  LineSeries,
  type LineData,
  type UTCTimestamp,
} from 'lightweight-charts';
import { useTheme } from './ThemeContext';

export interface LinePoint {
  time: number; // unix seconds
  value: number;
}

export interface LineSeries_ {
  name: string;
  data: LinePoint[];
  color?: string;
}

interface LineChartProps {
  series: LineSeries_[];
  height?: number;
  style?: React.CSSProperties;
  /** Show legend */
  legend?: boolean;
}

const DEFAULT_COLORS = ['#3b82f6', '#4ade80', '#f59e0b', '#f87171', '#a78bfa'];

function toLineData(p: LinePoint): LineData {
  return { time: p.time as UTCTimestamp, value: p.value };
}

export const LineChart: React.FC<LineChartProps> = ({
  series,
  height = 260,
  style,
  legend = true,
}) => {
  const containerRef  = useRef<HTMLDivElement>(null);
  const chartRef      = useRef<IChartApi | null>(null);
  const seriesRefs    = useRef<ISeriesApi<'Line'>[]>([]);
  const rafRef        = useRef<number>(0);
  const { theme }     = useTheme();
  const isDark        = theme === 'dark';

  // Create chart once
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width:  containerRef.current.clientWidth,
      height,
      layout: {
        background: { color: isDark ? '#0f172a' : '#ffffff' },
        textColor:  isDark ? '#94a3b8' : '#475569',
      },
      grid: {
        vertLines: { color: isDark ? '#1e293b' : '#e2e8f0' },
        horzLines: { color: isDark ? '#1e293b' : '#e2e8f0' },
      },
      rightPriceScale: { borderColor: isDark ? '#334155' : '#cbd5e1' },
      timeScale: {
        borderColor: isDark ? '#334155' : '#cbd5e1',
        timeVisible: true,
      },
    });

    chartRef.current = chart;

    // rAF-throttled ResizeObserver prevents layout thrashing
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(() => {
        if (containerRef.current && chartRef.current) {
          chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
        }
      });
    });
    ro.observe(containerRef.current);

    return () => {
      cancelAnimationFrame(rafRef.current);
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRefs.current = [];
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height]);

  // Update theme
  useEffect(() => {
    chartRef.current?.applyOptions({
      layout: {
        background: { color: isDark ? '#0f172a' : '#ffffff' },
        textColor:  isDark ? '#94a3b8' : '#475569',
      },
      grid: {
        vertLines: { color: isDark ? '#1e293b' : '#e2e8f0' },
        horzLines: { color: isDark ? '#1e293b' : '#e2e8f0' },
      },
    });
  }, [isDark]);

  // Sync series data
  useEffect(() => {
    if (!chartRef.current) return;

    // Remove old series
    seriesRefs.current.forEach((s) => {
      try { chartRef.current?.removeSeries(s); } catch { /* already removed */ }
    });
    seriesRefs.current = [];

    // Add new series
    series.forEach((s, i) => {
      const color = s.color ?? DEFAULT_COLORS[i % DEFAULT_COLORS.length] ?? '#3b82f6';
      const ls = chartRef.current!.addSeries(LineSeries, {
        color,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
        crosshairMarkerVisible: true,
      });
      ls.setData(s.data.map(toLineData));
      seriesRefs.current.push(ls);
    });

    chartRef.current.timeScale().fitContent();
    chartRef.current.timeScale().scrollToRealTime();
  }, [series]);

  return (
    <div style={{ position: 'relative', ...style }}>
      <div ref={containerRef} style={{ width: '100%', height }} />
      {legend && series.length > 1 && (
        <div style={legendStyle}>
          {series.map((s, i) => (
            <span key={s.name} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
              <span style={{
                background: s.color ?? DEFAULT_COLORS[i % DEFAULT_COLORS.length],
                borderRadius: 2,
                display: 'inline-block',
                height: 3,
                width: 16,
              }} />
              {s.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
};

const legendStyle: React.CSSProperties = {
  bottom: 8,
  color: '#94a3b8',
  display: 'flex',
  flexWrap: 'wrap',
  gap: 12,
  left: 8,
  position: 'absolute',
};
