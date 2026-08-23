/**
 * components/charts/EquityCurveChart.tsx
 * Equity curve with drawdown shading, Sharpe/Sortino overlays,
 * and time-range selector (1D / 1W / 1M / 3M / 1Y / ALL).
 * Rendered with lightweight-charts v5 — no recharts dependency.
 */

import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  createChart, AreaSeries, HistogramSeries,
} from 'lightweight-charts';
import type { IChartApi, ISeriesApi, UTCTimestamp } from 'lightweight-charts';
import { useStore } from '../../store';
import { Panel } from '../ui/Panel';
import { MetricTile } from '../ui/MetricTile';
import { fmtPct, fmtPctRaw, fmtRatio, fmtPrice, pnlColor } from '../../lib/utils';
import type { EquityPoint } from '../../types';

type Range = '1D' | '1W' | '1M' | '3M' | '1Y' | 'ALL';
const RANGES: Range[] = ['1D', '1W', '1M', '3M', '1Y', 'ALL'];

const RANGE_MS: Record<Range, number> = {
  '1D':  24 * 60 * 60 * 1000,
  '1W':  7  * 24 * 60 * 60 * 1000,
  '1M':  30 * 24 * 60 * 60 * 1000,
  '3M':  90 * 24 * 60 * 60 * 1000,
  '1Y':  365 * 24 * 60 * 60 * 1000,
  'ALL': Infinity,
};

function toUT(ts: string | number): UTCTimestamp {
  if (typeof ts === 'number') return Math.floor(ts > 1e12 ? ts / 1000 : ts) as UTCTimestamp;
  return Math.floor(new Date(ts).getTime() / 1000) as UTCTimestamp;
}

// ── Chart component ───────────────────────────────────────────────────────────
export function EquityCurveChart() {
  const rawCurve = useStore((s) => s.equityCurve);
  const perf     = useStore((s) => s.performanceSummary);
  const [range, setRange] = useState<Range>('ALL');

  const containerRef  = useRef<HTMLDivElement>(null);
  const chartApiRef   = useRef<IChartApi | null>(null);
  const equitySerRef  = useRef<ISeriesApi<'Area'> | null>(null);
  const ddSerRef      = useRef<ISeriesApi<'Histogram'> | null>(null);
  const priceLineRef  = useRef<ReturnType<ISeriesApi<'Area'>['createPriceLine']> | null>(null);
  const rafRef        = useRef<number>(0);

  // ── Chart init (mount once) ────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout:    { background: { color: '#060d18' }, textColor: '#64748b' },
      grid:      { vertLines: { color: '#0d1421' }, horzLines: { color: '#0d1421' } },
      rightPriceScale: { borderColor: '#1e2d3d' },
      leftPriceScale:  { borderColor: '#1e2d3d', visible: true, scaleMargins: { top: 0.8, bottom: 0 } },
      timeScale: { borderColor: '#1e2d3d', timeVisible: false },
      height: containerRef.current.clientHeight || 260,
      width:  containerRef.current.clientWidth,
    });

    const equitySeries = chart.addSeries(AreaSeries, {
      lineColor:   '#00d4ff',
      topColor:    'rgba(0,212,255,0.20)',
      bottomColor: 'rgba(0,212,255,0)',
      lineWidth:   2,
      priceScaleId: 'right',
      lastValueVisible: true,
      priceLineVisible: false,
    });

    const ddSeries = chart.addSeries(HistogramSeries, {
      color:        'rgba(255,59,92,0.5)',
      priceScaleId: 'left',
      lastValueVisible: false,
      priceLineVisible: false,
    });

    chartApiRef.current  = chart;
    equitySerRef.current = equitySeries;
    ddSerRef.current     = ddSeries;

    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(() => {
        if (containerRef.current && chartApiRef.current) {
          chartApiRef.current.applyOptions({
            width:  containerRef.current.clientWidth,
            height: containerRef.current.clientHeight || 260,
          });
        }
      });
    });
    ro.observe(containerRef.current);

    return () => {
      cancelAnimationFrame(rafRef.current);
      ro.disconnect();
      chart.remove();
      chartApiRef.current  = null;
      equitySerRef.current = null;
      ddSerRef.current     = null;
      priceLineRef.current = null;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Data update ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!equitySerRef.current || !ddSerRef.current || !rawCurve.length) return;

    const cutoff = range === 'ALL' ? 0 : Date.now() - RANGE_MS[range];
    const filtered = rawCurve.filter((pt: EquityPoint) => new Date(pt.timestamp).getTime() >= cutoff);

    if (!filtered.length) {
      equitySerRef.current.setData([]);
      ddSerRef.current.setData([]);
      return;
    }

    // Deduplicate by second-level timestamp (LWC requires monotonically increasing times)
    const seen = new Set<number>();
    const equityData: { time: UTCTimestamp; value: number }[] = [];
    const ddData: { time: UTCTimestamp; value: number; color: string }[] = [];

    for (const pt of [...filtered].sort((a, b) =>
      new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    )) {
      const t = toUT(pt.timestamp);
      // Skip duplicate or non-finite points — LWC throws on NaN/Infinity and
      // requires strictly increasing, valid timestamps.
      if (seen.has(t) || !Number.isFinite(t) || !Number.isFinite(pt.equity)) continue;
      seen.add(t);
      equityData.push({ time: t, value: pt.equity });
      ddData.push({ time: t, value: Number.isFinite(pt.drawdown) ? pt.drawdown : 0, color: 'rgba(255,59,92,0.5)' });
    }

    equitySerRef.current.setData(equityData);
    ddSerRef.current.setData(ddData);

    // Draw start-equity reference line. Remove the previous one first so lines
    // don't accumulate on every 30s refetch.
    if (priceLineRef.current) {
      equitySerRef.current.removePriceLine(priceLineRef.current);
      priceLineRef.current = null;
    }
    const startEquity = equityData[0]?.value ?? 0;
    priceLineRef.current = equitySerRef.current.createPriceLine({
      price:              startEquity,
      color:              '#1e2d3d',
      lineWidth:          1,
      lineStyle:          2,
      axisLabelVisible:   false,
      title:              '',
    });

    chartApiRef.current?.timeScale().fitContent();
  }, [rawCurve, range]);

  // ── Derived header stats ───────────────────────────────────────────────────
  const { totalReturn, maxDD } = useMemo(() => {
    if (!rawCurve.length) return { totalReturn: 0, maxDD: 0 };
    const cutoff = range === 'ALL' ? 0 : Date.now() - RANGE_MS[range];
    const filtered = rawCurve.filter((pt: EquityPoint) => new Date(pt.timestamp).getTime() >= cutoff);
    const start = filtered[0]?.equity ?? 0;
    const end   = filtered[filtered.length - 1]?.equity ?? 0;
    const tr    = start > 0 ? (end - start) / start : 0;
    const rawDD = filtered.map((p) => p.drawdown);
    const md    = perf?.max_drawdown_pct ?? (rawDD.length ? Math.min(...rawDD) * -100 : 0);
    return { totalReturn: tr, maxDD: md };
  }, [rawCurve, range, perf]);

  // ── Range selector ─────────────────────────────────────────────────────────
  const rangeSelector = (
    <div style={{ display: 'flex', gap: 2 }}>
      {RANGES.map((r) => (
        <button
          key={r}
          onClick={() => setRange(r)}
          style={{
            padding: '2px 7px', borderRadius: 4, fontSize: 10, fontWeight: 700,
            fontFamily: 'monospace', cursor: 'pointer', letterSpacing: 0.5,
            border: `1px solid ${range === r ? '#3b82f6' : '#1e293b'}`,
            background: range === r ? 'rgba(59,130,246,0.15)' : 'transparent',
            color: range === r ? '#60a5fa' : '#475569',
            transition: 'all 0.15s ease',
          }}
        >
          {r}
        </button>
      ))}
    </div>
  );

  const headerRight = (
    <div className="flex items-center gap-4">
      {rangeSelector}
      <MetricTile label="Return" to="/performance" toHint="performance detail" value={fmtPct(totalReturn)} valueColor={totalReturn >= 0 ? '#00e676' : '#ff1744'} compact />
      <MetricTile label="Sharpe" to="/performance" toHint="risk-adjusted performance"  value={perf ? fmtRatio(perf.sharpe_ratio)  : '—'} valueColor="#00d4ff" compact />
      <MetricTile label="Sortino" to="/performance" toHint="risk-adjusted performance" value={perf ? fmtRatio(perf.sortino_ratio) : '—'} valueColor="#a855f7" compact />
      <MetricTile label="Max DD" to="/performance" toHint="the drawdown curve"  value={perf ? `${maxDD.toFixed(1)}%`        : '—'} valueColor="#ff3b5c" compact />
    </div>
  );

  return (
    <Panel title="Equity Curve" headerRight={headerRight} noPad bodyClass="p-0">
      {rawCurve.length === 0 ? (
        <div className="flex items-center justify-center h-full text-slate-600 text-sm">
          Awaiting equity data…
        </div>
      ) : (
        <div className="flex flex-col h-full">
          <div className="flex-1 min-h-0 px-2 pt-3">
            <div ref={containerRef} className="w-full h-full" />
          </div>

          {perf && (
            <div className="flex items-center gap-6 px-4 py-2.5 border-t border-[#1e2d3d] shrink-0">
              <MetricTile label="Win Rate" to="/journal" toHint="the trades behind it"      value={fmtPctRaw(perf.win_rate, 1)} valueColor="#00e676" compact />
              <MetricTile label="Profit Factor" to="/journal" toHint="the trades behind it" value={fmtRatio(perf.profit_factor)}            valueColor="#00d4ff" compact />
              <MetricTile label="Total Trades" to="/journal" toHint="the trade journal"  value={perf.total_trades?.toString() ?? '—'}            compact />
              <MetricTile label="Avg Trade" to="/journal" toHint="the trade journal"     value={fmtPrice(perf.avg_trade_pnl, 2)}        valueColor={pnlColor(perf.avg_trade_pnl)} compact />
              <MetricTile label="CVaR 95%" to="/risk-calculator" toHint="the Risk Calculator"      value={fmtPct(perf.cvar_95, 1)} valueColor="#ff3b5c" compact />
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}
