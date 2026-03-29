/**
 * EquityCurve.tsx
 * Advanced equity curve with dynamic drawdown shading, Sharpe/Sortino
 * overlays, zoom/pan, and intelligent annotations.
 * Built on Recharts for smooth SVG rendering with custom components.
 */

import React, { useState, useMemo, memo, useCallback } from 'react';
import {
  AreaChart, Area, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine, ReferenceArea,
  ComposedChart, Bar,
} from 'recharts';
import { useEquityCurve } from '../hooks/useChartData';
import { useChartBotStore } from '../store/chart-bot-store';
import { COLORS, CHART_DIMS } from '../utils/design-tokens';
import { formatPnl, formatPct, formatDateTime, formatPrice } from '../utils/formatters';
import type { EquityPoint } from '../types';

// ─── Period selector ──────────────────────────────────────────────────────────

const PERIODS = [
  { label: '1W',  days: 7   },
  { label: '1M',  days: 30  },
  { label: '3M',  days: 90  },
  { label: '6M',  days: 180 },
  { label: '1Y',  days: 365 },
  { label: 'ALL', days: 0   },
];

// ─── Custom Tooltip ───────────────────────────────────────────────────────────

interface TooltipPayload {
  payload?: EquityPoint;
}

const EquityTooltip = memo(({ active, payload }: { active?: boolean; payload?: TooltipPayload[] }) => {
  if (!active || !payload?.length || !payload[0].payload) return null;
  const d = payload[0].payload;
  const isDrawdown = d.drawdown < -0.5;

  return (
    <div style={styles.tooltip}>
      <div style={styles.ttDate}>{formatDateTime(d.time)}</div>
      <div style={styles.ttRow}>
        <span style={styles.ttLabel}>Equity</span>
        <span style={{ ...styles.ttVal, color: COLORS.neon.cyan }}>{formatPnl(d.equity)}</span>
      </div>
      <div style={styles.ttRow}>
        <span style={styles.ttLabel}>Drawdown</span>
        <span style={{ ...styles.ttVal, color: isDrawdown ? COLORS.loss.base : COLORS.text.secondary }}>
          {formatPct(d.drawdown)}
        </span>
      </div>
      <div style={styles.ttRow}>
        <span style={styles.ttLabel}>Sharpe</span>
        <span style={{ ...styles.ttVal, color: d.sharpe >= 1 ? COLORS.profit.base : d.sharpe >= 0 ? COLORS.neon.gold : COLORS.loss.base }}>
          {d.sharpe.toFixed(2)}
        </span>
      </div>
      <div style={styles.ttRow}>
        <span style={styles.ttLabel}>Sortino</span>
        <span style={{ ...styles.ttVal, color: d.sortino >= 1.5 ? COLORS.profit.base : d.sortino >= 0 ? COLORS.neon.gold : COLORS.loss.base }}>
          {d.sortino.toFixed(2)}
        </span>
      </div>
      {d.annotation && (
        <div style={styles.ttAnnotation}>{d.annotation}</div>
      )}
    </div>
  );
});
EquityTooltip.displayName = 'EquityTooltip';

// ─── Stats Bar ────────────────────────────────────────────────────────────────

interface Stats {
  totalReturn: number;
  totalReturnPct: number;
  maxDrawdown: number;
  avgSharpe: number;
  avgSortino: number;
  winDays: number;
  lossDays: number;
  currentEquity: number;
  peakEquity: number;
}

const StatsBar = memo(({ stats }: { stats: Stats }) => (
  <div style={styles.statsBar}>
    <StatPill label="Total Return" value={formatPnl(stats.totalReturn)} color={stats.totalReturn >= 0 ? COLORS.profit.base : COLORS.loss.base} />
    <StatPill label="Return %" value={formatPct(stats.totalReturnPct)} color={stats.totalReturnPct >= 0 ? COLORS.profit.base : COLORS.loss.base} />
    <StatPill label="Max DD" value={formatPct(stats.maxDrawdown)} color={COLORS.loss.base} />
    <StatPill label="Sharpe" value={stats.avgSharpe.toFixed(2)} color={stats.avgSharpe >= 1 ? COLORS.profit.base : COLORS.neon.gold} />
    <StatPill label="Sortino" value={stats.avgSortino.toFixed(2)} color={stats.avgSortino >= 1.5 ? COLORS.profit.base : COLORS.neon.gold} />
    <StatPill label="Win Days" value={`${stats.winDays}`} color={COLORS.profit.base} />
    <StatPill label="Loss Days" value={`${stats.lossDays}`} color={COLORS.loss.base} />
  </div>
));
StatsBar.displayName = 'StatsBar';

const StatPill = memo(({ label, value, color }: { label: string; value: string; color: string }) => (
  <div style={styles.statPill}>
    <span style={styles.statLabel}>{label}</span>
    <span style={{ ...styles.statValue, color }}>{value}</span>
  </div>
));
StatPill.displayName = 'StatPill';

// ─── Main Component ───────────────────────────────────────────────────────────

const EquityCurve: React.FC = () => {
  const [period, setPeriod] = useState(90);
  const { data: rawPoints, isLoading } = useEquityCurve(period || 365);
  const livePoints = useChartBotStore((s) => s.equityCurve);

  // Merge fetched + live streaming points
  const points: EquityPoint[] = useMemo(() => {
    const base = rawPoints ?? [];
    if (!livePoints.length) return base;
    const lastFetched = base[base.length - 1]?.time ?? 0;
    const newLive = livePoints.filter((p) => p.time > lastFetched);
    return [...base, ...newLive];
  }, [rawPoints, livePoints]);

  // Compute stats
  const stats = useMemo<Stats>(() => {
    if (!points.length) return { totalReturn: 0, totalReturnPct: 0, maxDrawdown: 0, avgSharpe: 0, avgSortino: 0, winDays: 0, lossDays: 0, currentEquity: 0, peakEquity: 0 };
    const first = points[0].equity;
    const last  = points[points.length - 1].equity;
    const peak  = Math.max(...points.map((p) => p.equity));
    const maxDD = Math.min(...points.map((p) => p.drawdown));
    const avgSharpe  = points.reduce((a, p) => a + p.sharpe,  0) / points.length;
    const avgSortino = points.reduce((a, p) => a + p.sortino, 0) / points.length;
    const winDays  = points.filter((p, i) => i > 0 && p.equity > points[i - 1].equity).length;
    const lossDays = points.filter((p, i) => i > 0 && p.equity < points[i - 1].equity).length;
    return {
      totalReturn:    last - first,
      totalReturnPct: ((last - first) / first) * 100,
      maxDrawdown:    maxDD,
      avgSharpe,
      avgSortino,
      winDays,
      lossDays,
      currentEquity: last,
      peakEquity:    peak,
    };
  }, [points]);

  // Find drawdown regions for shading
  const drawdownRegions = useMemo(() => {
    const regions: { start: number; end: number; depth: number }[] = [];
    let inDD = false;
    let ddStart = 0;
    let maxDepth = 0;
    for (const pt of points) {
      if (pt.drawdown < -1 && !inDD) {
        inDD = true;
        ddStart = pt.time;
        maxDepth = pt.drawdown;
      } else if (pt.drawdown < -1 && inDD) {
        maxDepth = Math.min(maxDepth, pt.drawdown);
      } else if (pt.drawdown >= -1 && inDD) {
        regions.push({ start: ddStart, end: pt.time, depth: maxDepth });
        inDD = false;
        maxDepth = 0;
      }
    }
    if (inDD && points.length) {
      regions.push({ start: ddStart, end: points[points.length - 1].time, depth: maxDepth });
    }
    return regions;
  }, [points]);

  // Annotations
  const annotations = useMemo(() =>
    points.filter((p) => p.annotation),
  [points]);

  const handlePeriod = useCallback((days: number) => setPeriod(days), []);

  if (isLoading && !points.length) {
    return (
      <div style={styles.wrapper}>
        <div style={styles.loading}>Loading equity curve…</div>
      </div>
    );
  }

  return (
    <div style={styles.wrapper}>
      {/* Header */}
      <div style={styles.header}>
        <div style={styles.headerLeft}>
          <span style={styles.title}>EQUITY CURVE</span>
          <span style={{ ...styles.equityVal, color: stats.totalReturn >= 0 ? COLORS.profit.base : COLORS.loss.base }}>
            {formatPnl(stats.currentEquity)}
          </span>
        </div>
        <div style={styles.periodRow}>
          {PERIODS.map((p) => (
            <button
              key={p.label}
              onClick={() => handlePeriod(p.days)}
              style={{ ...styles.periodBtn, ...(period === p.days ? styles.periodBtnActive : {}) }}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Stats */}
      <StatsBar stats={stats} />

      {/* Main equity area chart */}
      <div style={{ padding: '0 4px' }}>
        <ResponsiveContainer width="100%" height={CHART_DIMS.equityCurveHeight}>
          <ComposedChart data={points} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor={COLORS.neon.cyan} stopOpacity={0.25} />
                <stop offset="95%" stopColor={COLORS.neon.cyan} stopOpacity={0.02} />
              </linearGradient>
              <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor={COLORS.loss.base} stopOpacity={0.3} />
                <stop offset="95%" stopColor={COLORS.loss.base} stopOpacity={0.05} />
              </linearGradient>
            </defs>

            <CartesianGrid
              strokeDasharray="2 4"
              stroke={COLORS.bg.surface}
              vertical={false}
            />

            <XAxis
              dataKey="time"
              tickFormatter={(t) => formatDateTime(t)}
              tick={{ fill: COLORS.text.muted, fontSize: 9, fontFamily: '"JetBrains Mono", monospace' }}
              axisLine={{ stroke: COLORS.bg.border }}
              tickLine={false}
              interval="preserveStartEnd"
            />

            <YAxis
              yAxisId="equity"
              tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
              tick={{ fill: COLORS.text.muted, fontSize: 9, fontFamily: '"JetBrains Mono", monospace' }}
              axisLine={false}
              tickLine={false}
              width={48}
            />

            <YAxis
              yAxisId="ratio"
              orientation="right"
              domain={[-2, 4]}
              tickFormatter={(v) => v.toFixed(1)}
              tick={{ fill: COLORS.text.muted, fontSize: 9, fontFamily: '"JetBrains Mono", monospace' }}
              axisLine={false}
              tickLine={false}
              width={32}
            />

            <Tooltip content={<EquityTooltip />} />

            {/* Drawdown shading regions */}
            {drawdownRegions.map((r, i) => (
              <ReferenceArea
                key={i}
                yAxisId="equity"
                x1={r.start}
                x2={r.end}
                fill={COLORS.loss.base}
                fillOpacity={Math.min(0.15, Math.abs(r.depth) / 100)}
                stroke="none"
              />
            ))}

            {/* Zero line */}
            <ReferenceLine yAxisId="ratio" y={0} stroke={COLORS.bg.divider} strokeDasharray="3 3" />
            <ReferenceLine yAxisId="ratio" y={1} stroke={COLORS.neon.gold} strokeDasharray="2 4" strokeOpacity={0.4} />

            {/* Equity area */}
            <Area
              yAxisId="equity"
              type="monotone"
              dataKey="equity"
              stroke={COLORS.neon.cyan}
              strokeWidth={2}
              fill="url(#equityGrad)"
              dot={false}
              activeDot={{ r: 4, fill: COLORS.neon.cyan, stroke: COLORS.bg.void, strokeWidth: 2 }}
            />

            {/* Sharpe ratio line */}
            <Line
              yAxisId="ratio"
              type="monotone"
              dataKey="sharpe"
              stroke={COLORS.neon.gold}
              strokeWidth={1}
              dot={false}
              strokeDasharray="4 2"
              opacity={0.7}
            />

            {/* Sortino ratio line */}
            <Line
              yAxisId="ratio"
              type="monotone"
              dataKey="sortino"
              stroke={COLORS.neon.purple}
              strokeWidth={1}
              dot={false}
              strokeDasharray="2 3"
              opacity={0.7}
            />

            {/* Annotation markers */}
            {annotations.map((a) => (
              <ReferenceLine
                key={a.time}
                yAxisId="equity"
                x={a.time}
                stroke={COLORS.neon.amber}
                strokeWidth={1}
                strokeDasharray="3 2"
                label={{
                  value: '●',
                  fill: COLORS.neon.amber,
                  fontSize: 8,
                  position: 'top',
                }}
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Drawdown sub-chart */}
      <div style={{ padding: '0 4px', marginTop: 2 }}>
        <div style={styles.ddLabel}>DRAWDOWN</div>
        <ResponsiveContainer width="100%" height={60}>
          <AreaChart data={points} margin={{ top: 0, right: 8, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="ddAreaGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor={COLORS.loss.base} stopOpacity={0.5} />
                <stop offset="95%" stopColor={COLORS.loss.base} stopOpacity={0.05} />
              </linearGradient>
            </defs>
            <XAxis dataKey="time" hide />
            <YAxis
              tickFormatter={(v) => `${v.toFixed(0)}%`}
              tick={{ fill: COLORS.text.muted, fontSize: 8, fontFamily: '"JetBrains Mono", monospace' }}
              axisLine={false}
              tickLine={false}
              width={36}
            />
            <Area
              type="monotone"
              dataKey="drawdown"
              stroke={COLORS.loss.base}
              strokeWidth={1}
              fill="url(#ddAreaGrad)"
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Legend */}
      <div style={styles.legend}>
        <LegendItem color={COLORS.neon.cyan}   label="Equity" />
        <LegendItem color={COLORS.neon.gold}   label="Sharpe" dashed />
        <LegendItem color={COLORS.neon.purple} label="Sortino" dashed />
        <LegendItem color={COLORS.loss.base}   label="Drawdown" />
      </div>
    </div>
  );
};

const LegendItem = memo(({ color, label, dashed }: { color: string; label: string; dashed?: boolean }) => (
  <div style={styles.legendItem}>
    <div style={{ ...styles.legendLine, background: dashed ? 'transparent' : color, borderTop: dashed ? `1px dashed ${color}` : 'none', width: 20 }} />
    <span style={{ ...styles.legendLabel, color: COLORS.text.muted }}>{label}</span>
  </div>
));
LegendItem.displayName = 'LegendItem';

// ─── Styles ───────────────────────────────────────────────────────────────────

const styles: Record<string, React.CSSProperties> = {
  wrapper: {
    background: COLORS.bg.surface,
    border: `1px solid ${COLORS.bg.border}`,
    borderRadius: 8,
    overflow: 'hidden',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '10px 14px 8px',
    borderBottom: `1px solid ${COLORS.bg.border}`,
    flexWrap: 'wrap',
    gap: 8,
  },
  headerLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
  },
  title: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 10,
    fontWeight: 700,
    color: COLORS.text.muted,
    letterSpacing: '0.12em',
  },
  equityVal: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 18,
    fontWeight: 700,
    letterSpacing: '-0.02em',
  },
  periodRow: {
    display: 'flex',
    gap: 3,
  },
  periodBtn: {
    background: 'transparent',
    border: `1px solid ${COLORS.bg.border}`,
    borderRadius: 4,
    color: COLORS.text.muted,
    cursor: 'pointer',
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 10,
    fontWeight: 600,
    padding: '3px 7px',
    letterSpacing: '0.06em',
  },
  periodBtnActive: {
    background: COLORS.bg.elevated,
    borderColor: COLORS.neon.cyan,
    color: COLORS.neon.cyan,
  },
  statsBar: {
    display: 'flex',
    gap: 0,
    borderBottom: `1px solid ${COLORS.bg.border}`,
    overflowX: 'auto',
  },
  statPill: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    padding: '6px 12px',
    borderRight: `1px solid ${COLORS.bg.border}`,
    minWidth: 72,
    flexShrink: 0,
  },
  statLabel: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 9,
    color: COLORS.text.muted,
    letterSpacing: '0.08em',
    textTransform: 'uppercase' as const,
    marginBottom: 2,
  },
  statValue: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 12,
    fontWeight: 700,
    letterSpacing: '-0.01em',
  },
  ddLabel: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 9,
    color: COLORS.loss.base,
    letterSpacing: '0.1em',
    padding: '4px 8px 0',
    opacity: 0.7,
  },
  legend: {
    display: 'flex',
    gap: 16,
    padding: '6px 14px 8px',
    borderTop: `1px solid ${COLORS.bg.border}`,
  },
  legendItem: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
  },
  legendLine: {
    height: 2,
  },
  legendLabel: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 9,
    letterSpacing: '0.06em',
  },
  tooltip: {
    background: COLORS.bg.elevated,
    border: `1px solid ${COLORS.bg.divider}`,
    borderRadius: 6,
    padding: '8px 12px',
    minWidth: 160,
  },
  ttDate: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 10,
    color: COLORS.text.muted,
    marginBottom: 6,
    letterSpacing: '0.04em',
  },
  ttRow: {
    display: 'flex',
    justifyContent: 'space-between',
    gap: 16,
    marginBottom: 3,
  },
  ttLabel: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 10,
    color: COLORS.text.muted,
  },
  ttVal: {
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 10,
    fontWeight: 700,
  },
  ttAnnotation: {
    fontFamily: '"Inter", sans-serif',
    fontSize: 10,
    color: COLORS.neon.amber,
    marginTop: 6,
    borderTop: `1px solid ${COLORS.bg.border}`,
    paddingTop: 4,
  },
  loading: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    height: 200,
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 12,
    color: COLORS.text.muted,
    letterSpacing: '0.08em',
  },
};

export default memo(EquityCurve);
