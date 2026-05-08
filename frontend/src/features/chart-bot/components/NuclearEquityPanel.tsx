/**
 * NuclearEquityPanel.tsx
 * Bottom panel — equity curve with annotated nuclear events.
 * Shows: equity line, drawdown fill, pause/hedge/liquidation markers,
 * timestamps, and impact estimates.
 */

import React, { useEffect, useRef, memo } from 'react';
import {
  createChart,
  IChartApi,
  ISeriesApi,
  LineSeries,
  AreaSeries,
  HistogramSeries,
  AreaData,
  LineData,
  HistogramData,
  createSeriesMarkers,
  ISeriesMarkersPluginApi,
  SeriesMarker,
  Time,
  UTCTimestamp,
} from 'lightweight-charts';
import { useNuclearStore } from '../store/nuclear-store';
import { severityColor } from '../types/nuclear';
import type { NuclearEquityPoint, NuclearEvent } from '../types/nuclear';

// ─── Helpers ──────────────────────────────────────────────────────────────────

function toUTC(ts: number): UTCTimestamp {
  return (ts > 1e10 ? Math.floor(ts / 1000) : ts) as UTCTimestamp;
}

// ─── Stats bar ────────────────────────────────────────────────────────────────

const EquityStats = memo(() => {
  const risk = useNuclearStore((s) => s.risk);
  const curve = useNuclearStore((s) => s.equityCurve);

  const equity    = risk?.equity ?? 0;
  const balance   = risk?.balance ?? 0;
  const dailyPnl  = risk?.daily_pnl ?? 0;
  const drawdown  = risk?.drawdown_pct ?? 0;
  const maxDD     = curve.length
    ? Math.min(...curve.map((p) => p.drawdown))
    : 0;

  const pnlColor = dailyPnl >= 0 ? '#00ff88' : '#ef4444';
  const ddColor  = drawdown < -2 ? '#ef4444' : drawdown < -1 ? '#fbbf24' : '#64748b';

  return (
    <div style={s.statsRow}>
      <StatCell label="EQUITY"    value={`$${equity.toLocaleString('en', { minimumFractionDigits: 2 })}`} color="#f1f5f9" />
      <StatCell label="DAILY P&L" value={`${dailyPnl >= 0 ? '+' : ''}$${dailyPnl.toFixed(2)}`} color={pnlColor} />
      <StatCell label="DRAWDOWN"  value={`${drawdown.toFixed(2)}%`} color={ddColor} />
      <StatCell label="MAX DD"    value={`${maxDD.toFixed(2)}%`}    color={maxDD < -3 ? '#ef4444' : '#64748b'} />
      <StatCell label="BALANCE"   value={`$${balance.toLocaleString('en', { minimumFractionDigits: 2 })}`} color="#94a3b8" />
    </div>
  );
});

const StatCell = memo(({ label, value, color }: { label: string; value: string; color: string }) => (
  <div style={s.statCell}>
    <span style={s.statLabel}>{label}</span>
    <span style={{ ...s.statValue, color }}>{value}</span>
  </div>
));

// ─── Main panel ───────────────────────────────────────────────────────────────

const NuclearEquityPanel = memo(() => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef     = useRef<IChartApi | null>(null);
  const equityRef    = useRef<ISeriesApi<'Area'> | null>(null);
  const ddRef        = useRef<ISeriesApi<'Histogram'> | null>(null);
  const markersRef   = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const rafRef       = useRef<number>(0);

  const equityCurve   = useNuclearStore((s) => s.equityCurve);
  const nuclearEvents = useNuclearStore((s) => s.nuclearEvents);

  // ── Chart init ──────────────────────────────────────────────────────────────

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: '#020408' },
        textColor: '#64748b',
        fontFamily: 'monospace',
        fontSize: 10,
      },
      grid: {
        vertLines: { color: '#0a1628' },
        horzLines: { color: '#0a1628' },
      },
      rightPriceScale: { borderColor: '#1a2e4a', textColor: '#64748b' },
      timeScale: { borderColor: '#1a2e4a', timeVisible: true },
      handleScroll: true,
      handleScale: true,
    });
    chartRef.current = chart;

    // Equity area series
    const equity = chart.addSeries(AreaSeries, {
      lineColor:   '#00ff88',
      topColor:    'rgba(0,255,136,0.15)',
      bottomColor: 'rgba(0,255,136,0.0)',
      lineWidth:   2,
      priceLineVisible: false,
    });
    equityRef.current = equity;

    // Drawdown histogram
    const dd = chart.addSeries(HistogramSeries, {
      color:  'rgba(239,68,68,0.4)',
      priceScaleId: 'dd',
      priceLineVisible: false,
      lastValueVisible: false,
    });
    chart.priceScale('dd').applyOptions({
      scaleMargins: { top: 0.7, bottom: 0 },
    });
    ddRef.current = dd;

    // Event markers on equity series
    markersRef.current = createSeriesMarkers(equity, []);

    // rAF-throttled ResizeObserver prevents layout thrashing
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(() => {
        if (containerRef.current && chartRef.current) {
          chartRef.current.applyOptions({
            width:  containerRef.current.clientWidth,
            height: containerRef.current.clientHeight || undefined,
          });
        }
      });
    });
    ro.observe(containerRef.current);

    return () => {
      cancelAnimationFrame(rafRef.current);
      ro.disconnect();
      chart.remove();
      chartRef.current  = null;
      equityRef.current = null;
      ddRef.current     = null;
    };
  }, []);

  // ── Update equity data ──────────────────────────────────────────────────────

  useEffect(() => {
    if (!equityRef.current || !equityCurve.length) return;

    const sorted = [...equityCurve].sort((a, b) => a.time - b.time);

    const equityData: AreaData[] = sorted.map((p) => ({
      time: toUTC(p.time),
      value: p.equity,
    }));

    const ddData: HistogramData[] = sorted.map((p) => ({
      time: toUTC(p.time),
      value: p.drawdown,
      color: p.drawdown < -3 ? 'rgba(255,0,51,0.5)' :
             p.drawdown < -1 ? 'rgba(239,68,68,0.4)' :
             'rgba(239,68,68,0.2)',
    }));

    equityRef.current.setData(equityData);
    ddRef.current?.setData(ddData);
    // Always show the most recent equity data on load
    chartRef.current?.timeScale().fitContent();
    chartRef.current?.timeScale().scrollToRealTime();
  }, [equityCurve]);

  // ── Update event markers ────────────────────────────────────────────────────

  useEffect(() => {
    if (!markersRef.current) return;

    const markers: SeriesMarker<Time>[] = [];

    // Nuclear events
    nuclearEvents
      .filter((ev) => ev.severity >= 5)
      .forEach((ev) => {
        const actionEmoji = {
          nuclear_mode:      '☢️',
          hedge_mode:        '🛡️',
          pause_new_entries: '⏸️',
          normal:            '✅',
        }[ev.action] ?? '⚠️';

        markers.push({
          time: toUTC(Math.floor(ev.ts / 1000)) as Time,
          position: 'aboveBar' as const,
          color: severityColor(ev.severity),
          shape: ev.severity >= 9 ? 'arrowDown' as const : 'circle' as const,
          text: `${actionEmoji} SEV${ev.severity}`,
          size: ev.severity >= 7 ? 2 : 1,
        });
      });

    // Equity curve annotations
    equityCurve
      .filter((p) => p.annotation)
      .forEach((p) => {
        markers.push({
          time: toUTC(p.time) as Time,
          position: 'belowBar' as const,
          color: '#fbbf24',
          shape: 'circle' as const,
          text: p.annotation!,
          size: 1,
        });
      });

    markers.sort((a, b) => (a.time as number) - (b.time as number));
    markersRef.current.setMarkers(markers);
  }, [nuclearEvents, equityCurve]);

  return (
    <div style={s.wrapper}>
      <div style={s.header}>
        <span style={s.title}>EQUITY CURVE</span>
        <EquityStats />
      </div>
      <div ref={containerRef} style={s.canvas} />
    </div>
  );
});

export default NuclearEquityPanel;

// ─── Styles ───────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  wrapper: {
    height: 200, display: 'flex', flexDirection: 'column',
    background: '#020408',
    borderTop: '1px solid #1a2e4a',
    flexShrink: 0,
  },
  header: {
    display: 'flex', alignItems: 'center', gap: 16,
    padding: '6px 12px',
    borderBottom: '1px solid #0a1628',
    flexShrink: 0,
  },
  title: {
    fontSize: 9, fontWeight: 800, letterSpacing: 2, color: '#475569',
    flexShrink: 0,
  },
  statsRow: {
    display: 'flex', gap: 20, flex: 1,
  },
  statCell: {
    display: 'flex', flexDirection: 'column', gap: 1,
  },
  statLabel: {
    fontSize: 8, color: '#334155', letterSpacing: 1.5, fontWeight: 700,
  },
  statValue: {
    fontSize: 12, fontWeight: 700, fontFamily: 'monospace',
  },
  canvas: {
    flex: 1, minHeight: 0,
  },
};
