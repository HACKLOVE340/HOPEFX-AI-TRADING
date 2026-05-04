/**
 * components/charts/EquityCurveChart.tsx
 * Equity curve with drawdown shading, Sharpe/Sortino overlays,
 * and time-range selector (1D / 1W / 1M / 3M / 1Y / ALL).
 */

import React, { useMemo, useState } from 'react';
import {
  ComposedChart, Area, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { useStore } from '../../store';
import { Panel } from '../ui/Panel';
import { MetricTile } from '../ui/MetricTile';
import { fmtPrice, fmtPct, fmtRatio, pnlColor } from '../../lib/utils';
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

// ── Custom tooltip ────────────────────────────────────────────────────────────
function ChartTooltip({ active, payload, label }: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-[#111827] border border-[#1e2d3d] rounded-lg p-3 shadow-xl text-xs font-mono">
      <p className="text-slate-500 mb-2">{label}</p>
      {payload.map((p) => (
        <div key={p.name} className="flex items-center justify-between gap-4">
          <span style={{ color: p.color }}>{p.name}</span>
          <span className="text-slate-200 tabular-nums">
            {p.name === 'Drawdown'
              ? `${(p.value * 100).toFixed(2)}%`
              : `$${p.value.toLocaleString('en-US', { minimumFractionDigits: 2 })}`}
          </span>
        </div>
      ))}
    </div>
  );
}

// ── Chart component ───────────────────────────────────────────────────────────
export function EquityCurveChart() {
  const rawCurve = useStore((s) => s.equityCurve);
  const perf     = useStore((s) => s.performanceSummary);
  const [range, setRange] = useState<Range>('ALL');

  const chartData = useMemo(() => {
    if (!rawCurve.length) return [];
    const cutoff = range === 'ALL' ? 0 : Date.now() - RANGE_MS[range];
    return rawCurve
      .filter((pt: EquityPoint) => new Date(pt.timestamp).getTime() >= cutoff)
      .map((pt: EquityPoint) => ({
        time:     new Date(pt.timestamp).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
        equity:   pt.equity,
        drawdown: pt.drawdown,
      }));
  }, [rawCurve, range]);

  const startEquity = chartData[0]?.equity ?? 0;
  const endEquity   = chartData[chartData.length - 1]?.equity ?? 0;
  const totalReturn = startEquity > 0 ? (endEquity - startEquity) / startEquity : 0;
  const rawDrawdowns = rawCurve.map((p) => p.drawdown);
  const maxDD = perf?.max_drawdown_pct ?? (rawDrawdowns.length > 0 ? Math.min(...rawDrawdowns) * -100 : 0);

  // Time-range selector
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
      <MetricTile label="Return" value={fmtPct(totalReturn)} valueColor={totalReturn >= 0 ? '#00e676' : '#ff1744'} compact />
      <MetricTile label="Sharpe"  value={perf ? fmtRatio(perf.sharpe_ratio)  : '—'} valueColor="#00d4ff" compact />
      <MetricTile label="Sortino" value={perf ? fmtRatio(perf.sortino_ratio) : '—'} valueColor="#a855f7" compact />
      <MetricTile label="Max DD"  value={perf ? `${maxDD.toFixed(1)}%`        : '—'} valueColor="#ff3b5c" compact />
    </div>
  );

  return (
    <Panel title="Equity Curve" headerRight={headerRight} noPad bodyClass="p-0">
      {chartData.length === 0 ? (
        <div className="flex items-center justify-center h-full text-slate-600 text-sm">
          {rawCurve.length === 0 ? 'Awaiting equity data…' : `No data for ${range} range`}
        </div>
      ) : (
        <div className="flex flex-col h-full">
          <div className="flex-1 min-h-0 px-2 pt-3">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#00d4ff" stopOpacity={0.2} />
                    <stop offset="95%" stopColor="#00d4ff" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#ff3b5c" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#ff3b5c" stopOpacity={0.05} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="2 4" stroke="#1e2d3d" vertical={false} />
                <XAxis dataKey="time" tick={{ fill: '#475569', fontSize: 9, fontFamily: 'monospace' }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
                <YAxis yAxisId="equity" orientation="right" tick={{ fill: '#475569', fontSize: 9, fontFamily: 'monospace' }} axisLine={false} tickLine={false} tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} width={48} />
                <YAxis yAxisId="dd" orientation="left" tick={{ fill: '#475569', fontSize: 9, fontFamily: 'monospace' }} axisLine={false} tickLine={false} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} width={36} domain={['dataMin', 0]} />
                <Tooltip content={<ChartTooltip />} />
                <Bar yAxisId="dd" dataKey="drawdown" name="Drawdown" fill="url(#ddGrad)" stroke="#ff3b5c" strokeWidth={0} opacity={0.6} />
                <Area yAxisId="equity" type="monotone" dataKey="equity" name="Equity" stroke="#00d4ff" strokeWidth={1.5} fill="url(#equityGrad)" dot={false} activeDot={{ r: 3, fill: '#00d4ff', strokeWidth: 0 }} />
                <ReferenceLine yAxisId="equity" y={startEquity} stroke="#1e2d3d" strokeDasharray="4 4" />
              </ComposedChart>
            </ResponsiveContainer>
          </div>

          {perf && (
            <div className="flex items-center gap-6 px-4 py-2.5 border-t border-[#1e2d3d] shrink-0">
              <MetricTile label="Win Rate"      value={`${perf.win_rate.toFixed(1)}%`}         valueColor="#00e676" compact />
              <MetricTile label="Profit Factor" value={fmtRatio(perf.profit_factor)}            valueColor="#00d4ff" compact />
              <MetricTile label="Total Trades"  value={perf.total_trades.toString()}            compact />
              <MetricTile label="Avg Trade"     value={fmtPrice(perf.avg_trade_pnl, 2)}        valueColor={pnlColor(perf.avg_trade_pnl)} compact />
              <MetricTile label="CVaR 95%"      value={`${(perf.cvar_95 * 100).toFixed(1)}%`} valueColor="#ff3b5c" compact />
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}
