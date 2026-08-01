/**
 * CandleChart — lightweight-charts candlestick wrapper.
 *
 * Handles:
 * - Chart creation / ResizeObserver (rAF-throttled)
 * - Series update when data prop changes
 * - Real-time tick update — aligned to current bar time to prevent phantom candles
 * - Dark/light theme via ThemeContext
 * - Cleanup on unmount
 */

import React, { useEffect, useRef } from 'react';
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  CandlestickSeries,
  type CandlestickData,
  type UTCTimestamp,
} from 'lightweight-charts';
import { useTheme } from './ThemeContext';

export interface OHLCBar {
  time: number; // unix seconds
  open: number;
  high: number;
  low: number;
  close: number;
}

interface CandleChartProps {
  data: OHLCBar[];
  /** Latest tick — updates the last bar in real-time */
  tick?: { time: number; bid: number; ask: number } | null;
  height?: number;
  style?: React.CSSProperties;
}

function toChartBar(b: OHLCBar): CandlestickData {
  return {
    time: b.time as UTCTimestamp,
    open: b.open,
    high: b.high,
    low: b.low,
    close: b.close,
  };
}

export const CandleChart: React.FC<CandleChartProps> = ({
  data,
  tick,
  height = 320,
  style,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef     = useRef<IChartApi | null>(null);
  const seriesRef    = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const rafRef       = useRef<number>(0);
  const { theme }    = useTheme();

  const isDark = theme === 'dark';

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
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: isDark ? '#334155' : '#cbd5e1' },
      timeScale: {
        borderColor: isDark ? '#334155' : '#cbd5e1',
        timeVisible: true,
        secondsVisible: false,
      },
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor:          '#4ade80',
      downColor:        '#f87171',
      borderUpColor:    '#4ade80',
      borderDownColor:  '#f87171',
      wickUpColor:      '#4ade80',
      wickDownColor:    '#f87171',
    });

    chartRef.current  = chart;
    seriesRef.current = series;

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
      chartRef.current  = null;
      seriesRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height]);

  // Update theme colours without recreating chart
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

  // Load historical data — always scroll to the most recent candle
  useEffect(() => {
    if (!seriesRef.current || data.length === 0) return;
    seriesRef.current.setData(data.map(toChartBar));
    chartRef.current?.timeScale().fitContent();
    chartRef.current?.timeScale().scrollToRealTime();
  }, [data]);

  // Real-time tick update — align to the current bar's open time so the tick
  // updates the existing candle rather than creating a phantom future candle.
  useEffect(() => {
    const last = data[data.length - 1];
    if (!tick || !seriesRef.current || !last) return;
    const mid  = (tick.bid + tick.ask) / 2;
    seriesRef.current.update({
      time:  last.time as UTCTimestamp,
      open:  last.open,
      high:  Math.max(last.high, tick.ask),
      low:   Math.min(last.low,  tick.bid),
      close: mid,
    });
  }, [tick, data]);

  return (
    <div
      ref={containerRef}
      style={{ width: '100%', height, ...style }}
    />
  );
};
